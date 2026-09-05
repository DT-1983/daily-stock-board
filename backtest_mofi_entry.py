# -*- coding: utf-8 -*-
"""回測老墨的進場組合：擠壓釋放（閃電）→ 動能翻紅 → N 日內出現 RS 粉紅/藍點。

## 規則從哪來（2026-09-05，Leo 上課筆記 + 老墨自己的影片逐字稿）

Leo 轉述：「EXCEED CHARGE 出現閃電，十日內 RS 出現粉紅、藍點，是個很好的進場訊號」。
回去查我們 9/3 抓的老墨 XQ 教學逐字稿（obis youtube_learning），他自己的說法是：

> 充能爆發指標：市場沒方向時進入「擠壓」狀態，擠壓到最後會「釋放（閃電符號）」，
> **看釋放後變紅柱還綠柱決定方向**。搭配 SuperTrend 使用。

⭐ 所以**閃電 = 擠壓釋放**，但**釋放本身不是方向**——釋放後動能柱紅(>0)才是偏多。
只掃「釋放」會把往下噴的那一半也算成買訊。

RS 三點定義（同一份筆記）：🟡長線RS轉正／🔵短線RS創新高／🩷創新高但股價未創＝
資金流入比股價快。與 `technical_indicators.rs_signal_series()` 既有實作一致，
RS 週期 60/240 也對得上他的「短期一季／長期一年」。

## ⚠️ 動這支之前必讀 memory/supertrend_backtest_findings.md

那份記錄了三個我犯過的判斷錯誤，這支刻意避開：
1. **短樣本不能判策略生死** → 預設 5 年，不用「過去兩週」。
2. **不對等基準** → 同池同期的「隨機日」報酬當基準，不是拿別的池子比。
3. **前視偏差要講明** → 母體是**今天的**守備清單，倖存者偏差無法消除，只能標註。

## 這支不做什麼

⚠️ 不改任何既有門檻、不動 `COMBO_MIN`、不碰模擬倉。**只輸出數字**，
要不要採用是 Leo 的決定（硬規則：不自行變更投資方法門檻/母體/排序）。

用法:
    python backtest_mofi_entry.py                    # 預設 5 年、RS 窗 10 日
    python backtest_mofi_entry.py --years 5 --rs-window 10 --pool 60
    python backtest_mofi_entry.py --eval 10,20,60
"""
import argparse
import io
import json
import os
import statistics as st
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                           # noqa: E402
import technical_indicators as ti                            # noqa: E402


def pool(limit=None):
    """母體＝守備清單（combo_scan 掃的那批）。⚠️ 是**今天的**名單，有倖存者偏差。"""
    try:
        import combo_scan
        tks = list(combo_scan.watchlist())
    except Exception:                                        # noqa: BLE001
        cr = json.load(io.open("state/combo_result.json", encoding="utf-8"))
        rows = cr.get("rows") or cr.get("items") or []
        tks = [r["ticker"] for r in rows if r.get("ticker")]
    seen, out = set(), []
    for t in tks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit] if limit else out


def series_for(tk, years):
    """回 (closes, highs, lows, bench_closes, index) 或 None。用 yfinance 直取，
    period 拉長；price_store 的快取只有 3 年，這裡要 5 年。"""
    import yfinance as yf
    import re
    import tw_symbol
    is_tw = bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(tk)))
    sym = tw_symbol.resolve(tk) if is_tw else str(tk).replace(".", "-")
    bench_sym = "^TWII" if is_tw else "^GSPC"
    try:
        h = yf.Ticker(sym).history(period=f"{years}y", auto_adjust=True)
        if h.empty or len(h) < 400:
            return None
        b = yf.Ticker(bench_sym).history(period=f"{years}y", auto_adjust=True)
        if b.empty:
            return None
    except Exception:                                        # noqa: BLE001
        return None
    # ⭐ 基準必須 reindex 到個股的日期軸——長度一樣不代表日期一樣
    # （2026-09 踩過：RS 全檔 off-by-one 就是漏了這一步）。
    bs = b["Close"].reindex(h.index).ffill().bfill()
    return (h["Close"].tolist(), h["High"].tolist(), h["Low"].tolist(),
            bs.tolist(), [str(x)[:10] for x in h.index])


