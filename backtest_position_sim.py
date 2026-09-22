# -*- coding: utf-8 -*-
"""三訊號進出全倉位模擬：買 SuperTrend翻多+RS(30日)>0+EXCEED CHARGE剛噴出，
賣分兩階段——① SuperTrend單獨翻空就賣一半（不用等RS/squeeze同時翻），
② RS(60日)線跌破自己的60日均線（即rs_60從正翻負）才全出。

2026-08-11：用戶說「ST反轉賣一半，RS跌破60MA全出」是他自己回測出來最優的出場法，
指示改掉原本backtest_combined_signal.py那種「三條件同時翻才賣」的對稱設計。
這支是真正的「倉位模擬」（逐日模擬進出、算實現損益），跟backtest_combined_signal.py
的「訊號後N日報酬統計」不同層次，兩支互補、不是取代關係。

用法：python backtest_position_sim.py --start 2026-06-30 --universe chain_all
"""
import argparse
from datetime import datetime

import yfinance as yf

import board_html_legacy as L
from paper_portfolio import chain_select_union
from technical_indicators import squeeze_momentum, mansfield_rs_series, _benchmark, double_typhoon


def simulate(ticker, start_date, atr="wilder"):
    try:
        # 2026-09-02：原本寫死 period="1y"，所以再怎麼設 --start 都只能回測一年
        # ——預設起點 2026-06-30 只有 64 天、3~7 檔觸發，樣本小到不能下結論。
        # 改成依 start_date 往前多抓一年暖機（指標要 210 根以上才算得出來）。
        _need = (datetime.now().date() - start_date).days + 400
        _per = "2y" if _need <= 730 else ("5y" if _need <= 1825 else "10y")
        hist = yf.Ticker(ticker).history(period=_per, auto_adjust=True)
        if hist.empty or len(hist) < 210:
            return None
        # 2026-09-16：台股常常最後一根是 NaN（今天這根還沒真的收，yfinance 照樣給一列）
        # ——跟 trade_plan.py::_drop_unclosed() 是同一個病灶，這支原本沒接那層防護，
        # 導致 closes[-1] 是 nan，害「買進持有」欄位幾乎每一檔台股都消失（20 檔裡
        # 20 檔全滅），跟策略欄位的股票組成對不起來，兩欄變成不是同一批股票在比較。
        # 直接砍掉尾端的 NaN 列，用最後一個真的有收盤價的那天，不要整檔排除。
        while len(hist) and hist["Close"].iloc[-1] != hist["Close"].iloc[-1]:   # NaN 檢查
            hist = hist.iloc[:-1]
        if len(hist) < 210:
            return None
        highs, lows, closes = hist["High"].tolist(), hist["Low"].tolist(), hist["Close"].tolist()
        bench = yf.Ticker(_benchmark(ticker)).history(period="1y", auto_adjust=True)
        bench_closes = bench["Close"].tolist() if not bench.empty else []
    except Exception:
        return None
    if not bench_closes:
        return None

    # 2026-09-02：加 atr 切換。老墨的 SUPER TREND 實測是 SMA 版 ATR（3037 對得上
    # 到小數），我們的顯示層已改用 SMA；策略層要不要跟著換，取決於這支回測的結論
    # 會不會變——所以做成參數，兩版都能跑、可重複驗證，而不是改完就回不去。
    if atr == "sma":
        from technical_indicators import double_typhoon as _st_sma
        st = _st_sma(highs, lows, closes)
    else:
        st = L.supertrend(highs, lows, closes)
    if not st:
        return None
    dr = st["dir"]
    sq = squeeze_momentum(highs, lows, closes)
    # mansfield_rs_series 內部用 min(len(closes),len(bench_closes)) 對齊到「尾端」，
    # 台美股交易日曆天數常不同、bench_closes 可能比 closes 短——直接用同一個i索引
    # closes/dr跟rs_30/rs_60會對錯位（2026-08-11踩到的IndexError就是這裡）。
    # 補None讓rs陣列長度跟closes一致、位置對齊，下面迴圈才能安心用同一個i。
    def _align(rs):
        pad = len(closes) - len(rs)
        vals = [None] * pad + list(rs) if pad > 0 else list(rs)
        return [None if (v is None or v != v) else v for v in vals]   # v!=v 抓 NaN
    rs_30 = _align(mansfield_rs_series(closes, bench_closes, 30))
    rs_60 = _align(mansfield_rs_series(closes, bench_closes, 60))
    dates = [d.date() for d in hist.index]

    try:
        start_i = next(i for i, d in enumerate(dates) if d >= start_date)
    except StopIteration:
        return None

    # 2026-09-16 Leo：「如果用 SuperTrend 4 倍做為下限一定要賣出的呢」——
    # 老墨畫面本來就有「停損四倍」這條線（mult=4.0，比策略用的 3 倍更寬），
    # 目前只拿來畫圖沒接進出場規則。這裡加一個對照組：完全不管 RS/籃子，
    # 只有價格真的跌破 4 倍寬的那條線才全出（一次全賣，沒有「賣一半」那個中間站）。
    # 用同一個進場點，才跟現有兩階段規則、買進持有三個一起公平比。
    st4 = double_typhoon(highs, lows, closes, mult=4.0)
    dr4 = st4["dir"] if st4 else [None] * len(closes)

    frac = 0.0          # 0 / 0.5 / 1.0 目前持倉比例（現行兩階段規則，可能多次進出）
    entry_px = None
    trades = []          # 每筆實現損益記錄
    realized_pct_sum = 0.0   # 以「進場當時的部位比例」加權的實現報酬總和

    frac4 = 0.0          # 4倍下限對照組：只有 0 / 1.0（沒有賣一半那一階），進場點跟現行規則同步
    entry_px4 = None
    trades4 = []
    realized_pct4_sum = 0.0

    # 2026-09-16 Leo：「只算ST翻空出一半，RS低於60且ST也是空，這樣的回測呢」——
    # 「①ST單獨翻空→賣一半」不變，但②全出的條件從「RS破線（不管ST）」改成
    # 「RS破線『而且』ST當下也已經翻空」，拿掉上一輪拆解抓到的那 54%「RS單獨
    # 觸發、ST還沒翻」的情況，只留下「兩個訊號都確認轉弱」的 46% 才全出。
    fracC = 0.0          # confirmed 規則：只有 0 / 0.5 / 1.0，跟現行規則同一套階段
    entry_pxC = None
    tradesC = []
    realized_pctC_sum = 0.0

    # 四條 NAV 曲線，都從「第一次進場」那天開始記，拿來算最大回檔：
    # nav_strat：現行兩階段規則的實際曝險（frac 隨賣一半/全出而降，之後若再次進場訊號又回1.0）。
    # nav_st4：4倍下限對照組的曝險（進出場點跟上面同步觸發，只是出場條件換成4倍線）。
    # nav_C：confirmed 對照組（RS+ST都空才全出）的曝險。
    # nav_bh：買進持有，從第一次進場那天起，之後**永遠 100% 曝險、不出場**，
    #   拿來測「如果訊號讓你進場後你什麼都不做」會怎樣——這才是跟策略公平的對照組
    #   （2026-09-15 那版誤用「回測視窗起點」當買進持有基準，進場晚的股票會被
    #   算進一大段訊號根本沒讓你進的漲幅，對策略不公平；已修正見 dev_log 2026-09-16）。
    # ⚠️ 每天都要記一筆（就算當天曝險是 0，nav 持平也要記），不能因為 frac==0 就跳過，
    # 否則等於「部位出清後這條線就停止累積」——那正是 2026-09-16 抓到的第一個 bug。
    nav_strat, nav_st4, nav_C, nav_bh = [1.0], [1.0], [1.0], [1.0]
    entry_i = None      # 第一次進場的索引，只設一次

    for i in range(max(start_i, 1), len(closes)):
        if dr[i] is None or dr[i - 1] is None or rs_30[i] is None:
            continue
        px = closes[i]
        px_prev = closes[i - 1]
        day_ret = (px / px_prev - 1) if px_prev else 0.0
        # 今天要用「今天開盤前」的曝險比例算今天的漲跌（收盤才換倉、今天訊號當天
        # 買進的部位不算今天的報酬），所以先存一份快照，entry/exit 判斷完再用它記帳。
        frac_before, frac4_before, fracC_before = frac, frac4, fracC
        bh_before = 1.0 if (entry_i is not None and i > entry_i) else 0.0

        if frac == 0.0:
            flip_bull = dr[i] == 1 and dr[i - 1] == -1
            fired = bool(sq["squeeze_on"][i - 1]) and not bool(sq["squeeze_on"][i]) if sq is not None else False
            if flip_bull and rs_30[i] > 0 and fired:
                frac = 1.0
                entry_px = px
                frac4 = 1.0
                entry_px4 = px
                fracC = 1.0
                entry_pxC = px
                if entry_i is None:
                    entry_i = i
                trades.append({"date": str(dates[i]), "action": "買進100%", "px": round(px, 2)})

        if entry_i is not None:
            nav_strat.append(nav_strat[-1] * (1 + frac_before * day_ret))
            nav_st4.append(nav_st4[-1] * (1 + frac4_before * day_ret))
            nav_C.append(nav_C[-1] * (1 + fracC_before * day_ret))
            nav_bh.append(nav_bh[-1] * (1 + bh_before * day_ret))

        # 已有部位：先檢查①ST單獨翻空→賣一半
        if frac == 1.0:
            flip_bear = dr[i] == -1 and dr[i - 1] == 1
            if flip_bear:
                pnl_pct = (px / entry_px - 1) * 100
                realized_pct_sum += pnl_pct * 0.5
                frac = 0.5
                trades.append({"date": str(dates[i]), "action": "ST翻空賣一半", "px": round(px, 2),
                              "pnl_pct": round(pnl_pct, 2)})

        # 再檢查②RS(60日)跌破自己的60MA(即rs_60由正轉負)→剩餘全出
        if frac > 0.0 and rs_60[i] is not None and i > 0 and rs_60[i - 1] is not None:
            crossed_down = rs_60[i - 1] >= 0 and rs_60[i] < 0
            if crossed_down:
                pnl_pct = (px / entry_px - 1) * 100
                realized_pct_sum += pnl_pct * frac
                trades.append({"date": str(dates[i]), "action": f"RS跌破60MA全出(剩{frac*100:.0f}%)",
                              "px": round(px, 2), "pnl_pct": round(pnl_pct, 2)})
                frac = 0.0
                entry_px = None

        # 4倍下限對照組：不管 RS、不管籃子，只看價格有沒有真的跌破 4 倍寬的線
        if frac4 == 1.0 and dr4[i] is not None and dr4[i - 1] is not None:
            broke4 = dr4[i] == -1 and dr4[i - 1] == 1
            if broke4:
                pnl_pct4 = (px / entry_px4 - 1) * 100
                realized_pct4_sum += pnl_pct4
                trades4.append({"date": str(dates[i]), "action": "跌破4倍線全出", "px": round(px, 2),
                               "pnl_pct": round(pnl_pct4, 2)})
                frac4 = 0.0
                entry_px4 = None

        # confirmed 對照組：①ST單獨翻空→賣一半（跟現行規則同一個條件）
        if fracC == 1.0:
            flip_bearC = dr[i] == -1 and dr[i - 1] == 1
            if flip_bearC:
                pnl_pctC = (px / entry_pxC - 1) * 100
                realized_pctC_sum += pnl_pctC * 0.5
                fracC = 0.5
                tradesC.append({"date": str(dates[i]), "action": "ST翻空賣一半", "px": round(px, 2),
                               "pnl_pct": round(pnl_pctC, 2)})
        # confirmed 對照組：②全出條件改成「RS<0 且 ST當下也是空頭」（狀態同時成立才觸發，
        # 不是crossing事件——不管誰先發生，只要兩個條件同一天都成立就全出）
        if fracC > 0.0 and rs_60[i] is not None and dr[i] == -1:
            confirmedC = rs_60[i] < 0
            if confirmedC:
                pnl_pctC = (px / entry_pxC - 1) * 100
                realized_pctC_sum += pnl_pctC * fracC
                tradesC.append({"date": str(dates[i]), "action": f"RS且ST皆空全出(剩{fracC*100:.0f}%)",
                               "px": round(px, 2), "pnl_pct": round(pnl_pctC, 2)})
                fracC = 0.0
                entry_pxC = None

    if entry_i is None:
        return None       # 這檔窗口內從沒進場——不算「有效模擬」，跟原本行為一致

    # 期末還有未平倉部位：用最後一天收盤價算未實現損益，一併計入才不會低估/高估績效
    unrealized_pct = 0.0
    if frac > 0.0 and entry_px:
        unrealized_pct = (closes[-1] / entry_px - 1) * 100 * frac
    unrealized_pct4 = 0.0
    if frac4 > 0.0 and entry_px4:
        unrealized_pct4 = (closes[-1] / entry_px4 - 1) * 100
    unrealized_pctC = 0.0
    if fracC > 0.0 and entry_pxC:
        unrealized_pctC = (closes[-1] / entry_pxC - 1) * 100 * fracC

    def _max_dd(nav):
        """最大回檔：曲線上任一點相對「之前最高點」的最大跌幅百分比。"""
        peak, mdd = nav[0], 0.0
        for v in nav:
            peak = max(peak, v)
            if peak > 0:
                mdd = max(mdd, (peak - v) / peak * 100)
        return round(mdd, 2)

    return {"ticker": ticker, "trades": trades, "realized_pct": round(realized_pct_sum, 2),
            "unrealized_pct": round(unrealized_pct, 2), "still_held": frac > 0.0,
            "buyhold_pct": round((closes[-1] / closes[entry_i] - 1) * 100, 2),
            "trades4": trades4, "realized_pct4": round(realized_pct4_sum, 2),
            "unrealized_pct4": round(unrealized_pct4, 2), "still_held4": frac4 > 0.0,
            "tradesC": tradesC, "realized_pctC": round(realized_pctC_sum, 2),
            "unrealized_pctC": round(unrealized_pctC, 2), "still_heldC": fracC > 0.0,
            "dd_strat": _max_dd(nav_strat), "dd_st4": _max_dd(nav_st4),
            "dd_C": _max_dd(nav_C), "dd_bh": _max_dd(nav_bh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-30")
    ap.add_argument("--universe", default=None, help="逗號分隔ticker清單，預設用產業鏈全(七鏈聯集)")
    ap.add_argument("--atr", default="sma", choices=["wilder", "sma"],
                    help="SuperTrend 的 ATR 平滑法。預設 sma（2026-09-02 起策略層的實際算法）；wilder=換算法前的舊基準，留著對照用")
    args = ap.parse_args()
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()

    tickers = args.universe.split(",") if args.universe else chain_select_union()
    print(f"股票宇宙：{len(tickers)} 檔（產業鏈全）　回測起點：{args.start} 到今天\n")

    results = []
    for i, tk in enumerate(tickers, 1):
        r = simulate(tk, start_date, atr=args.atr)
        if r is None:
            continue
        results.append(r)
        total = r["realized_pct"] + r["unrealized_pct"]
        total4 = r["realized_pct4"] + r["unrealized_pct4"]
        totalC = r["realized_pctC"] + r["unrealized_pctC"]
        if r["trades"]:
            tag = "（未平倉）" if r["still_held"] else ""
            tag4 = "（未平倉）" if r["still_held4"] else ""
            tagC = "（未平倉）" if r["still_heldC"] else ""
            print(f"  [{i}/{len(tickers)}] {tk}: 策略{total:+.2f}%{tag}(dd{r['dd_strat']:.1f}%)　"
                 f"4倍線{total4:+.2f}%{tag4}(dd{r['dd_st4']:.1f}%)　"
                 f"RS+ST皆空{totalC:+.2f}%{tagC}(dd{r['dd_C']:.1f}%)　"
                 f"買進持有{r['buyhold_pct']:+.2f}%(dd{r['dd_bh']:.1f}%)")

    if not results:
        print("⚠️ 沒有任何股票有效模擬，可能資料不足或全部404。")
        return

    # 2026-09-16：全宇宙平均會被「從沒進場」的股票用 0% 稀釋（那些股票策略沒動作，
    # 但買進持有卻是真實的多年漲幅），不是在測出場規則好不好，是在測進場門檻嚴不嚴——
    # 兩個不同問題。公平比較一定要限定在「三種規則都用同一個進場點」的 traded 子集，
    # 拿掉 Leo 2026-09-15 那次的教訓（見 dev_log）。
    traded = [r for r in results if r["trades"]]
    if not traded:
        print("⚠️ 沒有任何股票觸發進場，三個規則都沒東西可比。")
        return

    # 2026-09-16：台股 yfinance 抓到的最後一根 K 棒偶爾是 NaN（跟 trade_plan.py
    # _drop_unclosed() 處理的是同一類問題，這支沒接那層防護）——未平倉的
    # unrealized_pct跟買進持有都要靠 closes[-1]，一筆 NaN 沒濾掉，sum() 整條平均
    # 就全部變 nan（2026-09-16 首次改完就撞到：2049.TW/3324.TWO/3653.TW）。
    # 每一欄都要各自濾，不能只濾其中一欄，否則其他欄還是會被同樣的NaN污染。
    # 2026-09-16 加第三個規則（RS+ST皆空才全出）後改成表格式迴圈，避免每加一個
    # 規則就要手動複製貼上四段幾乎一樣的程式碼（那正是前一版程式碼會長這麼亂的原因）。
    VARIANTS = [
        ("現行兩階段規則", "realized_pct", "unrealized_pct", "dd_strat"),
        ("4倍線下限全出", "realized_pct4", "unrealized_pct4", "dd_st4"),
        ("RS+ST皆空全出", "realized_pctC", "unrealized_pctC", "dd_C"),
    ]
    stats = {}
    for name, rk, uk, ddk in VARIANTS:
        rets = [r[rk] + r[uk] for r in traded]
        rets = [x for x in rets if x == x]              # 濾 NaN
        dds = [r[ddk] for r in traded if r[ddk] == r[ddk]]
        stats[name] = {"rets": rets, "dds": dds}
        print(f"{name}  平均報酬 {sum(rets)/len(rets):+.2f}%　"
             f"勝率(>0) {sum(1 for x in rets if x>0)/len(rets)*100:.0f}%　"
             f"平均最大回檔 {sum(dds)/len(dds):.1f}%")
    bh_rets = [r["buyhold_pct"] for r in traded if r["buyhold_pct"] == r["buyhold_pct"]]
    dd_bh = [r["dd_bh"] for r in traded if r["dd_bh"] == r["dd_bh"]]
    print(f"買進持有      平均報酬 {sum(bh_rets)/len(bh_rets):+.2f}%　"
         f"勝率(>0) {sum(1 for x in bh_rets if x>0)/len(bh_rets)*100:.0f}%　"
         f"平均最大回檔 {sum(dd_bh)/len(dd_bh):.1f}%")

    print(f"\n===== 彙總（限定 {len(traded)} 檔有觸發進場、同一進場點，才公平比較）=====")
    for name, rk, uk, _ in VARIANTS:
        pairs_bh = [(r[rk] + r[uk], r["buyhold_pct"]) for r in traded
                    if (r[rk] + r[uk]) == (r[rk] + r[uk]) and r["buyhold_pct"] == r["buyhold_pct"]]
        beat = sum(1 for a, b in pairs_bh if a > b)
        print(f"{name} 報酬贏過買進持有：{beat}/{len(pairs_bh)}")
    for name, rk, uk, _ in VARIANTS[1:]:
        pairs_strat = [(r[rk] + r[uk], r["realized_pct"] + r["unrealized_pct"]) for r in traded
                       if (r[rk] + r[uk]) == (r[rk] + r[uk])
                       and (r["realized_pct"] + r["unrealized_pct"]) == (r["realized_pct"] + r["unrealized_pct"])]
        beat = sum(1 for a, b in pairs_strat if a > b)
        print(f"{name} 報酬贏過現行兩階段規則：{beat}/{len(pairs_strat)}")

    n_full_exit = sum(1 for r in traded if any("全出" in t["action"] for t in r["trades"]))
    n_half_exit = sum(1 for r in traded if any("賣一半" in t["action"] for t in r["trades"]))
    n_still_held = sum(1 for r in traded if r["still_held"])
    n_full_exit4 = sum(1 for r in traded if r["trades4"])
    n_still_held4 = sum(1 for r in traded if r["still_held4"])
    n_full_exitC = sum(1 for r in traded if any("全出" in t["action"] for t in r["tradesC"]))
    n_still_heldC = sum(1 for r in traded if r["still_heldC"])
    print(f"\n訊號統計：{len(traded)}檔進場　現行規則—{n_half_exit}檔賣一半／"
         f"{n_full_exit}檔RS全出／{n_still_held}檔仍持有　　"
         f"4倍線規則—{n_full_exit4}檔跌破全出／{n_still_held4}檔仍持有　　"
         f"RS+ST皆空規則—{n_full_exitC}檔全出／{n_still_heldC}檔仍持有")

    # 2026-09-16 Leo：「RS全出是含ST為空嗎」——上面 n_full_exit 是「這檔股票的
    # 生命週期裡有沒有出現過 RS 全出」，一檔可能進出好幾次，混在一起看不出來
    # 每一次 RS 全出當下 ST 翻了沒有。這裡拆到「事件」層級，用當下記的 frac 分：
    # frac==100% 代表 RS 破線當下 ST 根本沒翻（AMD 那種單獨觸發）；
    # frac==50% 代表 ST 已經先翻空賣過一半了，RS 只是把剩下的清掉。
    rs_events = [t for r in traded for t in r["trades"] if "RS跌破60MA全出" in t["action"]]
    rs_pure = sum(1 for t in rs_events if "剩100%" in t["action"])
    rs_after_st = sum(1 for t in rs_events if "剩50%" in t["action"])
    print(f"\nRS全出事件拆解：共 {len(rs_events)} 次——"
         f"{rs_pure} 次是「ST還沒翻空、RS單獨觸發」（跟AMD同一種）、"
         f"{rs_after_st} 次是「ST已經翻空賣過一半、RS再清剩下的」")

    days = (datetime.now().date() - start_date).days
    print(f"\n⚠️ 樣本量提醒：回測窗只有{days}天（約{days//7}週），{len(traded)}檔觸發進場——"
         "跟supertrend_backtest_findings.md既有的5.5年回測比是極短樣本，"
         "只能看方向、不能當策略定論。")


if __name__ == "__main__":
    main()
