# -*- coding: utf-8 -*-
"""接力股什麼時候賣？出場規則回測（2026-09-28，Leo：「那接力股什麼時候賣掉?」）。

老墨「技術面選股組合」原文只講選股、沒有出場規則 → 只能拿我們系統現有的出場訊號回測比較，不自己編。
進場事件跟 backtest_relay.py 完全一樣（嚴格版接力、事件第一天、隔天開盤進）。

比較的賣法（出場訊號都是「當天收盤確認 → 隔天開盤賣」，最長抱 250 日；資料結束還沒賣的用最後收盤估值並計數）：
  固定20日／固定60日        ：對照組（backtest_relay 的做法）
  EC翻負                    ：EC 動能 ≤ 0
  ST翻空                    ：SuperTrend（Wilder，跟燈號倉／失效條件同一支）翻空
  RS60跌破                  ：Mansfield RS(60) < 0（失效條件「RS 跌破 60MA」同一支）
  跌破60日成本              ：收盤 < 60 日平均成本（AVWAP 同算法）
  燈號倉（ST賣半＋RS全出）   ：一半在 ST翻空 或 RS60跌破（先到者）賣，另一半在 RS60跌破 賣
基準：同期「全市場等權指數」（每天全部股票平均漲跌累乘），超額＝這筆報酬 − 同期全市場。
"""
import argparse
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_relay as br                     # noqa: E402
import technical_indicators as ti               # noqa: E402
from board_html_legacy import supertrend        # noqa: E402

MAX_HOLD = 250
RULES = ["固定20日", "固定60日", "EC翻負", "ST翻空", "RS60跌破", "跌破60日成本", "燈號倉(ST賣半+RS全出)",
         "ST賣半+RS百分位<60全出"]
# 2026-09-28 Leo：「supertrend 翻空賣一半，rs<60 全賣呢?」——「RS60 跌破」就是上面的燈號倉；
# 另一種解讀「RS 百分位 < 60」（產業輪動頁／接力清單顯示的全市場排名，Mansfield RS(120)）也一起測。
RS_PCT_EXIT = 60


def _series(h, bclose):
    C, H, L, V, O = h["Close"], h["High"], h["Low"], h["Volume"], h["Open"]
    ok = (C.notna() & H.notna() & L.notna()).to_numpy()
    n = len(C)
    vi = np.where(ok)[0]
    mom = np.full(n, np.nan)
    stdir = np.full(n, np.nan)
    rs60 = np.full(n, np.nan)
    if len(vi) > 80:
        Hl, Ll, Cl = H.iloc[vi].tolist(), L.iloc[vi].tolist(), C.iloc[vi].tolist()
        sq = ti.squeeze_momentum(Hl, Ll, Cl)
        if sq is not None:
            mom[vi] = np.array(sq["momentum"], dtype=float)
        st = supertrend(Hl, Ll, Cl)
        if st:
            stdir[vi] = np.array([np.nan if d is None else d for d in st["dir"]], dtype=float)
        rs = ti.mansfield_rs_series(Cl, bclose.iloc[vi].tolist(), 60)
        if rs is not None:
            rs60[vi] = np.array([np.nan if x is None else x for x in rs], dtype=float)
    tp = (H + L + C) / 3
    vw = ((tp * V).rolling(60, min_periods=60).sum() / V.rolling(60, min_periods=60).sum()).to_numpy()
    below_cost = C.to_numpy() < vw
    return {"O": O.to_numpy(), "C": C.to_numpy(), "mom": mom, "st": stdir, "rs": rs60, "below": below_cost}


def _first(cond, start, end):
    """cond[start:end] 裡第一個 True 的位置；沒有回 None。"""
    seg = cond[start:end]
    k = np.argmax(seg) if len(seg) else 0
    return start + k if len(seg) and seg[k] else None


