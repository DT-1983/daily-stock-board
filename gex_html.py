# -*- coding: utf-8 -*-
"""台指選擇權 GEX 頁 → docs/gex.html

讀 data/gex/latest.json（gex_options.py 產出）。純靜態、不載外部 JS。
🔴 配色／字級一律對齊站內其他頁（Leo 2026-10-08：「gex 配色跟字體跟其它頁面差很多，以後都要用相近配色」）：
   色票＝board_theme :root（青 --accent＝避震器、紅 --down＝油門、琥珀 --lamp＝翻轉點）；
   字級＝首頁卡片（標籤 11.5px／主數字 17px 等寬 .num／說明 11.5px／內文 13.5px）；方角 2px。
   新頁面不要自己訂字級與圓角，先看 home_html.py 的 .idx／.hsec。
用法：python gex_html.py [-o docs/gex.html]
"""
from board_theme import snapped as _bt_snapped
import argparse
import glob
import json
import os
import sys
from datetime import datetime

from board_theme import BASE_CSS, header, icon, esc, NAV
import gex_bars
import datetime as _dt

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "gex")
POS, NEG, FLIP = "#22D3EE", "#EF4444", "#FFB627"

CSS_EXTRA = """
.gxhero{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--lamp);
 border-radius:2px;padding:12px 15px;margin:14px 0;font-size:13.5px;line-height:1.75}
.gxhero b{font-weight:700}
.gxhero .xtra{font-size:11.5px;color:var(--muted);display:block;margin-top:3px}
.gxgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:12px 0}
@media(max-width:700px){.gxgrid{grid-template-columns:repeat(2,1fr)}}
.gxc{background:var(--surface);border:1px solid var(--line);border-radius:2px;padding:11px 13px}
.gxc .nm{font-size:11.5px;color:var(--muted);font-weight:600}
.gxc .px{font-size:17px;font-weight:700;margin-top:3px}
.gxc .chg{font-size:11.5px;color:var(--dim);margin-top:2px;line-height:1.6}
.gxsec{margin-top:20px}
.gxsec h2{font-size:15px;font-weight:700;display:flex;align-items:center;gap:7px}
.gxsec .hnote{font-size:11px;color:var(--dim);margin:2px 0 8px}
.gxbox{background:var(--surface);border:1px solid var(--line);border-radius:2px;padding:12px 13px;margin:8px 0}
.gxsteps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:9px}
.gxsteps div{background:var(--surface);border:1px solid var(--line);border-radius:2px;padding:11px 13px;
 font-size:12.5px;line-height:1.7;color:var(--muted)}
.gxsteps b{color:var(--ink);font-size:13.5px}
table.gxh{width:100%;border-collapse:collapse;font-size:12.5px}
table.gxh th,table.gxh td{padding:7px 8px;border-bottom:1px solid var(--line2);text-align:right;
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
table.gxh th:first-child,table.gxh td:first-child{text-align:left}
table.gxh th{color:var(--dim);font-weight:600;font-size:11.5px;font-family:inherit}
.gxk{display:flex;gap:0;border:1px solid var(--line);border-radius:2px;background:var(--surface);margin:8px 0}
.gxk .main{flex:1;min-width:0;display:flex;flex-direction:column}
.gxk .side{width:190px;flex:none;border-left:1px solid var(--line);display:flex;flex-direction:column}
@media(max-width:700px){.gxk .side{width:120px}}
.gxbar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:8px 0 0}
.gxrd{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11.5px;line-height:18px;height:38px;
 padding:2px 10px;overflow:hidden;border-bottom:1px solid var(--line2);white-space:nowrap}
.gxrd .dim{color:var(--dim)}
#gxk{height:400px;width:100%}
#gxs{width:100%;height:400px;display:block}
@media(max-width:700px){#gxk,#gxs{height:320px}}
.gxlegend{font-size:11.5px;color:var(--muted);display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 2px}
.gxlegend i{display:inline-block;width:14px;height:0;border-top:2px solid;vertical-align:middle;margin-right:5px}
#gx3d{width:100%;min-height:360px}
details.gxdet{margin-top:20px}
details.gxdet summary{cursor:pointer;font-size:15px;font-weight:700;list-style:none;padding:4px 0}
details.gxdet summary::-webkit-details-marker{display:none}
details.gxdet summary::before{content:"▸ ";color:var(--accent)}
details.gxdet[open] summary::before{content:"▾ "}
.gxck{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:9px;margin-top:8px}
.gxck>div{background:var(--surface);border:1px solid var(--line);border-radius:2px;padding:11px 13px;font-size:12.5px;line-height:1.75;color:var(--muted)}
.gxck h3{font-size:13.5px;color:var(--ink);font-weight:700;margin-bottom:3px}
.gxck h3 em{font-style:normal;color:var(--accent);font-family:'IBM Plex Mono',ui-monospace,monospace;margin-right:6px}
.gxck b{color:var(--ink)}
.gxck .dim{color:var(--dim);font-size:11.5px}
.gxcalc{display:grid;grid-template-columns:1fr 1fr;gap:6px 8px;margin:6px 0}
.gxcalc label{font-size:11.5px;color:var(--muted);display:flex;flex-direction:column;gap:2px}
.gxcalc input,.gxcalc select{background:var(--bg);border:1px solid var(--line);border-radius:2px;color:var(--ink);
 padding:6px 8px;font-size:13px;font-family:'IBM Plex Mono',ui-monospace,monospace;min-height:34px;width:100%}
.gxcalc input:focus,.gxcalc select:focus{outline:1px solid var(--accent)}
#gxcres{background:var(--card);border:1px solid var(--line);border-radius:2px;padding:9px 11px;min-height:96px;font-size:12.5px;line-height:1.8}
table.pc_t td{padding:4px 5px;vertical-align:top}
table.pc_t select,table.pc_t input{background:var(--bg);border:1px solid var(--line);border-radius:2px;color:var(--ink);
 padding:6px 6px;font-size:13px;font-family:'IBM Plex Mono',ui-monospace,monospace;min-height:34px;width:100%}
table.pc_t td:nth-child(4) input{width:62px}
table.pc_t td:nth-child(5) input{width:92px}
table.pc_t .qh{font-size:10.5px;margin-top:2px;white-space:nowrap}
table.pc_t .x{background:none;border:1px solid var(--line);color:var(--dim);border-radius:2px;min-height:34px;min-width:34px;cursor:pointer}
.pc_addbtn{margin-top:6px;background:var(--card);border:1px solid var(--hud-lit,#1F4E6E);color:var(--accent);border-radius:2px;padding:7px 12px;min-height:36px;cursor:pointer;font-size:12.5px}
#pc_res{font-size:13.5px;line-height:1.9;min-height:60px}
#pc_tbl td.up{color:var(--up)}#pc_tbl td.dn{color:var(--down)}
@media(max-width:700px){table.pc_t{display:block;overflow-x:auto}}
svg.gxsvg text{font-family:'IBM Plex Mono',ui-monospace,monospace}
"""


