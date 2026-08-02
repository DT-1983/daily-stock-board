"""財報懶人包 Infographic（CLI）→ HTML

用法：
    python earnings_infographic.py TSLA
    python earnings_infographic.py TSLA -o docs/earnings_TSLA.html
    python earnings_infographic.py 2330.TW --no-llm      # 只出數據不跑敘事

設計原則（重要）：
  · **所有財務數字一律來自 yfinance 真實財報**，不讓 LLM 生成任何數字。
    這種「機構級」版面看起來很有說服力，數字錯了會比純文字更誤導。
  · LLM 只負責「敘事層」（亮點/風險/投資邏輯），且 prompt 明確禁止編造數字，
    只能引用下方餵給它的真實數據。
  · 星級評分**由數據算**（成長性/財務體質/估值/風險由公式決定），
    只有「競爭護城河」這種無法量化的才交給 LLM。
  · 評級標章顯示的是 **分析師共識**（yfinance recommendationKey + 目標價 + 分析師人數），
    明確標示來源，不是本工具自己的買賣建議。
"""
import os
import io
import sys
import json
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yfinance as yf

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"


# ────────────────────────────── 資料層 ──────────────────────────────

def _safe(df, row, col):
    try:
        v = df.loc[row, col]
        return float(v) if v == v else None      # NaN → None
    except Exception:
        return None


