# -*- coding: utf-8 -*-
"""老墨進場組合 ＋ 產業強弱過濾（2026-09-05，Leo 指定「回測」）。

## 為什麼要有這一支

`backtest_mofi_entry.py` 測出四個版本都沒有優勢，但那**不是老墨的完整流程**：
他是「**先由上而下挑出當下轉強的產業** → 再從裡面找領頭羊 → 才看那三個指標」。
少了最前面那層，等於把他的方法砍掉一半再說它沒用。這支把那層補上。

## 🔴 為什麼用 SPDR 類股 ETF 而不是我們生產版的 RRG 籃子

生產版（`industry_rotation.py`）2026-08-26 起改用「TradingView 分類 + **今天的**成分股
歷史股價聚合」。拿它回推 5 年會有**成分變動偏差**——今天的成分股名單套到 5 年前，
被剔除的公司完全消失。而且 `price_store` 只有 3 年，歷史 RRG 檔只存 250 個交易日。

改用 11 檔 SPDR 類股 ETF：
・ETF **自己處理成分調整**，沒有我需要重建的部分，也就沒有重建偏差
・價格序列是**真實可交易的**，5 年以上乾淨歷史
・當初換掉 SPDR 的理由是「ETF 查不到歷史股數，泡泡大小不能隨時間變」——
  **回測不需要泡泡大小，只需要象限**，那個理由在這裡不成立

⚠️ 代價要講明：**這支算出來的象限跟生產版看板的象限不會完全一樣**（兩把尺）。
它回答的是「產業強弱過濾有沒有用」這個概念問題，不是「照著看板點下去會怎樣」。

## 產業對照怎麼來

**不自己編 TradingView→GICS 對照表**——那是把領域事實寫死，錯了比沒有更糟。
改用 yfinance 每檔自己回報的 `sector`（GICS 體系），跟 SPDR 是一對一。查一次存快取。

用法:
    python backtest_mofi_rrg.py                      # 5 年、只在領先象限進場
    python backtest_mofi_rrg.py --quadrants leading,improving
    python backtest_mofi_rrg.py --refresh-sectors    # 重抓類股對照
"""
import argparse
import io
import json
import os
import statistics as stat
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backtest_mofi_entry as base                           # noqa: E402
import industry_rotation as ir                               # noqa: E402

SECTOR_CACHE = "bt_sector_gics.json"

# yfinance 回報的 GICS sector → SPDR 類股 ETF。這**不是我編的對照**，
# 是這兩套本來就一對一（SPDR 的 11 檔就是照 GICS 11 大類發行的）。
GICS_TO_SPDR = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}
BENCH = "SPY"


