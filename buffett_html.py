"""巴菲特價值清單 HTML 頁（洪瑞泰俗貴價法）。

資料：buffett_watch.json（從 TradingBot DB 匯出，含 sector/eps/roe/俗貴價/龍頭rank）
顯示：洪瑞泰核心（現價 vs 俗/合理/貴價 → 訊號）為主，加兩層補充：
  ① 龍頭#1/#2/#3（同 sector 市值排名）
  ② 照妖鏡（forward EPS 衰退 / 高負債）= 價值陷阱警示
不改洪瑞泰估值，只加標註。

用法:python buffett_html.py [-o docs/buffett.html]
"""
import os
import json
import html as _html
import argparse
from datetime import datetime
import yfinance as yf

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"
PAGES_URL = "https://dt-1983.github.io/daily-stock-board/"
DECLINE_RATIO = 0.90   # forward/trailing < 0.9 → EPS 衰退
DE_HIGH = 250          # 負債權益比 > 250% → 高槓桿

SIG = {  # 訊號: (emoji, 中文, css)
    "buy":   ("🟢", "買進", "buy"),
    "watch": ("🟡", "觀望", "watch"),
    "hold":  ("🔵", "持有", "hold"),
    "sell":  ("🔴", "賣出", "sell"),
    "na":    ("⚪", "無資料", "hold"),
}
ORDER = ["buy", "watch", "hold", "sell", "na"]


def esc(s):
    return _html.escape(str(s if s is not None else ""))


def hong_signal(price, cheap, fair, exp):
    """洪瑞泰訊號：現價 vs 俗/合理/貴價。"""
    if not price or not cheap:
        return "na"
    if price <= cheap:
        return "buy"
    if fair and price <= fair:
        return "watch"
    if exp and price <= exp:
        return "hold"
    return "sell"


def quality_flags(tk):
    """照妖鏡：forward EPS 衰退 + 高負債（價值陷阱照妖）。回 tags list。"""
    tags = []
    try:
        i = yf.Ticker(tk).info
        te, fe, de = i.get("trailingEps"), i.get("forwardEps"), i.get("debtToEquity")
        if te and fe and te > 0 and (fe / te) < DECLINE_RATIO:
            tags.append(f"EPS估降{(1-fe/te)*100:.0f}%")
        if de and de > DE_HIGH:
            tags.append(f"高負債{de:.0f}%")
    except Exception:
        pass
    return tags


CSS = """
*{box-sizing:border-box}
body{font-family:"Microsoft JhengHei","PingFang TC",-apple-system,sans-serif;margin:0;
 background:#0f1115;color:#e6e6e6;line-height:1.55;font-size:15px}
.wrap{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:6px 0}.sub{color:#9aa0a6;font-size:13px}
a{color:#6db3ff}
.legend{background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;padding:10px 12px;margin:10px 0;font-size:13px}
.sec{margin:22px 0 6px;font-size:17px;border-left:4px solid #4a9eff;padding-left:10px;display:flex;align-items:center;gap:8px}
.cnt{font-size:12px;color:#9aa0a6;background:#1c2128;padding:1px 8px;border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:4px 0}
th,td{border:1px solid #2a2e35;padding:6px 8px;text-align:right;white-space:nowrap}
th{background:#222831;text-align:center;position:sticky;top:0;cursor:pointer}
td.l,th.l{text-align:left}
tr.buy{background:#10241a}tr.sell{background:#251114}tr.watch{background:#231f10}
.tk{font-weight:700;font-size:14px}
.lead{font-size:11px;color:#ffd479;background:#2a2410;padding:1px 6px;border-radius:8px}
.trap{font-size:11px;color:#ff9b9b;background:#2a1414;padding:1px 6px;border-radius:8px}
.ok{font-size:11px;color:#3ddc84}
.dis{color:#3ddc84;font-weight:600}
.scrollbox{overflow-x:auto}
"""