def entries(tk, years, rs_window, require_st=False):
    """回這檔在樣本期內所有符合的進場日 index，以及供評估的收盤序列。"""
    d = series_for(tk, years)
    if not d:
        return None, None
    closes, highs, lows, bench, idx = d
    sq = ti.squeeze_momentum(highs, lows, closes)
    if not sq:
        return None, None
    on, mom = sq["squeeze_on"], sq["momentum"]

    rs_s = ti.mansfield_rs_series(closes, bench, 60)
    rs_l = ti.mansfield_rs_series(closes, bench, 240)
    if rs_s is None or rs_l is None:
        return None, None
    _turn, newh, lead = ti.rs_signal_series(rs_s, rs_l, closes)

    stdir = None
    if require_st:
        stx = ti.double_typhoon(highs, lows, closes)
        stdir = stx["dir"] if stx else None

    # ⭐ 一次算三個版本（同一次抓資料）：要回答「RS 那個點有沒有加分」，
    # 就必須有「拿掉它」的對照組，不然只知道整套有效、不知道哪一段有效。
    v_full, v_nors, v_bare = [], [], []
    n = len(closes)
    for i in range(1, n):
        # ① 閃電＝擠壓釋放：前一根在擠壓、這一根跳出來
        try:
            fired = bool(on[i - 1]) and not bool(on[i])
        except (IndexError, TypeError, ValueError):
            continue
        if not fired:
            continue
        if require_st and stdir is not None and not (i < len(stdir) and stdir[i] == 1):
            continue
        v_bare.append(i)
        # ② 釋放後動能柱要紅（>0）——老墨：「看釋放後變紅柱還綠柱決定方向」
        m = mom[i] if i < len(mom) else None
        if m is None or (isinstance(m, float) and np.isnan(m)) or m <= 0:
            continue
        v_nors.append(i)
        # ③ 之後 rs_window 個交易日內出現 🩷 或 🔵
        j1 = min(n, i + rs_window + 1)
        if any((newh[j] is not None) or (lead[j] is not None) for j in range(i, j1)):
            v_full.append(i)
    return {"full": v_full, "no_rs": v_nors, "bare": v_bare}, closes


def fwd(closes, i, k):
    """i 日進場、k 個交易日後的報酬(%)。

    🔴 2026-09-05 首跑抓到：原本沒擋 NaN，18 萬筆基準樣本裡混到一筆壞資料，
    **整個「60 日基準平均」變成 nan**。中位數不受影響所以差點沒發現。
    ⭐ 一個 NaN 就能污染整組平均，但中位數會若無其事——**兩個一起看才看得出來**。
    """
    if i + k >= len(closes):
        return None
    a_, b_ = closes[i], closes[i + k]
    for v in (a_, b_):
        if v is None or (isinstance(v, float) and v != v) or v == 0:
            return None
    return (b_ / a_ - 1) * 100