def load_sectors(tickers, refresh=False):
    """每檔的 GICS sector（yfinance 自己回報的）。查一次存快取。"""
    cache = {}
    if os.path.exists(SECTOR_CACHE) and not refresh:
        try:
            cache = json.load(io.open(SECTOR_CACHE, encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            cache = {}
    todo = [t for t in tickers if t not in cache]
    if todo:
        import yfinance as yf
        print(f"查 {len(todo)} 檔的類股（yfinance，之後走快取）…", flush=True)
        for n, t in enumerate(todo, 1):
            try:
                info = yf.Ticker(t.replace(".", "-")).info or {}
                cache[t] = info.get("sector")
            except Exception:                                # noqa: BLE001
                cache[t] = None
            if n % 25 == 0:
                print(f"  …{n}/{len(todo)}", flush=True)
        json.dump(cache, io.open(SECTOR_CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return cache


def sector_quadrants(years, period=60):
    """每個 SPDR 類股 ETF 逐日的 RRG 象限。回 {etf: {date: quadrant}}。

    ⭐ 直接複用生產版的 `rs_ratio_momentum()`——**不重寫公式**。它本來就回傳整段
    序列（畫軌跡尾巴要用），所以歷史象限是現成的，只是生產版只取最後一天。
    """
    import yfinance as yf
    import pandas as pd
    etfs = sorted(set(GICS_TO_SPDR.values()))
    print(f"抓 {len(etfs)} 檔 SPDR 類股 ETF + {BENCH}（{years} 年）…", flush=True)
    px = {}
    for t in etfs + [BENCH]:
        h = yf.Ticker(t).history(period=f"{years}y", auto_adjust=True)
        if h.empty:
            print(f"  ⚠️ {t} 抓不到")
            continue
        s = h["Close"].dropna()
        s.index = pd.to_datetime([str(x)[:10] for x in s.index])
        px[t] = s
    bench = px.get(BENCH)
    if bench is None:
        raise RuntimeError(f"抓不到基準 {BENCH}")

    out = {}
    for t in etfs:
        s = px.get(t)
        if s is None:
            continue
        rm = ir.rs_ratio_momentum(s, bench, periods=[period])
        if not rm:
            continue
        ratio, mom = rm[period]["ratio"], rm[period]["momentum"]
        q = {}
        for d in ratio.index:
            qq = ir.quadrant(ratio.get(d), mom.get(d))
            if qq:
                q[str(d)[:10]] = qq
        out[t] = q
        n_lead = sum(1 for v in q.values() if v == "leading")
        print(f"  {t}  {len(q)} 天　領先 {n_lead} 天（{n_lead/max(len(q),1)*100:.0f}%）")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--rs-window", type=int, default=10)
    ap.add_argument("--eval", default="10,20,60")
    ap.add_argument("--period", type=int, default=60, help="RRG 用哪個週期（生產版有 20/60/120/240）")
    ap.add_argument("--quadrants", default="leading", help="逗號分隔，例 leading,improving")
    ap.add_argument("--pool", type=int, default=0)
    ap.add_argument("--refresh-sectors", action="store_true")
    a = ap.parse_args()
    evals = [int(x) for x in a.eval.split(",")]
    want_q = {x.strip() for x in a.quadrants.split(",") if x.strip()}

    import re
    allp = base.pool(a.pool or None)
    us = [t for t in allp if not re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(t))]
    print(f"母體 {len(allp)} 檔，其中**美股 {len(us)} 檔**"
          f"（台股沒有對應的 SPDR 類股，這支只測美股）")
    print(f"樣本 {a.years} 年｜RRG 週期 {a.period}｜只在 {'/'.join(sorted(want_q))} 象限進場")
    print()

    secs = load_sectors(us, a.refresh_sectors)
    quads = sector_quadrants(a.years, a.period)

    mapped = {t: GICS_TO_SPDR.get(secs.get(t)) for t in us}
    n_ok = sum(1 for v in mapped.values() if v)
    print(f"\n對得到類股 ETF 的：{n_ok}/{len(us)} 檔")
    miss = sorted({secs.get(t) for t, v in mapped.items() if not v} - {None})
    if miss:
        print(f"  ⚠️ 沒有對應 SPDR 的 sector：{miss}")
    nosec = [t for t in us if not secs.get(t)]
    if nosec:
        print(f"  ⚠️ yfinance 查不到 sector 的 {len(nosec)} 檔：{', '.join(nosec[:10])}"
              + ("…" if len(nosec) > 10 else ""))

    VAR = [("bare", "① 只有閃電"), ("no_rs", "② 閃電+紅柱"),
           ("full", "③ 閃電→RS點"), ("pre", "④ RS點先→再閃電")]
    raw = {v: {k: [] for k in evals} for v, _ in VAR}
    flt = {v: {k: [] for k in evals} for v, _ in VAR}
    basel = {k: [] for k in evals}
    cnt_raw = {v: 0 for v, _ in VAR}
    cnt_flt = {v: 0 for v, _ in VAR}
    ok = 0

    for c, tk in enumerate(us, 1):
        etf = mapped.get(tk)
        d = base.series_for(tk, a.years)
        if not d:
            continue
        closes = d[0]
        idx = d[4]
        hits, _ = base.entries(tk, a.years, a.rs_window)
        if hits is None:
            continue
        ok += 1
        q = quads.get(etf, {}) if etf else {}
        for v, _lbl in VAR:
            for i in hits[v]:
                day = idx[i] if i < len(idx) else None
                inq = bool(day and q.get(day) in want_q)
                cnt_raw[v] += 1
                if inq:
                    cnt_flt[v] += 1
                for k in evals:
                    x = base.fwd(closes, i, k)
                    if x is None:
                        continue
                    raw[v][k].append(x)
                    if inq:
                        flt[v][k].append(x)
        for i in range(200, len(closes) - max(evals)):
            for k in evals:
                x = base.fwd(closes, i, k)
                if x is not None:
                    basel[k].append(x)
        if c % 20 == 0:
            print(f"  …{c}/{len(us)} 檔", flush=True)

    print()
    print(f"可用 {ok} 檔")
    print("訊號數（全部 → 只留產業在指定象限）：")
    for v, lbl in VAR:
        keep = f"{cnt_flt[v]/cnt_raw[v]*100:.0f}%" if cnt_raw[v] else "—"
        print(f"  {lbl:18} {cnt_raw[v]:5} → {cnt_flt[v]:5}（留下 {keep}）")

    for k in evals:
        print()
        print(f"【{k} 個交易日後】")
        base.describe("基準（任意一天）", basel[k])
        for v, lbl in VAR:
            base.describe(lbl + "　全部", raw[v][k], basel[k])
            base.describe(lbl + "　產業過濾後", flt[v][k], basel[k])

    print()
    print("⚠️ 注意事項：")
    print("  1. 象限用 **SPDR 類股 ETF** 算，跟生產版看板（TradingView 自組籃子）是兩把尺，")
    print("     數字不會一樣。這支回答「產業強弱過濾有沒有用」，不是「照看板點下去會怎樣」。")
    print("  2. 母體仍是今天的守備清單 → 倖存者偏差還在。")
    print("  3. 只測美股（台股沒有對應的 SPDR 類股 ETF）。")
    print("  4. 訊號診斷，非策略回測：無停損、無部位管理、未計成本。")

    def _s(vals):
        if not vals:
            return None
        return {"n": len(vals), "median": stat.median(vals),
                "win": sum(1 for x in vals if x > 0) / len(vals) * 100}
    out = {"years": a.years, "period": a.period, "quadrants": sorted(want_q),
           "us_n": len(us), "usable": ok, "cnt_raw": cnt_raw, "cnt_filtered": cnt_flt,
           "result": {str(k): dict({"base": _s(basel[k])},
                                   **{f"{v}_all": _s(raw[v][k]) for v, _ in VAR},
                                   **{f"{v}_rrg": _s(flt[v][k]) for v, _ in VAR})
                      for k in evals}}
    p = f"bt_mofi_rrg_{a.years}y_p{a.period}.json"
    json.dump(out, io.open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n結果存 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
