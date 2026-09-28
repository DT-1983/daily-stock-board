# -*- coding: utf-8 -*-
"""回測：RS＋EC 接力訊號（嚴格版）出現後，20／60 個交易日的報酬（2026-09-28，Leo：「回測」）。

問題：接力訊號（market_relay_scan／產業輪動頁同定義）有沒有預測力？值不值得放進燈號當條件？

設計（避免前視偏差——9/5、9/6 都踩過「漂亮但錯」的回測）：
- 訊號定義跟上線版一模一樣：RS 比值線（股價/大盤）在 120 日新高、EC 動能 10 日內由負翻正且仍 >0、
  大盤收盤站上 60 日均線。全部只用「當天收盤以前」的資料。
- 進場：訊號日**隔天開盤**（當天收盤才知道訊號，不能用當天收盤價進場）。出場：進場後第 20／60 個交易日收盤。
- 同一檔連續符合只算第一天（前 10 個交易日沒訊號才算新事件）。
- 基準＝同一天「全市場每檔都買」的平均報酬（同樣隔天開盤進、同樣持有天數）。
  超額報酬＝接力股報酬 − 同日全市場平均。另附大盤指數同期報酬。
- 統計：先把同一天的事件平均成一個數（同日事件高度相關，不能當獨立樣本），再對「日」算平均與標準誤。
- 分組：訊號當天「距 60 日成本」的全市場位階（🔴前1%／🟡前1～5%／🟢其他，門檻逐日重算）；前半段／後半段期間。

⚠️ 已知限制（報告裡要講）：
- 倖存者偏差：母體是「今天」還在交易的股票（TradingView 今天的清單），期間下市的不在裡面；
  美股市值 ≥5 億美元也是用今天的市值篩 → 偏向活下來、長大的公司，報酬會偏高，但接力股跟基準都吃同一個偏差，
  **超額報酬**受影響較小。
- 期間只有快取裡的 2～3 年（2023/9～2026/9），基本上是多頭；空頭時期的表現沒測到。
用法：python backtest_relay.py [--market tw|us|all]
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import industry_rotation as ir          # noqa: E402
import market_relay_scan as mrs         # noqa: E402
import price_store                      # noqa: E402
import technical_indicators as ti       # noqa: E402

HORIZONS = (20, 60)
NEWHIGH = ir.RS_NEWHIGH_LOOKBACK        # 120
WIN = ir.RELAY_WIN                      # 10
MKT_MA = ir.MKT_MA                      # 60
WARMUP = 130


def _panel(market):
    uni = mrs.universe(market)
    syms = [u["yf"] for u in uni]
    bench_tk = ir._MARKET_BENCH[market]
    px = price_store.get_ohlc(syms + [bench_tk], period="3y", refresh=False)
    b = px.get(bench_tk)
    if b is None or b.empty:
        raise RuntimeError(f"快取沒有大盤 {bench_tk}")
    idx = b.index
    cols = {}
    for u in uni:
        h = px.get(u["yf"])
        if h is None or h.empty or not {"Open", "High", "Low", "Close", "Volume"} <= set(h.columns):
            continue
        cols[u["ticker"]] = h.reindex(idx)
    return uni, b["Close"], cols


def _signals(h, bclose):
    """回 (relay 布林序列, 距60日成本%序列)。只用當天以前的資料。"""
    C, H, L, V = h["Close"], h["High"], h["Low"], h["Volume"]
    ok = C.notna() & H.notna() & L.notna()
    n = len(C)
    relay = np.zeros(n, dtype=bool)
    d60 = np.full(n, np.nan)
    if ok.sum() < WARMUP + 20:
        return relay, d60
    # RS 比值線與 120 日新高（含當天）
    line = (C / bclose).to_numpy()
    roll_max = pd.Series(line).rolling(NEWHIGH, min_periods=NEWHIGH).max().to_numpy()
    newhigh = np.where(np.isnan(roll_max), False, line >= roll_max)
    # EC 動能：只在有效列上算，再放回原位置
    vi = np.where(ok.to_numpy())[0]
    sq = ti.squeeze_momentum(H.iloc[vi].tolist(), L.iloc[vi].tolist(), C.iloc[vi].tolist())
    mom = np.full(n, np.nan)
    if sq is not None:
        mom[vi] = np.array(sq["momentum"], dtype=float)
    up = np.zeros(n, dtype=bool)
    up[1:] = (mom[:-1] <= 0) & (mom[1:] > 0)
    up_recent = pd.Series(up).rolling(WIN, min_periods=1).max().to_numpy().astype(bool)
    ec = up_recent & (mom > 0)
    # 大盤站上 60MA
    bma = bclose.rolling(MKT_MA, min_periods=MKT_MA).mean()
    mkt = (bclose > bma).to_numpy()
    relay = newhigh & ec & mkt & ok.to_numpy()
    # 距 60 日成本：60 根典型價×量 / 量（跟 avwap.dist_from_df 同算法）
    tp = (H + L + C) / 3
    pv = (tp * V).rolling(60, min_periods=60).sum()
    vv = V.rolling(60, min_periods=60).sum()
    d60 = ((C / (pv / vv) - 1) * 100).to_numpy()
    return relay, d60


def _fwd(h, hz):
    """隔天開盤進、持有 hz 天後收盤出的報酬（對齊到訊號日 t）。"""
    O, C = h["Open"], h["Close"]
    entry = O.shift(-1).where(lambda s: s > 0)             # 開盤 0＝資料錯（會除出 inf）
    exitp = C.shift(-hz).where(lambda s: s > 0)
    r = (exitp / entry - 1).to_numpy()
    r[~np.isfinite(r)] = np.nan
    # 持有 20／60 日內 >+300% 或 <−90% 幾乎都是資料錯（除權沒調整、單日壞點），排除並計數
    bad = (r > 3) | (r < -0.9)
    _fwd.dropped = getattr(_fwd, "dropped", 0) + int(np.nansum(bad))
    r[bad] = np.nan
    return r


def run(market):
    uni, bclose, cols = _panel(market)
    tks = list(cols)
    dates = bclose.index
    n = len(dates)
    print(f"[{market}] 母體 {len(uni)} 檔，有快取 {len(tks)} 檔，期間 {dates[0].date()}～{dates[-1].date()}（{n} 日）")
    R = {hz: np.full((len(tks), n), np.nan) for hz in HORIZONS}
    S = np.zeros((len(tks), n), dtype=bool)
    D = np.full((len(tks), n), np.nan)
    for i, tk in enumerate(tks):
        h = cols[tk]
        try:
            S[i], D[i] = _signals(h, bclose)
        except Exception:                                   # noqa: BLE001
            pass
        for hz in HORIZONS:
            R[hz][i] = _fwd(h, hz)
    # 只算事件第一天：前 WIN 天沒訊號
    prev = np.zeros_like(S)
    for k in range(1, WIN + 1):
        prev[:, k:] |= S[:, :-k]
    E = S & ~prev
    # 逐日全市場「距60日成本」門檻
    p95 = np.nanpercentile(D, 95, axis=0)
    p99 = np.nanpercentile(D, 99, axis=0)
    tier = np.where(D >= p99, "hot", np.where(D >= p95, "warm", "ok"))
    # 大盤同期報酬（隔天開盤→hz 天後收盤，用收盤近似開盤：指數開盤價缺漏多）
    bench_fwd = {hz: (bclose.shift(-hz) / bclose.shift(-1) - 1).to_numpy() for hz in HORIZONS}
    half = dates[WARMUP + (n - WARMUP) // 2]
    out = {"market": market, "universe": len(uni), "cached": len(tks),
           "period": [str(dates[0].date()), str(dates[-1].date())], "split": str(half.date()), "results": {}}
    for hz in HORIZONS:
        base = np.nanmean(R[hz], axis=0)                    # 同日全市場平均
        groups = {"全部": E, "🔴 過熱(前1%)": E & (tier == "hot"),
                  "🟡 偏熱(前1～5%)": E & (tier == "warm"), "🟢 其他": E & (tier == "ok"),
                  "前半段": E & (dates < half)[None, :], "後半段": E & (dates >= half)[None, :]}
        res = {}
        for g, M in groups.items():
            ii, jj = np.where(M & ~np.isnan(R[hz]))
            if len(ii) == 0:
                res[g] = {"n": 0}
                continue
            ret = R[hz][ii, jj]
            exc = ret - base[jj]
            # 同日事件先平均成一個數，再對「日」算平均與標準誤
            by_day = pd.Series(exc).groupby(jj).mean()
            se = by_day.std(ddof=1) / math.sqrt(len(by_day)) if len(by_day) > 1 else float("nan")
            res[g] = {"n": int(len(ii)), "days": int(len(by_day)),
                      "ret_mean": round(float(np.mean(ret)) * 100, 2),
                      "ret_median": round(float(np.median(ret)) * 100, 2),
                      "base_mean": round(float(np.mean(base[jj])) * 100, 2),
                      "bench_mean": round(float(np.nanmean(bench_fwd[hz][jj])) * 100, 2),
                      "excess_mean": round(float(by_day.mean()) * 100, 2),
                      # 中位數：少數大漲股會把平均拉高，只看平均會誤判「大多數接力股」的表現
                      "excess_median": round(float(np.median(exc)) * 100, 2),
                      # 頭尾各 1% 不算的平均（極端值敏感度）
                      "excess_trim": round(float(np.mean(np.clip(exc, *np.percentile(exc, [1, 99])))) * 100, 2),
                      "excess_t": round(float(by_day.mean() / se), 2) if se and se == se else None,
                      "beat_pct": round(float(np.mean(exc > 0)) * 100, 1)}
        out["results"][str(hz)] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="all")
    a = ap.parse_args()
    ms = ["tw", "us"] if a.market == "all" else [a.market]
    allres = {"date": dt.date.today().isoformat(), "markets": {}}
    for m in ms:
        r = run(m)
        allres["markets"][m] = r
        for hz, res in r["results"].items():
            print(f"\n[{m}] 持有 {hz} 日　（超額＝接力股 − 同日全市場平均；t＞2 才算明顯）")
            for g, x in res.items():
                if not x.get("n"):
                    print(f"  {g}: 無事件")
                    continue
                print(f"  {g:<12} 事件{x['n']:>5}（{x['days']}天）　報酬 平均{x['ret_mean']:+6.2f}% 中位{x['ret_median']:+6.2f}%　"
                      f"全市場{x['base_mean']:+6.2f}%　大盤{x['bench_mean']:+6.2f}%　超額 平均{x['excess_mean']:+6.2f}%（t={x['excess_t']}）"
                      f" 中位{x['excess_median']:+6.2f}% 去極端{x['excess_trim']:+6.2f}%　贏過全市場 {x['beat_pct']}%")
        print(f"  （排除資料錯誤報酬 {getattr(_fwd, 'dropped', 0)} 筆）")
        _fwd.dropped = 0
    os.makedirs("state", exist_ok=True)
    with open("state/backtest_relay.json", "w", encoding="utf-8") as f:
        json.dump(allres, f, ensure_ascii=False, indent=1)
    print("\n已存 state/backtest_relay.json")


if __name__ == "__main__":
    main()
