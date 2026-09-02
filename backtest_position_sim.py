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
from technical_indicators import squeeze_momentum, mansfield_rs_series, _benchmark


def simulate(ticker, start_date, atr="wilder"):
    try:
        # 2026-09-02：原本寫死 period="1y"，所以再怎麼設 --start 都只能回測一年
        # ——預設起點 2026-06-30 只有 64 天、3~7 檔觸發，樣本小到不能下結論。
        # 改成依 start_date 往前多抓一年暖機（指標要 210 根以上才算得出來）。
        _need = (datetime.now().date() - start_date).days + 400
        _per = "2y" if _need <= 730 else ("5y" if _need <= 1825 else "10y")
        hist = yf.Ticker(ticker).history(period=_per)
        if hist.empty or len(hist) < 210:
            return None
        highs, lows, closes = hist["High"].tolist(), hist["Low"].tolist(), hist["Close"].tolist()
        bench = yf.Ticker(_benchmark(ticker)).history(period="1y")
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

    frac = 0.0          # 0 / 0.5 / 1.0 目前持倉比例
    entry_px = None
    trades = []          # 每筆實現損益記錄
    realized_pct_sum = 0.0   # 以「進場當時的部位比例」加權的實現報酬總和

    for i in range(max(start_i, 1), len(closes)):
        if dr[i] is None or dr[i - 1] is None or rs_30[i] is None:
            continue
        px = closes[i]

        if frac == 0.0:
            flip_bull = dr[i] == 1 and dr[i - 1] == -1
            fired = bool(sq["squeeze_on"][i - 1]) and not bool(sq["squeeze_on"][i]) if sq is not None else False
            if flip_bull and rs_30[i] > 0 and fired:
                frac = 1.0
                entry_px = px
                trades.append({"date": str(dates[i]), "action": "買進100%", "px": round(px, 2)})
            continue

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

    # 期末還有未平倉部位：用最後一天收盤價算未實現損益，一併計入才不會低估/高估績效
    unrealized_pct = 0.0
    if frac > 0.0 and entry_px:
        unrealized_pct = (closes[-1] / entry_px - 1) * 100 * frac

    return {"ticker": ticker, "trades": trades, "realized_pct": round(realized_pct_sum, 2),
            "unrealized_pct": round(unrealized_pct, 2), "still_held": frac > 0.0,
            "buyhold_pct": round((closes[-1] / closes[start_i] - 1) * 100, 2)}


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
        if r["trades"]:
            tag = "（未平倉）" if r["still_held"] else ""
            print(f"  [{i}/{len(tickers)}] {tk}: {len(r['trades'])}筆交易 策略{total:+.2f}%{tag}　"
                 f"買進持有{r['buyhold_pct']:+.2f}%")

    if not results:
        print("⚠️ 沒有任何股票有效模擬，可能資料不足或全部404。")
        return

    traded = [r for r in results if r["trades"]]
    strat_rets = [r["realized_pct"] + r["unrealized_pct"] for r in results]
    # 2026-09-02：yfinance 的 closes 偶爾夾 nan，算出的 buyhold_pct 也是 nan，
    # 一筆 nan 就會把整個平均汙染成 nan——對照組整欄變成 "+nan%"，等於沒有對照。
    # 過濾掉並印出排除幾筆，不要靜默丟資料。
    _bh_all = [r["buyhold_pct"] for r in results]
    bh_rets = [x for x in _bh_all if x == x]        # x != x 抓 NaN
    _bad = len(_bh_all) - len(bh_rets)
    if _bad:
        print(f"（買進持有對照排除 {_bad} 筆 NaN——來源資料有缺值）")

    print(f"\n===== 彙總（{len(results)}檔納入，{len(traded)}檔有觸發交易）=====")
    print(f"三訊號策略  平均報酬 {sum(strat_rets)/len(strat_rets):+.2f}%　"
         f"勝率(>0) {sum(1 for x in strat_rets if x>0)/len(strat_rets)*100:.0f}%")
    print(f"買進持有    平均報酬 {sum(bh_rets)/len(bh_rets):+.2f}%　"
         f"勝率(>0) {sum(1 for x in bh_rets if x>0)/len(bh_rets)*100:.0f}%")

    n_full_exit = sum(1 for r in results if any("全出" in t["action"] for t in r["trades"]))
    n_half_exit = sum(1 for r in results if any("賣一半" in t["action"] for t in r["trades"]))
    n_still_held = sum(1 for r in results if r["still_held"])
    print(f"\n訊號統計：{len(traded)}檔進場　{n_half_exit}檔觸發ST翻空賣一半　"
         f"{n_full_exit}檔觸發RS跌破60MA全出　{n_still_held}檔目前仍持有中")

    days = (datetime.now().date() - start_date).days
    print(f"\n⚠️ 樣本量提醒：回測窗只有{days}天（約{days//7}週），{len(traded)}檔觸發進場——"
         "跟supertrend_backtest_findings.md既有的5.5年回測比是極短樣本，"
         "只能看方向、不能當策略定論。")


if __name__ == "__main__":
    main()
