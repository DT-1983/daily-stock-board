# -*- coding: utf-8 -*-
"""台指選擇權 GEX 頁 → docs/gex.html

讀 data/gex/latest.json（gex_options.py 產出）。純靜態、不載外部 JS。
配色：不是買賣訊號，所以不用紅綠——正 GEX（避震器）用青藍、負 GEX（油門）用橘。
用法：python gex_html.py [-o docs/gex.html]
"""
from board_theme import snapped as _bt_snapped
import argparse
import glob
import json
import os
import sys
from datetime import datetime

from board_theme import BASE_CSS, header, esc, NAV

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "gex")
POS, NEG, FLIP = "#3B82F6", "#EF4444", "#EAB308"   # 站內語彙：藍＝穩定（避震器）、紅＝警戒（油門）、黃＝分界

CSS_EXTRA = """
.gxhero{background:var(--surface);border:1px solid var(--line);border-left:4px solid #EAB308;
 border-radius:12px;padding:16px 18px;margin:14px 0;font-size:16px;line-height:1.75}
.gxhero b{font-weight:800}
.gxcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:12px 0}
.gxc{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--line);
 border-radius:11px;padding:13px 14px}
.gxc .k{font-size:12.5px;font-weight:700;color:var(--muted)}
.gxc .v{font-size:26px;font-weight:800;margin:4px 0 2px}
.gxc .s{font-size:12px;color:var(--dim);line-height:1.6}
.gxbox{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.gxbox h2{font-size:14.5px;font-weight:700;margin-bottom:4px}
.gxbox .meta{font-size:11.5px;color:var(--dim);margin-bottom:8px}
.gxsteps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:10px 0}
.gxsteps div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:13px;line-height:1.7;color:var(--muted)}
.gxsteps b{color:var(--ink)}
table.gxh{width:100%;border-collapse:collapse;font-size:13px}
table.gxh th,table.gxh td{padding:7px 8px;border-bottom:1px solid var(--line2);text-align:right}
table.gxh th:first-child,table.gxh td:first-child{text-align:left}
table.gxh th{color:var(--dim);font-weight:600;font-size:12px}
"""


def _chart(d):
    """價位軸垂直、GEX 水平：右＝避震器（正）、左＝油門（負），跟老墨頁同方向，好對照。"""
    rows = [(k, v) for k, v in d["by_strike"]
            if abs(v) >= 0.05 and d["spot"] * 0.95 <= k <= d["spot"] * 1.05]
    if not rows:
        return "<p>沒有足夠的資料</p>"
    rows.sort(key=lambda x: -x[0])
    mx = max(abs(v) for _, v in rows) or 1
    W, H, mid, bh = 700, 18, 345, 14
    n = len(rows)
    height = n * H + 36
    out = [f'<svg viewBox="0 0 {W} {height}" width="100%" role="img" aria-label="各履約價 GEX">']
    out.append(f'<line x1="{mid}" y1="14" x2="{mid}" y2="{height - 8}" stroke="#16304A"/>')
    out.append(f'<text x="{mid - 8}" y="10" text-anchor="end" fill="{NEG}" font-size="11">◀ 油門（負 GEX）</text>')
    out.append(f'<text x="{mid + 8}" y="10" fill="{POS}" font-size="11">避震器（正 GEX）▶</text>')
    spot, flip = d["spot"], d.get("flip")
    marks = {}
    for i, (k, v) in enumerate(rows):
        y = 20 + i * H
        w = abs(v) / mx * 270
        col = POS if v > 0 else NEG
        x = mid if v > 0 else mid - w
        out.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w, 1):.1f}" height="{bh}" rx="2" fill="{col}"><title>{k:,.0f}　{v:+.2f} 億</title></rect>')
        lab = f'{k:,.0f}'
        tag = ""
        if k == d["call_wall"]:
            tag = "買權牆"
        elif k == d["put_wall"]:
            tag = "賣權牆"
        out.append(f'<text x="2" y="{y + 11}" fill="#9DB0C8" font-size="11">{lab}</text>')
        if tag:
            out.append(f'<text x="58" y="{y + 11}" fill="#DCE7F5" font-size="11" font-weight="700">{tag}</text>')
        marks[k] = y
    # 現價與翻轉點：畫在最接近的履約價列
    def _near(p):
        return min(rows, key=lambda r: abs(r[0] - p))[0]
    for p, name, col in ((spot, "現價", "#DCE7F5"), (flip, "翻轉點", FLIP)):
        if not p:
            continue
        y = marks[_near(p)] + bh + 1
        out.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{col}" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{W - 2}" y="{y - 3}" text-anchor="end" fill="{col}" font-size="11" font-weight="700">{name} {p:,.0f}</text>')
    out.append("</svg>")
    return "".join(out)


