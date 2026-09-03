"""三頁共用的設計系統（看板／巴菲特／賽馬），確保視覺統一。

2026-08-03：用戶要求「看板風格統一」。抽出 board_html_v2.py 的
CSS/SVG圖示/圖例/頁首，三頁都用同一套，不再各自維護一份 CSS。

顏色語彙（三頁一致）：
  綠 #22C55E＝買進/正面   紅 #EF4444＝賣出/負面
  藍 #3B82F6＝持有/連結   灰 #64748B＝觀望/次要
  評分/數字類一律不上色（白/灰兩階），顏色只給「訊號」用，
  避免同一頁出現「灰點但綠字」這種同色不同義的矛盾（2026-08-03 看板修過的坑）。
"""
import html as _html

SIG_COLOR = {"buy": "#22C55E", "sell": "#EF4444", "hold": "#3B82F6", "watch": "#64748B"}
SIG_LABEL = {"buy": "買進", "sell": "賣出", "hold": "持有", "watch": "觀望"}

ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "gdp": '<path d="M22 12h-4l-3 8-4-16-3 8H2"/>',
    "board": '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    "buffett": '<path d="M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6"/>',
    "portfolio": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "earnings": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
    "ark": '<path d="M3 3v18h18"/><path d="m7 14 4-5 3 3 5-7"/>',
    "rotation": '<circle cx="12" cy="12" r="3"/><path d="M12 3a9 9 0 0 1 8.5 6M21 12a9 9 0 0 1-8.5 6M3 12a9 9 0 0 1 3-6.7M6 20.7A9 9 0 0 1 3 14"/>',
    # 進出燈號＝交通號誌（三顆燈）：直接對應「亮幾燈」這件事
    "lamp": '<rect x="7" y="2" width="10" height="20" rx="5"/><circle cx="12" cy="7" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="17" r="1.6"/>',
    # 籌碼異動＝疊起來的籌碼／代幣
    "chip": '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v5c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 11v5c0 1.7 3.6 3 8 3s8-1.3 8-3v-5"/>',
    "back": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "chevron": '<path d="M9 18l6-6-6-6"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
}


# 全站導覽（2026-08-04 首頁改版：儀表板當首頁，看板搬 board.html，新增 GDP 頁）
# 各頁一律 from board_theme import NAV，不要自己再定義一份。
# 2026-09-03 Leo 指定順序：產業輪動 → 進出燈號 → 籌碼異動 → 策略賽馬 → 產業鏈 →
# 財報分析 → GDP → ARK。首頁維持第一個（站台慣例）；巴菲特清單 Leo 沒列到，
# 先擺在指定的八項之後，要拿掉或插回中間再說。
# ── 查任意股票的入口（2026-09-03）──────────────────────────────
#
# ⚠️ **為什麼是連出去而不是做在站內**：這個投資站是 GitHub Pages 靜態託管，
# 只能放事先產好的檔案。查任意代號要即時抓 3 年 OHLC ＋算指標，一定要有後端在跑。
# 所以入口在站內（首頁＋進出燈號頁）、運算在本機服務（lookup_page.py）。
#
# ⚠️ 這站是公開的，網址寫在這裡等於公開，但服務端有 token 門檻：沒授權過的裝置
# 點進去只會看到「這台裝置還沒授權」的說明頁。Leo 每台裝置用 ?key= 開一次即可。
# ⚠️ 服務跑在 Leo 的電腦上——電腦關機或 bot 沒跑時連結會連不上。
#
# 放在 board_theme 而不是各頁自己寫：兩個頁面（首頁、進出燈號）都要用，
# 複製兩份必然會漂移（見 investment_site_ui_standard 記憶的原則）。
LOOKUP_URL = "https://stock.talentxtrend.com/lookup"
LOOKUP_BOX = (
    '<form class="lkbox" method="get" action="' + LOOKUP_URL + '" target="_blank">'
    '<span class="lkl">🔍 查任意股票</span>'
    '<input name="ticker" placeholder="代號或名稱：2454 / 台積電 / COST" '
    'autocomplete="off" autocapitalize="characters">'
    '<button type="submit">查燈號＋圖表</button>'
    '<span class="lkn">不限掃描母體；台股可打中文名。即時計算約 3–8 秒</span>'
    '</form>')

LOOKUP_CSS = """
.lkbox{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:14px 0 4px;
 background:#12151b;border:1px solid #2a2e35;border-radius:11px;padding:11px 13px}
.lkbox .lkl{font-size:13px;font-weight:700;color:#93C5FD}
.lkbox input{flex:1 1 190px;min-width:0;padding:8px 11px;border-radius:8px;
 border:1px solid #2a2e35;background:#0d1016;color:#e8eaed;font-size:14px;font-family:inherit}
.lkbox button{padding:8px 15px;border-radius:8px;border:1px solid #2a2e35;background:#1a1d23;
 color:#93C5FD;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;white-space:nowrap}
.lkbox button:hover{border-color:#4a9eff}
.lkbox .lkn{flex:1 1 100%;font-size:11px;color:#6b7280}
"""

