# -*- coding: utf-8 -*-
"""ABF 載板相關股的估值重看（2026-10-05，Leo：「研究一下」軍師『考慮出場』有多少是公式造成的）。

不選倍數、不替任何人決定「合理價」。只做三件機械式的事（都用 FinMind／證交所已公布數字）：
  ① 現價在這檔自己的歷史本益比分布（過去 5 年、10 年）的位置——只當背景，不當結論（聯發科單檔回測顯示這種位置對成長／循環股會誤導）。
  ② 反推：現價要成立，EPS 至少要多少？（用三把尺：這檔自己 5 年本益比中位數、洪瑞泰上限 30 倍、這檔自己 5 年本益比第 75 百分位）。
  ③ 對照：把「反推要的 EPS」跟「已經公布的 EPS 水準」放在一起——過去 12 個月、最新一季年化、最新一季『本業』年化（扣掉業外）、過去 5 年平均、歷史最高年度。
     另列券商報告自己用的 EPS（若有）。
限制：本業 EPS 以「EPS × 營業利益 ÷（營業利益＋業外）」粗估（沒有逐項稅額），只在業外為正時使用；12 年財報；價格用最新收盤（未含股利）。
用法：python abf_valuation_check.py
"""
import statistics as st
import sys
import datetime as dt

sys.path.insert(0, ".")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from fundamentals_reality import _fm, _tw_quarterly   # noqa: E402

STOCKS = [("3037", "欣興"), ("8046", "南電"), ("3189", "景碩"), ("6213", "聯茂"), ("3167", "大量")]
# 券商報告自己用的 EPS（取自 advisor_reports 登錄簿，下面會現讀，這裡不寫死）


def pct(sample, v):
    return 100.0 * sum(1 for x in sample if x <= v) / len(sample)


def prices(code):
    import yfinance as yf
    import tw_symbol
    h = yf.Ticker(tw_symbol.resolve(code)).history(period="10d")["Close"].dropna()
    return float(h.iloc[-1]), str(h.index[-1])[:10]


def broker_eps(code):
    """登錄簿裡這檔報告用的基準 EPS 與倍數（現讀）。"""
    import advisor_reports as ar
    out = []
    for r in ar._live_reports():
        if ar._tk_key(r.get("ticker")) == ar._tk_key(code) and r.get("valuation_eps") and r.get("valuation_multiple"):
            out.append((r.get("broker"), r.get("date"), float(r["valuation_eps"]), float(r["valuation_multiple"]),
                        r.get("valuation_eps_label") or "", r.get("target")))
    return out


def run(code, name):
    q = _tw_quarterly(code, n=48)
    q = [x for x in q if x.get("eps") is not None]
    if len(q) < 12:
        print(f"{code} {name}：季資料不足"); return None
    px, pday = prices(code)
    ttm = sum(x["eps"] for x in q[-4:])
    last = q[-1]
    run_rate = last["eps"] * 4
    core = None
    if last.get("op_income") is not None and last.get("non_op") is not None and last["non_op"] > 0 and last["op_income"] > 0:
        core = last["eps"] * last["op_income"] / (last["op_income"] + last["non_op"]) * 4
    annual = {}
    for x in q:
        annual.setdefault(x["period"][:4], []).append(x["eps"])
    full = {y: sum(v) for y, v in annual.items() if len(v) == 4}
    last5 = [full[y] for y in sorted(full)[-5:]]
    avg5 = st.mean(last5) if len(last5) == 5 else None
    peak_y = max(full, key=full.get) if full else None
    # 歷史本益比
    per_rows = _fm("TaiwanStockPER", code, (dt.date.today() - dt.timedelta(days=3660)).isoformat()) or []
    per = [(x["date"], float(x["PER"])) for x in per_rows if x.get("PER") not in (None, "") and float(x["PER"]) > 0]
    per5 = [v for d, v in per if d >= (dt.date.today() - dt.timedelta(days=1830)).isoformat()]
    per_now = per[-1][1] if per else None
    print("=" * 78)
    print(f"{code} {name}　現價 {px:,.0f}（{pday} 收）")
    print(f"  已公布 EPS：過去 12 個月 {ttm:.2f}｜最新一季（{last['period']}）{last['eps']:.2f}，年化 {run_rate:.2f}"
          + (f"｜最新一季本業粗估年化 {core:.2f}（業外 {last['non_op']/1e8:.1f} 億、本業營業利益 {last['op_income']/1e8:.1f} 億）" if core else "｜本業粗估：業外非正，不拆"))
    if avg5:
        print(f"  過去 5 個完整年度 EPS：{', '.join(f'{y} {full[y]:.2f}' for y in sorted(full)[-5:])}｜平均 {avg5:.2f}｜12 年最高 {peak_y} 年 {full[peak_y]:.2f}")
    if per5:
        med, p75 = st.median(per5), sorted(per5)[int(len(per5) * 0.75)]
        print(f"  過去本益比：現在 {per_now:.1f} 倍（證交所），5 年中位 {med:.1f}、第 75 百分位 {p75:.1f}、區間 {min(per5):.1f}～{max(per5):.1f}；"
              f"現在在 5 年的第 {pct(per5, per_now):.0f} 百分位")
        print("  ② 反推：現價要成立，EPS 至少要多少？")
        for lab, m in (("5 年本益比中位數", med), ("洪瑞泰上限 30 倍", 30.0), ("5 年本益比第 75 百分位", p75)):
            need = px / m
            vs = f"過去12個月 {need / ttm:.1f} 倍" if ttm > 0 else ""
            vs2 = f"、最新一季年化 {need / run_rate:.1f} 倍" if run_rate > 0 else ""
            vs3 = f"、本業粗估年化 {need / core:.1f} 倍" if core else ""
            print(f"     用{lab}（{m:.1f}x）：EPS ≥ {need:.1f}（是 {vs}{vs2}{vs3}）")
    be = broker_eps(code)
    for b, d, e, m, lab, t in be:
        print(f"  券商報告：{b} {d}　目標 {t}＝{m:g} 倍 × EPS {e:.2f}（{lab or '基準年未標'}）→ 比最新一季年化 {e / run_rate:.1f} 倍、比過去 12 個月 {e / ttm:.1f} 倍" if run_rate > 0 and ttm > 0 else f"  券商報告：{b} {d}　EPS {e:.2f}")
    return {"code": code, "name": name, "px": px, "ttm": ttm, "run": run_rate, "core": core, "avg5": avg5}


def main():
    res = [run(c, n) for c, n in STOCKS]
    print("=" * 78)
    print("說明：『反推要的 EPS』是算術，不是預測；它只回答「現價在什麼 EPS 水準下才不算貴」。")


if __name__ == "__main__":
    main()
