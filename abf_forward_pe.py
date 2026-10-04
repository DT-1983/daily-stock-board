# -*- coding: utf-8 -*-
"""ABF 載板五檔：現價是「未來 EPS」的幾倍？（2026-10-05，Leo：「AI 浪潮下歷史 EPS 不太可信，看現價是未來 EPS 的幾倍，再判斷是否不合理」）

未來 EPS 來源＝分析師共識（yfinance earnings_estimate，免費，含最高／最低與分析師人數）。法說會原文另行蒐集，不在本檔。
只做：① 現價 ÷ 共識 EPS（2026E／2027E 與最高／最低）；② 2026 下半年隱含 EPS（全年共識 − 上半年已公布）；
③ 2027E 對「現在本業年化」的倍數；④ 上一輪景氣高峰（2021-07～2022-12）市場給的本益比（證交所過去本益比）當對照。
不選倍數、不判定合理價；賣方預估歷史上偏樂觀（Bradshaw, Brown & Huang 2013，美國樣本），所以最低值也一起看。
用法：python abf_forward_pe.py"""
import datetime as dt
import statistics as st
import sys

sys.path.insert(0, ".")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from fundamentals_reality import _fm, _tw_quarterly   # noqa: E402

STOCKS = [("3037", "欣興"), ("8046", "南電"), ("3189", "景碩"), ("6213", "聯茂"), ("3167", "大量")]


def consensus(code):
    import yfinance as yf
    import tw_symbol
    t = yf.Ticker(tw_symbol.resolve(code))
    px = float(t.history(period="10d")["Close"].dropna().iloc[-1])
    try:
        ee = t.earnings_estimate
        if ee is None or ee.empty:
            return px, None
        return px, {k: {c: float(ee.loc[k, c]) for c in ("avg", "low", "high", "numberOfAnalysts")} for k in ("0y", "+1y")}
    except Exception:                                        # noqa: BLE001
        return px, None


def prev_peak_pe(code):
    rows = _fm("TaiwanStockPER", code, "2021-07-01") or []
    v = [float(x["PER"]) for x in rows if x.get("PER") not in (None, "") and float(x["PER"]) > 0 and "2021-07-01" <= x["date"] <= "2022-12-31"]
    return (min(v), st.median(v), max(v)) if v else None


def run(code, name):
    px, c = consensus(code)
    q = [x for x in _tw_quarterly(code, n=8) if x.get("eps") is not None]
    last = q[-1]
    h1 = None
    if len(q) >= 2 and q[-1]["period"].endswith("-06") and q[-2]["period"].endswith("-03"):
        h1 = q[-1]["eps"] + q[-2]["eps"]
    core_q = None
    if last.get("op_income") is not None and last.get("non_op") is not None and last["non_op"] > 0 and last["op_income"] > 0:
        core_q = last["eps"] * last["op_income"] / (last["op_income"] + last["non_op"])
    run_core = (core_q if core_q is not None else last["eps"]) * 4
    print("=" * 74)
    print(f"{code} {name}　現價 {px:,.0f}")
    if not c:
        print("  共識 EPS：查無（免費來源沒有這檔的分析師預估）")
        return
    a0, a1 = c["0y"], c["+1y"]
    print(f"  共識 EPS　2026E {a0['avg']:.2f}（{a0['low']:.1f}～{a0['high']:.1f}，{int(a0['numberOfAnalysts'])} 位）｜2027E {a1['avg']:.2f}（{a1['low']:.1f}～{a1['high']:.1f}，{int(a1['numberOfAnalysts'])} 位）")
    print(f"  現價 ÷ 共識 EPS　2026E {px / a0['avg']:.1f} 倍｜2027E {px / a1['avg']:.1f} 倍"
          f"（2027E 最高估 {px / a1['high']:.1f} 倍～最低估 {px / a1['low']:.1f} 倍）")
    if h1 is not None:
        h2 = a0["avg"] - h1
        print(f"  2026 上半年已公布 EPS {h1:.2f}；全年共識隱含下半年 {h2:.2f}（約每季 {h2 / 2:.2f}，最新一季 {last['eps']:.2f}"
              + (f"、本業粗估 {core_q:.2f}" if core_q is not None else "") + "）")
    print(f"  2027E 共識 ÷ 現在本業年化 EPS（{run_core:.1f}）＝ {a1['avg'] / run_core:.1f} 倍；2027E 比 2026E 要成長 {(a1['avg'] / a0['avg'] - 1) * 100:.0f}%")
    pk = prev_peak_pe(code)
    if pk:
        print(f"  對照：上一輪景氣高峰（2021-07～2022-12）市場給的過去本益比 最低 {pk[0]:.1f}／中位 {pk[1]:.1f}／最高 {pk[2]:.1f} 倍")


def main():
    for code, name in STOCKS:
        run(code, name)
    print("=" * 74)
    print("說明：共識 EPS 來自免費資料（yfinance），分析師人數少時（<10）參考性有限；賣方預估歷史上偏樂觀，請同時看最低估。")


if __name__ == "__main__":
    main()
