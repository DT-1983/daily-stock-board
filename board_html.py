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
from technical_indicators import double_typhoon as _st_sma  # SMA 版 SuperTrend（顯示層用）
from technical_indicators import typhoon_state_series  # 雙重颱風三態（給蠟燭圖上色）
from board_html_legacy import (parse_report, oneliner, CHAIN_ORDER, CHAIN_MAP,
                        CHAIN_THEMES, CHAIN_REPORTS, ma_series, supertrend,
                        fetch_us_charts, esc_tw, TW_JSON, OBIS, CHAIN_PHASE,
                        CHAIN_ICON, TW_NAME, _align_rs)  # alert_telegram.py 從本模組 import，要 re-export
from technical_indicators import squeeze_momentum, mansfield_rs_series
from board_theme import NAV, header as theme_header

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 印 emoji 會炸

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
    "玻璃基板/TGV": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 8h.01M12 8h.01M16 8h.01M8 12h.01M12 12h.01M16 12h.01M8 16h.01M12 16h.01M16 16h.01"/>',
    "關鍵金屬/原物料": '<path d="M6 3h12l4 6-10 12L2 9Z"/><path d="M11 3 8 9l4 12 4-12-3-6"/><path d="M2 9h20"/>',
    "AI 材料/被動元件": '<rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><path d="M8 4v6M16 14v6"/>',
    "AI 電源/散熱": '<path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0z"/><path d="M12 17v5"/>',
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
.nl.cur{border-color:var(--accent);background:#152238;color:#fff}
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
.chartbox-sm{height:100px}
.tclabel{font-size:11px;color:#8a8f98;margin:10px 0 4px}
.cbtools{display:flex;align-items:center;gap:10px;margin:10px 0 4px;flex-wrap:wrap}
.cbhint{font-size:10.5px;color:var(--dim)}
.tcreset{background:none;border:1px solid var(--line);border-radius:7px;color:var(--muted);
 font-size:11px;font-weight:600;padding:5px 11px;cursor:pointer;font-family:inherit;margin-left:auto}
.tcreset:hover{border-color:var(--accent);color:#93C5FD}
.phase{font-size:11px;color:#F5B841;background:#2a2410;border:1px solid #5a4a1a;padding:2px 9px;border-radius:14px;white-space:nowrap}
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

/* 產業深度解讀片段（chain_reports.json 預轉 HTML）的配套樣式。
   2026-08-04 用戶回報格式跑掉——v2 改版時只搬了 .mct 基本字體，
   漏了整組 .rpt 樣式（表格/TL;DR 卡/多空對照/統計盒），從 legacy 原封搬回。 */
.rpt{font-size:14px}
.rpt h2{font-size:15.5px;margin:18px 0 6px;border-left:3px solid #4a9eff;padding-left:9px}
.rpt p{margin:7px 0}
.rpt .note{background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;padding:8px 11px;font-size:13px;color:#cfd3d8;margin:9px 0}
.rpt .tldr{background:#12151b;border:1px solid #2a2e35;border-radius:10px;padding:12px 14px;margin:6px 0 16px}
.rpt .tldr .lab{font-size:11.5px;font-weight:700;letter-spacing:.5px;color:#8a8f98;margin-bottom:9px}
.rpt .tldr .row{display:flex;gap:8px;margin:8px 0;font-size:13.5px;align-items:flex-start}
.rpt .tldr .ic{flex:0 0 auto}
.rpt .tldr .r1{border-left:3px solid #4a9eff;padding-left:10px}
.rpt .tldr .r2{border-left:3px solid #3ddc84;padding-left:10px}
.rpt .tldr .r3{border-left:3px solid #ff5c5c;padding-left:10px}
.rpt .tldr b,.rpt td b,.rpt p b{color:#fff}
.rpt .tw{margin:9px 0}
.rpt table{border-collapse:collapse;width:100%;font-size:13px}
.rpt th,.rpt td{border-bottom:1px solid #2a2e35;padding:7px 9px;text-align:left;vertical-align:top}
.rpt th{background:#222831;color:#bcd2ff;font-weight:700}
.rpt .tag{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:9px;background:#262b33;color:#cfd3d8;margin-right:4px}
.rpt ol,.rpt ul{margin:7px 0;padding-left:20px}.rpt li{margin:5px 0}
.rpt .risk li b{color:#ffb4b4}
.rpt .watch li{list-style:none;margin-left:-14px}.rpt .watch li::before{content:"🎯 "}
.rpt .cap{background:#12151b;border:1px solid #2a2e35;border-radius:10px;padding:11px 13px;margin:12px 0 0}
.rpt .stat{display:flex;flex-wrap:wrap;gap:9px;margin:11px 0}
.rpt .stat .box{flex:1 1 150px;background:#1a1d23;border:1px solid #2a2e35;border-radius:9px;padding:10px 12px}
.rpt .stat .n{font-size:17px;font-weight:800;color:#6db3ff}
.rpt .stat .t{font-size:11.5px;color:#9aa0a6;margin-top:3px;line-height:1.4}
.rpt .bb{display:flex;flex-wrap:wrap;gap:11px;margin:9px 0}
.rpt .bb .col{flex:1 1 300px;border-radius:9px;padding:11px 13px}
.rpt .bull{background:#12251a;border:1px solid #295c3c}
.rpt .bear{background:#2a1618;border:1px solid #5c2f33}
.rpt .bb h4{margin:0 0 6px;font-size:13.5px}
.rpt .bull h4{color:#4ade80}.rpt .bear h4{color:#ff8a8a}
.rpt .bb ul{padding-left:17px;margin:4px 0}.rpt .bb li{font-size:13px;margin:5px 0}
.rpt details{margin:10px 0 0;border:1px solid #2a2e35;border-radius:8px;background:#161a20}
.rpt details>summary{cursor:pointer;color:#bcd2ff;font-size:13.5px;font-weight:700;padding:9px 11px;display:block;list-style:none}
.rpt details>summary::-webkit-details-marker{display:none}
.rpt details>summary::after{content:" ▾";color:#6b7280}
.rpt details[open]>summary::after{content:" ▴"}
.rpt .inr{padding:0 11px 11px}
.rpt .disc{color:#6b7280;font-size:11.5px;margin-top:16px;line-height:1.6}
/* 手機上表格寬過螢幕 → 只讓表格自己橫滑，不撐破彈窗 */
.mct table{display:block;overflow-x:auto;white-space:nowrap}
@media(min-width:700px){.mct table{display:table;white-space:normal}}

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
.legend{margin-top:26px;padding:12px 14px;background:var(--surface);
 border:1px solid var(--line);border-radius:11px;font-size:12.5px;color:var(--muted);line-height:2}
.legend span{margin-right:13px;white-space:nowrap}
.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;
 vertical-align:middle}
.legend .lgnote{display:block;margin-top:5px;color:var(--dim);font-size:11.5px;
 line-height:1.7;white-space:normal}
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
 // 2026-09-02 Leo：跟燈號/財報頁的圖表樣式統一——雙重颱風畫真的蠟燭圖（三態上色）、
 // SuperTrend 改黃(多方)/紫(空方)，不再是紅/綠（原本跟蠟燭的紅偏多/綠偏空撞色）。
 // 有開盤價才畫蠟燭；台股資料還沒補到 open 之前（見 fetch_us_charts/tw_data 那段）
 // 自動退回原本的收盤線，不會整段掛掉。
 const hasCandle=c.open&&c.open.length===c.close.length&&typeof Chart.registry.controllers.get==='function'
   &&!!Chart.registry.controllers.get('candlestick');
 const TY_COL={1:'#ef4444','-1':'#22c55e',0:'#eab308'};
 const ds=[];
 if(hasCandle){
  const tyColorFn=ctx=>{const v=(c.ty||[])[ctx.dataIndex];const col=TY_COL[v]||'#8FA8C8';
   return{up:col,down:col,unchanged:col};};
  ds.push({type:'candlestick',label:'K線（雙重颱風三色）',
   data:c.dates.map((dt,i)=>({x:i,o:c.open[i],h:c.high[i],l:c.low[i],c:c.close[i]}))
     .filter(pt=>pt.o!=null&&pt.h!=null&&pt.l!=null&&pt.c!=null),
   backgroundColors:tyColorFn,borderColors:tyColorFn,borderWidth:1});
 }else{
  ds.push({type:'line',label:'收盤',data:c.close.map((v,i)=>({x:i,y:v})),
   borderColor:'#3B82F6',borderWidth:2,pointRadius:0,tension:.25});
 }
 if(c.ma20)ds.push({type:'line',label:'MA20',data:c.ma20.map((v,i)=>({x:i,y:v})),
  borderColor:'#94A3B8',borderWidth:1,pointRadius:0,borderDash:[4,3]});
 if(c.supertrend){const dir=c.supertrend.dir;
  ds.push({type:'line',label:'SuperTrend',data:c.supertrend.st.map((v,i)=>({x:i,y:v})),borderWidth:1.6,pointRadius:0,
   segment:{borderColor:ctx=>{const i=ctx.p1DataIndex;
    return dir[i]===1?'#facc15':(dir[i]===-1?'#c084fc':'#94A3B8');}}});}
 const main=new Chart(el,{type:hasCandle?'candlestick':'line',data:{datasets:ds},
  options:{responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},
   plugins:{legend:{labels:{color:'#94A3B8',boxWidth:11,font:{size:10}}},zoom:zoomOpt(id,c)},
   scales:{x:{type:'linear',min:0,max:c.dates.length-1,offset:true,
     ticks:{color:'#64748B',maxTicksLimit:6,font:{size:9},
       callback:v=>c.dates[Math.round(v)]||''},grid:{color:'#1E293B'}},
           y:{ticks:{color:'#64748B',font:{size:9}},grid:{color:'#1E293B'}}}}});
 ZOOM_GROUP[id]=[main];
 drawExtra(id,c);}
// 2026-09-02 Leo：「產業鏈也能做縮放嗎」——跟進出燈號/財報卡同一套：滾輪縮放、
// 拖曳平移（拖曳要 hammerjs，CDN 已載），三張圖共用同一段 x 範圍，量價才對得上。
// ZOOM_GROUP[id] 收同一檔的三張圖；syncing 旗標防 A 同步 B、B 再回頭同步 A 的迴圈。
const ZOOM_GROUP={};
let zoomSyncing=false;
function syncZoom(id,src){
 if(zoomSyncing)return; zoomSyncing=true;
 const xs=src.scales.x;
 (ZOOM_GROUP[id]||[]).forEach(ch=>{if(ch!==src)ch.zoomScale('x',{min:xs.min,max:xs.max},'none');});
 zoomSyncing=false;}
function zoomOpt(id,c){
 return {pan:{enabled:true,mode:'x',onPanComplete:({chart})=>syncZoom(id,chart)},
  zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:'x',
   onZoom:({chart})=>syncZoom(id,chart),onZoomComplete:({chart})=>syncZoom(id,chart)},
  limits:{x:{min:0,max:c.dates.length-1,minRange:5}}};}
function resetZoomFor(id){(ZOOM_GROUP[id]||[]).forEach(ch=>ch.resetZoom());}
function drawExtra(id,c){
 const elSq=document.getElementById('cvsq'+id),elRs=document.getElementById('cvrs'+id);
 if(elSq&&c.mom&&c.mom.length){
  const momColor=c.mom.map((v,i)=>{if(v==null)return'#2a2e35';const prev=i>0?c.mom[i-1]:v;
   if(v>=0)return v>=prev?'#4ade80':'#1e7a45';return v<=prev?'#ff8a8a':'#8a2e2e';});
  const dotColor=(c.sq_on||[]).map((on,i)=>{if(on)return'#EAB308';const m=c.mom[i];
   return m==null?'#6b7280':(m>=0?'#4ade80':'#ff8a8a');});
  const sq=new Chart(elSq,{type:'bar',data:{datasets:[
    {label:'動能',data:c.mom.map((v,i)=>({x:i,y:v})),backgroundColor:momColor,order:2},
    {label:'擠壓/釋放',type:'line',data:c.mom.map((_,i)=>({x:i,y:0})),showLine:false,
     pointRadius:2.6,pointBackgroundColor:dotColor,pointBorderWidth:0,order:1}]},
   options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},zoom:zoomOpt(id,c)},
    scales:{x:{type:'linear',min:0,max:c.dates.length-1,offset:true,
      ticks:{display:false},grid:{display:false}},
     y:{ticks:{color:'#64748B',font:{size:9}},grid:{color:'#1E293B'}}}}});
  if(ZOOM_GROUP[id])ZOOM_GROUP[id].push(sq);}
 if(elRs&&((c.rs_s&&c.rs_s.length)||(c.rs_l&&c.rs_l.length))){
  const base=(c.rs_s&&c.rs_s.length?c.rs_s:c.rs_l).map((_,i)=>({x:i,y:0}));
  const rsds=[{label:'基準線(0%)',data:base,borderColor:'#EF4444',borderWidth:2,pointRadius:0,order:3}];
  if(c.rs_s&&c.rs_s.length)rsds.push({label:'短線30日',data:c.rs_s.map((v,i)=>({x:i,y:v})),borderColor:'#EAB308',borderWidth:1.4,pointRadius:0,tension:.15,order:1});
  if(c.rs_l&&c.rs_l.length)rsds.push({label:'長線1年',data:c.rs_l.map((v,i)=>({x:i,y:v})),borderColor:'#4a9eff',borderWidth:1.4,pointRadius:0,tension:.15,order:2});
  const rsc=new Chart(elRs,{type:'line',data:{datasets:rsds},
   options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{labels:{color:'#9aa0a6',boxWidth:11,font:{size:10},
     filter:item=>item.text!=='基準線(0%)'}},zoom:zoomOpt(id,c)},
    scales:{x:{type:'linear',min:0,max:c.dates.length-1,offset:true,
      ticks:{display:false},grid:{display:false}},
     y:{ticks:{color:'#64748B',font:{size:9}},grid:{color:'#1E293B'}}}}});
  if(ZOOM_GROUP[id])ZOOM_GROUP[id].push(rsc);}}
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


# 2026-08-03：評分不再上色。原本評分用綠/黃/紅、訊號小圓點也用綠/黃/紅，
# 同一列會出現「灰點(觀望) + 綠色評分」這種矛盾（實例 MSFT 評分72但判斷是別追）。
# 現在顏色**專屬訊號**，評分高低改由長條長度與白/灰階表達。
def _score_color(s):
    s = int(s) if str(s).isdigit() else 0
    return "#F8FAFC" if s >= 50 else "#94A3B8"      # 只分「較高/較低」兩階，不搶訊號的顏色


# 2026-08-11：跟財報卡（technical_indicators.py）一樣多兩張圖——EXCEED CHARGE 動能柱、
# RS 相對強弱。資料在 CHARTS[id] 裡（mom/sq_on/rs_s/rs_l），JS 的 drawChart() 沒資料會自動跳過畫布。
def _extra_charts(rid):
    return (f'<div class="tclabel">EXCEED CHARGE 動能柱</div>'
            f'<div class="chartbox chartbox-sm"><canvas id="cvsq{rid}"></canvas></div>'
            f'<div class="tclabel">RS 相對強弱</div>'
            f'<div class="chartbox chartbox-sm"><canvas id="cvrs{rid}"></canvas></div>')


def _chart_block(rid):
    """整組圖表（工具列＋主圖＋動能柱＋RS）。2026-09-02 Leo：「產業鏈也能做縮放嗎」——
    工具列放主圖上面，展開就看得到；onclick 不帶引號問題所以 rid 直接內插（都是代號，
    只有英數與點，_row 那邊已經當 id 用了）。"""
    return (f'<div class="cbtools"><span class="cbhint">滾輪縮放／拖曳平移，三張圖同步</span>'
            f'<button class="tcreset" onclick="resetZoomFor(\'{rid}\')">↺ 重置縮放</button></div>'
            f'<div class="chartbox"><canvas id="cv{rid}"></canvas></div>{_extra_charts(rid)}')


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
        f'<span class="bar" style="width:{max(s*0.46,6):.0f}px;background:#475569"></span></span>'
        f'<svg class="chev" width="15" height="15" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>'
        f'</button>'
        f'<div class="detail" data-for="{rid}" data-mkt="{mkt}" data-sig="{cls}">{detail_html}</div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default="docs/board.html")  # 2026-08-04 首頁改版：index 讓給儀表板
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
    # 2026-08-11：台股 EXCEED CHARGE / RS 圖表要跟財報卡一樣多兩張圖（用戶要求）。
    # tw_analyze.py 的 closes 只存近60天，不夠算RS長線200日——只算短線25日，長線留空。
    try:
        tw_bench_closes = yf.Ticker("^TWII").history(period="6mo")["Close"].tolist()
    except Exception:
        tw_bench_closes = []
    for r in tw_data:
        cl = r.get("closes")
        if cl:
            highs, lows = r.get("highs"), r.get("lows")
            # 2026-09-02：opens 是這次才加進 tw_analyze.py 輸出——沒有的話（要等下次排程）
            # 蠟燭圖前端會自動退回原本的收盤線，不會因為缺欄位整段掛掉。
            opens = r.get("opens")
            st = _st_sma(highs, lows, cl) if highs else None
            ty = typhoon_state_series(cl, None, st["dir"]) if st else None
            sq = squeeze_momentum(highs, lows, cl) if highs and lows else None
            rs_s = mansfield_rs_series(cl, tw_bench_closes, 30) if tw_bench_closes else None
            charts[r["code"]] = {
                "dates": r.get("dates", []), "close": cl,
                "open": opens, "high": highs, "low": lows, "ty": ty,
                "ma20": ma_series(cl, 20),
                "supertrend": st,
                "mom": [None if (v is None or v != v) else round(float(v), 2) for v in sq["momentum"]] if sq else [],
                "sq_on": [None if (isinstance(v, float) and v != v) else bool(v) for v in sq["squeeze_on"]] if sq else [],
                "rs_s": _align_rs(rs_s, len(cl)) if rs_s is not None else [], "rs_l": []}

    import markdown as md
    mdc = md.Markdown(extensions=["tables", "sane_lists", "nl2br"])

    body, modals, nav = [], [], []
    for i, c in enumerate(CHAIN_ORDER):
        us, tw = us_by.get(c, []), tw_by.get(c, [])
        # 2026-08-25 修：兩邊都是照原始清單順序疊進去的，從沒依分數排序——
        # 使用者截圖看到台股 76/30/65/62/40/28/43/47 完全打散，
        # 不是資料問題，是這裡從來沒 sort 過。分數高的排最上面才有意義（一眼看重點）。
        us = sorted(us, key=lambda x: int(us_score.get(x[1], -1)) if str(us_score.get(x[1], "-1")).lstrip("-").isdigit() else -1, reverse=True)
        tw = sorted(tw, key=lambda r: r.get("score") if isinstance(r.get("score"), (int, float)) else -1, reverse=True)
        if not us and not tw and not CHAIN_REPORTS.get(c):
            continue  # 沒個股也沒深度報告才跳過——新鏈上線首日判讀還沒跑，仍要露出報告
        nav.append(f'<a href="#c{i}" title="{esc_tw(c)}" aria-label="{esc_tw(c)}">{_icon(c, 15)}</a>')
        rows = []
        for sig, tk, nm, blk in us:
            det = mdc.convert(re.sub(r"(?s)^##.*?\n", "", blk, count=1)); mdc.reset()
            ch = _chart_block(tk) if tk in charts else ""
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
            ch = _chart_block(code) if code in charts else ""
            # 2026-08-11：台股名字一律優先查 TW_NAME（中文），report_*.md 裡的 name
            # 是本機判讀當天自己查yfinance寫的、常常是英文——只當TW_NAME沒收錄時的備援
            nm = TW_NAME.get(code) or r.get("name", code)
            rows.append(_row(code, "TW", r.get("emoji", "⚪"), code, nm,
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
            f'<h2>{esc_tw(c)}</h2><span class="cnt">美 {len(us)} · 台 {len(tw)}</span>'
            + (f'<span class="phase" title="老墨三段時程：這條鏈的主行情落在哪一段（見報告）">⏱ {esc_tw(CHAIN_PHASE[c])}</span>'
               if CHAIN_PHASE.get(c) else "") + '</div>'
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
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script><script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js"></script><script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script><script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js"></script>
<style>{CSS}</style></head><body><div class="wrap">
{theme_header("board", "產業鏈看板",
    f"{date} · {len(nav)} 條產業鏈 · 美股 yfinance／台股 FinMind · 判讀 Claude（本機）"
    f" · 每日 09:00 自動更新", NAV, "board")}
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
<div class="legend">
  <b>顏色只代表訊號</b>：
  <span><i style="background:#22C55E"></i>買進</span>
  <span><i style="background:#EF4444"></i>賣出</span>
  <span><i style="background:#3B82F6"></i>持有</span>
  <span><i style="background:#64748B"></i>觀望</span><br>
  <span class="lgnote">右側數字是 AI 評分（0-100），長條表示高低 —— 刻意不上色，
  避免和訊號的顏色混淆。評分高不等於該買（例：多頭排列但乖離過大 → 評分高但訊號是觀望）。</span>
</div>
<p class="sub" style="margin-top:18px">點任一列展開走勢圖與完整判讀 · 產生於 {datetime.now():%Y-%m-%d %H:%M}</p>
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
