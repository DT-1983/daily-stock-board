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


_HIST_CACHE = {}


def prefetch(scr):
    """一次批次抓完所有鏈的成分股（2026-08-27 加）：原本逐檔 Ticker().history()
    要 120 次連線＋sleep，改用 yf.download 批次拉，這才是 12 分鐘的真正省時點
    （RRG 沿用只省下 2 次大盤抓取，見 compute_chain docstring）。
    台股後綴用 .TW 批次抓，抓不到的（上櫃）再逐檔試 .TWO fallback。"""
    import yfinance as yf
    for market in ("us", "tw"):
        codes = sorted({r["code"] for rows in (scr.get(market) or {}).values() for r in rows})
        if not codes:
            continue
        syms = [c if (market != "tw" or "." in str(c)) else f"{c}.TW" for c in codes]
        try:
            data = yf.download(syms, period="1y", progress=False, threads=False,
                               auto_adjust=True, group_by="ticker")
        except Exception as e:
            print(f"  [{market}] 批次抓取失敗，改逐檔：{e}")
            continue
        got = 0
        for code, sym in zip(codes, syms):
            try:
                df = data[sym] if len(syms) > 1 else data
                df = df.dropna(subset=["Close"])
                if len(df) >= 120:
                    _HIST_CACHE[(market, code)] = df
                    got += 1
            except Exception:
                pass
        print(f"  [{market}] 批次取得 {got}/{len(codes)} 檔歷史價")


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
                # 2026-08-28 修：Ticker().history() 回 tz-aware index（如 America/New_York），
                # 但 prefetch() 的批次 yf.download() 回 tz-naive。同一條鏈裡混到一個
                # cache 命中（naive）+ 一個這裡 fallback 抓的（aware），_basket_index
                # union 時間戳會直接 TypeError。兩條路徑統一在這裡去掉 tz，只保留日期本身
                # （日線資料本來就不需要時區資訊）。
                if h.index.tz is not None:
                    h = h.tz_localize(None)
                return h
        except Exception:
            continue
    return None


def compute_chain(members, market, bench_closes, with_rrg=True, prev=None):
    """單一鏈：成員 OHLC → 籃子指數(含合成高低價) → RRG + SuperTrend + 擠壓。

    2026-08-27 Leo：「每日只算 SuperTrend+擠壓、RRG 沿用週六的」——
    with_rrg=False 時跳過 RRG 計算、直接沿用 prev（上次的結果）裡的 rrg 欄位並標
    rrg_from（哪天算的）。誠實說明：**這樣省不了多少時間**，因為 12 分鐘幾乎都花在
    抓 120 檔成分股歷史價，而 SuperTrend/擠壓要用同一批資料；真正的省時來自
    批次抓取（_fetch_batch）。RRG 沿用的真正好處是「跟週六的產業輪動頁數字一致」，
    不會出現頁面說領先、日報說改善的錯亂。

    回 dict 或 None（資料不足）。"""
    from industry_rotation import _basket_index, rs_ratio_momentum, quadrant
    import board_html as _L
    from technical_indicators import squeeze_momentum, squeeze_intensity

    # 2026-08-28 修：原本用 `_HIST_CACHE.get(...) or _fetch_hist(...)`——`or` 要先對
    # 左邊求真假值，而 pandas DataFrame 只要不是空的/單一值就會直接炸
    # ValueError("truth value of a DataFrame is ambiguous")。cache 命中（prefetch()
    # 已經抓過的股票，正常情況幾乎每次都命中）就必爆，這支 --daily 模式第一次真的
    # 上排程（8/28 08:45）就撞上，之前只在手動測試時跑過少量股票沒踩到。
    def _cached_or_fetch(c):
        h = _HIST_CACHE.get((market, c))
        return h if h is not None else _fetch_hist(c, market)
    hist_list = [h for h in (_cached_or_fetch(c) for c in members) if h is not None]
    closes_list = [h["Close"] for h in hist_list]
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

    # ① RRG：籃子 vs 大盤（每日模式沿用上次算的，見 docstring）
    if not with_rrg and prev and prev.get("rrg"):
        out["rrg"] = prev["rrg"]
        out["rrg_from"] = prev.get("rrg_from") or prev.get("_date")
    else:
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
        # 2026-09-02：改用 SMA 版 ATR，跟進出燈號頁/財報卡一致。
        # 老墨的 SUPER TREND 實測是 SMA 版（3037 @ 09-02 空方壓力 1223.7 對到小數，
        # Wilder 版 964.2 且方向相反）。不改的話同一檔股票在兩個頁面會顯示不同方向。
        # ⚠️ 策略層（st_alert / paper_portfolio / trade_plan）仍是 Wilder，不受影響。
        from technical_indicators import double_typhoon as _st_sma
        st = _st_sma(hi, lo, c)
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


