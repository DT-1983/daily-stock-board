# -*- coding: utf-8 -*-
"""未來 EPS 檢查（2026-10-05，Leo：「把 EPS 放進個股之中」）。

回答「現價是（市場共識的）未來 EPS 的幾倍？它要求獲利從哪裡跳到哪裡？」——只描述，不選倍數、不給合理價。
資料：分析師共識 EPS（yfinance earnings_estimate，免費；含最高／最低與分析師人數）＋ 台股另用 FinMind 已公布財報。
輸出（台股較完整，美股只有現價÷共識）：
  · 現價 ÷ 共識 EPS（2026E／2027E，與最高估～最低估）；
  · 2026 上半年已公布 EPS → 全年共識隱含的下半年 EPS（對照最新一季、本業粗估）；
  · 2027E 共識 ÷ 現在本業年化 EPS；
  · 對照：上一輪景氣高峰（2021-07～2022-12）市場給的過去本益比（證交所），以及「2027E × 該倍數」的情境價格（算術，不是預測）。
限制：共識是賣方預估，歷史上偏樂觀（Bradshaw, Brown & Huang 2013），分析師人數少（<8）時參考性有限；
  本業 EPS＝EPS×營業利益÷（營業利益＋業外）的粗估，只在業外為正時使用。同日內快取（state/forward_eps_cache.json）。
"""
import datetime as dt
import io
import json
import os
import statistics as st

CACHE = "state/forward_eps_cache.json"