def fetch(ticker: str) -> dict:
    """抓最近一季財報 + 去年同期（YoY）+ 估值。全部真實數據。"""
    t = yf.Ticker(ticker)
    q, cf = t.quarterly_income_stmt, t.quarterly_cashflow
    if q is None or q.empty:
        raise SystemExit(f"❌ {ticker} 沒有季度財報資料")
    cols = list(q.columns)
    cur = cols[0]
    # 去年同期＝往前 4 季；季報不足 5 季就退回最舊那季並標記
    yoy = cols[4] if len(cols) >= 5 else cols[-1]
    partial = len(cols) < 5

    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    def pair(df, row):
        a, b = _safe(df, row, cur), _safe(df, row, yoy)
        pct = ((a / b - 1) * 100) if (a is not None and b not in (None, 0)) else None
        return {"cur": a, "prev": b, "yoy": pct}

    d = {
        "ticker": ticker.upper(),
        "name": info.get("longName") or info.get("shortName") or ticker.upper(),
        "quarter": f"Q{(cur.month - 1)//3 + 1} {cur.year}",
        "period_end": str(cur.date()),
        "yoy_period": str(yoy.date()),
        "partial_yoy": partial,
        "currency": info.get("financialCurrency", "USD"),
        "revenue":   pair(q, "Total Revenue"),
        "gross":     pair(q, "Gross Profit"),
        "op_income": pair(q, "Operating Income"),
        "net_income": pair(q, "Net Income"),
        "eps":       pair(q, "Diluted EPS"),
        "ocf":       pair(cf, "Operating Cash Flow"),
        "capex":     pair(cf, "Capital Expenditure"),
        "fcf":       pair(cf, "Free Cash Flow"),
        "price": info.get("currentPrice"),
        "market_cap": info.get("marketCap"),
        "fwd_pe": info.get("forwardPE"),
        "trail_pe": info.get("trailingPE"),
        "peg": info.get("pegRatio"),
        "ev_rev": info.get("enterpriseToRevenue"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "pb": info.get("priceToBook"),
        "target": info.get("targetMeanPrice"),
        "reco": info.get("recommendationKey"),
        "n_analysts": info.get("numberOfAnalystOpinions"),
        "cash": info.get("totalCash"),
        "debt": info.get("totalDebt"),
        "margin": info.get("profitMargins"),
        "beta": info.get("beta"),
        "wk_high": info.get("fiftyTwoWeekHigh"),
        "wk_low": info.get("fiftyTwoWeekLow"),
        "sector": info.get("sector", ""),
    }
    # 毛利率 / 營益率（自己算，不靠 info 的口徑）
    rev = d["revenue"]["cur"]
    if rev:
        d["gross_margin"] = (d["gross"]["cur"] / rev * 100) if d["gross"]["cur"] else None
        d["op_margin"] = (d["op_income"]["cur"] / rev * 100) if d["op_income"]["cur"] else None
        prev_rev = d["revenue"]["prev"]
        d["op_margin_prev"] = (d["op_income"]["prev"] / prev_rev * 100) \
            if (d["op_income"]["prev"] and prev_rev) else None
    return d


# ────────────────────────── 星級評分（由數據算） ──────────────────────────

def _stars(v, thresholds):
    """thresholds 由高到低對應 5→1 星。v 為 None 回 None（顯示「資料不足」不硬給分）。"""
    if v is None:
        return None
    for i, th in enumerate(thresholds):
        if v >= th:
            return 5 - i
    return 1


def score(d: dict) -> dict:
    rev_g = d["revenue"]["yoy"]
    fcf = d["fcf"]["cur"]
    cash, debt = d["cash"], d["debt"]
    net_cash = (cash - debt) if (cash is not None and debt is not None) else None
    peg, fwd_pe, beta = d["peg"], d["fwd_pe"], d["beta"]

    growth = _stars(rev_g, [25, 15, 8, 3])
    # 財務體質：淨現金為正且 FCF 為正最好；FCF 轉負扣分
    health = None
    if net_cash is not None:
        health = 5 if net_cash > 0 else 2
        if fcf is not None and fcf < 0:
            health = max(1, health - 2)      # 燒錢中，體質分數下修
    # 估值：PEG 越低越好（PEG 缺值改看 forward P/E）
    if peg is not None and peg > 0:
        val = _stars(-peg, [-1.0, -1.5, -2.5, -4.0])
    elif fwd_pe is not None and fwd_pe > 0:
        val = _stars(-fwd_pe, [-15, -25, -40, -70])
    else:
        val = None
    # 風險（星越多＝風險越低）：beta 越低越好
    risk = _stars(-beta, [-0.9, -1.2, -1.6, -2.2]) if beta is not None else None

    return {"growth": growth, "health": health, "valuation": val, "risk": risk,
            "net_cash": net_cash}


# ────────────────────────────── 敘事層（LLM） ──────────────────────────────

def narrative(d: dict, sc: dict) -> dict:
    from llm_board import ask_json

    def f(x, unit="B"):
        if x is None:
            return "N/A"
        return f"{x/1e9:.2f}B" if abs(x) > 1e6 else f"{x:.2f}"

    facts = f"""公司：{d['name']}（{d['ticker']}）　產業：{d['sector']}
本季：{d['quarter']}（截至 {d['period_end']}），YoY 比較基準 {d['yoy_period']}

損益（{d['currency']}）
  營收       {f(d['revenue']['cur'])}   YoY {d['revenue']['yoy']:+.1f}%
  毛利       {f(d['gross']['cur'])}   YoY {d['gross']['yoy']:+.1f}%　毛利率 {d.get('gross_margin') or 0:.1f}%
  營業利益   {f(d['op_income']['cur'])}   YoY {d['op_income']['yoy']:+.1f}%　營益率 {d.get('op_margin') or 0:.1f}%（去年同期 {d.get('op_margin_prev') or 0:.1f}%）
  淨利       {f(d['net_income']['cur'])}   YoY {d['net_income']['yoy']:+.1f}%
  EPS        {f(d['eps']['cur'])}   YoY {d['eps']['yoy']:+.1f}%

現金流
  營運現金流 {f(d['ocf']['cur'])}   YoY {d['ocf']['yoy']:+.1f}%
  資本支出   {f(d['capex']['cur'])}   YoY {d['capex']['yoy']:+.1f}%
  自由現金流 {f(d['fcf']['cur'])}   YoY {d['fcf']['yoy']:+.1f}%

估值與體質
  股價 {d['price']}　市值 {f(d['market_cap'])}　52週 {d['wk_low']}~{d['wk_high']}
  Forward P/E {d['fwd_pe']}　Trailing P/E {d['trail_pe']}　PEG {d['peg']}
  EV/Rev {d['ev_rev']}　EV/EBITDA {d['ev_ebitda']}　P/B {d['pb']}
  總現金 {f(d['cash'])}　總負債 {f(d['debt'])}　淨現金 {f(sc['net_cash'])}
  Beta {d['beta']}　分析師共識 {d['reco']}（{d['n_analysts']} 位）　平均目標價 {d['target']}
"""

    prompt = f"""你是專業財報分析師，要為以下這季財報寫一份「懶人包」的敘事內容。

【鐵則】
1. **只能引用下方提供的真實數據，絕對不可以編造任何數字、日期、產品名稱、管理層發言或新聞事件。**
   你沒有這家公司的財報電話會議內容，也沒有新聞，只有下面這些數字。
2. 需要提到具體數字時，直接引用下方數據。不確定的事情就不要寫。
3. 用繁體中文台灣用語（營收/毛利率/營益率/資本支出/自由現金流/部位）。
4. 要點出「數字背後的矛盾」——例如營收成長但獲利衰退、現金流轉負等，這才是懶人包的價值。

{facts}

請只回 JSON，不要任何說明文字：
{{
  "highlights": [
    {{"icon":"適合的單個emoji","title":"亮點標題(10字內)","desc":"說明(45字內，要引用具體數字)"}}
  ],
  "capital": [
    {{"icon":"單個emoji","title":"資本/產能面標題(10字內)","desc":"說明(45字內，聚焦資本支出與現金流)"}}
  ],
  "positives": ["利多條列(30字內)"],
  "risks": ["風險條列(30字內)"],
  "moat_stars": 1到5的整數,
  "moat_reason": "護城河評分理由(35字內)",
  "thesis": "長線投資邏輯(60字內)",
  "investor": "適合什麼樣的投資人(30字內)",
  "sentiment": "市場情緒評級，只能從這五選一：VERY BEARISH / BEARISH / NEUTRAL / BULLISH / VERY BULLISH",
  "sentiment_reason": "情緒評級理由(30字內)",
  "entry": "進場策略建議(40字內，可參考52週區間與目標價)",
  "bottom_line": "一句話總結長期投資價值(50字內)"
}}
highlights 與 capital 各給 3-4 項，positives 與 risks 各給 4-5 項。"""
    return ask_json(prompt)


# ────────────────────────────── 版面 ──────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0A1628;color:#E8EEF7;
 font-family:"Microsoft JhengHei","PingFang TC",-apple-system,"Segoe UI",sans-serif;
 padding:22px;line-height:1.5}