def run(with_rrg=True):
    if not os.path.exists("screen_result.json"):
        print("找不到 screen_result.json（守備清單），跳過")
        return None
    scr = json.load(open("screen_result.json", encoding="utf-8"))
    prev_all = {}
    if not with_rrg:
        try:
            prev_all = (json.load(open(OUT_PATH, encoding="utf-8")) or {}).get("chains", {})
        except Exception:
            prev_all = {}
        if not prev_all:
            print("  沒有上次的結果可沿用 RRG，這次改算完整版")
            with_rrg = True

    import yfinance as yf
    prefetch(scr)
    out = {"date": time.strftime("%Y-%m-%d"), "period": PERIOD,
           "mode": "full" if with_rrg else "daily", "chains": {}}
    for market in ("us", "tw"):
        chains = scr.get(market) or {}
        if not chains:
            continue
        try:
            bh = yf.Ticker(BENCH[market]).history(period="1y")
            # 同一個 tz 問題（見 _fetch_hist 的說明）：這裡也是 Ticker().history()，
            # index 是 tz-aware，跟籃子成分股（現已統一 tz-naive）放一起比較會炸。
            bidx = bh.index.tz_localize(None) if bh.index.tz is not None else bh.index
            bench_closes = {"index": bidx, "close": bh["Close"].tolist()}
        except Exception as e:
            print(f"  {market} 大盤 {BENCH[market]} 抓取失敗，跳過：{e}")
            continue
        for chain, rows in chains.items():
            members = [r["code"] for r in rows]
            key = f"{market}:{chain}"
            d = compute_chain(members, market, bench_closes,
                              with_rrg=with_rrg, prev=prev_all.get(key))
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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true",
                    help="每日模式：只算 SuperTrend+擠壓，RRG 沿用上次（週六）的值")
    run(with_rrg=not ap.parse_args().daily)


# ────────────────────────── 跨鏈總覽（零成本模板，2026-08-28）──────────────────────────
# 靈感來自 tide-tw.app 的 daily_brief.json：把排序後的數字直接套句型，**不叫 AI**。
# 我們現有的 researcher_industry 是「翻象限才寫、寫的時候叫 AI 解釋為什麼」——
# 那個保留（真的翻象限時值得花額度）；這裡補的是「每天都能給的一句話現況」，
# 零成本、零延遲，適合放日報開場。兩者不重複：這個講「現在誰強誰弱」，
# researcher_industry 講「為什麼會變」。

_QUAD_RANK = {"領先": 0, "改善": 1, "弱化": 2, "落後": 3}
_MKT_LABEL = {"us": "美", "tw": "台"}


def _split_key(key):
    """'us:AI 伺服器' → ('美', 'AI 伺服器')"""
    mkt, _, name = key.partition(":")
    return _MKT_LABEL.get(mkt, mkt), name


def overview_line(path=OUT_PATH):
    """一句話講今天八鏈的相對強弱。回 None 表示沒資料可講（不硬湊）。"""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    rows = []
    for key, c in (d.get("chains") or {}).items():
        r = c.get("rrg") or {}
        if r.get("ratio") is None:
            continue
        mkt, name = _split_key(key)
        rows.append({"mkt": mkt, "name": name, "ratio": r["ratio"],
                     "quad": r.get("quadrant"), "st": c.get("supertrend")})
    if len(rows) < 3:
        return None
    rows.sort(key=lambda x: -x["ratio"])
    top, bottom = rows[0], rows[-1]
    strong = sum(1 for r in rows if r["quad"] in ("領先", "改善"))
    weak = len(rows) - strong

    s = (f"📊 產業輪動：**{top['name']}（{top['mkt']}）領先全場**（RS {top['ratio']}）"
         f"，**{bottom['name']}（{bottom['mkt']}）墊底**（RS {bottom['ratio']}）")
    # 美台各算一次（同一個題材在兩個市場是兩筆），所以講「N 個籃子」不講「N 條鏈」——
    # 寫「16 條鏈」會讓人以為有 16 個不同題材，實際是 8 個題材 × 兩個市場。
    n_us = sum(1 for r in rows if r["mkt"] == "美")
    n_tw = len(rows) - n_us
    s += (f"｜{len(rows)} 個籃子（美{n_us}/台{n_tw}）中 "
          f"{strong} 個領先或改善、{weak} 個弱化或落後")
    # 2026-09-01 Leo：「SuperTrend 接在前面了，請改為獨立一段」——原本用「｜」
    # 續在產業輪動後面，手機上那一行會折成 4~5 行，兩件事糊在一起看不出斷點。
    # 改由 bears_line() 另外回傳，呼叫端當獨立一行放。
    return s


def bears_line(path=OUT_PATH):
    """SuperTrend 已翻空頭的鏈，獨立一行。沒有就回 None（不硬湊）。

    跟 overview_line 分開的理由：那是「相對強弱排名」，這是「趨勢已經轉壞」——
    兩件事不同層級，接在同一行會讓人以為墊底的那條就是翻空的那條。"""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    bears = []
    for key, c in (d.get("chains") or {}).items():
        if c.get("supertrend") == "空頭":
            mkt, name = _split_key(key)
            bears.append(f"{name}（{mkt}）")
    if not bears:
        return None
    return f"⚠️ **SuperTrend 空頭**（{len(bears)} 條鏈）：" + "、".join(bears)
