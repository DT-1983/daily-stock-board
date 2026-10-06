# -*- coding: utf-8 -*-
"""全市場 RS 排名＋RS＋EC 接力掃描（2026-09-28，參考老墨「技術面選股組合」）。

Leo：「RS＋EC 可以做全台美股市場嗎？」→「做 1」。
範圍：台股上市＋上櫃全部普通股、美股 NYSE＋NASDAQ 市值 ≥ 5 億美元（小型股資料缺漏多、假訊號多）。
訊號定義跟產業輪動頁完全一樣（9/28 起接力用嚴格版）（共用 industry_rotation._stock_signals／_market_filter），
差別只在排名範圍：這裡是全市場排名，產業輪動頁是各產業代表股之間排名。

輸出：docs/market_relay.json（只放接力清單＋各市場 RS 前 100，給產業輪動頁「全市場」按鈕讀）。
⚠️ 只能在本機跑：Yahoo 擋 GitHub Actions 的 IP。價格快取共用 state/price_store（已 gitignore）。
用法：python market_relay_scan.py [--limit N]（N 只取前 N 檔，測試用）
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import avwap                                        # noqa: E402
import industry_rotation as ir                      # noqa: E402
import price_store                                  # noqa: E402
from tradingview_screener import Query, col         # noqa: E402

US_MIN_CAP = 5e8
TOP_N = 100
CALC_BARS = 320          # 計算只用最近 320 根：120 日 RS＋120 日新高回看＋10 日窗口，綽綽有餘（實測比整段 3 年快 2.7 倍）
OUT = "docs/market_relay.json"


def universe(market):
    tv = {"tw": "taiwan", "us": "america"}[market]
    ex = ["TWSE", "TPEX"] if market == "tw" else ["NYSE", "NASDAQ"]
    w = [col("exchange").isin(ex), col("type") == "stock", col("close") > 0]
    if market == "us":
        w.append(col("market_cap_basic") >= US_MIN_CAP)
    # 2026-10-07：TradingView scanner 偶爾讀取逾時（預設 20 秒）→ 整支失敗、看板用舊資料。
    # 改成逾時放寬到 60 秒、失敗重試 3 次（間隔 5／15 秒）；三次都失敗才丟出例外（維持原本失敗行為，不靜默）。
    import time as _t
    last = None
    for _i in range(3):
        try:
            _, df = (Query().set_markets(tv)
                     .select("name", "description", "sector", "industry", "market_cap_basic", "close", "exchange",
                             "logoid", "volume")
                     .where(*w).order_by("market_cap_basic", ascending=False).limit(8000)
                     .get_scanner_data(timeout=60))
            break
        except Exception as e:                              # noqa: BLE001
            last = e
            print(f"  [relay] TradingView 第 {_i + 1} 次失敗：{str(e)[:80]}", flush=True)
            if _i < 2:
                _t.sleep(5 if _i == 0 else 15)
    else:
        raise last
    df = ir.dedupe_company(df)   # 同公司多檔只留一檔
    names = ir._tw_chinese_names() if market == "tw" else {}
    out = []
    for _, r in df.iterrows():
        code = str(r["name"])
        if market == "us" and "/" in code:
            continue                                   # 特別股
        yf_tk = (code + (".TW" if r["exchange"] == "TWSE" else ".TWO")) if market == "tw" else code.replace(".", "-")
        out.append({"ticker": code, "yf": yf_tk, "name": names.get(code) or r.get("description") or code,
                    "sector": r.get("sector") or "", "cap": float(r.get("market_cap_basic") or 0)})
    return out


def scan(market, limit=None):
    uni = universe(market)
    if limit:
        uni = uni[:limit]
    bench_tk = ir._MARKET_BENCH[market]
    t0 = time.time()
    # fill_gaps=False：不打 FinMind 補台股缺漏 K 棒（2,300 檔會用光免費額度，影響其他排程；
    # 120 日 RS／EC 少一根影響極小）
    px = price_store.get_ohlc([u["yf"] for u in uni] + [bench_tk], period="2y", fill_gaps=False)
    t1 = time.time()
    bench = px.get(bench_tk)
    if bench is None or bench.empty:
        raise RuntimeError(f"抓不到大盤 {bench_tk}")
    bench = bench["Close"]
    mkt = ir._market_filter(bench)
    rows, miss, glitch = [], 0, []
    for u in uni:
        h = px.get(u["yf"])
        if h is None or h.empty or not {"High", "Low", "Close"} <= set(h.columns):
            miss += 1
            continue
        # 2026-09-29：DCX 9/28 單日 0.13→16 美元（+12491%，反向分割沒調整）→ 假接力、距 60 日成本 +3247%
        # 上了 Discord。近 130 根內單日 >+150% 或 <−75% 幾乎都是資料錯，整檔排除（不進排名、分布、清單）。
        dr = h["Close"].iloc[-130:].pct_change()
        if (dr > 1.5).any() or (dr < -0.75).any():
            glitch.append(u["ticker"])
            continue
        try:
            s = ir._stock_signals(h.iloc[-CALC_BARS:], bench)
        except Exception:
            s = None
        if not s or s["rs"] is None:
            miss += 1
            continue
        rows.append({**{k: u[k] for k in ("ticker", "name", "sector", "cap")},
                     "close": round(float(h["Close"].iloc[-1]), 2), "asof": str(h.index[-1].date()),
                     # 2026-09-28 AVWAP：收盤距 60 日錨定均價 %（全市場分布＝紅黃綠門檻的來源）
                     "d60": avwap.dist_from_df(h, 60), **s})
    t2 = time.time()
    vals = sorted(r["rs"] for r in rows)
    n = len(vals)
    import bisect
    dq = avwap.quantiles([r["d60"] for r in rows])
    for r in rows:
        r["d60_pct"] = avwap.pct_rank(r["d60"], dq)
        r["rs_pct"] = round(100.0 * bisect.bisect_right(vals, r["rs"]) / n) if n else None
        # 2026-09-28 Leo 定案用嚴格版：今天 RS 在新高、EC 10 日內翻正、大盤站上 60MA（跟產業輪動頁同定義）
        both = r["ec_up_ago"] is not None and r["rs_hi_ago"] == 0
        r["relay"] = bool(both and mkt and mkt["ok"])
        r["relay_nomkt"] = bool(both and not r["relay"])
        # 舊的寬鬆版（兩事件都在 10 日內）留著對照
        r["relay_loose"] = bool(r["ec_up_ago"] is not None and r["rs_hi_ago"] is not None and mkt and mkt["ok"])
    print(f"  {market}: 範圍 {len(uni)} 檔，算出 {n} 檔（缺資料 {miss}），"
          f"抓價 {t1-t0:.0f} 秒、計算 {t2-t1:.0f} 秒；接力 {sum(r['relay'] for r in rows)}、"
          f"寬鬆版 {sum(r['relay_loose'] for r in rows)}、大盤濾網 {'✅' if mkt and mkt['ok'] else '❌'}")
    if glitch:
        print(f"  {market}: 價格資料異常排除 {len(glitch)} 檔（近半年單日 >+150% 或 <−75%）：{', '.join(glitch[:15])}")
    if dq:
        r_ = avwap.RES
        print(f"  {market}: 距 60 日成本 中位數 {dq[50*r_]:+.1f}%、前 5% 門檻 {dq[95*r_]:+.1f}%、前 1% 門檻 {dq[99*r_]:+.1f}%")
    return rows, mkt, len(uni), miss, dq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("-o", "--output", default=OUT)
    a = ap.parse_args()
    res = {"date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "us_min_cap": US_MIN_CAP, "markets": {}}
    for m in ("tw", "us"):
        rows, mkt, n_uni, miss, dq = scan(m, a.limit)
        keep = lambda r: {k: r[k] for k in ("ticker", "name", "sector", "cap", "close", "asof", "rs", "rs_pct",
                                              "ec_up_ago", "rs_hi_ago", "relay", "relay_nomkt", "relay_loose",
                                              "d60", "d60_pct")}
        relay = sorted([r for r in rows if r["relay"] or r["relay_nomkt"]], key=lambda r: -r["rs_pct"])
        top = sorted(rows, key=lambda r: -r["rs"])[:TOP_N]
        res["markets"][m] = {"mkt": mkt, "universe": n_uni, "scanned": len(rows), "missing": miss,
                             "relay": [keep(r) for r in relay], "top": [keep(r) for r in top],
                             # 距 60 日成本的全市場分布（0～100 分位點）；avwap.tier()/pct_rank() 讀這個
                             "d60_dist": dq,
                             "counts": {"relay": sum(r["relay"] for r in rows),
                                        "relay_loose": sum(r["relay_loose"] for r in rows),
                                        "ec_up": sum(r["ec_up_ago"] is not None for r in rows),
                                        "rs_high": sum(r["rs_hi_ago"] is not None for r in rows)}}
    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已存：{a.output}（{os.path.getsize(a.output)/1024:.0f} KB）")


if __name__ == "__main__":
    main()
