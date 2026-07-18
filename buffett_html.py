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

SECTOR_TW = {  # yfinance GICS 產業 → 繁中
    "Technology": "科技", "Financial Services": "金融", "Healthcare": "醫療保健",
    "Consumer Cyclical": "非必需消費", "Consumer Defensive": "必需消費",
    "Communication Services": "通訊服務", "Industrials": "工業", "Energy": "能源",
    "Basic Materials": "原物料", "Real Estate": "房地產", "Utilities": "公用事業",
    "Unknown": "未分類", "": "未分類",
}


def sector_tw(s):
    return SECTOR_TW.get(s, s)


SIG = {  # 訊號: (emoji, 中文, css)
    "buy":   ("🟢", "買進", "buy"),
    "watch": ("🟡", "觀望", "watch"),
    "hold":  ("🔵", "持有", "hold"),
    "sell":  ("🔴", "太貴", "sell"),
    "na":    ("⚪", "無資料", "hold"),
}
ORDER = ["buy", "watch", "hold", "sell", "na"]


def esc(s):
    return _html.escape(str(s if s is not None else ""))


def hong_signal(price, cheap, exp):
    """洪瑞泰訊號：只有俗價(買)/貴價(賣)兩條線。便宜~貴之間＝觀望，>貴＝太貴。"""
    if not price or not cheap:
        return "na"
    if price <= cheap:
        return "buy"
    if exp and price <= exp:
        return "watch"
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
.toggle{display:inline-flex;background:#1c2128;border-radius:18px;padding:3px;margin:10px 0}
.toggle button{border:0;background:transparent;color:#9aa0a6;padding:6px 18px;border-radius:15px;font-size:14px;cursor:pointer;font-weight:600}
.toggle button.on{background:#4a9eff;color:#fff}
.nm{color:#9aa0a6;font-size:12px;font-weight:400}
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
.filt{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
.fb{font-size:13px;padding:5px 12px;border-radius:16px;border:1px solid #2a2e35;
 background:#1c2128;color:#bcd2ff;cursor:pointer}
.fb.on{background:#4a9eff;color:#fff;border-color:#4a9eff}
"""


def _market_html(mkt, rows, show):
    """單一市場（US/TW）的篩選鈕 + 各訊號分組表。show=True 預設顯示。"""
    o = [f'<div class="market" data-mkt="{mkt}"{"" if show else " style=display:none"}>']
    total = sum(len(rows[s]) for s in ORDER)
    if not total:
        o.append('<p class="sub">此市場暫無 BUY/WATCH 標的（掃描後更新）。</p></div>')
        return "".join(o)
    # 篩選鈕
    o.append(f'<div class="filt"><button class="fb on" onclick="flt(this,\'all\')">全部 {total}</button>')
    for sig in ORDER:
        if rows[sig]:
            e, nm, _ = SIG[sig]
            o.append(f'<button class="fb" onclick="flt(this,\'{sig}\')">{e} {nm} {len(rows[sig])}</button>')
    o.append('</div>')
    for sig in ORDER:
        lst = rows[sig]
        if not lst:
            continue
        emoji, name, _ = SIG[sig]
        # 洪瑞泰：EPS 估降＝公司變壞、俗價是假便宜 → 一律排後面（體質過關優先浮上）
        def _decline(r):
            return 1 if any(str(t).startswith("EPS估降") for t in (r.get("tags") or [])) else 0
        if sig == "buy":
            lst.sort(key=lambda r: (_decline(r), -(r["dis"] or 0)))
        else:
            lst.sort(key=lambda r: (_decline(r), r["rank"] or 9, -(r["roe"] or 0)))
        o.append(f'<div class="sgroup" data-sig="{sig}">')
        o.append(f'<div class="sec">{emoji} <b>{name}</b> <span class="cnt">{len(lst)} 檔</span></div>')
        o.append('<div class="scrollbox"><table>')
        o.append('<tr><th class="l">代號</th><th class="l">產業</th><th>現價</th>'
                 '<th>俗價</th><th>貴價</th><th>折價%</th>'
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
            nm_disp = f'<span class="nm">{esc(r["name"])}</span>' if r.get("name") else ""
            o.append(
                f'<tr class="{sig}"><td class="l">{lead}<span class="tk">{esc(r["tk"])}</span> {nm_disp}</td>'
                f'<td class="l">{esc(sector_tw(r["sector"]))}</td><td>{px}</td>'
                f'<td>{r["cheap"]:.1f}</td><td>{r["exp"]:.0f}</td>'
                f'<td>{dis}</td><td>{roe}</td><td>{eps}</td><td class="l">{note}</td></tr>'
            )
        o.append('</table></div></div>')
    o.append('</div>')
    return "".join(o)


def build(watch):
    # 取現價（批次，美台混抓）
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

    # 依市場分組（US / TW），各自再依訊號分組
    mkts = {"US": {k: [] for k in ORDER}, "TW": {k: [] for k in ORDER}}
    for tk, d in watch.items():
        mkt = d.get("market", "US")
        mkts.setdefault(mkt, {k: [] for k in ORDER})
        price = prices.get(tk)
        cheap, fair, exp = d.get("cheap"), d.get("fair"), d.get("expensive")
        sig = hong_signal(price, cheap, exp)
        dis = ((cheap - price) / cheap * 100) if (price and cheap and price <= cheap) else None
        tags = quality_flags(tk) if sig in ("buy", "watch") else []
        disp_tk = tk[:-3] if (mkt == "TW" and tk.endswith(".TW")) else tk   # 台股去 .TW
        mkts[mkt][sig].append({
            "tk": disp_tk, "name": d.get("name"), "sector": d.get("sector", ""),
            "rank": d.get("rank"), "price": price, "cheap": cheap, "fair": fair,
            "exp": exp, "roe": d.get("roe"), "eps": d.get("eps"), "dis": dis, "tags": tags,
        })

    n_us = sum(len(mkts["US"][s]) for s in ORDER)
    n_tw = sum(len(mkts["TW"][s]) for s in ORDER)
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    upd = next((v.get("updated") for v in watch.values() if v.get("updated")), "?")
    out = [f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>巴菲特價值清單</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>🏛️ 巴菲特價值清單（洪瑞泰俗貴價法）</h1>
<div class="sub">資料更新 {esc(upd)} · 產生 {date} · 美股 {n_us} / 台股 {n_tw} 檔 · <a href="{PAGES_URL}">← 產業鏈看板</a></div>
<div class="toggle">
 <button data-m="US" class="on" onclick="setMkt('US')">🇺🇸 美股 {n_us}</button>
 <button data-m="TW" onclick="setMkt('TW')">🇹🇼 台股 {n_tw}</button>
</div>
<div class="legend">
<b>訊號（洪瑞泰）</b>：🟢買進 現價≤俗價 ｜ 🟡觀望 俗價~貴價之間 ｜ 🔴太貴 現價&gt;貴價<br>
<b>俗價</b>=EPS×12（<b>買進線</b>，報酬15%）｜ <b>貴價</b>=EPS×30（<b>賣出線</b>，報酬0%）<span class="sub">　洪瑞泰只設便宜買／貴賣兩條線，不用合理價</span><br>
<span class="lead">龍頭#N</span> = 同 sector 市值前 3（補充參考）
<span class="trap">⚠️照妖鏡</span> = forward EPS 衰退 / 負債&gt;{DE_HIGH}%（俗價用過去 EPS 算，未來恐縮水 → 便宜有理由，別追）<br>
<i>排序：<b>✅體質過關優先浮上</b>，⚠️EPS 估降者殿後（EPS 變差＝俗價是假便宜，洪瑞泰不追）。🟢🟡才跑照妖鏡。台股價格為 TWD。</i>
</div>"""]

    out.append(_market_html("US", mkts["US"], show=True))
    out.append(_market_html("TW", mkts["TW"], show=False))

    out.append('<p class="sub" style="margin-top:20px">洪瑞泰俗貴價法 · 龍頭=同市場同產業市值前3 · '
               '照妖鏡=forward EPS+負債（補充非洪瑞泰）· 資料源 TV-Screener + yfinance</p>')
    out.append("""<script>
function flt(b,s){const m=b.closest('.market');
m.querySelectorAll('.fb').forEach(x=>x.classList.remove('on'));b.classList.add('on');
m.querySelectorAll('.sgroup').forEach(g=>{g.style.display=(s=='all'||g.dataset.sig==s)?'':'none';});}
function setMkt(m){document.querySelectorAll('.toggle button').forEach(b=>b.classList.toggle('on',b.dataset.m===m));
document.querySelectorAll('.market').forEach(x=>x.style.display=(x.dataset.mkt===m)?'':'none');}
</script>""")
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
