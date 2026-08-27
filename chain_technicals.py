# -*- coding: utf-8 -*-
"""七鏈籃子技術面（2026-08-27，Leo 拍板「當參考不當門檻」）。

**為什麼做**：原本「產業輪動 RRG」用的是 TradingView 的 20 個通用類股，跟 Leo 真正在
追的七鏈（AI伺服器/矽光子光通訊/低軌衛星/太陽能/機器人/AI電力核能/玻璃基板）**是兩套
分類**，接不起來。這支直接對七鏈自己算，分類問題自然消失（守備清單與產業講的是同一批股票）。

**指標選擇有依據，不是想到什麼加什麼**：
  · RRG（RS-Ratio/RS-Momentum）＝資金往哪流（方向）
  · SuperTrend＝趨勢站穩了沒（確認）——**用在籃子(≈指數)層級是 Leo 自己 5.5 年回測
    的定論：對指數有效、對高波動個股反而害人**（見 memory/supertrend_backtest_findings）
  · Exceed Charge 擠壓＝能量累積、發動前兆（時機）
  Leo 的定位：「七鏈主要是看長期趨勢看好，還要等買點」——前兩個回答趨勢還健不健康，
  第三個回答買點近不近。

**當參考不當門檻**（Leo 2026-08-27 明確決定）：輸出只是投資長判斷時多一份背景材料，
**不擋掉任何個股訊號**——維持「多鏡頭獨立判斷不投票」的既有硬規則
（見 memory/investment_advisor_architecture）。

輸出 state/chain_technicals.json，投資長 gather_material 讀它。
用法: python chain_technicals.py
"""
import os
import sys
import json
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_PATH = "state/chain_technicals.json"
BENCH = {"us": "^GSPC", "tw": "^TWII"}
PERIOD = 60          # RRG 週期，跟產業輪動頁預設「60日波段」對齊
MIN_MEMBERS = 3      # 少於這麼多檔抓得到價，該鏈不算（不用殘缺資料硬算）

QUAD_LABEL = {"leading": "領先", "improving": "改善",
              "lagging": "落後", "weakening": "弱化"}


def _fetch_hist(code, market):
    """台股上市.TW／上櫃.TWO 兩種後綴都試（yfinance 常見坑，見 memory
    hongruitai_rules_coverage：曾有257檔上櫃股全404被當成「基本面不合格」）。"""
    import yfinance as yf
    if market != "tw" or "." in str(code):
        cands = [str(code)]
    else:
        cands = [f"{code}.TW", f"{code}.TWO"]
    for sym in cands:
        try:
            h = yf.Ticker(sym).history(period="1y")
            if h is not None and not h.empty and len(h) >= 120:
                return h
        except Exception:
            continue
    return None


