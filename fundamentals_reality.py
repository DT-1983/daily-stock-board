"""財報與營收實況（BEST MATCH 拆解功能 #2）→ 財報卡新增區塊

- 季度趨勢表（近 6 季）：營收／毛利率／營益率／EPS
- 台股加月營收 YoY 表（近 6 月，FinMind 才有這個顆粒度，美股無對應揭露）
- 業外>本業警示：業外收益若大於本業營業利益，直接示警（BEST MATCH 報告示範的
  「這個每股盈餘的品質」查核，本質是純數字比較，可以自動化）

資料源：台股 FinMind FinancialStatements／MonthRevenue（tw_analyze.py 已在用，
這裡重新拉一份較長歷史）；美股 yfinance quarterly_income_stmt（跟 earnings_infographic.py
主表同源，不重造）。

用法：
    python fundamentals_reality.py 3037.TW
    python fundamentals_reality.py NVDA
"""
import os
import sys
import re
import argparse
from datetime import datetime, timedelta

import requests
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")


def _is_tw(ticker):
    return bool(re.match(r"^\d{4,5}(\.TWO?)?$", ticker.upper()))


def _fm(dataset, sid, start):
    params = {"dataset": dataset, "data_id": sid, "start_date": start}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
    r = requests.get(FINMIND, params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("data") or []


# ── 台股 ──────────────────────────────────────────────────────────

def _tw_quarterly(code, n=6):
    start = (datetime.now() - timedelta(days=95 * (n + 2))).strftime("%Y-%m-%d")
    d = _fm("TaiwanStockFinancialStatements", code, start)
    if not d:
        return []
    dates = sorted(set(x["date"] for x in d))[-n:]
    out = []
    for dt in dates:
        byt = {x["type"]: x["value"] for x in d if x["date"] == dt}
        rev, gp, op, nonop, eps = (byt.get("Revenue"), byt.get("GrossProfit"),
                                   byt.get("OperatingIncome"),
                                   byt.get("TotalNonoperatingIncomeAndExpense"),
                                   byt.get("EPS"))
        out.append({
            "period": dt[:7], "revenue": rev, "eps": eps,
            "gross_margin": (gp / rev * 100) if (gp is not None and rev) else None,
            "op_margin": (op / rev * 100) if (op is not None and rev) else None,
            "op_income": op, "non_op": nonop,
            "non_op_dominant": bool(op is not None and nonop is not None and
                                    nonop > 0 and nonop > op),
        })
    return out


def _tw_monthly(code, n=6):
    """FinMind MonthRevenue 沒有現成的 YoY 欄位，自己拿去年同月算。"""
    start = (datetime.now() - timedelta(days=30 * (n + 13))).strftime("%Y-%m-%d")
    d = _fm("TaiwanStockMonthRevenue", code, start)
    if not d:
        return []
    d = sorted(d, key=lambda x: x["date"])
    by_ym = {(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in d}
    recent = d[-n:]
    out = []
    for x in recent:
        y, m = x["revenue_year"], x["revenue_month"]
        prev = by_ym.get((y - 1, m))
        yoy = ((x["revenue"] / prev - 1) * 100) if prev else None
        out.append({"period": f"{y}-{m:02d}", "revenue": x.get("revenue"), "yoy": yoy})
    return out


# ── 美股 ──────────────────────────────────────────────────────────

def _us_quarterly(ticker, n=6):
    t = yf.Ticker(ticker)
    q = t.quarterly_income_stmt
    if q is None or q.empty:
        return []
    cols = list(q.columns)[:n]

    def cell(row, col):
        try:
            v = q.loc[row, col]
            return None if v != v else float(v)  # NaN check
        except Exception:
            return None

    out = []
    for col in reversed(cols):
        rev, gp, op = cell("Total Revenue", col), cell("Gross Profit", col), cell("Operating Income", col)
        pretax, eps = cell("Pretax Income", col), cell("Diluted EPS", col)
        nonop = (pretax - op) if (pretax is not None and op is not None) else None
        out.append({
            "period": str(col.date())[:7], "revenue": rev, "eps": eps,
            "gross_margin": (gp / rev * 100) if (gp is not None and rev) else None,
            "op_margin": (op / rev * 100) if (op is not None and rev) else None,
            "op_income": op, "non_op": nonop,
            "non_op_dominant": bool(op is not None and nonop is not None and
                                    nonop > 0 and nonop > op),
        })
    return out


# ── 渲染 ──────────────────────────────────────────────────────────

def _fmt_rev(v, is_tw):
    if v is None:
        return "—"
    return f"{v/1e8:,.1f}億" if is_tw else f"${v/1e9:,.2f}B"


def _row(q, is_tw):
    gm = f'{q["gross_margin"]:.1f}%' if q["gross_margin"] is not None else "—"
    om = f'{q["op_margin"]:.1f}%' if q["op_margin"] is not None else "—"
    eps = f'{q["eps"]:.2f}' if q["eps"] is not None else "—"
    warn = ' <span class="ndot" title="業外收益大於本業營業利益">⚠</span>' if q["non_op_dominant"] else ""
    return (f'<tr><td>{q["period"]}{warn}</td><td class="num">{_fmt_rev(q["revenue"], is_tw)}</td>'
            f'<td class="num">{gm}</td><td class="num">{om}</td><td class="num">{eps}</td></tr>')


def build(ticker):
    """算一次，回 (html, summary_text)。summary_text 給 narrative() 的 LLM prompt 用，
    避免財報卡渲染跟 LLM 敘事各自重打一次 API（FinMind 限流教訓，2026-08-05）。"""
    is_tw = _is_tw(ticker)
    code = ticker.upper().replace(".TWO", "").replace(".TW", "")
    try:
        quarters = _tw_quarterly(code) if is_tw else _us_quarterly(ticker)
    except Exception as e:
        print(f"  [fundamentals_reality] {ticker} 抓取失敗：{e}")
        return "", ""
    if not quarters:
        return "", ""

    rows = "".join(_row(q, is_tw) for q in quarters)
    latest = quarters[-1]
    warn_html = ""
    if latest["non_op_dominant"]:
        pct = latest["non_op"] / (latest["op_income"] + latest["non_op"]) * 100
        warn_html = (
            f'<div class="realitywarn">⚠️ 最新一季（{latest["period"]}）業外收益'
            f'（{_fmt_rev(latest["non_op"], is_tw)}）大於本業營業利益'
            f'（{_fmt_rev(latest["op_income"], is_tw)}），約占稅前損益 {pct:.0f}%——'
            f'EPS 有一半以上不是本業賺的，成長性判斷請扣除業外看本業趨勢。</div>')

    monthly_html = ""
    if is_tw:
        try:
            months = _tw_monthly(code)
        except Exception:
            months = []
        if months:
            mrows = "".join(
                f'<tr><td>{m["period"]}</td><td class="num">{_fmt_rev(m["revenue"], True)}</td>'
                f'<td class="num {"pos" if (m["yoy"] or 0) > 0 else "neg" if (m["yoy"] or 0) < 0 else "flat"}">'
                f'{f"{m['yoy']:+.1f}%" if m["yoy"] is not None else "—"}</td></tr>'
                for m in months)
            monthly_html = (f'<div class="realitysub">月營收 YoY（近 {len(months)} 月）</div>'
                            f'<table class="realitytbl"><tr><th>月份</th><th>營收</th><th>年增率</th></tr>'
                            f'{mrows}</table>')

    html = f"""<div class="reality"><h3>財報與營收實況</h3>
<div class="posnote">近 {len(quarters)} 季趨勢，⚠ 標記業外收益大於本業營業利益的季度</div>
<table class="realitytbl"><tr><th>季度</th><th>營收</th><th>毛利率</th><th>營益率</th><th>EPS</th></tr>{rows}</table>
{warn_html}
{monthly_html}
</div>"""

    def _tsum(q):
        gm = f'毛利{q["gross_margin"]:.1f}%' if q["gross_margin"] is not None else ""
        return f'{q["period"]} 營收{_fmt_rev(q["revenue"], is_tw)}{gm}'

    trend = "、".join(_tsum(q) for q in quarters)
    summary = f"近{len(quarters)}季趨勢：{trend}"
    if latest["non_op_dominant"]:
        pct = latest["non_op"] / (latest["op_income"] + latest["non_op"]) * 100
        summary += (f"\n⚠️ 最新一季（{latest['period']}）業外收益"
                    f"（{_fmt_rev(latest['non_op'], is_tw)}）大於本業營業利益"
                    f"（{_fmt_rev(latest['op_income'], is_tw)}），占稅前損益約{pct:.0f}%，"
                    f"EPS品質需扣除業外才能看本業真實成長。")
    return html, summary


def build_html(ticker):
    """CLI／向下相容用：只要 HTML。"""
    return build(ticker)[0]


CSS = """
.reality{margin-top:16px;padding-top:14px;border-top:1px solid #16223A}
.reality h3{font-size:14px;font-weight:700;color:#F5B841;margin-bottom:4px}
.realitysub{font-size:11.5px;color:#93C5FD;font-weight:600;margin:12px 0 5px}
.realitytbl{width:100%;border-collapse:collapse;font-size:12px}
.realitytbl th{color:#8a8f98;font-weight:600;text-align:right;padding:5px 7px;
 border-bottom:1px solid #2a2e35;font-size:10.5px}
.realitytbl th:first-child,.realitytbl td:first-child{text-align:left}
.realitytbl td{padding:5px 7px;border-bottom:1px solid #1a1d23;text-align:right;color:#e8eaed}
.realitytbl tr:last-child td{border-bottom:0}
.realitytbl .pos{color:#4ade80}.realitytbl .neg{color:#ff8a8a}.realitytbl .flat{color:#6b7280}
.ndot{color:#EAB308;cursor:help}
.realitywarn{background:#2a2410;border:1px solid #5c4a1a;border-radius:8px;
 padding:9px 11px;font-size:12px;line-height:1.6;color:#F5D98B;margin-top:10px}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    print(build_html(args.ticker) or "（無資料）")


if __name__ == "__main__":
    main()