NAV = [
    ("home", "home", "首頁", "./"),
    ("rotation", "rotation", "產業輪動", "rotation.html"),
    ("combo", "lamp", "進出燈號", "combo.html"),
    ("chip", "chip", "籌碼異動", "chip.html"),
    ("portfolio", "portfolio", "策略賽馬", "portfolios.html"),
    ("board", "board", "產業鏈看板", "board.html"),
    ("earnings", "earnings", "財報分析", "earnings.html"),
    ("gdp", "gdp", "GDP 觀察", "gdp.html"),
    ("ark", "ark", "ARK 追蹤", "ark.html"),
    ("buffett", "buffett", "巴菲特清單", "buffett.html"),
]


def esc(s):
    return _html.escape(str(s if s is not None else ""))


def icon(name, size=17, color="currentColor", stroke=2):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICONS.get(name, "")}</svg>')


# ── 共用 CSS：base(全站通用) ─────────────────────────────────────────
BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#020617;--surface:#0F172A;--card:#131F35;--line:#1E293B;--line2:#16223A;
 --ink:#F8FAFC;--muted:#94A3B8;--dim:#64748B;--accent:#3B82F6;
 --up:#22C55E;--down:#EF4444;--warn:#EAB308}
body{background:var(--bg);color:var(--ink);line-height:1.5;-webkit-font-smoothing:antialiased;
 font-family:Inter,-apple-system,"Microsoft JhengHei","PingFang TC",sans-serif;font-size:15px}
.wrap{max-width:1100px;margin:0 auto;padding:14px 14px 60px}
.num{font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums}
a{color:inherit}