.wrap{max-width:1280px;margin:0 auto}
.card{background:#132A47;border:1px solid #1E3A5F;border-radius:14px;padding:16px}
.hd{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
 border-bottom:3px solid #F5B841;padding-bottom:14px;margin-bottom:18px;flex-wrap:wrap}
.hd h1{font-size:27px;font-weight:800;letter-spacing:.5px}
.hd .sub{color:#8FA8C8;font-size:13px;margin-top:3px}
.tk{font-size:34px;font-weight:800;color:#F5B841;line-height:1}
.tk-sub{color:#8FA8C8;font-size:12px;text-align:right;margin-top:4px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:16px}
.kpi{background:#132A47;border:1px solid #1E3A5F;border-radius:14px;padding:14px 12px;
 border-top:3px solid #2E4A6F}
.kpi .lb{color:#8FA8C8;font-size:11.5px;letter-spacing:.4px;text-transform:uppercase}
.kpi .vl{font-size:26px;font-weight:800;margin:5px 0 3px;letter-spacing:-.5px}
.kpi .yo{font-size:13px;font-weight:700}
.up{color:#22C55E}.dn{color:#EF4444}.neu{color:#8FA8C8}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px}
h2{font-size:14px;font-weight:800;color:#F5B841;letter-spacing:.6px;margin-bottom:11px;
 text-transform:uppercase}
.item{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #1E3A5F}
.item:last-child{border-bottom:0}
.ic{font-size:19px;line-height:1.2;flex-shrink:0;width:24px;text-align:center}
.it-t{font-weight:700;font-size:13.5px;margin-bottom:2px}
.it-d{color:#A9C0DC;font-size:12.5px;line-height:1.55}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:#8FA8C8;font-weight:600;text-align:right;padding:6px 4px;
 border-bottom:1px solid #1E3A5F;font-size:11.5px}
th:first-child{text-align:left}
td{padding:6px 4px;text-align:right;border-bottom:1px solid #16304F}
td:first-child{text-align:left;color:#C7D8EC}
.gauge{text-align:center;margin-top:12px}
.gauge .lbl{font-size:15px;font-weight:800;margin-top:-8px}
.gauge .rsn{color:#8FA8C8;font-size:11.5px;margin-top:5px;line-height:1.45}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.pos{background:#0E2E1E;border:1px solid #1B5E3A}
.neg{background:#2E1418;border:1px solid #5E1B24}
.pos h2{color:#22C55E}.neg h2{color:#EF4444}
.li{display:flex;gap:9px;padding:7px 0;font-size:12.8px;line-height:1.5;align-items:flex-start}
.li .m{flex-shrink:0;font-weight:800}
.pos .m{color:#22C55E}.neg .m{color:#EF4444}
.dec{display:grid;grid-template-columns:1.15fr 1fr;gap:12px;margin-bottom:16px}
.rate{display:flex;justify-content:space-between;align-items:center;padding:8px 0;
 border-bottom:1px solid #1E3A5F;font-size:13px}
.rate:last-of-type{border-bottom:0}
.st{color:#F5B841;letter-spacing:2.5px;font-size:14.5px}
.st .off{color:#33507A}
.na{color:#8FA8C8;font-size:11.5px;letter-spacing:0}
.badge{text-align:center;padding:14px;border-radius:12px;margin-bottom:12px}
.badge .bg{font-size:31px;font-weight:800;letter-spacing:2px;line-height:1}
.badge .bs{font-size:11.5px;margin-top:5px;opacity:.92}
.note{color:#8FA8C8;font-size:11.5px;margin-top:9px;line-height:1.5}
.bl{background:linear-gradient(90deg,#14304F,#1B3E63);border:1px solid #2A4E78;
 border-radius:14px;padding:16px 20px;display:flex;align-items:center;gap:15px}
.bl .e{font-size:29px;flex-shrink:0}
.bl .t{font-size:11.5px;color:#F5B841;font-weight:800;letter-spacing:1.2px;margin-bottom:3px}
.bl .c{font-size:14.5px;line-height:1.6}
.ftr{color:#6B84A6;font-size:11px;margin-top:16px;line-height:1.7;
 border-top:1px solid #1E3A5F;padding-top:12px}
.warn{background:#3A2A0E;border:1px solid #7A5A1E;color:#F5C96B;border-radius:9px;
 padding:9px 13px;font-size:12px;margin-bottom:14px}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(2,1fr)}
 .grid3,.two,.dec{grid-template-columns:1fr}}
"""


def _fmt(v, cur="USD"):
    if v is None:
        return "N/A"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a/1e9:.2f}B" if cur == "USD" else f"{sign}{a/1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a/1e6:.0f}M" if cur == "USD" else f"{sign}{a/1e6:.0f}M"
    return f"{sign}${a:.2f}" if cur == "USD" else f"{sign}{a:.2f}"


def _yoy(p, invert=False):
    """invert=True 用於 CapEx 這種「增加不一定是好事」的指標 → 只顯示不上色。"""
    if p is None:
        return '<span class="yo neu">— YoY 無可比基期</span>'
    if invert:
        return f'<span class="yo neu">{p:+.1f}% YoY</span>'
    cls, arw = ("up", "▲") if p >= 0 else ("dn", "▼")
    return f'<span class="yo {cls}">{arw} {p:+.1f}% YoY</span>'


def _stars_html(n):
    if n is None:
        return '<span class="na">資料不足，不評分</span>'
    return ('<span class="st">' + "★" * n
            + f'<span class="off">{"★" * (5 - n)}</span></span>')


GAUGE = ["VERY BEARISH", "BEARISH", "NEUTRAL", "BULLISH", "VERY BULLISH"]


def _gauge_svg(label):
    idx = GAUGE.index(label) if label in GAUGE else 2
    import math
    ang = math.pi - (idx / 4) * math.pi              # 180°(左/看空) → 0°(右/看多)
    cx, cy, r = 110, 100, 76
    x, y = cx + r * 0.82 * math.cos(ang), cy - r * 0.82 * math.sin(ang)
    segs, colors = 5, ["#EF4444", "#F97316", "#8FA8C8", "#4ADE80", "#22C55E"]
    arcs = []
    for i in range(segs):
        a0, a1 = math.pi - i * math.pi / segs, math.pi - (i + 1) * math.pi / segs
        x0, y0 = cx + r * math.cos(a0), cy - r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy - r * math.sin(a1)
        arcs.append(f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}" '
                    f'stroke="{colors[i]}" stroke-width="15" fill="none" stroke-linecap="butt"/>')
    color = colors[idx]
    return (f'<svg viewBox="0 0 220 118" style="width:100%;max-width:220px">'
            + "".join(arcs)
            + f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#E8EEF7" '
              f'stroke-width="3.5" stroke-linecap="round"/>'
              f'<circle cx="{cx}" cy="{cy}" r="7" fill="#E8EEF7"/></svg>'
              f'<div class="lbl" style="color:{color}">{label}</div>')


BADGE_STYLE = {
    "strong_buy": ("#0E3A22", "#22C55E", "STRONG BUY"),
    "buy":        ("#0E3A22", "#22C55E", "BUY"),
    "hold":       ("#3A3212", "#F5B841", "HOLD"),
    "underperform": ("#3A1A18", "#EF4444", "UNDERPERFORM"),
    "sell":       ("#3A1418", "#EF4444", "SELL"),
}


def render(d, sc, n):
    cur = d["currency"]
    up = d["target"] and d["price"] and (d["target"] / d["price"] - 1) * 100
    bg, fg, txt = BADGE_STYLE.get(d["reco"], ("#22374F", "#8FA8C8", (d["reco"] or "N/A").upper()))

    kpis = [
        ("營收 Revenue", _fmt(d["revenue"]["cur"], cur), d["revenue"]["yoy"], False),
        ("毛利 Gross Profit", _fmt(d["gross"]["cur"], cur), d["gross"]["yoy"], False),
        ("營業利益 Op. Income", _fmt(d["op_income"]["cur"], cur), d["op_income"]["yoy"], False),
        ("淨利 Net Income", _fmt(d["net_income"]["cur"], cur), d["net_income"]["yoy"], False),
        ("資本支出 CapEx", _fmt(abs(d["capex"]["cur"]) if d["capex"]["cur"] else None, cur),
         d["capex"]["yoy"], True),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="lb">{lb}</div><div class="vl">{v}</div>{_yoy(p, inv)}</div>'
        for lb, v, p, inv in kpis)

    def items(rows):
        return "".join(
            f'<div class="item"><div class="ic">{r.get("icon","•")}</div><div>'
            f'<div class="it-t">{r.get("title","")}</div>'
            f'<div class="it-d">{r.get("desc","")}</div></div></div>' for r in rows)

    fin_rows = [("營收", d["revenue"]), ("毛利", d["gross"]), ("營業利益", d["op_income"]),
                ("淨利", d["net_income"]), ("營運現金流", d["ocf"]), ("自由現金流", d["fcf"])]
    fin_html = "".join(
        f'<tr><td>{lb}</td><td>{_fmt(p["cur"], cur)}</td>'
        f'<td class="{"up" if (p["yoy"] or 0) >= 0 else "dn"}">'
        f'{f"{p['yoy']:+.1f}%" if p["yoy"] is not None else "—"}</td></tr>'
        for lb, p in fin_rows)

    val_rows = [("Forward P/E", d["fwd_pe"], "低於 20 偏便宜"),
                ("Trailing P/E", d["trail_pe"], "看過去 12 個月"),
                ("PEG Ratio", d["peg"], "小於 1 代表成長性被低估"),
                ("EV / Revenue", d["ev_rev"], "越低越好"),
                ("EV / EBITDA", d["ev_ebitda"], "越低越好"),
                ("P / B", d["pb"], "資產面估值")]
    val_html = "".join(
        f'<tr><td>{lb}</td><td>{f"{v:.2f}" if isinstance(v, (int, float)) else "N/A"}</td>'
        f'<td style="color:#6B84A6;font-size:11px;text-align:right">{h}</td></tr>'
        for lb, v, h in val_rows)

    rates = [("成長性 Growth Outlook", sc["growth"], "依營收 YoY 計算"),
             ("競爭護城河 Moat", n.get("moat_stars"), n.get("moat_reason", "")),
             ("財務體質 Financial Health", sc["health"], "依淨現金與自由現金流"),
             ("估值 Valuation", sc["valuation"], "依 PEG / Forward P/E"),
             ("風險輪廓 Risk Profile", sc["risk"], "依 Beta，星多＝波動低")]
    rate_html = "".join(
        f'<div class="rate"><div>{lb}<div style="color:#6B84A6;font-size:10.5px;'
        f'font-weight:400;margin-top:1px">{hint}</div></div>{_stars_html(v)}</div>'
        for lb, v, hint in rates)

    warn = ('<div class="warn">⚠️ 這檔季報資料不足 5 季，YoY 比較基期不是去年同期，'
            '成長率僅供參考。</div>') if d["partial_yoy"] else ""

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{d['ticker']} {d['quarter']} 財報懶人包</title>
<style>{CSS}</style></head><body><div class="wrap">

<div class="hd">
  <div><h1>{d['name']}</h1>
    <div class="sub">{d['quarter']} 財報懶人包　·　會計期間截至 {d['period_end']}　·　YoY 基準 {d['yoy_period']}</div></div>
  <div><div class="tk">{d['ticker']}</div>
    <div class="tk-sub">股價 {d['price']} {cur}　·　產生於 {datetime.now():%Y-%m-%d %H:%M}</div></div>
</div>
{warn}
<div class="kpis">{kpi_html}</div>

<div class="grid3">
  <div class="card"><h2>營運亮點 Highlights</h2>{items(n.get('highlights', []))}</div>
  <div class="card"><h2>財務數據 Financial Results</h2>
    <table><tr><th>項目</th><th>本季</th><th>YoY</th></tr>{fin_html}</table>
    <div class="gauge"><h2 style="margin-top:16px">市場情緒 Sentiment</h2>
      {_gauge_svg(n.get('sentiment', 'NEUTRAL'))}
      <div class="rsn">{n.get('sentiment_reason', '')}</div></div>
  </div>
  <div class="card"><h2>資本與產能動態 Capital &amp; Capacity</h2>{items(n.get('capital', []))}</div>
</div>

<div class="two">
  <div class="card pos"><h2>✓ 利多 Key Positives</h2>
    {"".join(f'<div class="li"><span class="m">✓</span><span>{x}</span></div>' for x in n.get('positives', []))}</div>
  <div class="card neg"><h2>✕ 風險 Key Risks &amp; Concerns</h2>
    {"".join(f'<div class="li"><span class="m">✕</span><span>{x}</span></div>' for x in n.get('risks', []))}</div>
</div>

<div class="dec">
  <div class="card"><h2>投資決策矩陣 Decision Framework</h2>{rate_html}
    <div style="margin-top:13px;padding-top:12px;border-top:1px solid #1E3A5F">
      <div style="color:#F5B841;font-size:11.5px;font-weight:700;margin-bottom:4px">長線投資邏輯</div>
      <div style="font-size:12.8px;line-height:1.6;color:#C7D8EC">{n.get('thesis', '')}</div>
      <div style="color:#F5B841;font-size:11.5px;font-weight:700;margin:11px 0 4px">適合的投資人</div>
      <div style="font-size:12.8px;color:#C7D8EC">{n.get('investor', '')}</div>
    </div>
  </div>
  <div class="card"><h2>分析師共識與估值 Consensus</h2>
    <div class="badge" style="background:{bg};border:1px solid {fg}">
      <div class="bg" style="color:{fg}">{txt}</div>
      <div class="bs" style="color:{fg}">{d['n_analysts'] or '?'} 位分析師共識　·　平均目標價 {d['target'] or 'N/A'}
        {f'（潛在空間 {up:+.1f}%）' if up is not None else ''}</div>
    </div>
    <table>{val_html}</table>
    <div style="margin-top:11px;padding-top:10px;border-top:1px solid #1E3A5F">
      <div style="color:#F5B841;font-size:11.5px;font-weight:700;margin-bottom:4px">進場策略</div>
      <div style="font-size:12.8px;line-height:1.6;color:#C7D8EC">{n.get('entry', '')}</div>
      <div class="note">52 週區間 {d['wk_low']} ~ {d['wk_high']}　·　市值 {_fmt(d['market_cap'], cur)}
        　·　淨現金 {_fmt(sc['net_cash'], cur)}</div>
    </div>
  </div>
</div>

<div class="bl"><div class="e">💡</div>
  <div><div class="t">BOTTOM LINE</div><div class="c">{n.get('bottom_line', '')}</div></div>
  <div class="e">📈</div></div>

<div class="ftr">
  <b>資料來源</b>：所有財務數字與估值指標皆取自 yfinance 之公司申報財報，未經 AI 生成或修改。
  星級評分中的成長性/財務體質/估值/風險由公式計算，「競爭護城河」與文字敘述由 AI 依上述數據撰寫。<br>
  <b>評級說明</b>：BUY/HOLD 標章顯示的是<b>市場分析師共識</b>（yfinance 彙整），不是本工具的買賣建議。
  本頁為研究參考，不構成投資建議。<br>
  <b>已知限制</b>：無法取得法說會內容、管理層展望與新聞，因此「下季展望」類資訊不予呈現，避免編造。
</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="財報懶人包 Infographic 產生器")
    ap.add_argument("ticker")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--no-llm", action="store_true", help="跳過 AI 敘事層，只出數據")
    ap.add_argument("--obis", action="store_true", help="同時存一份到 obis")
    args = ap.parse_args()

    print(f"抓 {args.ticker} 財報 …", end=" ", flush=True)
    d = fetch(args.ticker)
    print(f"{d['quarter']}（截至 {d['period_end']}）")
    sc = score(d)

    n = {}
    if not args.no_llm:
        print("AI 撰寫敘事層 …", end=" ", flush=True)
        try:
            n = narrative(d, sc)
            print("完成")
        except Exception as e:
            print(f"失敗：{e}\n  → 改出純數據版")
    if not n:
        n = {"sentiment": "NEUTRAL", "highlights": [], "capital": [],
             "positives": [], "risks": [],
             "bottom_line": "（未產生 AI 敘事層，本頁僅呈現真實財報數據）"}

    out = args.output or f"docs/earnings_{d['ticker'].replace('.', '_')}.html"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    html = render(d, sc, n)
    targets = [out] + ([os.path.join(OBIS, f"{d['ticker']}_{d['quarter']}_財報懶人包.html")]
                       if args.obis else [])
    for p in targets:
        try:
            open(p, "w", encoding="utf-8").write(html)
            print(f"✅ {p}")
        except Exception as e:
            print(f"⚠️ 寫入 {p} 失敗：{e}")


if __name__ == "__main__":
    main()
