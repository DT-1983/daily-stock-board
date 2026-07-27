# -*- coding: utf-8 -*-
"""2026 YTD 回測：趨勢規則 vs 買進持有 vs 大盤。
重點回答：SuperTrend 翻燈在「完整一段期間」是加分還是扣分？新護欄有沒有用？
方法：用現行守備清單為池子，逐日重算 SuperTrend，模擬三種操作方式。
⚠️ 池子是「現在」篩出來的 → 有倖存者偏差，只能比較「同池子不同操作」，不能當絕對績效。
"""
import json, sys
import pandas as pd, numpy as np, yfinance as yf

START, END = "2025-11-01", "2026-07-27"   # 多抓前段給 SuperTrend 暖身
TRADE_START = "2026-01-02"
CONFIRM_DAYS = 2
MIN_SLOTS = 8
FEE = 0.001          # 單邊 0.1% 交易成本（含手續費+滑價，保守）


def supertrend_dir(h, l, c, period=10, mult=3.0):
    n = len(c)
    if n < period + 1:
        return [None]*n
    tr = [h[0]-l[0]]
    for i in range(1, n):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    atr=[None]*n; atr[period-1]=sum(tr[:period])/period
    for i in range(period, n):
        atr[i]=(atr[i-1]*(period-1)+tr[i])/period
    hl2=[(h[i]+l[i])/2 for i in range(n)]
    up=[None]*n; lo=[None]*n; dr=[None]*n
    for i in range(period-1, n):
        if atr[i] is None: continue
        bu, bl = hl2[i]+mult*atr[i], hl2[i]-mult*atr[i]
        if i==period-1 or up[i-1] is None:
            up[i], lo[i] = bu, bl
            dr[i] = 1 if c[i] >= hl2[i] else -1
        else:
            up[i] = bu if (bu<up[i-1] or c[i-1]>up[i-1]) else up[i-1]
            lo[i] = bl if (bl>lo[i-1] or c[i-1]<lo[i-1]) else lo[i-1]
            dr[i] = 1 if c[i]>up[i-1] else (-1 if c[i]<lo[i-1] else dr[i-1])
    return dr


def main():
    pool = json.load(open("pool.json", encoding="utf-8"))
    data = yf.download(pool, start=START, end=END, progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    close, dirs = {}, {}
    for t in pool:
        try:
            df = data[t].dropna()
            if len(df) < 60: continue
            close[t] = df["Close"]
            dirs[t] = pd.Series(supertrend_dir(df["High"].tolist(), df["Low"].tolist(),
                                               df["Close"].tolist()), index=df.index)
        except Exception:
            pass
    px = pd.DataFrame(close).dropna(how="all").ffill()
    dr = pd.DataFrame(dirs).reindex(px.index).ffill()
    days = px.index[px.index >= TRADE_START]
    tickers = list(px.columns)
    print(f"池子 {len(tickers)} 檔，回測 {days[0].date()} → {days[-1].date()}（{len(days)} 交易日）")

    def run(mode):
        """mode: 'trend'(現行) / 'trend_fix'(2天確認+現金) / 'hold'(買進持有)"""
        nav, held, streak, flips = 1.0, {}, {}, 0
        curve, trades = [], []
        for i, d in enumerate(days):
            prices = px.loc[d]
            if i > 0:                       # 先按昨日持股計算今日損益
                prev = px.loc[days[i-1]]
                if held:
                    r = sum(w * (prices[t]/prev[t] - 1) for t, w in held.items()
                            if pd.notna(prices[t]) and pd.notna(prev[t]))
                    nav *= (1 + r)
            green = [t for t in tickers if dr.loc[d, t] == 1 and pd.notna(prices[t])]
            if mode == "hold":
                target = tickers if i == 0 else list(held)
            elif mode == "trend":
                target = green
            else:
                gset = set(green)
                target = []
                for t in tickers:
                    sig = 1 if t in gset else -1
                    prv = streak.get(t)
                    streak[t] = [sig, (prv[1]+1) if (prv and prv[0]==sig) else 1]
                    ok = streak[t][1] >= CONFIRM_DAYS
                    if t in held:
                        if not (sig == -1 and ok): target.append(t)
                    elif sig == 1 and ok:
                        target.append(t)
            slots = max(len(target), MIN_SLOTS) if mode == "trend_fix" else max(len(target), 1)
            new = {t: 1.0/slots for t in target if pd.notna(prices[t])}
            turn = sum(abs(new.get(t,0)-held.get(t,0)) for t in set(new)|set(held))
            if turn > 1e-9:
                if set(new) != set(held): flips += 1
                nav *= (1 - turn*FEE)       # 換手成本
                trades.append((d.date(), sorted(set(new)-set(held)), sorted(set(held)-set(new))))
            held = new
            curve.append((d.date().isoformat(), round(nav,4), len(held)))
        return nav, flips, curve, trades

    res = {}
    for m in ["hold", "trend", "trend_fix"]:
        nav, flips, curve, trades = run(m)
        res[m] = {"ret": (nav-1)*100, "flips": flips, "curve": curve, "trades": len(trades)}
        peak = 1.0; mdd = 0
        for _, v, _ in curve:
            peak = max(peak, v); mdd = min(mdd, v/peak - 1)
        res[m]["mdd"] = mdd*100
        print(f"  {m:<10} 報酬 {(nav-1)*100:+7.2f}%  換股 {flips:>3} 次  最大回撤 {mdd*100:6.1f}%")

    # 基準
    bm = yf.download(["SPY","QQQ","^TWII"], start=TRADE_START, end=END, progress=False,
                     threads=False, auto_adjust=True, group_by="ticker")
    for b in ["SPY","QQQ","^TWII"]:
        try:
            c = bm[b]["Close"].dropna()
            res[b] = {"ret": (c.iloc[-1]/c.iloc[0]-1)*100}
            peak=c.iloc[0]; mdd=0
            for v in c:
                peak=max(peak,v); mdd=min(mdd, v/peak-1)
            res[b]["mdd"]=mdd*100
            print(f"  {b:<10} 報酬 {res[b]['ret']:+7.2f}%              最大回撤 {mdd*100:6.1f}%")
        except Exception as e:
            print(b, "ERR", e)
    json.dump(res, open("bt_result.json","w"), default=str)


if __name__ == "__main__":
    main()
