"""看板 v2 原型（方案 C：手機優先自適應清單）

跟 board_html.py 吃同樣的輸入（reports/report_*.md + tw_analysis.json），
只是換版面。確認後再取代 board_html.py。

用法：python board_html_v2.py reports/report_20260802.md -o docs/preview.html

設計依據（ui-ux-pro-max）：
  · 手機優先 —— 用戶「大部分用手機看」。列式排版（左資訊右數字）不需固定欄寬，
    375px 不橫捲；桌機自動變兩欄。
  · 不用 emoji 當結構圖示，改 inline SVG（emoji 跨平台長相不一、無法統一調色）
  · 數字 tabular-nums 對齊；評分同時用「數字＋長條＋顏色」三重編碼
    （不能只靠顏色傳達意義 — 色盲可及性）
  · 觸控目標 ≥44px；hover/focus 都有狀態；prefers-reduced-motion 尊重
"""
import os
import re
import sys
import json
import argparse
from datetime import datetime

import yfinance as yf
from tw_report import convert
from board_html import (parse_report, oneliner, CHAIN_ORDER, CHAIN_MAP,
                        CHAIN_THEMES, CHAIN_REPORTS, ma_series, supertrend,
                        fetch_us_charts, esc_tw, TW_JSON, OBIS)

PAGES = "https://dt-1983.github.io/daily-stock-board"

# 產業鏈圖示（Lucide 24x24 stroke，統一 2px 線寬）
ICONS = {
    "AI 伺服器": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "矽光子/光通訊": '<path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="4"/>',
    "機器人": '<rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4M8 16h.01M16 16h.01"/>',
    "低軌衛星": '<path d="M13 7 9 3 5 7l4 4M17 11l4 4-4 4-4-4"/><path d="m8 12 4 4M16 8l-4-4"/>',
    "AI 電力/核能": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "太陽能": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
    "Bitcoin→AI 機房": '<path d="M11 7h4a3 3 0 0 1 0 6h-4zM11 13h5a3 3 0 0 1 0 6h-5zM11 7V4M11 20v-3M15 7V4M15 20v-3M7 7h4M7 13h4M7 19h4"/>',
}
SIG = {"🟢": ("buy", "買進", "#22C55E"), "🔴": ("sell", "賣出", "#EF4444"),
       "🔵": ("hold", "持有", "#3B82F6"), "🟡": ("watch", "觀望", "#EAB308"),
       "⚪": ("watch", "觀望", "#64748B")}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#020617;--surface:#0F172A;--card:#131F35;--line:#1E293B;--line2:#16223A;
 --ink:#F8FAFC;--muted:#94A3B8;--dim:#64748B;--accent:#3B82F6;
 --up:#22C55E;--down:#EF4444;--warn:#EAB308}
body{background:var(--bg);color:var(--ink);line-height:1.5;-webkit-font-smoothing:antialiased;
 font-family:Inter,-apple-system,"Microsoft JhengHei","PingFang TC",sans-serif;font-size:15px}
.wrap{max-width:1100px;margin:0 auto;padding:14px 14px 60px}
.num{font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums}

/* header */
header{padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:6px}
h1{font-size:19px;font-weight:800;letter-spacing:-.3px;display:flex;align-items:center;gap:9px}
h1 svg{flex-shrink:0}
.sub{color:var(--muted);font-size:12.5px;margin-top:5px}
.navlinks{display:flex;gap:7px;margin-top:11px;flex-wrap:wrap}
.nl{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;min-height:38px;
 border:1px solid var(--line);border-radius:9px;background:var(--surface);
 color:#BFDBFE;text-decoration:none;font-size:12.5px;font-weight:600;
 transition:border-color .18s,background .18s}
