# -*- coding: utf-8 -*-
"""回測：SuperTrend翻多+RS(30日)贏過大盤+EXCEED CHARGE剛噴出 三指標合流訊號，
vs 純SuperTrend單指標，訊號後續報酬比較。

背景（2026-08-11）：用戶想知道「多指標合流」是否比模擬倉現有的純SuperTrend策略準。
⚠️ 動這類判斷前先讀 memory/supertrend_backtest_findings.md——已有既定結論：
日線SuperTrend單獨用在高波動個股上，賣訊75%是錯的（正常回檔被誤判成反轉），
這也是為什麼paper_portfolio.py的趨勢倉後來改成週線判斷。本次假說剛好是想
用RS+EXCEED CHARGE當「降噪濾網」去解決這個已知問題，值得測，但：
1. 用戶要求的「過去兩週」樣本量太小，不能拿來下策略定論（同份memory記錄過
   「只看4週就判策略生死」是已犯過的錯）——本腳本會印出來但同時強制印警語。
2. 沿用既有評測方法論（訊號後N日報酬），跟memory裡的既有數據可比較，不重新發明指標。

用法：python backtest_combined_signal.py [--weeks 2] [--eval-days 5]
"""
import argparse
import yfinance as yf

import board_html_legacy as L
from paper_portfolio import chain_select_union
from technical_indicators import squeeze_momentum, mansfield_rs_series, _benchmark


def _signals_for(ticker, window_days, eval_days):
    """回這檔股票在偵測窗內每個SuperTrend翻燈點的(型態, 純ST報酬, 合流條件是否成立)。"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty or len(hist) < 210:
            return []
        highs, lows, closes = hist["High"].tolist(), hist["Low"].tolist(), hist["Close"].tolist()
        bench = yf.Ticker(_benchmark(ticker)).history(period="1y")
        bench_closes = bench["Close"].tolist() if not bench.empty else []
    except Exception:
        return []

    st = L.supertrend(highs, lows, closes)
    if not st:
        return []
    dr = st["dir"]
    sq = squeeze_momentum(highs, lows, closes)
    # mansfield_rs_series 內部用 min(len(closes),len(bench_closes)) 右對齊——台美交易日曆
    # 天數常不同，bench較短時回傳陣列比closes短，直接拿i去索引兩邊會對錯位（2026-08-11
    # 在backtest_position_sim.py/paper_portfolio.py都踩過同一個坑，這裡一併補上）。
    # 補None對齊到跟closes同長度，下面迴圈才能安心用同一個i。
    def _align(rs):
        if rs is None:
            return None
        pad = len(closes) - len(rs)
        vals = [None] * pad + list(rs) if pad > 0 else list(rs)
        return [None if (v is None or v != v) else v for v in vals]
    rs_s = _align(mansfield_rs_series(closes, bench_closes, 30)) if bench_closes else None  # 2026-08-11：25→30日
    n = len(closes)

    # 訊號偵測窗：最近 window_days 個交易日；但要留 eval_days 天算「訊號後報酬」，
    # 所以最新的 eval_days 天沒有訊號可評（資料還沒發生），偵測窗往前多抓一段
    detect_end = n - eval_days
    detect_start = max(200, detect_end - window_days)   # RS長線200日需要暖機

    out = []
    for i in range(detect_start, detect_end):
        if dr[i] is None or dr[i - 1] is None:
            continue
        flip_bull = dr[i] == 1 and dr[i - 1] == -1
        flip_bear = dr[i] == -1 and dr[i - 1] == 1
        if not (flip_bull or flip_bear):
            continue
        fwd_ret = (closes[i + eval_days] / closes[i] - 1) * 100
        sig_type = "buy" if flip_bull else "sell"

        # 2026-08-11 修正：不是「還在擠壓中」，是「擠壓剛噴出」——
        # squeeze_on 前一根True、這一根False，代表能量蓄積完成、方向剛炸開
        confirm = False
        if rs_s is not None and rs_s[i] is not None and sq is not None and i > 0:
            fired = bool(sq["squeeze_on"][i - 1]) and not bool(sq["squeeze_on"][i])
            if fired:
                if flip_bull:
                    confirm = rs_s[i] > 0
                else:
                    confirm = rs_s[i] < 0

        out.append({"ticker": ticker, "date": str(hist.index[i].date()),
                    "type": sig_type, "fwd_ret": fwd_ret, "confirmed": confirm})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=float, default=2.0, help="回溯幾週偵測訊號（交易日≈週數×5）")
    ap.add_argument("--eval-days", type=int, default=5, help="訊號後幾個交易日算報酬")
    ap.add_argument("--universe", default=None, help="逗號分隔ticker清單，預設用模擬倉七鏈聯集")
    args = ap.parse_args()
    window_days = round(args.weeks * 5)

    tickers = (args.universe.split(",") if args.universe else chain_select_union())
    print(f"股票宇宙：{len(tickers)} 檔　偵測窗：近{window_days}個交易日（≈{args.weeks}週）　"
          f"評估期：訊號後{args.eval_days}個交易日\n")

    all_sig = []
    for i, tk in enumerate(tickers, 1):
        sigs = _signals_for(tk, window_days, args.eval_days)
        all_sig.extend(sigs)
        if sigs:
            print(f"  [{i}/{len(tickers)}] {tk}: {len(sigs)} 個訊號")

    if not all_sig:
        print("\n⚠️ 這段期間沒有任何SuperTrend翻燈訊號，樣本數=0，無法比較。")
        return

    def stats(sigs, label):
        buys = [s for s in sigs if s["type"] == "buy"]
        sells = [s for s in sigs if s["type"] == "sell"]
        print(f"\n【{label}】訊號數 {len(sigs)}（買{len(buys)}／賣{len(sells)}）")
        if buys:
            avg = sum(s["fwd_ret"] for s in buys) / len(buys)
            win = sum(1 for s in buys if s["fwd_ret"] > 0) / len(buys) * 100
            print(f"  買訊後平均報酬 {avg:+.2f}%　勝率 {win:.0f}%")
        if sells:
            avg = sum(s["fwd_ret"] for s in sells) / len(sells)
            # 賣訊後續漲＝賣錯了（沿用supertrend_backtest_findings.md的既有評測邏輯）
            wrong = sum(1 for s in sells if s["fwd_ret"] > 0) / len(sells) * 100
            print(f"  賣訊後平均報酬 {avg:+.2f}%　賣錯率(續漲) {wrong:.0f}%")

    stats(all_sig, "純SuperTrend（不篩RS/EXCEED CHARGE）")
    confirmed = [s for s in all_sig if s["confirmed"]]
    stats(confirmed, "合流訊號（SuperTrend+RS+EXCEED CHARGE同時成立）")

    print(f"\n合流訊號篩掉了 {len(all_sig) - len(confirmed)}/{len(all_sig)} "
          f"（{(1 - len(confirmed)/len(all_sig))*100:.0f}%）個純SuperTrend訊號。")
    print("\n⚠️ 樣本量提醒：這是" + f"{args.weeks}週窗、{len(confirmed)}個合流訊號的小樣本，"
          "不能拿來下策略定論（memory/supertrend_backtest_findings.md 記錄過"
          "「只看4週就判策略生死」是已犯過的錯，該次事後證明短樣本方向是反的）。"
          "這裡只能看「方向對不對」，要真正決定要不要接進模擬倉，"
          "建議至少拉到近6個月甚至跟現有5.5年回測同期比較。")


if __name__ == "__main__":
    main()