def _load():
    try:
        return json.load(io.open(CACHE, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}


def _save(c):
    os.makedirs("state", exist_ok=True)
    io.open(CACHE, "w", encoding="utf-8").write(json.dumps(c, ensure_ascii=False))


def _compute(code):
    import yfinance as yf
    is_tw = str(code).isdigit()
    if is_tw:
        import tw_symbol
        sym = tw_symbol.resolve(code)
    else:
        sym = str(code).replace(".", "-")
    t = yf.Ticker(sym)
    px = float(t.history(period="10d")["Close"].dropna().iloc[-1])
    cons = None
    try:
        ee = t.earnings_estimate
        if ee is not None and not ee.empty:
            cons = {k: {c: float(ee.loc[k, c]) for c in ("avg", "low", "high", "numberOfAnalysts")} for k in ("0y", "+1y")}
    except Exception:                                        # noqa: BLE001
        cons = None
    out = {"code": str(code), "price": px, "cons": cons, "tw": is_tw}
    if is_tw and cons:
        from fundamentals_reality import _fm, _tw_quarterly
        q = [x for x in _tw_quarterly(code, n=8) if x.get("eps") is not None]
        if q:
            last = q[-1]
            h1 = (q[-1]["eps"] + q[-2]["eps"]) if len(q) >= 2 and q[-1]["period"].endswith("-06") and q[-2]["period"].endswith("-03") else None
            core_q = None
            if last.get("op_income") is not None and last.get("non_op") is not None and last["non_op"] > 0 and last["op_income"] > 0:
                core_q = last["eps"] * last["op_income"] / (last["op_income"] + last["non_op"])
            out.update({"last_period": last["period"], "last_eps": last["eps"], "core_q": core_q,
                        "run_core": (core_q if core_q is not None else last["eps"]) * 4, "h1": h1})
        try:
            rows = _fm("TaiwanStockPER", code, "2021-07-01") or []
            v = [float(x["PER"]) for x in rows if x.get("PER") not in (None, "") and float(x["PER"]) > 0
                 and "2021-07-01" <= x["date"] <= "2022-12-31"]
            if v:
                out["prev_peak_pe"] = {"min": min(v), "median": st.median(v), "max": max(v)}
        except Exception:                                    # noqa: BLE001
            pass
    return out


def get(code):
    """同日快取；任何失敗回 None（呼叫端略過這個區塊，不影響其他內容）。"""
    today = dt.date.today().isoformat()
    c = _load()
    k = str(code)
    if k in c and c[k].get("_d") == today:
        return c[k]["data"]
    try:
        d = _compute(code)
    except Exception as e:                                   # noqa: BLE001
        print(f"[forward_eps] {code} 取得失敗：{str(e)[:80]}")
        return None
    c[k] = {"_d": today, "data": d}
    _save(c)
    return d


def derived(d):
    """由原始資料算出要顯示的數字（共用給文字與 HTML）。回 None 代表沒有共識 EPS。"""
    if not d or not d.get("cons"):
        return None
    px, a0, a1 = d["price"], d["cons"]["0y"], d["cons"]["+1y"]
    o = {"px": px, "a0": a0, "a1": a1, "pe0": px / a0["avg"], "pe1": px / a1["avg"],
         "pe1_hi": px / a1["high"], "pe1_lo": px / a1["low"], "g": (a1["avg"] / a0["avg"] - 1) * 100,
         "n0": int(a0["numberOfAnalysts"]), "n1": int(a1["numberOfAnalysts"])}
    if d.get("h1") is not None:
        o["h2"] = a0["avg"] - d["h1"]
        o["h1"] = d["h1"]
    if d.get("run_core"):
        o["run_core"] = d["run_core"]
        o["x_run"] = a1["avg"] / d["run_core"]
        o["last_eps"], o["core_q"], o["last_period"] = d.get("last_eps"), d.get("core_q"), d.get("last_period")
    pk = d.get("prev_peak_pe")
    if pk:
        o["pk"] = pk
        o["scen"] = {"low": a1["low"] * pk["median"], "avg": a1["avg"] * pk["median"], "high": a1["high"] * pk["median"]}
    return o


def lines(d):
    """軍師材料／軍師資料庫用的文字行。"""
    o = derived(d)
    if not o:
        return []
    out = [f"未來 EPS（市場共識，{o['n1']} 位分析師；賣方預估歷史上偏樂觀）：2026E {o['a0']['avg']:.2f}、2027E {o['a1']['avg']:.2f}"
           f"（{o['a1']['low']:.1f}～{o['a1']['high']:.1f}）→ 現價 {o['px']:,.0f} 是 2026E 的 {o['pe0']:.1f} 倍、2027E 的 {o['pe1']:.1f} 倍"
           f"（2027E 最高估 {o['pe1_hi']:.1f}～最低估 {o['pe1_lo']:.1f} 倍）；2027E 比 2026E 要再成長 {o['g']:.0f}%"]
    if "h2" in o:
        out.append(f"2026 上半年已公布 EPS {o['h1']:.2f}，全年共識隱含下半年 {o['h2']:.2f}（約每季 {o['h2'] / 2:.2f}，"
                   f"最新一季 {o['last_eps']:.2f}" + (f"、本業粗估 {o['core_q']:.2f}" if o.get("core_q") else "") + "）")
    if "x_run" in o:
        out.append(f"2027E 共識是現在本業年化 EPS（{o['run_core']:.1f}）的 {o['x_run']:.1f} 倍")
    if "scen" in o:
        s, pk = o["scen"], o["pk"]
        out.append(f"情境算術（不是預測）：若 2027 是高峰年、市場給上一輪高峰的過去本益比中位數 {pk['median']:.1f} 倍，"
                   f"2027E 最低估→共識→最高估 對應價格 {s['low']:,.0f}→{s['avg']:,.0f}→{s['high']:,.0f}（現價 {o['px']:,.0f}）")
    return out


def html(d, esc):
    """個股頁區塊（沿用 .fc 表格樣式）：回 (標題, 副標, 內文 HTML)；沒有共識就回 None。"""
    o = derived(d)
    if not o:
        return None
    rows = [("2026E", o["a0"]["avg"], o["a0"]["low"], o["a0"]["high"], o["pe0"], o["px"] / o["a0"]["high"], o["px"] / o["a0"]["low"]),
            ("2027E", o["a1"]["avg"], o["a1"]["low"], o["a1"]["high"], o["pe1"], o["pe1_hi"], o["pe1_lo"])]
    trs = "".join(f"<tr><td class=\"k\">{y}</td><td>{e:.2f}（{lo:.1f}～{hi:.1f}）</td>"
                  f"<td>{pe:.1f} 倍<span class=\"note\">最高估 {phi:.1f}～最低估 {plo:.1f} 倍</span></td></tr>"
                  for y, e, lo, hi, pe, phi, plo in rows)
    notes = []
    if "h2" in o:
        notes.append(f"2026 上半年已公布 EPS {o['h1']:.2f}；全年共識隱含下半年 {o['h2']:.2f}（約每季 {o['h2'] / 2:.2f}，"
                     f"最新一季 {o['last_eps']:.2f}" + (f"、本業粗估 {o['core_q']:.2f}" if o.get("core_q") else "") + "）。")
    if "x_run" in o:
        notes.append(f"2027E 共識是現在本業年化 EPS（{o['run_core']:.1f}）的 <b>{o['x_run']:.1f} 倍</b>；2027E 比 2026E 要再成長 {o['g']:.0f}%。")
    if "scen" in o:
        s, pk = o["scen"], o["pk"]
        notes.append(f"情境算術（不是預測）：若 2027 是高峰年、市場給上一輪高峰（2021-07～2022-12）的過去本益比中位數 {pk['median']:.1f} 倍，"
                     f"2027E 最低估→共識→最高估 對應 {s['low']:,.0f}→{s['avg']:,.0f}→{s['high']:,.0f}（現價 {o['px']:,.0f}）。")
    body = (f'<table class="fc"><tr><th>年度</th><th>共識 EPS（最低～最高）</th><th>現價 ÷ 共識 EPS</th></tr>{trs}</table>'
            f'<div class="sub" style="margin-top:8px">{"<br>".join(notes)}</div>')
    sub = (f"共識 EPS 來自 yfinance（{o['n1']} 位分析師），<b>賣方預估歷史上偏樂觀，最低估也要一起看</b>；"
           "這一塊只描述「現價在賭什麼」，不是合理價、不是買賣訊號。")
    return ("未來 EPS：現價是共識未來獲利的幾倍", sub, body)