.nl:hover,.nl:focus-visible{border-color:var(--accent);background:#152238}
.nl svg{flex-shrink:0;opacity:.85}

/* sticky controls */
.ctrl{position:sticky;top:0;z-index:20;background:var(--bg);padding:11px 0 9px;
 border-bottom:1px solid var(--line);margin-bottom:4px}
.seg{display:inline-flex;background:var(--line);border-radius:9px;padding:3px}
.seg button{border:0;background:transparent;color:var(--muted);font-size:13px;font-weight:600;
 padding:7px 16px;min-height:38px;border-radius:7px;cursor:pointer;font-family:inherit;
 transition:background .18s,color .18s}
.seg button[aria-pressed=true]{background:#334155;color:var(--ink)}
.sorts{display:flex;gap:6px;margin-top:9px;overflow-x:auto;padding-bottom:2px;
 scrollbar-width:none}
.sorts::-webkit-scrollbar{display:none}
.sc{border:1px solid var(--line);background:var(--surface);color:var(--muted);
 font-size:12px;padding:6px 12px;min-height:34px;border-radius:17px;cursor:pointer;
 white-space:nowrap;font-family:inherit;font-weight:600;transition:all .18s}
.sc[aria-pressed=true]{background:#334155;color:var(--ink);border-color:#475569}
.sc b{font-family:'Fira Code',monospace;font-weight:600;margin-left:1px}
.d2{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:middle}

/* chain */
.chain{margin-top:22px;scroll-margin-top:104px}
.chd{display:flex;align-items:center;gap:9px;margin-bottom:3px}
.chd .ico{width:30px;height:30px;border-radius:8px;background:#1E3A5F;display:grid;
 place-items:center;flex-shrink:0}
.chd h2{font-size:16.5px;font-weight:700}
.cnt{font-size:11.5px;color:var(--dim);background:var(--line);padding:2px 9px;border-radius:16px}
.theme{color:var(--muted);font-size:12.5px;line-height:1.6;margin:5px 0 10px}
.theme details{margin-top:4px}
.theme summary{cursor:pointer;color:#93C5FD;font-size:12px;list-style:none}
.theme summary::-webkit-details-marker{display:none}
.theme .ex{display:block;margin:5px 0 0 14px;color:var(--dim);font-size:12px}
.rptbtn{display:inline-flex;align-items:center;gap:7px;margin:2px 0 10px;padding:9px 13px;
 min-height:40px;background:var(--surface);border:1px solid var(--line);border-radius:9px;
 color:#BFDBFE;font-size:12.5px;font-weight:600;cursor:pointer;font-family:inherit;
 transition:border-color .18s}
.rptbtn:hover,.rptbtn:focus-visible{border-color:var(--accent)}

/* rows */
.rows{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--surface)}
.row{display:flex;align-items:flex-start;gap:10px;padding:12px 13px;min-height:56px;
 border-bottom:1px solid var(--line2);cursor:pointer;width:100%;text-align:left;
 background:transparent;border-left:0;border-right:0;border-top:0;color:inherit;
 font-family:inherit;font-size:inherit;transition:background .15s}
.row:last-child{border-bottom:0}
.row:hover,.row:focus-visible{background:#16223A}
.row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:6px}
.info{flex:1;min-width:0}
.t1{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap}
.tk{font-weight:700;font-size:14.5px}
.nm{color:var(--dim);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;max-width:190px}
.sigtag{font-size:10px;font-weight:700;padding:1px 7px;border-radius:5px}
.one{color:var(--muted);font-size:12px;margin-top:3px;line-height:1.5}
.rt{text-align:right;flex-shrink:0;min-width:52px}
.sv{font-size:17px;font-weight:600;line-height:1}
.bar{height:4px;border-radius:2px;margin-top:5px;margin-left:auto}
.chev{flex-shrink:0;margin-top:4px;opacity:.4;transition:transform .2s}
.row[aria-expanded=true] .chev{transform:rotate(90deg)}
.detail{display:none;padding:0 13px 14px;border-bottom:1px solid var(--line2);
 background:#101B2E}
.detail.on{display:block}
.chartbox{height:180px;margin-top:4px}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:8px;margin-top:10px}
.dcell{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:7px 9px}
.dcell .k{color:var(--dim);font-size:10px;letter-spacing:.3px}
.dcell .v{font-size:13px;font-weight:600;margin-top:2px}
.mdbody{color:#C7D8EC;font-size:12.5px;line-height:1.7;margin-top:10px}
.mdbody h3{font-size:13px;color:#F5B841;margin:11px 0 4px;font-weight:700}
.mdbody table{width:100%;border-collapse:collapse;font-size:12px;margin:7px 0}
.mdbody th,.mdbody td{border:1px solid var(--line);padding:5px 7px;text-align:right}
.mdbody th:first-child,.mdbody td:first-child{text-align:left}
.mdbody blockquote{border-left:3px solid var(--accent);padding:3px 10px;margin:6px 0;color:#CBD5E1}
.mdbody ul{margin-left:17px}

/* modal */
.modal{display:none;position:fixed;inset:0;z-index:60;background:rgba(2,6,23,.75);
 backdrop-filter:blur(3px);padding:14px}
.modal.on{display:block}
.mbox{max-width:860px;margin:0 auto;height:100%;background:var(--surface);
 border:1px solid var(--line);border-radius:14px;display:flex;flex-direction:column;overflow:hidden}
.mhd{display:flex;justify-content:space-between;align-items:center;gap:12px;
 padding:13px 15px;border-bottom:1px solid var(--line);font-weight:700;font-size:14.5px}
.mhd button{background:var(--line);border:0;color:var(--ink);width:40px;height:40px;
 border-radius:9px;cursor:pointer;font-size:19px;line-height:1}
.mct{overflow-y:auto;padding:15px;color:#C7D8EC;font-size:13px;line-height:1.75}

.jump{position:fixed;right:9px;top:50%;transform:translateY(-50%);z-index:30;
 display:flex;flex-direction:column;gap:3px}
.jump a{width:34px;height:34px;display:grid;place-items:center;border-radius:9px;
 background:rgba(19,31,53,.9);border:1px solid var(--line);color:#93C5FD;
 text-decoration:none;transition:border-color .18s}
.jump a:hover,.jump a:focus-visible{border-color:var(--accent)}
@media(max-width:600px){.jump{display:none}.nm{max-width:120px}}
@media(min-width:900px){.rows{display:grid;grid-template-columns:1fr 1fr}
 .row{border-right:1px solid var(--line2)}
 .detail{grid-column:1/-1}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

JS = """
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let MKT='US',FILT='all';
function visible(e){return e.dataset.mkt===MKT&&(FILT==='all'||e.dataset.sig===FILT);}
function applyAll(){
 $$('.seg button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.m===MKT));
 $$('.row').forEach(r=>{const v=visible(r);r.style.display=v?'':'none';
   const d=$(`.detail[data-for="${r.dataset.id}"]`);
   if(d)d.style.display=(v&&d.classList.contains('on'))?'block':'none';});
 $$('.chain').forEach(c=>{const n=[...c.querySelectorAll('.row')].filter(r=>r.style.display!=='none').length;
   c.style.display=n?'':'none';});
 // 篩選鈕檔數：只算目前市場
 const cnt={all:0,buy:0,sell:0,hold:0,watch:0};
 $$('.row').forEach(r=>{if(r.dataset.mkt!==MKT)return;cnt.all++;cnt[r.dataset.sig]++;});
 for(const k in cnt){const el=document.getElementById('n-'+k);if(el)el.textContent=cnt[k];}}
$$('.seg button').forEach(b=>b.onclick=()=>{MKT=b.dataset.m;applyAll();});
$$('.sc.f').forEach(b=>b.onclick=()=>{FILT=b.dataset.f;
 $$('.sc.f').forEach(x=>x.setAttribute('aria-pressed',x===b));applyAll();});
$$('.row').forEach(r=>r.onclick=()=>{
 const d=$(`.detail[data-for="${r.dataset.id}"]`),open=r.getAttribute('aria-expanded')==='true';
 r.setAttribute('aria-expanded',!open); d.classList.toggle('on',!open);
 d.style.display=!open?'block':'none';
 if(!open&&!d.dataset.drawn){d.dataset.drawn=1;drawChart(r.dataset.id);}});
function drawChart(id){const c=CHARTS[id];if(!c)return;
 const el=document.getElementById('cv'+id);if(!el)return;
 const ds=[{label:'收盤',data:c.close,borderColor:'#3B82F6',borderWidth:2,pointRadius:0,tension:.25}];
 if(c.ma20)ds.push({label:'MA20',data:c.ma20,borderColor:'#94A3B8',borderWidth:1,pointRadius:0,borderDash:[4,3]});
 if(c.supertrend)ds.push({label:'SuperTrend',data:c.supertrend.st,borderColor:'#EAB308',borderWidth:1.2,pointRadius:0});
 new Chart(el,{type:'line',data:{labels:c.dates,datasets:ds},
  options:{responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},
   plugins:{legend:{labels:{color:'#94A3B8',boxWidth:11,font:{size:10}}}},
   scales:{x:{ticks:{color:'#64748B',maxTicksLimit:6,font:{size:9}},grid:{color:'#1E293B'}},
           y:{ticks:{color:'#64748B',font:{size:9}},grid:{color:'#1E293B'}}}}});}
function openM(i){$('#m'+i).classList.add('on');document.body.style.overflow='hidden';}
function closeM(i){$('#m'+i).classList.remove('on');document.body.style.overflow='';}
document.addEventListener('keydown',e=>{if(e.key==='Escape')
 $$('.modal.on').forEach(m=>{m.classList.remove('on');document.body.style.overflow='';});});
applyAll();
"""


def _icon(chain, size=17, color="#60A5FA"):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{ICONS.get(chain, "<circle cx=\'12\' cy=\'12\' r=\'9\'/>")}</svg>')


def _theme_html(t):
    if isinstance(t, dict):
        cat = esc_tw(t.get("catalyst", ""))
        ex = []
        if t.get("risk"):
            ex.append(f'<span class="ex">⚠ 風險：{esc_tw(t["risk"])}</span>')
        if t.get("watch"):
            ex.append(f'<span class="ex">👁 本週觀察：{esc_tw(t["watch"])}</span>')
        if ex:
            return (f'<div class="theme">{cat}<details><summary>展開風險與觀察重點</summary>'
                    f'{"".join(ex)}</details></div>')
        return f'<div class="theme">{cat}</div>'
    return f'<div class="theme">{esc_tw(t)}</div>' if t else ""


def _score_color(s):
    s = int(s) if str(s).isdigit() else 0
    return "#22C55E" if s >= 70 else "#EAB308" if s >= 50 else "#64748B" if s >= 35 else "#EF4444"


def _row(rid, mkt, sig, tk, nm, score, one, detail_html):
    cls, lab, col = SIG.get(sig, SIG["⚪"])
    rank = {"buy": 0, "sell": 1, "hold": 2, "watch": 3}[cls]
    s = int(score) if str(score).isdigit() else 0
    sc_col = _score_color(score)
    tag = (f'<span class="sigtag" style="background:{col}22;color:{col}">{lab}</span>'
           if cls in ("buy", "sell") else "")
    return (
        f'<button class="row" data-id="{rid}" data-mkt="{mkt}" data-score="{s}" '
        f'data-sigrank="{rank}" data-sig="{cls}" data-tk="{esc_tw(tk)}" aria-expanded="false">'
        f'<span class="dot" style="background:{col}"></span>'
        f'<span class="info"><span class="t1"><span class="tk">{esc_tw(tk)}</span>'
        f'<span class="nm">{esc_tw(nm)}</span>{tag}</span>'
        f'<span class="one">{esc_tw(one) or "—"}</span></span>'
        f'<span class="rt"><span class="sv num" style="color:{sc_col}">{score}</span>'
        f'<span class="bar" style="width:{max(s*0.46,6):.0f}px;background:{sc_col}"></span></span>'
        f'<svg class="chev" width="15" height="15" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>'
        f'</button>'
        f'<div class="detail" data-for="{rid}" data-mkt="{mkt}" data-sig="{cls}">{detail_html}</div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default="docs/preview.html")
    args = ap.parse_args()

    raw = convert(open(args.input, encoding="utf-8").read())
    summary, stocks = parse_report(raw)
    us_score = dict(re.findall(r"\(([A-Z\.]+)\)\*\*[:：][^|]*\|\s*評分\s*(\d+)", summary))

    tw_data = json.load(open(TW_JSON, encoding="utf-8")) if os.path.exists(TW_JSON) else []
    us_by, tw_by = {c: [] for c in CHAIN_ORDER}, {c: [] for c in CHAIN_ORDER}
    for sig, tk, nm, blk in stocks:
        if CHAIN_MAP.get(tk):
            us_by[CHAIN_MAP[tk]].append((sig, tk, nm, blk))
    for r in tw_data:
        tw_by.setdefault(r["chain"], []).append(r)

    charts = fetch_us_charts([tk for _, tk, _, _ in stocks])
    for r in tw_data:
        cl = r.get("closes")
        if cl:
            charts[r["code"]] = {
                "dates": r.get("dates", []), "close": cl, "ma20": ma_series(cl, 20),
                "supertrend": supertrend(r.get("highs"), r.get("lows"), cl)
                if r.get("highs") else None}

    import markdown as md
    mdc = md.Markdown(extensions=["tables", "sane_lists", "nl2br"])

    body, modals, nav = [], [], []
    for i, c in enumerate(CHAIN_ORDER):
        us, tw = us_by.get(c, []), tw_by.get(c, [])
        if not us and not tw:
            continue
        nav.append(f'<a href="#c{i}" title="{esc_tw(c)}" aria-label="{esc_tw(c)}">{_icon(c, 15)}</a>')
        rows = []
        for sig, tk, nm, blk in us:
            det = mdc.convert(re.sub(r"(?s)^##.*?\n", "", blk, count=1)); mdc.reset()
            ch = (f'<div class="chartbox"><canvas id="cv{tk}"></canvas></div>'
                  if tk in charts else "")
            rows.append(_row(tk, "US", sig, tk, nm, us_score.get(tk, "—"),
                             oneliner(blk), ch + f'<div class="mdbody">{det}</div>'))
        for r in tw:
            code = r["code"]
            cells = [("現價", r.get("last")), ("MA5", r.get("ma5")), ("MA20", r.get("ma20")),
                     ("外資", f'{r.get("foreign","—")} 張'), ("投信", f'{r.get("trust","—")} 張'),
                     ("月營收YoY", f'{r.get("rev_yoy")}%' if r.get("rev_yoy") is not None else "—")]
            grid = "".join(f'<div class="dcell"><div class="k">{k}</div>'
                           f'<div class="v num">{v}</div></div>' for k, v in cells)
            extra = "".join(
                f'<h3>{lab}</h3><p>{esc_tw(r.get(key))}</p>'
                for lab, key in [("理由", "reason"), ("風險", "risk"),
                                 ("買點", "buy_point"), ("停損", "stop_loss")]
                if r.get(key))
            ch = f'<div class="chartbox"><canvas id="cv{code}"></canvas></div>' if code in charts else ""
            rows.append(_row(code, "TW", r.get("emoji", "⚪"), code, r.get("name", code),
                             r.get("score", "—"), r.get("oneliner", ""),
                             ch + f'<div class="dgrid">{grid}</div><div class="mdbody">{extra}</div>'))

        # 產業深度解讀（全螢幕彈窗）
        rpt = CHAIN_REPORTS.get(c)
        rptbtn = ""
        if rpt:
            rptbtn = (
                f'<button class="rptbtn" onclick="openM({i})" aria-haspopup="dialog">'
                f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="2" aria-hidden="true"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
                f'<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>'
                f'產業深度解讀</button>')
            modals.append(
                f'<div class="modal" id="m{i}" role="dialog" aria-modal="true" '
                f'aria-label="{esc_tw(c)} 產業深度解讀" onclick="if(event.target===this)closeM({i})">'
                f'<div class="mbox"><div class="mhd"><span>{esc_tw(c)} · 產業深度解讀</span>'
                f'<button onclick="closeM({i})" aria-label="關閉">&times;</button></div>'
                f'<div class="mct">{rpt}</div></div></div>')

        body.append(
            f'<section class="chain" id="c{i}" data-chain="{i}">'
            f'<div class="chd"><span class="ico">{_icon(c, 17)}</span>'
            f'<h2>{esc_tw(c)}</h2><span class="cnt">美 {len(us)} · 台 {len(tw)}</span></div>'
            f'{_theme_html(CHAIN_THEMES.get(c))}{rptbtn}'
            f'<div class="rows">{"".join(rows)}</div></section>')

    # 財報改成獨立頁（用戶 2026-08-03 指示），這裡只放一個入口，不再列一排裸代號
    import glob
    n_earn = len(glob.glob("docs/earnings_*.html"))
    earn = ""

    date = datetime.now().strftime("%Y-%m-%d")
    charts_json = json.dumps(charts, ensure_ascii=False)
    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{date} 產業鏈看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>{CSS}</style></head><body><div class="wrap">
<header>
  <h1><svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#3B82F6"
    stroke-width="2" stroke-linecap="round" aria-hidden="true">
    <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>產業鏈看板</h1>
  <div class="sub">{date} · 7 條產業鏈 · 美股 yfinance／台股 FinMind · 判讀 Claude（本機）</div>
  <div class="navlinks">
    <a class="nl" href="buffett.html"><svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6"/></svg>巴菲特價值清單</a>
    <a class="nl" href="portfolios.html"><svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>策略賽馬模擬倉</a>
    <a class="nl" href="earnings.html"><svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>財報深度分析{f' ({n_earn})' if n_earn else ''}</a>
  </div>
</header>
<div class="ctrl">
  <div class="seg" role="group" aria-label="切換市場">
    <button data-m="US" aria-pressed="true">美股</button>
    <button data-m="TW" aria-pressed="false">台股</button></div>
  <div class="sorts" role="group" aria-label="依訊號篩選">
    <button class="sc f" data-f="all" aria-pressed="true">全部 <b id="n-all">0</b></button>
    <button class="sc f" data-f="buy" aria-pressed="false"
      style="border-color:#166534"><span class="d2" style="background:#22C55E"></span>買進 <b id="n-buy">0</b></button>
    <button class="sc f" data-f="sell" aria-pressed="false"
      style="border-color:#7F1D1D"><span class="d2" style="background:#EF4444"></span>賣出 <b id="n-sell">0</b></button>
    <button class="sc f" data-f="hold" aria-pressed="false"><span class="d2" style="background:#3B82F6"></span>持有 <b id="n-hold">0</b></button>
    <button class="sc f" data-f="watch" aria-pressed="false"><span class="d2" style="background:#64748B"></span>觀望 <b id="n-watch">0</b></button>
  </div>

</div>
{"".join(body)}
<p class="sub" style="margin-top:26px">點任一列展開走勢圖與完整判讀 · 產生於 {datetime.now():%Y-%m-%d %H:%M}</p>
</div>
<nav class="jump" aria-label="產業鏈快速跳轉">{"".join(nav)}
  <a href="#top" title="回頂端" aria-label="回頂端"><svg width="15" height="15" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg></a></nav>
{"".join(modals)}
<script>const CHARTS={charts_json};{JS}</script></body></html>"""

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    open(args.output, "w", encoding="utf-8").write(html)
    print(f"✅ {args.output}")


if __name__ == "__main__":
    main()