def _history():
    files = sorted(glob.glob(os.path.join(DATA, "gex_2*.json")))[-15:]
    rows = []
    for f in reversed(files):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append(f'<tr><td>{d["date"][4:6]}/{d["date"][6:]}</td><td>{d["spot"]:,.0f}</td>'
                    f'<td>{d["net_gex"]:+.1f}</td><td>{d["call_wall"]:,.0f}</td>'
                    f'<td>{d["put_wall"]:,.0f}</td><td>{(d.get("flip") or 0):,}</td></tr>')
    if not rows:
        return ""
    return ('<div class="gxbox"><h2>每日紀錄</h2><div class="meta">每天收盤後存一筆，累積起來看牆與翻轉點怎麼移動</div>'
            '<table class="gxh"><tr><th>日期</th><th>日盤收盤</th><th>淨 GEX（億）</th><th>買權牆</th><th>賣權牆</th><th>翻轉點</th></tr>'
            + "".join(rows) + "</table></div>")


@_bt_snapped
def build(d):
    s, fl = d["spot"], d.get("flip")
    state = "避震器" if d["net_gex"] > 0 else "油門"
    if fl:
        gap = round(s - fl)
        pos = (f'現價 <b>{s:,.0f}</b> 在翻轉點 <b style="color:{FLIP}">{fl:,}</b> 上方，差 {gap} 點。'
               if gap >= 0 else
               f'現價 <b>{s:,.0f}</b> 已<b>跌破</b>翻轉點 <b style="color:{FLIP}">{fl:,}</b>（{-gap} 點），整體變成油門。')
    else:
        pos = f"現價 <b>{s:,.0f}</b>，±8% 內沒有翻轉點。"
    rb = d.get("robust") or {}
    warn = ""
    if rb and not rb.get("sign_agree", True):
        warn = (f'<br><span style="font-size:13px;color:{FLIP}">⚠️ 這個「偏{state}」不穩：換幾種合理的算法，淨 GEX 落在 '
                f'{rb["net_lo"]:+.0f}～{rb["net_hi"]:+.0f} 億，正負號不一致。<b>牆的位置比整體判斷可靠</b>。</span>')
    pws = sorted({v["put_wall"] for v in rb.get("variants", [])} | {d["put_wall"]})
    pw_note = (f'<br>⚠️ 各算法落在 {"、".join(f"{x:,.0f}" for x in pws)}，不穩' if len(pws) > 1 else "")
    hero = (f'{pos}整體偏<b>{state}</b>。上方最大壓力在 <b style="color:{POS}">{d["call_wall"]:,.0f}</b>，'
            f'下方油門最重在 <b style="color:{NEG}">{d["put_wall"]:,.0f}</b>。<br>'
            f'<span style="font-size:13px;color:var(--muted)">淨 GEX {d["net_gex"]:+.1f} 億元：指數每漲跌 1%，'
            f'造市商合計約要反向／順向買賣 {abs(d["contracts"]):.0f} 口大台。</span>{warn}')
    cards = (
        f'<div class="gxc" style="border-top-color:#DCE7F5"><div class="k">日盤收盤（台指期近月）</div><div class="v">{s:,.0f}</div><div class="s">資料日 {d["date"][:4]}/{d["date"][4:6]}/{d["date"][6:]}</div></div>'
        f'<div class="gxc" style="border-top-color:{POS}"><div class="k" style="color:{POS}">買權牆（最大壓力）</div><div class="v">{d["call_wall"]:,.0f}</div><div class="s">在現價{"上" if d["call_wall"] >= s else "下"}方 {abs(d["call_wall"] - s):,.0f} 點・{d["call_wall_gex"]:+.2f} 億</div></div>'
        f'<div class="gxc" style="border-top-color:{NEG}"><div class="k" style="color:{NEG}">賣權牆（油門最重）</div><div class="v">{d["put_wall"]:,.0f}</div><div class="s">在現價{"上" if d["put_wall"] >= s else "下"}方 {abs(d["put_wall"] - s):,.0f} 點・{d["put_wall_gex"]:+.2f} 億{pw_note}</div></div>'
        f'<div class="gxc" style="border-top-color:{FLIP}"><div class="k" style="color:{FLIP}">翻轉點</div><div class="v">{(fl or 0):,}</div><div class="s">跌破這裡，整體從避震器變油門{(f"<br>各算法範圍 {rb['flip_lo']:,}～{rb['flip_hi']:,}" if rb.get('flip_lo') else "")}</div></div>')
    chart = (f'<div class="gxbox"><h2>價位牆：每個履約價是避震器還是油門</h2>'
             f'<div class="meta">條越長，造市商在那個價位被迫對沖的力道越大（億元／指數 1%）；滑鼠移上去看數字</div>{_chart(d)}</div>')
    how = ('<div class="gxbox"><h2>怎麼看這一頁</h2><div class="gxsteps">'
           '<div><b>GEX 是什麼</b><br>賣選擇權給大家的「造市商」，指數每動 1%，必須用台指期對沖多少億元。這個被迫的方向，決定行情會變悶還是變急。</div>'
           '<div><b>正 GEX＝避震器</b><br>漲了他要賣、跌了他要買，等於一直把價格往回推，容易在區間裡來回。</div>'
           '<div><b>負 GEX＝油門</b><br>跌了還得賣、漲了還得買，等於幫行情踩油門，波動放大，容易一路衝或一路殺。</div>'
           '<div><b>買權牆／賣權牆／翻轉點</b><br>正 GEX 最大的價位像天花板；負 GEX 最大的價位波動最容易放大；翻轉點是兩種狀態的分界線。</div>'
           '</div></div>')
    note = ('<div class="note"><b>限制</b>：資料來自期交所開放資料，收盤後才彙整，<b>不是即時</b>；'
            '假設「客戶買、造市商賣」（買權 +、賣權 −），實際造市商部位看不到，所以這是估計。'
            '隱含波動率由結算價反推，到期日的遠期價用買賣權平價反推。<b>只描述對沖方向，不是買賣訊號。</b></div>')
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>台指選擇權 GEX</title>
<style>{BASE_CSS}{CSS_EXTRA}</style></head><body><div class="wrap">
{header("gex", "台指選擇權 GEX", f"造市商的避震器與油門在哪裡 · 資料日 {esc(d['date'])}（日盤收盤後）· 每個交易日晚間更新", NAV, "gex")}
<div class="gxhero">{hero}</div><div class="gxcards">{cards}</div>
{chart}{_history()}{how}{note}
<p class="sub" style="margin-top:20px">產生於 {datetime.now():%Y-%m-%d %H:%M} · 資料源 期交所開放資料（DailyMarketReportOpt／DailyOptionsDelta／DailyMarketReportFut）</p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/gex.html")
    a = ap.parse_args()
    src = os.path.join(DATA, "latest.json")
    if not os.path.exists(src):
        print("無 data/gex/latest.json，先跑 python gex_options.py")
        return 1
    d = json.load(open(src, encoding="utf-8"))
    html = build(d)
    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    open(a.output, "w", encoding="utf-8").write(html)
    print(f"✅ 已存 {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