header{padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:6px}
h1{font-size:19px;font-weight:800;letter-spacing:-.3px;display:flex;align-items:center;gap:9px}
h1 svg{flex-shrink:0}
.sub{color:var(--muted);font-size:12.5px;margin-top:5px;line-height:1.7}
.sub b{color:#CBD5E1}
.navlinks{display:flex;gap:7px;margin-top:11px;flex-wrap:wrap}
.nl{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;min-height:38px;
 border:1px solid var(--line);border-radius:9px;background:var(--surface);
 color:#BFDBFE;text-decoration:none;font-size:12.5px;font-weight:600;
 transition:border-color .18s,background .18s}
.nl:hover,.nl:focus-visible{border-color:var(--accent);background:#152238}
.nl svg{flex-shrink:0;opacity:.85}
.nl.cur{border-color:var(--accent);background:#152238;color:#fff}

.ctrl{position:sticky;top:0;z-index:20;background:var(--bg);padding:11px 0 9px;
 border-bottom:1px solid var(--line);margin-bottom:4px}
.seg{display:inline-flex;background:var(--line);border-radius:9px;padding:3px}
.seg button{border:0;background:transparent;color:var(--muted);font-size:13px;font-weight:600;
 padding:7px 16px;min-height:38px;border-radius:7px;cursor:pointer;font-family:inherit;
 transition:background .18s,color .18s}
.seg button[aria-pressed=true]{background:#334155;color:var(--ink)}
.sorts{display:flex;gap:6px;margin-top:9px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none}
.sorts::-webkit-scrollbar{display:none}
.sc{border:1px solid var(--line);background:var(--surface);color:var(--muted);
 font-size:12px;padding:6px 12px;min-height:34px;border-radius:17px;cursor:pointer;
 white-space:nowrap;font-family:inherit;font-weight:600;transition:all .18s}
.sc[aria-pressed=true]{background:#334155;color:var(--ink);border-color:#475569}
.sc b{font-family:'Fira Code',monospace;font-weight:600;margin-left:1px}
.d2{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:middle}

.sec{margin-top:22px;scroll-margin-top:104px}
.sechd{display:flex;align-items:center;gap:9px;margin-bottom:3px;flex-wrap:wrap}
.sechd .ico{width:30px;height:30px;border-radius:8px;background:#1E3A5F;display:grid;
 place-items:center;flex-shrink:0}
.sechd h2{font-size:16.5px;font-weight:700}
.cnt{font-size:11.5px;color:var(--dim);background:var(--line);padding:2px 9px;border-radius:16px}
.note{color:var(--muted);font-size:12.5px;line-height:1.6;margin:5px 0 10px}

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
.sv{font-size:17px;font-weight:600;line-height:1;color:var(--ink)}
.sv.dim{color:var(--dim)}
.bar{height:4px;border-radius:2px;margin-top:5px;margin-left:auto;background:#475569}
.chev{flex-shrink:0;margin-top:4px;opacity:.4;transition:transform .2s}
.row[aria-expanded=true] .chev{transform:rotate(90deg)}
.detail{display:none;padding:0 13px 14px;border-bottom:1px solid var(--line2);background:#101B2E}
.detail.on{display:block}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:8px;margin-top:10px}
.dcell{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:7px 9px}
.dcell .k{color:var(--dim);font-size:10px;letter-spacing:.3px}
.dcell .v{font-size:13px;font-weight:600;margin-top:2px}
.mdbody{color:#C7D8EC;font-size:12.5px;line-height:1.7;margin-top:10px}
.mdbody h3{font-size:13px;color:#F5B841;margin:11px 0 4px;font-weight:700}

/* 資料過期警示（2026-08-19）：抓取/調倉失敗時頁面照樣會產生，
   若不明講，使用者看到的是「今天的頁面＋上次的數字」而毫無察覺。
   刻意用醒目的紅底，不要做成低調的小灰字——這是要讓人看見的。 */
.stalewarn{margin:14px 0;padding:12px 15px;border-radius:11px;
 background:#2E1418;border:1px solid #7F1D1D;color:#FCA5A5;
 font-size:13px;line-height:1.8}
.stalewarn b{color:#FEE2E2}

.legend{margin-top:26px;padding:12px 14px;background:var(--surface);
 border:1px solid var(--line);border-radius:11px;font-size:12.5px;color:var(--muted);line-height:2}
.legend span{margin-right:13px;white-space:nowrap}
.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:middle}
.legend .lgnote{display:block;margin-top:5px;color:var(--dim);font-size:11.5px;line-height:1.7;white-space:normal}

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

.empty{background:var(--surface);border:1px dashed var(--line);border-radius:12px;
 padding:34px 20px;text-align:center;color:var(--muted);font-size:13.5px;line-height:1.8}

/* 賽馬頁：統計卡＋持股小卡（沿用 portfolio_html.py 的 holding_rows()，配對這裡的類別） */
.stat{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:16px;text-align:center;margin:10px 0}
.stat .big{font-size:28px;font-weight:800}
.stat .sub2{font-size:12.5px;color:var(--muted)}
.vsgrid{display:flex;gap:10px;margin:10px 0;flex-wrap:wrap}
.vsgrid .box{flex:1;min-width:160px;background:var(--surface);border:1px solid var(--line);
 border-radius:12px;padding:13px;text-align:center}
.vsgrid .box.win{border-color:#22C55E;box-shadow:0 0 0 1px #22C55E}
.vsgrid .nm{font-size:13.5px;font-weight:700}
.vsgrid .val{font-size:21px;font-weight:800;margin:5px 0}
.vsgrid .pnl{font-size:13px;font-weight:700}
.vsgrid details{margin-top:8px;text-align:left}
.vsgrid summary{cursor:pointer;color:#93C5FD;font-size:12px;text-align:center}
.pos{color:var(--up)}.neg{color:var(--down)}.flat{color:var(--dim)}
.hlist{margin-top:8px}
.hrow{padding:8px 0;border-bottom:1px solid var(--line2);font-size:12.5px}
.hrow:last-child{border-bottom:0}
.htop{display:flex;justify-content:space-between;gap:8px;font-weight:700}
.htk{font-size:13px}
.hsub{color:var(--dim);font-size:11.5px;margin-top:2px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0}
.card h2,.explain h3{font-size:14.5px;font-weight:700;margin-bottom:8px;color:#F5B841}
.explain p{font-size:13px;line-height:1.7;margin:8px 0;color:#C7D8EC}
.explain hr{border:0;border-top:1px solid var(--line);margin:12px 0}
.chartlegend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:12px;color:var(--muted)}
.chartlegend span{display:inline-flex;align-items:center;gap:5px}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def header(title_icon, title, subtitle, nav_items, current=None):
    """三頁共用頁首。nav_items = [(key, icon_name, label, href)]"""
    links = "".join(
        f'<a class="nl{" cur" if k == current else ""}" href="{href}">{icon(ic, 14)}{esc(lab)}</a>'
        for k, ic, lab, href in nav_items)
    return (f'<header><h1>{icon(title_icon, 21, "#3B82F6")}{esc(title)}</h1>'
            f'<div class="sub">{subtitle}</div>'
            f'<div class="navlinks">{links}</div></header>')


def score_class(v):
    """評分不上色（2026-08-03 定案）：只分白/灰兩階，顏色留給訊號用。"""
    try:
        return "" if float(v) >= 50 else "dim"
    except (TypeError, ValueError):
        return "dim"


LEGEND_SIGNAL = (
    '<div class="legend"><b>顏色只代表訊號</b>：'
    '<span><i style="background:#22C55E"></i>買進</span>'
    '<span><i style="background:#EF4444"></i>賣出</span>'
    '<span><i style="background:#3B82F6"></i>持有</span>'
    '<span><i style="background:#64748B"></i>觀望</span><br>'
    '<span class="lgnote">數字類指標刻意不上色，避免和訊號顏色混淆。</span></div>')
