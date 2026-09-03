# -*- coding: utf-8 -*-
"""電金比大盤總開關回測（風險官 P2 的證據，2026-09-03）。

**要回答的問題**：老墨的規則是「電金比連 32 日低於 100MA → 開盤全部清倉」。
我們沒有他的回測，只看過他 bot 的輸出。這支自己跑一次，看這個規則對台股加權
到底有沒有用、以及 N=32 是不是真的比較好。

⚠️ **這支不會自己決定要不要採用**——它只產生證據。門檻要不要訂、訂多少，是 Leo 的
決定（照不自行發明投資判定門檻的鐵則）。

## 方法

- 訊號：電金比（電子工業類指數 ÷ 金融保險類指數）跟自己的 100 日均線比。
  連續 N 日在均線下 → 空手（持有現金）；否則持有台股加權指數。
- 對照組：買進持有台股加權。
- 進出點用**隔日開盤**近似（用當日收盤價會用到當天收盤後才知道的訊號 → 前視偏誤）。
  我們只有收盤指數，所以用**次一交易日的收盤**當成交價，比用當日收盤保守。

## 一定要一起看的限制

1. **樣本期間短**：電金比資料從證交所 API 回補而來，深度取決於已回補多少（會印出來）。
   兩三年只涵蓋一兩個循環，**不足以證明規則有效**，只能排除「明顯有害」。
2. **掃 N 會過擬合**：所以這支印**整條 N 的曲線**而不是只報最好的那個。
   如果只有某幾個 N 特別好、旁邊的 N 都差 → 那是雜訊不是訊號。
3. 不含交易成本與稅。台股來回約 0.6%，換手多的 N 會被高估。

用法:
    python ef_backtest.py                # 掃 N=1..40
    python ef_backtest.py --n 32         # 只看單一 N，印進出明細
"""
import os
import sys
import json
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HIST = "state/ef_ratio.json"
BENCH = "^TWII"
MA_DAYS = 100


def load_ratio():
    d = json.load(open(HIST, encoding="utf-8"))
    dates = sorted(d)
    return dates, [d[k]["ratio"] for k in dates]


def load_bench(dates):
    """台股加權收盤，對齊電金比的日期。抓不到的日期直接剔除（兩邊都不算）。"""
    import price_store
    closes = price_store.get_closes([BENCH], period="10y")
    s = closes.get(BENCH)
    if s is None or s.empty:
        return None
    m = {str(i)[:10]: float(v) for i, v in s.dropna().items()}
    out = [(dt, m[dt]) for dt in dates if dt in m]
    return out


def ma_series(vals, win):
    """第 i 個位置的值＝含當日往前 win 日的均線；不足 win 日回 None（不硬算半套）。"""
    out = []
    for i in range(len(vals)):
        if i + 1 < win:
            out.append(None)
        else:
            out.append(sum(vals[i - win + 1:i + 1]) / win)
    return out


def simulate(dates, ratios, bench, n):
    """回 (績效 dict, 交易明細)。n=連續幾日在均線下就空手。"""
    bmap = dict(bench)
    ma = ma_series(ratios, MA_DAYS)
    streak = 0
    pos = 1          # 1=持有指數 0=空手
    equity, bh = 1.0, 1.0
    curve, trades = [], []
    prev_px = None
    for i, dt in enumerate(dates):
        px = bmap.get(dt)
        if px is None or ma[i] is None:
            continue
        if prev_px is not None:
            r = px / prev_px - 1
            bh *= (1 + r)
            equity *= (1 + r * pos)         # pos 是**昨天收盤後**決定的，沒有前視
            curve.append((dt, equity, bh))
        prev_px = px
        # 今天收盤後更新訊號 → 明天才生效
        streak = streak + 1 if ratios[i] < ma[i] else 0
        new_pos = 0 if streak >= n else 1
        if new_pos != pos:
            trades.append((dt, "清倉" if new_pos == 0 else "回補", round(px, 1),
                           round(equity, 4)))
            pos = new_pos
    if not curve:
        return None, []
    yrs = len(curve) / 252
    peak = mdd = 0.0
    for _, e, _ in curve:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    peak_b = mdd_b = 0.0
    for _, _, b in curve:
        peak_b = max(peak_b, b)
        mdd_b = min(mdd_b, b / peak_b - 1)
    in_mkt = sum(1 for t in trades if t[1] == "回補")
    return {
        "n": n, "days": len(curve), "years": round(yrs, 2),
        "strategy_total": round((equity - 1) * 100, 2),
        "buyhold_total": round((bh - 1) * 100, 2),
        "strategy_cagr": round((equity ** (1 / yrs) - 1) * 100, 2) if yrs > 0 else 0,
        "buyhold_cagr": round((bh ** (1 / yrs) - 1) * 100, 2) if yrs > 0 else 0,
        "strategy_mdd": round(mdd * 100, 2), "buyhold_mdd": round(mdd_b * 100, 2),
        "trades": len(trades), "exits": len(trades) - in_mkt,
    }, trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, help="只測這一個 N，並印進出明細")
    ap.add_argument("--max-n", type=int, default=40)
    a = ap.parse_args()

    dates, ratios = load_ratio()
    print(f"電金比樣本：{len(dates)} 個交易日（{dates[0]} ~ {dates[-1]}）")
    bench = load_bench(dates)
    if not bench:
        print("抓不到台股加權指數，無法回測")
        return 1
    print(f"對齊後可用：{len(bench)} 天　"
          f"（扣掉 {MA_DAYS} 天暖身後實際回測 {max(0, len(bench)-MA_DAYS)} 天）")
    if len(bench) - MA_DAYS < 250:
        print("⚠️ 暖身後不足一年，結論只能當參考不能當證據——先把歷史補深再跑")

    if a.n:
        res, trades = simulate(dates, ratios, bench, a.n)
        if not res:
            print("樣本不足")
            return 1
        print(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"{os.linesep}進出明細（{len(trades)} 次）：")
        for dt, act, px, eq in trades:
            print(f"  {dt}  {act}　加權 {px:,.0f}　策略淨值 {eq}")
        return 0

    print(f"{os.linesep}{'N':>3} {'策略總報酬':>10} {'買抱總報酬':>10} "
          f"{'策略MDD':>9} {'買抱MDD':>9} {'進出次數':>8}")
    rows = []
    for n in range(1, a.max_n + 1):
        res, _ = simulate(dates, ratios, bench, n)
        if not res:
            continue
        rows.append(res)
        print(f"{n:>3} {res['strategy_total']:>9.2f}% {res['buyhold_total']:>9.2f}% "
              f"{res['strategy_mdd']:>8.2f}% {res['buyhold_mdd']:>8.2f}% {res['trades']:>8}")
    if rows:
        best = max(rows, key=lambda r: r["strategy_total"])
        beat = [r for r in rows if r["strategy_total"] > r["buyhold_total"]]
        print(f"{os.linesep}贏過買進持有的 N：{len(beat)}/{len(rows)} 個"
              f"　最佳 N={best['n']}（{best['strategy_total']:+.2f}% vs 買抱 "
              f"{best['buyhold_total']:+.2f}%）")
        print("⚠️ 只有少數 N 贏＝可能是雜訊；要一整段 N 都穩定贏才算有結構性證據")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