def describe(name, vals, base=None):
    if not vals:
        print(f"  {name:26} 無樣本")
        return
    med = st.median(vals)
    avg = sum(vals) / len(vals)
    win = sum(1 for v in vals if v > 0) / len(vals) * 100
    line = (f"  {name:26} n={len(vals):5}  中位 {med:+6.2f}%  平均 {avg:+6.2f}%"
            f"  勝率 {win:5.1f}%")
    if base:
        line += f"  vs 基準 {med - st.median(base):+6.2f}pp"
    print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--rs-window", type=int, default=10, help="閃電後幾個交易日內要出現 RS 點")
    ap.add_argument("--eval", default="10,20,60", help="訊號後幾日評估報酬")
    ap.add_argument("--pool", type=int, default=0, help="只取前 N 檔（除錯用）")
    ap.add_argument("--with-supertrend", action="store_true",
                    help="加上 SuperTrend 多方（老墨說搭配用，但他沒說是必要條件）")
    a = ap.parse_args()
    evals = [int(x) for x in a.eval.split(",")]

    tks = pool(a.pool or None)
    print(f"母體 {len(tks)} 檔（今天的守備清單，⚠️ 有倖存者偏差）｜"
          f"樣本 {a.years} 年｜RS 窗 {a.rs_window} 個交易日"
          + ("｜加 SuperTrend 多方" if a.with_supertrend else ""))
    print("規則：擠壓釋放（閃電）→ 該根動能柱 > 0（紅柱）→ 窗內出現 🩷 或 🔵")
    print()

    VAR = [("bare", "① 只有閃電（擠壓釋放）"),
           ("no_rs", "② 閃電 + 動能紅柱"),
           ("full", "③ 閃電 + 紅柱 + RS 點  <- 老墨全套")]
    sig = {v: {k: [] for k in evals} for v, _ in VAR}
    base = {k: [] for k in evals}
    cnt = {v: 0 for v, _ in VAR}
    ok = skip = 0
    for c, tk in enumerate(tks, 1):
        hits, closes = entries(tk, a.years, a.rs_window, a.with_supertrend)
        if hits is None:
            skip += 1
            continue
        ok += 1
        for v, _lbl in VAR:
            cnt[v] += len(hits[v])
            for i in hits[v]:
                for k in evals:
                    x = fwd(closes, i, k)
                    if x is not None:
                        sig[v][k].append(x)
        # 基準：同一檔同一段期間的**所有交易日**（不是隨機抽樣，是全母體）
        # ⭐ 這樣「訊號日」跟「任何一天」才是同池同期的對等比較。
        for i in range(200, len(closes) - max(evals)):
            for k in evals:
                x = fwd(closes, i, k)
                if x is not None:
                    base[k].append(x)
        if c % 20 == 0:
            print(f"  ...{c}/{len(tks)} 檔，累計 {cnt}", flush=True)

    print()
    print(f"可用 {ok} 檔、跳過 {skip} 檔（資料不足）")
    print("訊號數：" + "｜".join(f"{lbl} {cnt[v]}" for v, lbl in VAR))
    print()
    print("訊號後報酬 vs 同池同期「任意一天進場」的基準：")
    for k in evals:
        print()
        print(f"【{k} 個交易日後】")
        describe("基準（任意一天）", base[k])
        for v, lbl in VAR:
            describe(lbl, sig[v][k], base[k])

    print()
    print("⚠️ 讀這張表的注意事項：")
    print("  1. 母體是**今天的**守備清單 → 有倖存者偏差，數字偏樂觀，不可消除只能標註。")
    print("  2. 沒有計交易成本、沒有做部位管理，這是**訊號診斷**不是策略回測。")
    print("  3. 跨市場（台股/美股）混在一起算；樣本 5 年含 2022 空頭。")
    print("  4. 這支不改任何門檻、不動模擬倉——要不要採用是 Leo 的決定。")

    def _stat(vals):
        if not vals:
            return None
        return {"n": len(vals), "median": st.median(vals),
                "mean": sum(vals) / len(vals),
                "win": sum(1 for x in vals if x > 0) / len(vals) * 100}
    out = {"years": a.years, "rs_window": a.rs_window, "pool_n": len(tks),
           "usable": ok, "counts": cnt, "with_supertrend": a.with_supertrend,
           "result": {str(k): dict({"base": _stat(base[k])},
                                   **{v: _stat(sig[v][k]) for v, _ in VAR})
                      for k in evals}}
    p = f"bt_mofi_entry_{a.years}y_w{a.rs_window}{'_st' if a.with_supertrend else ''}.json"
    json.dump(out, io.open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n結果存 {p}（scratch 用，不進 repo）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