def build(watch):
    # 取現價（批次）
    tickers = list(watch.keys())
    prices = {}
    try:
        data = yf.download(tickers, period="5d", progress=False, threads=False,
                           auto_adjust=True, group_by="ticker")
        for tk in tickers:
            try:
                prices[tk] = float(data[tk]["Close"].dropna().iloc[-1])
            except Exception:
                pass
    except Exception as e:
        print("price fetch err:", e)

    # 分組
    rows = {k: [] for k in ORDER}
    for tk, d in watch.items():
        price = prices.get(tk)
        cheap, fair, exp = d.get("cheap"), d.get("fair"), d.get("expensive")
        sig = hong_signal(price, cheap, fair, exp)
        dis = ((cheap - price) / cheap * 100) if (price and cheap and price <= cheap) else None
        # 照妖鏡只對 buy/watch（actionable）跑，省 API
        tags = quality_flags(tk) if sig in ("buy", "watch") else []
        rows[sig].append({
            "tk": tk, "sector": d.get("sector", ""), "rank": d.get("rank"),
            "price": price, "cheap": cheap, "fair": fair, "exp": exp,
            "roe": d.get("roe"), "eps": d.get("eps"), "dis": dis, "tags": tags,
        })

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    upd = next((v.get("updated") for v in watch.values() if v.get("updated")), "?")
    out = [f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>巴菲特價值清單</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>🏛️ 巴菲特價值清單（洪瑞泰俗貴價法）</h1>
<div class="sub">資料更新 {esc(upd)} · 產生 {date} · 共 {len(watch)} 檔 · <a href="{PAGES_URL}">← 產業鏈看板</a></div>
<div class="legend">
<b>訊號（洪瑞泰核心）</b>：🟢買進 現價≤俗價 ｜ 🟡觀望 俗價~合理價 ｜ 🔵持有 合理~貴價 ｜ 🔴賣出 現價&gt;貴價<br>
<b>俗價</b>=EPS×12 ｜ <b>合理價</b>=EPS×15 ｜ <b>貴價</b>=EPS×20（洪瑞泰原版倍數）<br>
<span class="lead">龍頭#N</span> = 同 sector 市值前 3（補充參考）
<span class="trap">⚠️照妖鏡</span> = forward EPS 衰退 / 負債&gt;{DE_HIGH}%（俗價用過去 EPS 算，未來恐縮水 → 便宜有理由，別追）<br>
<i>照妖鏡只是「多一層檢查」，不改洪瑞泰選股；🟢🟡才跑（actionable）。</i>
</div>"""]

    for sig in ORDER:
        lst = rows[sig]
        if not lst:
            continue
        emoji, name, _ = SIG[sig]
        # 排序：buy 按折價大→小，其餘按市值龍頭→ROE
        if sig == "buy":
            lst.sort(key=lambda r: -(r["dis"] or 0))
        else:
            lst.sort(key=lambda r: (r["rank"] or 9, -(r["roe"] or 0)))
        out.append(f'<div class="sec">{emoji} <b>{name}</b> <span class="cnt">{len(lst)} 檔</span></div>')
        out.append('<div class="scrollbox"><table>')
        out.append('<tr><th class="l">代號</th><th class="l">產業</th><th>現價</th>'
                   '<th>俗價</th><th>合理價</th><th>貴價</th><th>折價%</th>'
                   '<th>ROE</th><th>EPS</th><th class="l">標註</th></tr>')
        for r in lst:
            lead = f'<span class="lead">龍頭#{int(r["rank"])}</span> ' if r.get("rank") else ""
            if r["tags"]:
                note = " ".join(f'<span class="trap">⚠️{esc(t)}</span>' for t in r["tags"])
            elif sig in ("buy", "watch"):
                note = '<span class="ok">✅ 體質過關</span>'
            else:
                note = ""
            roe = f'{r["roe"]*100:.0f}%' if r.get("roe") is not None else "—"
            eps = f'{r["eps"]:.2f}' if r.get("eps") is not None else "—"
            dis = f'<span class="dis">{r["dis"]:.0f}%</span>' if r.get("dis") else "—"
            px = f'{r["price"]:.1f}' if r.get("price") else "—"
            out.append(
                f'<tr class="{sig}"><td class="l">{lead}<span class="tk">{esc(r["tk"])}</span></td>'
                f'<td class="l">{esc(r["sector"])}</td><td>{px}</td>'
                f'<td>{r["cheap"]:.1f}</td><td>{r["fair"]:.0f}</td><td>{r["exp"]:.0f}</td>'
                f'<td>{dis}</td><td>{roe}</td><td>{eps}</td><td class="l">{note}</td></tr>'
            )
        out.append('</table></div>')

    out.append('<p class="sub" style="margin-top:20px">洪瑞泰俗貴價法 · 龍頭=同產業市值前3 · '
               '照妖鏡=forward EPS+負債（補充非洪瑞泰）· 資料源 TradingBot DB</p>')
    out.append("</div></body></html>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/buffett.html")
    args = ap.parse_args()
    if not os.path.exists("buffett_watch.json"):
        print("無 buffett_watch.json，跳過")
        return
    watch = json.load(open("buffett_watch.json", encoding="utf-8"))
    html = build(watch)
    for out in [args.output, os.path.join(OBIS, "巴菲特價值清單.html")]:
        try:
            if os.path.dirname(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "w", encoding="utf-8").write(html)
            print(f"✅ 已存:{out}")
        except Exception as e:
            print(f"⚠️ 寫 {out} 失敗:{e}")


if __name__ == "__main__":
    main()