def compute_chain(members, market, bench_closes):
    """單一鏈：成員 OHLC → 籃子指數(含合成高低價) → RRG + SuperTrend + 擠壓。
    回 dict 或 None（資料不足）。"""
    from industry_rotation import _basket_index, rs_ratio_momentum, quadrant
    import board_html as _L
    from technical_indicators import squeeze_momentum, squeeze_intensity

    closes_list, hist_list = [], []
    for code in members:
        h = _fetch_hist(code, market)
        if h is None:
            continue
        closes_list.append(h["Close"])
        hist_list.append(h)
        time.sleep(0.15)
    if len(closes_list) < MIN_MEMBERS:
        return None

    idx = _basket_index(closes_list)          # 日報酬等權聚合（指數編制標準做法）
    if idx is None or len(idx) < 120:
        return None

    # 籃子的合成高低價：把成員「當日 high/close、low/close 的平均比例」套到籃子指數上。
    # 2026-08-27 修：第一版直接拿收盤價當 H/L，結果 ATR 大幅偏小 → KC 通道太窄 →
    # BB 幾乎不可能被包住 → **16 條鏈全部顯示「未擠壓」**（系統性偏誤不是真實訊號）。
    # ATR/擠壓這類指標需要真實日內波動幅度才有意義。
    try:
        import pandas as pd
        hr = pd.concat([(h["High"] / h["Close"]) for h in hist_list], axis=1).mean(axis=1)
        lr = pd.concat([(h["Low"] / h["Close"]) for h in hist_list], axis=1).mean(axis=1)
        hr, lr = hr.reindex(idx.index).ffill(), lr.reindex(idx.index).ffill()
        highs = (idx * hr).tolist()
        lows = (idx * lr).tolist()
    except Exception:
        highs = lows = None

    out = {"members_used": len(closes_list)}

    # ① RRG：籃子 vs 大盤
    try:
        import pandas as pd
        bench = pd.Series(bench_closes["close"], index=bench_closes["index"])
        rm = rs_ratio_momentum(idx, bench, periods=[PERIOD])
        if rm:
            r = rm[PERIOD]["ratio"].dropna()
            m = rm[PERIOD]["momentum"].dropna()
            if len(r) and len(m):
                rr, mm = float(r.iloc[-1]), float(m.iloc[-1])
                out["rrg"] = {"ratio": round(rr, 2), "momentum": round(mm, 2),
                              "quadrant": QUAD_LABEL.get(quadrant(rr, mm), "?")}
    except Exception as e:
        out["rrg_err"] = str(e)[:80]

    c = [float(x) for x in idx.tolist()]
    hi = [float(x) for x in highs] if highs else c
    lo = [float(x) for x in lows] if lows else c

    # ② SuperTrend（用上面算出來的合成高低價，ATR 才有意義）
    try:
        st = _L.supertrend(hi, lo, c)
        if st and st.get("dir"):
            d = [x for x in st["dir"] if x is not None]
            if d:
                out["supertrend"] = "多頭" if d[-1] == 1 else "空頭"
    except Exception as e:
        out["st_err"] = str(e)[:80]

    # ③ Exceed Charge 擠壓
    try:
        sq = squeeze_momentum(hi, lo, c)
        lvl, _ratio = squeeze_intensity(sq)
        mom = sq.get("momentum")
        out["squeeze"] = {
            "on": bool(sq["squeeze_on"][-1]) if len(sq["squeeze_on"]) else None,
            "level": lvl,
            "momentum_up": (float(mom[-1]) > 0) if (mom is not None and len(mom)
                                                    and mom[-1] == mom[-1]) else None,
        }
    except Exception as e:
        out["sq_err"] = str(e)[:80]
    return out


def summary_line(d):
    """組成投資長材料用的一行白話。"""
    if not d:
        return None
    parts = []
    if d.get("rrg"):
        parts.append(f"{d['rrg']['quadrant']}象限(RS {d['rrg']['ratio']}"
                     f"/動能 {d['rrg']['momentum']})")
    if d.get("supertrend"):
        parts.append(f"SuperTrend{d['supertrend']}")
    sq = d.get("squeeze") or {}
    if sq.get("on"):
        lvl = sq.get("level") or "擠壓"
        dirn = "動能偏多" if sq.get("momentum_up") else ("動能偏空" if sq.get("momentum_up") is False else "")
        parts.append(f"{lvl}蓄力中{('，' + dirn) if dirn else ''}")
    elif sq.get("on") is False:
        parts.append("未擠壓")
    return "｜".join(parts) if parts else None


def run():
    if not os.path.exists("screen_result.json"):
        print("找不到 screen_result.json（守備清單），跳過")
        return None
    scr = json.load(open("screen_result.json", encoding="utf-8"))

    import yfinance as yf
    out = {"date": time.strftime("%Y-%m-%d"), "period": PERIOD, "chains": {}}
    for market in ("us", "tw"):
        chains = scr.get(market) or {}
        if not chains:
            continue
        try:
            bh = yf.Ticker(BENCH[market]).history(period="1y")
            bench_closes = {"index": bh.index, "close": bh["Close"].tolist()}
        except Exception as e:
            print(f"  {market} 大盤 {BENCH[market]} 抓取失敗，跳過：{e}")
            continue
        for chain, rows in chains.items():
            members = [r["code"] for r in rows]
            d = compute_chain(members, market, bench_closes)
            key = f"{market}:{chain}"
            if not d:
                print(f"  {key}：資料不足，跳過")
                continue
            d["summary"] = summary_line(d)
            out["chains"][key] = d
            print(f"  {key}（{d['members_used']}檔）：{d['summary']}")

    if not out["chains"]:
        print("沒有任何鏈算出結果，不寫檔（避免覆蓋成空的）")
        return None
    os.makedirs("state", exist_ok=True)
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ {OUT_PATH}：{len(out['chains'])} 條鏈")
    return out


if __name__ == "__main__":
    run()
