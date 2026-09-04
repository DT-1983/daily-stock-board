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
    # 🔴 連續性檢查（2026-09-03 加）：回補被證交所限流擋掉時，資料會變成「範圍很長
    # 但中間全是洞」。100 日均線是**連續 100 筆**算出來的，餵給它一段跨越幾個月空洞的
    # 序列，它照樣會算出一個數字——**看起來正常但完全沒有意義**。寧可不跑也不要跑出
    # 假的結論（同 silent_failure_pattern：算得出來不等於算對）。
    import datetime as _dt
    import json as _json
    import io as _io
    # 🔴 2026-09-04 修：原本用「期間天數 × 5/7 × 0.96」推估應有交易日數，再看
    # 實際筆數的比例。這個估法**把國定假日當成資料缺口**——2026 農曆年假連休
    # 7 個工作日、清明/端午/勞動節各再幾天，估出來的涵蓋率被系統性低估。
    # 實測：這樣算「最長連續段 215 天、涵蓋率 75%」→ 判定資料不足拒絕回測；
    # 但**扣掉已知休市日之後其實有 533 個連續交易日**，早就過門檻。
    # ⭐ 量測工具本身錯了，而它的輸出看起來完全正常（同 grep -c 數行不數次那次）。
    #
    # 正解：讀 `ef_ratio_closed.json`（證交所正常回應但無指數＝非交易日，
    # 抓取時就記下來了），週末與已知休市**跳過不算斷**，真的缺一個交易日才算斷。
    try:
        closed = set(_json.load(_io.open("state/ef_ratio_closed.json", encoding="utf-8")))
    except Exception:                                       # noqa: BLE001
        closed = set()
    have = set(dates)
    d0, d1 = _dt.date.fromisoformat(dates[0]), _dt.date.fromisoformat(dates[-1])
    best = cur = 0
    bs = be = cs = None
    d = d0
    while d <= d1:
        k = d.isoformat()
        if d.weekday() >= 5 or k in closed:
            d += _dt.timedelta(days=1)
            continue
        if k in have:
            if cur == 0:
                cs = k
            cur += 1
            if cur > best:
                best, bs, be = cur, cs, k
        else:
            cur = 0
        d += _dt.timedelta(days=1)
    print(f"連續性：扣掉週末與 {len(closed)} 個已知休市日後，"
          f"最長連續交易日 {best} 天（{bs} ~ {be}）")
    NEED = MA_DAYS + 250          # 100 天暖身 + 至少一年
    if best < NEED:
        print(f"🔴 最長連續段 {best} 天 < 需要的 {NEED} 天（{MA_DAYS} 暖身＋250 回測）"
              "——100 日均線會算在不連續的序列上，**結果沒有意義，拒絕回測**。")
        print("   補歷史：python market_thermometer.py --backfill 1200 --pause 2")
        print("   補舊缺口：python market_thermometer.py --fill-gaps 6")
        print("   ⚠️ 每日排程只掃最近 14 天，舊缺口不會自己補")
        return 1
    # 只拿**最長連續段**去回測，前面那些有洞的歷史不要混進來
    if bs and be:
        dates2 = [d_ for d_ in dates if bs <= d_ <= be]
        if len(dates2) < len(dates):
            print(f"   → 只用這一段回測：{len(dates2)}/{len(dates)} 筆")
            ratios = [ratios[dates.index(d_)] for d_ in dates2]
            dates = dates2
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