def _trade(s, t, n):
    """訊號日 t → 各規則的 (報酬, 出場日索引, 是否未結束)。進場＝t+1 開盤。"""
    e = t + 1
    O, C = s["O"], s["C"]
    if e >= n or not (O[e] > 0):
        return None
    last = min(n - 1, e + MAX_HOLD)
    out = {}

    def sell_open(j):              # j＝訊號確認日（收盤），隔天開盤賣
        x = j + 1
        if x > n - 1:
            return C[n - 1] / O[e] - 1, n - 1, True
        px = O[x] if O[x] > 0 else C[x]
        return px / O[e] - 1, x, False

    for hz, name in ((20, "固定20日"), (60, "固定60日")):
        x = t + hz
        out[name] = (C[x] / O[e] - 1, x, False) if x <= n - 1 else (C[n - 1] / O[e] - 1, n - 1, True)
    conds = {"EC翻負": s["mom"] <= 0, "ST翻空": s["st"] == -1, "RS60跌破": s["rs"] < 0,
             "跌破60日成本": s["below"]}
    for name, cnd in conds.items():
        j = _first(cnd, e, last + 1)
        out[name] = sell_open(j) if j is not None else (C[last] / O[e] - 1, last, last == n - 1)
    # 燈號倉：一半在 ST翻空／RS跌破 先到者賣；另一半在 RS跌破 賣
    jr = _first(conds["RS60跌破"], e, last + 1)
    js = _first(conds["ST翻空"], e, last + 1)
    ja = min([j for j in (js, jr) if j is not None], default=None)
    a = sell_open(ja) if ja is not None else (C[last] / O[e] - 1, last, last == n - 1)
    b = sell_open(jr) if jr is not None else (C[last] / O[e] - 1, last, last == n - 1)
    out["燈號倉(ST賣半+RS全出)"] = (0.5 * a[0] + 0.5 * b[0], max(a[1], b[1]), a[2] or b[2])
    # ST 翻空賣一半；RS 百分位掉到 60 以下全出（先到的話兩半一起賣）
    jp = _first(s["rspct"] < RS_PCT_EXIT, e, last + 1)
    ja2 = min([j for j in (js, jp) if j is not None], default=None)
    a2 = sell_open(ja2) if ja2 is not None else (C[last] / O[e] - 1, last, last == n - 1)
    b2 = sell_open(jp) if jp is not None else (C[last] / O[e] - 1, last, last == n - 1)
    out["ST賣半+RS百分位<60全出"] = (0.5 * a2[0] + 0.5 * b2[0], max(a2[1], b2[1]), a2[2] or b2[2])
    return out


def _panel_lamp(market):
    """燈號母體（state/combo_result.json 今天的 242 檔）——只讀價格快取、不連網。"""
    import avwap
    import industry_rotation as ir
    import price_store
    rows = json.load(open("state/combo_result.json", encoding="utf-8"))["rows"]
    rows = [r for r in rows if avwap.market_of(r["ticker"]) == market and r.get("symbol")]
    bench_tk = ir._MARKET_BENCH[market]
    px = price_store.get_ohlc([r["symbol"] for r in rows] + [bench_tk], period="3y", refresh=False)
    b = px[bench_tk]
    cols = {}
    for r in rows:
        h = px.get(r["symbol"])
        if h is not None and not h.empty and {"Open", "High", "Low", "Close", "Volume"} <= set(h.columns):
            cols[r["ticker"]] = h.reindex(b.index)
    return rows, b["Close"], cols


def _lamp_events(h, bclose):
    """四燈亮到 ≥3 盞的第一天（前一天 <3）。跟燈號頁同一支 _lamp_series。
    ⚠️ 燈號倉進場還要「風報比 ≥1」，但歷史每天的分析師目標價沒存 → 重建不出來，這裡只用燈數。"""
    C, H, L, V = h["Close"], h["High"], h["Low"], h["Volume"]
    ok = (C.notna() & H.notna() & L.notna()).to_numpy()
    vi = np.where(ok)[0]
    n = len(C)
    lit3 = np.zeros(n, dtype=bool)
    if len(vi) < 150:
        return lit3
    Cl, Hl, Ll, Vl = C.iloc[vi].tolist(), H.iloc[vi].tolist(), L.iloc[vi].tolist(), V.iloc[vi].fillna(0).tolist()
    st = ti.double_typhoon(Hl, Ll, Cl)
    sq = ti.squeeze_momentum(Hl, Ll, Cl)
    lp = ti._lamp_series(Cl, Hl, Ll, Vl, bclose.iloc[vi].tolist(), st, sq, st)
    lit = np.sum(np.array(lp, dtype=float), axis=0)
    lit3[vi] = lit >= 3
    return lit3