def _chart(d):
    """價位軸垂直、GEX 水平：右＝避震器（正）、左＝油門（負），跟老墨頁同方向，好對照。"""
    rows = [(k, v) for k, v in d["by_strike"]
            if abs(v) >= 0.05 and d["spot"] * 0.95 <= k <= d["spot"] * 1.05]
    if not rows:
        return "<p>沒有足夠的資料</p>"
    rows.sort(key=lambda x: -x[0])
    mx = max(abs(v) for _, v in rows) or 1
    W, H, mid, bh = 1050, 18, 520, 14
    height = len(rows) * H + 36
    out = [f'<svg class="gxsvg" viewBox="0 0 {W} {height}" width="100%" role="img" aria-label="各履約價 GEX">']
    out.append(f'<line x1="{mid}" y1="14" x2="{mid}" y2="{height - 8}" stroke="#16304A"/>')
    out.append(f'<text x="{mid - 8}" y="10" text-anchor="end" fill="{NEG}" font-size="10.5">◀ 油門（負 GEX）</text>')
    out.append(f'<text x="{mid + 8}" y="10" fill="{POS}" font-size="10.5">避震器（正 GEX）▶</text>')
    spot, flip = d["spot"], d.get("flip")
    marks = {}
    for i, (k, v) in enumerate(rows):
        y = 20 + i * H
        w = abs(v) / mx * 420
        col = POS if v > 0 else NEG
        x = mid if v > 0 else mid - w
        out.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w, 1):.1f}" height="{bh}" fill="{col}" fill-opacity=".85">'
                   f'<title>{k:,.0f}　{v:+.2f} 億</title></rect>')
        tag = "買權牆" if k == d["call_wall"] else ("賣權牆" if k == d["put_wall"] else "")
        out.append(f'<text x="2" y="{y + 11}" fill="#9DB0C8" font-size="10.5">{k:,.0f}</text>')
        if tag:
            out.append(f'<text x="62" y="{y + 11}" fill="#DCE7F5" font-size="10.5" font-weight="700">{tag}</text>')
        marks[k] = y

    def _near(p):
        return min(rows, key=lambda r: abs(r[0] - p))[0]
    for p, name, col in ((spot, "現價", "#DCE7F5"), (flip, "翻轉點", FLIP)):
        if not p:
            continue
        y = marks[_near(p)] + bh + 1
        out.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{col}" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{W - 2}" y="{y - 3}" text-anchor="end" fill="{col}" font-size="10.5" font-weight="700">{name} {p:,.0f}</text>')
    out.append("</svg>")
    return "".join(out)


def _profile_svg(d):
    """假設台指期在各價位時的總 GEX：> 0 青色（避震器）、< 0 紅色（油門）。標出翻轉點／收盤／買權牆。"""
    pr = d.get("profile") or []
    if len(pr) < 3:
        return ""
    W, H, L, R, T, B = 1050, 300, 56, 16, 28, 40
    xs = [p[0] for p in pr]
    ys = [p[1] for p in pr]
    x0, x1 = min(xs), max(xs)
    ylo, yhi = min(ys + [0]), max(ys + [0])
    pad = (yhi - ylo) * 0.08 or 1
    ylo, yhi = ylo - pad, yhi + pad
    X = lambda v: L + (v - x0) / (x1 - x0) * (W - L - R)          # noqa: E731
    Y = lambda v: T + (yhi - v) / (yhi - ylo) * (H - T - B)       # noqa: E731
    z = Y(0)
    out = [f'<svg class="gxsvg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="價格假設下的總 GEX">']
    raw = (yhi - ylo) / 5.0
    mag = 10 ** (len(str(int(max(raw, 1)))) - 1)
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    for t in range(int(ylo // step) * step, int(yhi) + step, step):
        if ylo <= t <= yhi:
            out.append(f'<line x1="{L}" y1="{Y(t):.1f}" x2="{W - R}" y2="{Y(t):.1f}" stroke="#0E1B2B"/>'
                       f'<text x="{L - 6}" y="{Y(t) + 3:.1f}" text-anchor="end" fill="#5B6E8A" font-size="10.5">{t}</text>')
    tick = 500 if x1 - x0 > 4000 else 250
    for t in range(int(x0 // tick + 1) * tick, int(x1), tick):
        out.append(f'<line x1="{X(t):.1f}" y1="{T}" x2="{X(t):.1f}" y2="{H - B}" stroke="#0E1B2B"/>'
                   f'<text x="{X(t):.1f}" y="{H - B + 16}" text-anchor="middle" fill="#5B6E8A" font-size="10.5">{t:,}</text>')
    # 正負兩塊面積（在 0 軸處切開）
    pts = [(X(a), Y(b), b) for a, b in pr]
    for sign, col in ((1, POS), (-1, NEG)):
        seg = []
        for (px, py, v), (qx, qy, w) in zip(pts, pts[1:]):
            for (ax, ay, av) in ((px, py, v),):
                if av * sign >= 0:
                    seg.append((ax, ay))
            if v * w < 0:                                         # 跨 0：補交點
                t = v / (v - w)
                seg.append((px + (qx - px) * t, z))
        if pts[-1][2] * sign >= 0:
            seg.append((pts[-1][0], pts[-1][1]))
        if len(seg) >= 2:
            path = f"M{seg[0][0]:.1f},{z:.1f} " + " ".join(f"L{a:.1f},{b:.1f}" for a, b in seg) + f" L{seg[-1][0]:.1f},{z:.1f} Z"
            out.append(f'<path d="{path}" fill="{col}" fill-opacity=".22" stroke="none"/>')
    out.append(f'<line x1="{L}" y1="{z:.1f}" x2="{W - R}" y2="{z:.1f}" stroke="#2B4C6F"/>')
    out.append('<polyline fill="none" stroke="#DCE7F5" stroke-width="1.8" points="' +
               " ".join(f"{a:.1f},{b:.1f}" for a, b, _ in pts) + '"/>')
    marks = [(d.get("flip"), "翻轉點", FLIP, "6 4"), (d["spot"], "收盤", "#DCE7F5", ""), (d["call_wall"], "買權牆", POS, "2 3")]
    for i, (v, name, col, dash) in enumerate(m for m in marks if m[0] and x0 <= m[0] <= x1):
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{X(v):.1f}" y1="{T - 8}" x2="{X(v):.1f}" y2="{H - B}" stroke="{col}"{dd}/>')
        anchor = "end" if name == "翻轉點" else "start"
        dx = -4 if name == "翻轉點" else 4
        out.append(f'<text x="{X(v) + dx:.1f}" y="{T - 12}" text-anchor="{anchor}" fill="{col}" font-size="10.5" font-weight="700">{name} {v:,.0f}</text>')
    out.append(f'<text x="14" y="{(T + H - B) / 2:.0f}" transform="rotate(-90 14 {(T + H - B) / 2:.0f})" text-anchor="middle" fill="#5B6E8A" font-size="10.5">總 GEX（億元）</text>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 6}" text-anchor="middle" fill="#5B6E8A" font-size="10.5">假設台指期在</text>')
    out.append("</svg>")
    return "".join(out)


def _payload(d):
    m = d["matrix"]
    strikes = []
    for i, k in enumerate(m["strikes"]):
        g = round(sum(r[i] for r in m["gex"]), 3)
        strikes.append([k, g, sum(r[i] for r in m["oi_call"]), sum(r[i] for r in m["oi_put"])])
    bars = gex_bars.payload()
    keep = sorted({r[0] // 86400 for r in bars["m"]})[-7:]           # 內嵌最近 7 個日曆日的 1 分 K
    mins = [[int(r[0])] + [int(x) if float(x).is_integer() else x for x in r[1:]] for r in bars["m"] if r[0] // 86400 in keep]
    return {"m": mins, "d": bars["d"], "strikes": strikes, "spot": d["spot"], "call_wall": d["call_wall"],
            "put_wall": d["put_wall"], "flip": d.get("flip"), "matrix": m, "quotes": d.get("quotes"),
            "colors": {"pos": POS, "neg": NEG, "flip": FLIP}}


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def _us_line():
    """美股前一晚收盤（S&P／那斯達克／費半）。yfinance 取不到就明講，不留空。"""
    try:
        import yfinance as yf
        out, day = [], ""
        for sym, nm in (("^GSPC", "S&P 500"), ("^IXIC", "那斯達克"), ("^SOX", "費半")):
            h = yf.Ticker(sym).history(period="7d")["Close"].dropna()
            if len(h) < 2:
                continue
            pct = (h.iloc[-1] / h.iloc[-2] - 1) * 100
            day = h.index[-1].strftime("%m/%d")
            out.append(f'{nm} <b class="num" style="color:{"#22C55E" if pct >= 0 else "#EF4444"}">{pct:+.2f}%</b>')
        return (" ・ ".join(out) + f' <span class="dim">（{day} 收盤）</span>') if out else "美股這次取不到"
    except Exception as e:  # noqa: BLE001
        return f"美股這次取不到（{str(e)[:40]}）"


def _night_line():
    try:
        import night_session
        n = night_session.fetch()
        if not n:
            return "台指電子盤這次取不到"
        dd = _dt.datetime.strptime(n["date"], "%Y%m%d")
        pct = n.get("pct")
        col = "#22C55E" if (pct or 0) >= 0 else "#EF4444"
        chg = f' <b class="num" style="color:{col}">{n["change"]:+,.0f}（{pct:+.2f}%）</b>' if pct is not None else ""
        return (f'台指電子盤收 <b class="num">{n["last"]:,.0f}</b>{chg} '
                f'<span class="dim">（{dd:%m/%d} 15:00～{(dd + _dt.timedelta(days=1)):%m/%d} 05:00）</span>')
    except Exception as e:  # noqa: BLE001
        return f"台指電子盤這次取不到（{str(e)[:40]}）"


def _expiry_items(d):
    today = _dt.date.today()
    rows = []
    labels = (d.get("matrix") or {}).get("expiries") or []
    for lab, e in zip(labels, d.get("expiries") or []):
        day = _dt.datetime.strptime(e["sday"], "%Y%m%d").date()
        n = (day - today).days
        if 0 <= n <= 7:
            when = "今天" if n == 0 else ("明天" if n == 1 else f"{n} 天後")
            rows.append(f'<b>{when}</b>　{lab}　到期')
    return rows


CALC_JS = """
(function(){
  var $=function(i){return document.getElementById(i)};
  var spot=%SPOT%;
  $('gxc_in').value=spot;
  function run(){
    var acc=+$('gxc_acc').value, pct=+$('gxc_pct').value, ent=+$('gxc_in').value, stp=+$('gxc_stop').value, side=$('gxc_side').value;
    var out=$('gxcres');
    if(!acc||!pct||!ent||!stp){out.innerHTML='填入帳戶金額、可承受虧損、進場價、停損價，這裡會算出最多能下幾口。';return;}
    var pts=side==='L'?ent-stp:stp-ent;
    if(pts<=0){out.innerHTML='<span style="color:#FFB627">停損價要在進場價的「虧損方向」：做多＝停損價低於進場價，做空＝停損價高於進場價。</span>';return;}
    var risk=acc*pct/100, per=pts*10, lots=Math.floor(risk/per);
    var f=function(n){return Math.round(n).toLocaleString()};
    out.innerHTML='停損距離 <b>'+pts.toLocaleString()+' 點</b>（約 '+(pts/ent*100).toFixed(2)+'%）<br>'+
      '1 口微台停損時虧損 <b>'+f(per)+' 元</b>（每點 10 元）<br>'+
      '你願意虧的金額 <b>'+f(risk)+' 元</b>（帳戶的 '+pct+'%）→ 最多 <b style="color:var(--accent)">'+lots+' 口</b>'+
      (lots<1?'<br><span style="color:#FFB627">連 1 口都超過你設的虧損上限：要縮小停損距離，或提高可承受金額。</span>':'<br>'+lots+' 口停損時虧損約 <b>'+f(lots*per)+' 元</b>')+
      '<br><span class="dim">不含手續費、滑價、跳空；保證金另計，下單前請看券商公告的保證金。</span>';
  }
  ['gxc_acc','gxc_pct','gxc_in','gxc_stop','gxc_side'].forEach(function(i){$(i).addEventListener('input',run)});
  run();
})();
"""


def _checklist(d):
    s, fl = d["spot"], d.get("flip")
    rb = d.get("robust") or {}
    pws = sorted({v["put_wall"] for v in rb.get("variants", [])} | {d["put_wall"]})
    pw = f'賣權牆 <b class="num" style="color:{NEG}">{d["put_wall"]:,.0f}</b>' + (
        f'（各算法 {"、".join(f"{x:,.0f}" for x in pws)}，不穩）' if len(pws) > 1 else "")
    pos_txt = ""
    if fl:
        gap = round(s - fl)
        pos_txt = (f'收盤在翻轉點<b>上方 {gap} 點</b>，偏避震器那一側。' if gap >= 0 else
                   f'收盤在翻轉點<b>下方 {-gap} 點</b>，偏油門那一側。')
        q = d.get("quotes") or {}
        if q.get("kind") == "night" and q.get("spot"):                 # 夜盤比日盤新：把夜盤的位置也講出來
            ng = round(q["spot"] - fl)
            pos_txt += (f'<br><b>夜盤最新價 {q["spot"]:,.0f}</b>，在翻轉點<b>{"上" if ng >= 0 else "下"}方 {abs(ng)} 點</b>'
                        f'{"" if ng >= 0 else "，已經在油門那一側"}（上面的 GEX 是用日盤收盤的未平倉量算的）。')
    exp = _expiry_items(d)
    exp_html = "<br>".join(exp) if exp else "未來 7 天內沒有台指選擇權到期"
    items = [
        ("1", "開盤前：夜盤與美股", f'{_night_line()}<br>{_us_line()}'),
        ("2", "地圖：牆與翻轉點",
         f'買權牆 <b class="num" style="color:{POS}">{d["call_wall"]:,.0f}</b>（現價上方 {abs(d["call_wall"] - s):,.0f} 點）<br>{pw}<br>'
         f'翻轉點 <b class="num" style="color:{FLIP}">{(fl or 0):,}</b>'
         + (f'（各算法 {rb["flip_lo"]:,}～{rb["flip_hi"]:,}）' if rb.get("flip_lo") else "")),
        ("3", "位置：在翻轉點哪一邊",
         f'{pos_txt}<br><span class="dim">往上靠近買權牆時，造市商的對沖容易把價格壓回；跌破翻轉點後，對沖會讓波動放大。'
         '這是結構描述，不是進出場訊號。</span>'),
        ("4", "到期日：牆會變、會消失", f'{exp_html}<br><span class="dim">到期那天，該到期日的那一份牆就消失，整張圖會變；週選每週到期（通常週三、週五，遇假日順延）。</span>'),
    ]
    cards = "".join(f'<div><h3><em>{n}</em>{t}</h3>{b}</div>' for n, t, b in items)
    calc = (
        '<div><h3><em>5</em>認賠：算出最多能下幾口微台</h3>'
        '<div class="gxcalc">'
        '<label>帳戶金額（元）<input id="gxc_acc" type="number" inputmode="numeric" placeholder="例如你的期貨帳戶權益"></label>'
        '<label>最多願意虧（帳戶 %）<input id="gxc_pct" type="number" inputmode="decimal" placeholder="例如 1 或 2"></label>'
        '<label>方向<select id="gxc_side"><option value="L">做多（買進）</option><option value="S">做空（賣出）</option></select></label>'
        '<label>進場價<input id="gxc_in" type="number" inputmode="numeric"></label>'
        '<label style="grid-column:1/3">停損價（到這個價就認賠出場）<input id="gxc_stop" type="number" inputmode="numeric" placeholder="自己決定，這裡不替你填"></label>'
        '</div><div id="gxcres"></div>'
        '<div class="dim" style="margin-top:4px">公式：最多口數＝（帳戶 × 可承受虧損%）÷（停損點數 × 10 元）。數字只在你的瀏覽器計算，不會上傳或儲存。</div></div>')
    return ('<div class="gxsec"><h2>今日看盤清單</h2><div class="hnote">開盤前依序看這五件事；前四項是資料，第五項要你自己決定</div>'
            f'<div class="gxck">{cards}{calc}</div></div>'
            f'<script>{CALC_JS.replace("%SPOT%", str(int(s)))}</script>')


def _scenarios(d):
    """三種情境（只描述「發生時資料會長什麼樣、該去看哪個數字」，不含買賣建議）。數字全由當天資料帶入。"""
    s, fl = d["spot"], d.get("flip")
    cw, pw = d["call_wall"], d["put_wall"]
    bs = d.get("by_strike") or []
    above = sorted([(v, k) for k, v in bs if k > cw and v > 0], reverse=True)[:2]
    below = sorted([(v, k) for k, v in bs if k < pw and v > 0], reverse=True)[:1]
    nxt_up = "、".join(f"{k:,.0f}（{v:+.1f} 億）" for v, k in above) or "沒有明顯的下一道牆"
    nxt_dn = f"{below[0][1]:,.0f}（{below[0][0]:+.1f} 億）" if below else "附近沒有明顯的避震器"
    rb = d.get("robust") or {}
    pws = sorted({v["put_wall"] for v in rb.get("variants", [])} | {pw})
    pw_txt = "、".join(f"{x:,.0f}" for x in pws)
    flip_txt = f"{fl:,}" if fl else "—"
    cards = [
        ("A", "守住區間，來回震盪", POS,
         f"<b>條件</b>：價格留在翻轉點 {flip_txt} 上方，在賣權牆 {pw:,.0f} 與買權牆 {cw:,.0f} 之間。<br>"
         f"<b>資料會長這樣</b>：避震器還在作用，漲了造市商賣、跌了造市商買，把價格往回拉。<br>"
         f"<b>要看</b>：價格靠近 {cw:,.0f} 時有沒有被壓回；每天的買權牆有沒有被「拆掉」（那一格的未平倉口數明顯減少）。"),
        ("B", "跌破翻轉點，油門踩下去", NEG,
         f"<b>條件</b>：價格跌破 {flip_txt}（各算法範圍 {rb.get('flip_lo', '—'):,}～{rb.get('flip_hi', '—'):,}），"
         f"往賣權牆 {pw:,.0f} 靠近。<br>"
         f"<b>資料會長這樣</b>：進入負 GEX 區，造市商跌了還得賣，波動放大。賣權牆各算法落在 {pw_txt}，不穩，別把它當一定撐得住的位置。<br>"
         f"<b>要看</b>：成交量有沒有放大、夜盤和美股前一晚方向；下一個比較強的避震器大約在 {nxt_dn}。"),
        ("C", f"突破 {cw:,.0f} 並站穩", FLIP,
         f"<b>條件</b>：價格漲過 {cw:,.0f}，而且收盤站在上面。<br>"
         f"<b>資料會長這樣</b>：買權牆被消耗或往上移，上方壓力變小；是否真的站穩，要等隔天的未平倉資料才看得出來。<br>"
         f"<b>要看</b>：{cw:,.0f} 那一格的買權未平倉是否明顯減少；再往上的牆在 {nxt_up}。"),
    ]
    body = "".join(f'<div><h3><em style="color:{c}">{k}</em>{t}</h3>{b}</div>' for k, t, c, b in cards)
    return ('<div class="gxsec"><h2>三種情境：價格接下來可能怎麼走</h2>'
            '<div class="hnote">只描述「發生時資料會變成什麼樣、要去看哪個數字」，不是預測，也不是買賣建議</div>'
            f'<div class="gxck">{body}</div></div>')


def _calc_section(d):
    """選擇權損益試算器（邏輯在 gex_calc.js）。報價＝最近一場（夜盤或日盤）；頁面是靜態的，不是盤中即時。"""
    q = d.get("quotes") or {}
    asof = q.get("asof") or "沒有取到報價"
    return (
        '<div class="gxsec" id="pc_root"><h2>選擇權損益試算器：到期時會賺還是賠</h2>'
        f'<div class="hnote">報價取自 <b>{esc(asof)}</b>（頁面每個交易日收盤後更新，<b>不是盤中即時</b>）。'
        '買進用「賣價」、賣出用「買價」，夜盤買賣價差常常很大；你看到更新的報價，直接改「價格」欄就好。損益是<b>到期當天</b>的結果，未扣手續費與期交稅。</div>'
        '<div class="pc_body"><div class="gxbar seg" id="pc_btn" role="group">'
        '<button data-k="micro" aria-pressed="false">只做多微台</button>'
        '<button data-k="ins" aria-pressed="true">微台＋買進賣權（保險）</button>'
        '<button data-k="collar" aria-pressed="false">領口（再賣出買權）</button>'
        '<button data-k="strangle" aria-pressed="false">買進勒式（賣權＋買權）</button></div>'
        '<div class="gxbox"><div class="gxcalc">'
        '<label>到期日（選擇權）<select id="pc_exp"></select></label>'
        '<label>微台口數（0＝不做微台）<input id="pc_ml" type="number" min="0" value="5" inputmode="numeric"></label>'
        '<label>微台方向<select id="pc_md"><option value="L">做多</option><option value="S">做空</option></select></label>'
        '<label>微台進場價<input id="pc_me" type="number" inputmode="numeric"></label></div>'
        '<table class="gxh pc_t"><tr><th>買／賣</th><th>種類</th><th>履約價</th><th>口數</th><th>價格（點）</th><th></th></tr>'
        '<tbody id="pc_legs"></tbody></table>'
        '<button type="button" id="pc_add" class="pc_addbtn">＋ 加一腿</button></div>'
        '<div class="gxbox"><div id="pc_res"></div></div>'
        '<div class="gxbox"><div id="pc_svg"></div><table class="gxh" id="pc_tbl" style="margin-top:8px"></table></div>'
        '<div class="note">單位：台指選擇權每點 50 元、微台每點 10 元，所以 <b>5 口微台才對應 1 口選擇權</b>。'
        '這是教學用的試算，不是建議；選擇權比微台複雜，沒搞懂之前不要實際下單。</div></div></div>')


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
    return ('<div class="gxsec"><h2>每日紀錄</h2><div class="hnote">每天收盤後存一筆，累積起來看牆與翻轉點怎麼移動</div>'
            '<div class="gxbox"><table class="gxh"><tr><th>日期</th><th>日盤收盤</th><th>淨 GEX（億）</th>'
            '<th>買權牆</th><th>賣權牆</th><th>翻轉點</th></tr>' + "".join(rows) + "</table></div></div>")


def _card(label, value, sub, color=None):
    st = f' style="color:{color}"' if color else ""
    return (f'<div class="gxc"><div class="nm"{st}>{label}</div><div class="px num">{value}</div>'
            f'<div class="chg">{sub}</div></div>')


@_bt_snapped
def build(d):
    s, fl = d["spot"], d.get("flip")
    rb = d.get("robust") or {}
    state = "避震器" if d["net_gex"] > 0 else "油門"
    if fl:
        gap = round(s - fl)
        pos = (f'現價 <b class="num">{s:,.0f}</b> 在翻轉點 <b class="num" style="color:{FLIP}">{fl:,}</b> 上方，差 {gap} 點。'
               if gap >= 0 else
               f'現價 <b class="num">{s:,.0f}</b> 已<b>跌破</b>翻轉點 <b class="num" style="color:{FLIP}">{fl:,}</b>（{-gap} 點），整體變成油門。')
    else:
        pos = f'現價 <b class="num">{s:,.0f}</b>，±8% 內沒有翻轉點。'
    warn = ""
    if rb and not rb.get("sign_agree", True):
        warn = (f'<span class="xtra" style="color:{FLIP}">⚠️ 這個「偏{state}」不穩：換幾種合理的算法，淨 GEX 落在 '
                f'{rb["net_lo"]:+.0f}～{rb["net_hi"]:+.0f} 億，正負號不一致。<b>買權牆比整體判斷可靠</b>。</span>')
    pws = sorted({v["put_wall"] for v in rb.get("variants", [])} | {d["put_wall"]})
    pw_note = (f'<br>⚠️ 各算法落在 {"、".join(f"{x:,.0f}" for x in pws)}，不穩' if len(pws) > 1 else "")
    hero = (f'{pos}整體偏<b>{state}</b>。上方最大壓力在 <b class="num" style="color:{POS}">{d["call_wall"]:,.0f}</b>，'
            f'下方油門最重在 <b class="num" style="color:{NEG}">{d["put_wall"]:,.0f}</b>。'
            f'<span class="xtra">淨 GEX {d["net_gex"]:+.1f} 億元：指數每漲跌 1%，'
            f'造市商合計約要反向／順向買賣 {abs(d["contracts"]):.0f} 口大台。</span>{warn}')
    side = lambda p: "上" if p >= s else "下"          # noqa: E731
    flip_rng = (f'<br>各算法範圍 {rb["flip_lo"]:,}～{rb["flip_hi"]:,}' if rb.get("flip_lo") else "")
    cards = "".join([
        _card("日盤收盤（台指期近月）", f'{s:,.0f}', f'資料日 {d["date"][:4]}/{d["date"][4:6]}/{d["date"][6:]}'),
        _card("買權牆（最大壓力）", f'{d["call_wall"]:,.0f}',
              f'在現價{side(d["call_wall"])}方 {abs(d["call_wall"] - s):,.0f} 點 · {d["call_wall_gex"]:+.2f} 億', POS),
        _card("賣權牆（油門最重）", f'{d["put_wall"]:,.0f}',
              f'在現價{side(d["put_wall"])}方 {abs(d["put_wall"] - s):,.0f} 點 · {d["put_wall_gex"]:+.2f} 億{pw_note}', NEG),
        _card("翻轉點", f'{(fl or 0):,}', f'跌破這裡，整體從避震器變油門{flip_rng}', FLIP),
    ])
    kchart = (
        f'<div class="gxsec"><h2>{icon("gex", 16, "#3B82F6")}K 線＋價位牆：每個價位是避震器還是油門</h2>'
        '<div class="hnote">右邊的橫條跟左邊 K 線共用同一條價格軸：往右＝避震器（正 GEX）、往左＝油門（負 GEX），條越長力道越大。'
        '滑鼠移到圖上，上方會顯示那個價位的 GEX 與未平倉口數；滾輪／雙指可縮放。</div>'
        '<div class="gxbar seg" id="gxbtn" role="group" aria-label="K 線週期">'
        '<button data-n="5" aria-pressed="false">5 分</button><button data-n="15" aria-pressed="false">15 分</button>'
        '<button data-n="30" aria-pressed="true">30 分</button><button data-n="60" aria-pressed="false">60 分</button>'
        '<button data-n="0" aria-pressed="false">日 K</button></div>'
        '<div class="gxk"><div class="main"><div class="gxrd"><div id="gxr1">&nbsp;</div><div id="gxr2">&nbsp;</div></div>'
        '<div id="gxk"></div></div>'
        '<div class="side"><div class="gxrd" style="text-align:center;color:var(--dim)">各履約價 GEX</div><canvas id="gxs"></canvas></div></div>'
        f'<div class="gxlegend"><span><i style="border-color:#DCE7F5"></i>收盤 {s:,.0f}</span>'
        f'<span><i style="border-color:{POS}"></i>買權牆 {d["call_wall"]:,.0f}</span>'
        f'<span><i style="border-color:{NEG}"></i>賣權牆 {d["put_wall"]:,.0f}</span>'
        f'<span><i style="border-color:{FLIP};border-top-style:dashed"></i>翻轉點 {(fl or 0):,}</span>'
        '<span style="color:#ff5277">■ 漲</span><span style="color:#2ee6a8">□ 跌</span>'
        '<span class="dim" style="color:var(--dim)">（含夜盤；日 K 只算日盤）</span></div></div>')
    profile = (
        f'<div class="gxsec"><h2>價格移到不同位置，避震器還剩多少？</h2>'
        f'<div class="hnote">假設台指期移到橫軸那個價位、其他條件不變，重新計算全部選擇權的 GEX 再加總。'
        f'青色區塊＝避震器、紅色區塊＝油門；只是描述今天部位的結構，不代表價格會往哪邊走。</div>'
        f'<div class="gxbox">{_profile_svg(d)}</div></div>')
    adv = (
        '<details class="gxdet" id="gx3dwrap"><summary>進階：拆成每個到期日來看（熱力圖、3D 曲面）</summary>'
        '<div class="hnote" style="margin:4px 0 8px">同一個價位的壓力，可能來自這週到期的週選，也可能來自下個月的月選。'
        '越快到期的，對價格變動越敏感；到期一過，那一份就消失。圖上直接標出到期日，滑鼠移上去看「到期日／履約價／數值」。</div>'
        '<div class="gxbar seg" id="gx3dbtn" role="group"><button data-k="heat" aria-pressed="true">熱力圖（平面）</button>'
        '<button data-k="gex" aria-pressed="false">3D：GEX</button><button data-k="oi" aria-pressed="false">3D：未平倉量</button>'
        '<button data-k="iv" aria-pressed="false">3D：隱含波動率</button></div>'
        '<div class="gxbox"><div id="gx3d">展開後載入圖表…</div></div></details>')
    how = ('<div class="gxsec"><h2>先看懂：GEX 是什麼</h2><div class="hnote">一句話：指數每漲跌 1%，「賣選擇權的大戶」會被迫跟著買或賣多少台指期</div><div class="gxsteps">'
           '<div><b>誰是造市商？</b><br>賣選擇權給大家的人，像保險公司：大家跟他買選擇權（買保險），他賺保費和價差。他不想賭漲跌，只想穩穩賺。</div>'
           '<div><b>他為什麼要買賣台指期？</b><br>指數一動，他賣出去的「保單」風險就跟著變。為了不被行情咬到，他得馬上用台指期把風險抵銷，這叫「避險」。</div>'
           '<div><b>正 GEX＝避震器</b><br>漲了他要賣、跌了他要買，等於一直把價格往回推，容易在區間裡來回。</div>'
           '<div><b>負 GEX＝油門</b><br>跌了還得賣、漲了還得買，等於幫行情踩油門，波動放大，容易一路衝或一路殺。</div>'
           '<div><b>買權牆</b><br>正 GEX 最大的價位，漲到這裡避震器最強，像天花板。</div>'
           '<div><b>賣權牆</b><br>負 GEX 最大的價位，到了這附近油門最重，波動最容易放大。</div>'
           '<div><b>翻轉點</b><br>從避震器變成油門的分界線；價格在它上面比較穩，跌破就變急。</div>'
           '</div></div>')
    note = ('<div class="note" style="margin-top:14px"><b>資料來源與限制</b>：台指期與台指選擇權行情取自臺灣期貨交易所（每日行情、每日逐筆成交），'
            f'資料日期 {d["date"][:4]}/{d["date"][4:6]}/{d["date"][6:]}（日盤收盤後，<b>不是即時</b>）。'
            'GEX、隱含波動率為本站依公開模型自行估算，不是期交所或造市商公布的數字；'
            '採用業界常見的簡化做法：買權的 GEX 算正、賣權的 GEX 算負（等於假設造市商手上是買權多、賣權空）。'
            '實際造市商部位看不到，這個假設不一定符合實際，所以只是估計，換算法數字會有差異。'
            '<b>只描述對沖方向，不是買賣訊號。</b></div>')
    data_json = json.dumps(_payload(d), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    scripts = (f'<script>window.GEXDATA={data_json};</script>'
               f'<script>{_read("vendor/lightweight-charts.standalone.production.js")}</script>'
               f'<script id="gx-chart-js">{_read("gex_chart.js")}</script>'
               f'<script id="gx-3d-js">{_read("gex_3d.js")}</script>'
               f'<script id="gx-calc-js">{_read("gex_calc.js")}</script>')
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>台指選擇權 GEX</title>
<style>{BASE_CSS}{CSS_EXTRA}</style></head><body><div class="wrap">
{header("gex", "台指選擇權 GEX", f"造市商的避震器與油門在哪裡 · 資料日 {esc(d['date'])}（日盤收盤後）· 每個交易日收盤後更新", NAV, "gex")}
<div class="gxhero">{hero}</div><div class="gxgrid">{cards}</div>
{_checklist(d)}{_scenarios(d)}{_calc_section(d)}{how}{kchart}{profile}{adv}{_history()}{note}
<p class="sub" style="margin-top:20px">產生於 {datetime.now():%Y-%m-%d %H:%M} · 資料源 期交所每日行情（選擇權／台指期）</p>
</div>{scripts}</body></html>"""


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