def run(market, entry="relay"):
    if entry == "lamp":
        uni, bclose, cols = _panel_lamp(market)
    else:
        uni, bclose, cols = br._panel(market)
    tks = list(cols)
    dates = bclose.index
    n = len(dates)
    # 全市場等權指數（日報酬平均累乘；單日 |漲跌|>50% 視為資料錯排除）
    closes = pd.DataFrame({tk: cols[tk]["Close"] for tk in tks})
    dr = closes.pct_change(fill_method=None)
    dr = dr.where(dr.abs() <= 0.5)
    mkt = (1 + dr.mean(axis=1).fillna(0)).cumprod().to_numpy()
    # 每天全市場 RS 百分位（Mansfield RS 120，跟產業輪動頁／market_relay_scan 同定義）
    rsm = np.full((len(tks), n), np.nan)
    for i, tk in enumerate(tks):
        C = cols[tk]["Close"]
        vi = np.where(C.notna().to_numpy())[0]
        if len(vi) > 130:
            rs = ti.mansfield_rs_series(C.iloc[vi].tolist(), bclose.iloc[vi].tolist(), 120)
            if rs is not None:
                rsm[i, vi] = np.array([np.nan if x is None else x for x in rs], dtype=float)
    rspct = pd.DataFrame(rsm).rank(axis=0, pct=True).to_numpy() * 100
    rspct = np.where(np.isnan(rsm), np.nan, rspct)
    tk_i = {tk: i for i, tk in enumerate(tks)}
    rows = []
    for tk in tks:
        h = cols[tk]
        try:
            relay = _lamp_events(h, bclose) if entry == "lamp" else br._signals(h, bclose)[0]
        except Exception:                                    # noqa: BLE001
            continue
        if not relay.any():
            continue
        prev = np.zeros(n, dtype=bool)
        for k in range(1, br.WIN + 1):
            prev[k:] |= relay[:-k]
        ev = np.where(relay & ~prev)[0]
        if not len(ev):
            continue
        s = _series(h, bclose)
        s["rspct"] = rspct[tk_i[tk]]
        for t in ev:
            tr = _trade(s, t, n)
            if not tr:
                continue
            for rule, (ret, x, open_) in tr.items():
                if not np.isfinite(ret) or ret > 5 or ret < -0.95:
                    continue
                rows.append({"tk": tk, "t": int(t), "rule": rule, "ret": float(ret), "days": int(x - t),
                             "exc": float(ret - (mkt[x] / mkt[t] - 1)), "open": bool(open_)})
    df = pd.DataFrame(rows)
    res = {}
    for rule in RULES:
        g = df[df["rule"] == rule]
        if g.empty:
            continue
        res[rule] = {"n": int(len(g)), "open": int(g["open"].sum()),
                     "days_mean": round(float(g["days"].mean()), 1),
                     "ret_mean": round(float(g["ret"].mean()) * 100, 2),
                     "ret_median": round(float(g["ret"].median()) * 100, 2),
                     "win": round(float((g["ret"] > 0).mean()) * 100, 1),
                     "exc_mean": round(float(g["exc"].mean()) * 100, 2),
                     "exc_median": round(float(g["exc"].median()) * 100, 2),
                     "beat": round(float((g["exc"] > 0).mean()) * 100, 1),
                     # 每持有 20 個交易日（約一個月）平均超額：抱越久本來就越容易賺越多，要換算成同樣時間長度才公平
                     "exc_per20d": round(float(g["exc"].sum() / g["days"].sum() * 20) * 100, 2)}
    # 配對檢定：同一筆進場，每種賣法的超額 − 燈號倉規則的超額。同日進場先平均成一個數，再對「日」算 t。
    # ⚠️ 不同日的持有期會重疊（彼此相關），t 會略偏高；比 7 組要從嚴看（|t|>2.7 才算，約 Bonferroni 5%）。
    base_rule = "燈號倉(ST賣半+RS全出)"
    pv = df.pivot_table(index=["tk", "t"], columns="rule", values="exc")
    for rule in RULES:
        if rule == base_rule or rule not in pv or base_rule not in pv or rule not in res:
            continue
        d = (pv[rule] - pv[base_rule]).dropna()
        by_day = d.groupby(level="t").mean()
        se = by_day.std(ddof=1) / np.sqrt(len(by_day)) if len(by_day) > 1 else np.nan
        res[rule]["vs_lamp"] = round(float(by_day.mean()) * 100, 2)
        res[rule]["vs_lamp_t"] = round(float(by_day.mean() / se), 2) if se == se and se > 0 else None
    return {"market": market, "entry": entry, "events": int(df[df["rule"] == base_rule].shape[0]),
            "period": [str(dates[0].date()), str(dates[-1].date())], "results": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="all")
    ap.add_argument("--entry", default="relay", choices=["relay", "lamp"])
    a = ap.parse_args()
    ms = ["tw", "us"] if a.market == "all" else [a.market]
    allres = {"date": dt.date.today().isoformat(), "entry": a.entry, "markets": {}}
    for m in ms:
        r = run(m, a.entry)
        allres["markets"][m] = r
        print(f"\n[{m}/{a.entry}] {r['period'][0]}～{r['period'][1]}　進場 {r['events']} 筆"
              f"　（超額＝這筆報酬 − 同期全市場等權；vs燈號倉＝同一筆進場的超額差，t）")
        for rule, x in r["results"].items():
            vs = (f"　vs燈號倉 {x['vs_lamp']:+6.2f}%（t={x['vs_lamp_t']}）" if "vs_lamp" in x else "　（基準）")
            print(f"  {rule:<18} 平均抱{x['days_mean']:>6.1f}日　賺錢{x['win']:>5.1f}%　"
                  f"超額 平均{x['exc_mean']:+6.2f}% 中位{x['exc_median']:+6.2f}%　每月超額{x['exc_per20d']:+5.2f}%{vs}")
    out = "state/backtest_relay_exit.json" if a.entry == "relay" else "state/backtest_lamp_exit.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(allres, f, ensure_ascii=False, indent=1)
    print(f"\n已存 {out}")


if __name__ == "__main__":
    main()
