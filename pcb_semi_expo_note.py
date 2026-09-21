# -*- coding: utf-8 -*-
"""PCB 半導體化產業筆記（2026-09-22）。

來源：統一投顧 YouTube 頻道《投其所展》AI 帶動載板規格升級！從半導體展看 PCB 設備廠大商機
（2026-09-10 上架、公開影片，https://www.youtube.com/watch?v=LNnI1BxQH2c）。
公開影片＝非機密，可以進 repo；評論一律改寫成自己的話。

流程照 industry-note-intake：逐字稿（本機 whisper，會有聽打錯字）→ 名稱反查代號 →
FinMind 財報／月營收／現金流量核對 → 系統自己的燈號／輪動／base_rate 對照 → 存 obis 04_AI Report。
用法: python pcb_semi_expo_note.py
"""
import io
import os
import sys
import math
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                   # noqa: E402
from fundamentals_reality import _fm, _tw_quarterly, _tw_monthly  # noqa: E402

TITLE = "PCB 半導體化：載板與設備廠"
SOURCE_URL = "https://www.youtube.com/watch?v=LNnI1BxQH2c"
SOURCE_COMMENT = ("統一投顧 YouTube《投其所展》「AI 帶動載板規格升級！從半導體展看 PCB 設備廠大商機」"
                  "（2026-09-10，純產業分享、非投資建議）")
SOURCE_DATA = "FinMind TaiwanStockFinancialStatements／MonthRevenue／CashFlowsStatement、yfinance 日K"
CHECK_DATE = dt.date.today().isoformat()

CORE = [("3167", "大量", "PCB 鑽孔設備 → 光學檢測"),
        ("4958", "臻鼎-KY", "PCB 龍頭／光模塊板／載板"),
        ("7795", "長廣", "載板壓模（壓合）設備")]
PEERS = [("3037", "欣興", "ABF 載板"), ("8046", "南電", "ABF 載板"), ("3189", "景碩", "ABF 載板"),
         ("2368", "金像電", "PCB 板"), ("3044", "健鼎", "PCB 板"), ("3715", "定穎投控", "PCB 板")]

CSS = """
.rpt-sec{margin:22px 0}
.rpt-sec h2{font-size:16px;font-weight:800;color:#93C5FD;margin-bottom:10px}
.rpt-sec p{font-size:13.5px;line-height:1.9;color:var(--ink);margin:0 0 10px}
.rpt-sec ul{margin:0 0 10px 18px;font-size:13.5px;line-height:1.85;color:var(--ink)}
.rpt-sec li{margin-bottom:8px}
.rpt-sec b{color:#F5B841}
.rpt-tldr,.rpt-verify,.rpt-warn,.rpt-mine{background:var(--card);border-radius:12px;
  padding:16px 18px;margin:18px 0 28px;border:1px solid var(--accent)}
.rpt-verify{border-color:var(--up)}.rpt-warn{border-color:var(--down)}.rpt-mine{border-color:#F5B841}
.rpt-tldr .lbl,.rpt-verify .lbl,.rpt-warn .lbl,.rpt-mine .lbl{font-size:11px;font-weight:800;
  letter-spacing:.08em;margin-bottom:8px}
.rpt-tldr .lbl{color:var(--accent)}.rpt-verify .lbl{color:var(--up)}
.rpt-warn .lbl{color:var(--down)}.rpt-mine .lbl{color:#F5B841}
.rpt-tldr p,.rpt-verify p,.rpt-warn p,.rpt-mine p{font-size:13.5px;line-height:1.9;color:var(--ink);margin:0 0 8px}
.rpt-tldr b,.rpt-mine b,.rpt-verify b,.rpt-warn b{color:#F5B841}
.rpt-note{font-size:12px;color:var(--dim);border-top:1px solid var(--line);
  padding-top:10px;margin-top:22px;line-height:1.7}
.stk-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:13px 15px;margin:12px 0}
.stk-card .h{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin-bottom:6px}
.stk-card b{font-size:15px;color:#93C5FD}
.stk-card .tag{font-size:11px;color:var(--dim);background:var(--card);padding:2px 8px;border-radius:6px}
.stk-card .up{color:var(--up)}.stk-card .dn{color:var(--down)}.stk-card .hi{color:#F5B841;font-weight:700}
.stk-card .d{font-size:12.5px;line-height:1.75;color:var(--muted);margin-top:6px}
.stk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:10px 0}
.stk-grid .c{background:var(--card);border-radius:8px;padding:9px 11px}
.stk-grid .k{font-size:10.5px;color:var(--dim)}
.stk-grid .v{font-size:14px;font-weight:700;color:var(--ink);margin-top:2px;
  font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.rpt-chart{margin:14px 0 18px;background:var(--surface);border:1px solid var(--line);
  border-radius:10px;padding:14px 16px}
.rpt-chart .cap{font-size:11.5px;color:var(--dim);margin-top:8px;line-height:1.6}
.rpt-chart svg{width:100%;height:auto;display:block}
/* 圖不要隨螢幕變大：寬螢幕上 640 寬的 viewBox 被撐到 1600px，字放大 2.5 倍、一張圖就佔滿一屏，看不到前後文 */
.rpt-chart{max-width:640px}
.rpt-sec p,.rpt-sec ul{max-width:900px}
.rpt-chart .ttl{font-size:12.5px;font-weight:700;color:var(--ink);margin-bottom:6px}
.svgwrap{overflow-x:auto}
table.pe{width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0}
table.pe th{text-align:left;color:var(--dim);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--line)}
table.pe td{padding:6px 8px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
table.pe td.r,table.pe th.r{text-align:right}
"""

F = 'font-family="ui-sans-serif,system-ui,-apple-system,\'Microsoft JhengHei\',sans-serif"'


def T(x, y, s, size=11, fill="var(--ink)", anchor="start", weight=None, extra=""):
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"'
            f'{w} {extra}>{esc(s)}</text>')


def box(x, y, w, h, fill="var(--card)", stroke="var(--line)", rx=8, sw=1, extra=""):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>')


def arrow(x1, y1, x2, y2, color="var(--dim)", sw=1.6):
    ang = math.atan2(y2 - y1, x2 - x1)
    ax, ay = x2 - 7 * math.cos(ang), y2 - 7 * math.sin(ang)
    px, py = 4 * math.sin(ang), -4 * math.cos(ang)
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{ax:.1f}" y2="{ay:.1f}" stroke="{color}" stroke-width="{sw}"/>'
            f'<polygon points="{x2:.1f},{y2:.1f} {ax+px:.1f},{ay+py:.1f} {ax-px:.1f},{ay-py:.1f}" fill="{color}"/>')


def chart(title, svg, cap, w=None):
    return (f'<div class="rpt-chart"><div class="ttl">{esc(title)}</div><div class="svgwrap">'
            f'<svg viewBox="0 0 {w or 640} __H__" xmlns="http://www.w3.org/2000/svg" {F}>{svg}</svg></div>'
            f'<div class="cap">{cap}</div></div>')


def _fix_h(html, h):
    return html.replace("__H__", str(h), 1)


# ───────────────────────── 產業圖 ─────────────────────────

def svg_layers():
    """各類板子的層數（原文口述）。範圍畫成一條、下限開放的畫成漸層箭頭。"""
    rows = [("光模塊板（800G～NPO）", 10, 18, "10～18 層", "var(--accent)"),
            ("一般伺服器 CPU 板（三～五年前）", 12, 16, "12～16 層", "var(--dim)"),
            ("AI 伺服器 CPU 板（現在）", 20, 26, "20 層起跳", "#F5B841"),
            ("AI 機櫃板：24／30／34 層", 24, 34, "24～34 層", "#F5B841"),
            ("Switch 板（800G）", 30, 30, "30 層", "#F5B841")]
    x0, x1, top, rh = 210, 560, 34, 40
    sc = (x1 - x0) / 36.0
    out = []
    for g in range(0, 37, 6):
        gx = x0 + g * sc
        out.append(f'<line x1="{gx:.1f}" y1="{top-6}" x2="{gx:.1f}" y2="{top+rh*len(rows)-6}" stroke="var(--line)" stroke-width="1"/>')
        out.append(T(gx, top - 12, f"{g} 層", 10, "var(--dim)", "middle"))
    for i, (name, a, b, lab, col) in enumerate(rows):
        y = top + i * rh
        out.append(T(x0 - 10, y + 17, name, 11.5, "var(--ink)", "end"))
        if a == b:
            out.append(f'<circle cx="{x0 + a*sc:.1f}" cy="{y+12}" r="7" fill="{col}"/>')
            out.append(T(x0 + a * sc + 14, y + 16, lab, 11, col, weight=700))
        else:
            out.append(f'<rect x="{x0+a*sc:.1f}" y="{y+4}" width="{(b-a)*sc:.1f}" height="16" rx="4" fill="{col}" opacity="0.85"/>')
            out.append(T(x0 + b * sc + 8, y + 17, lab, 11, col, weight=700))
    return _fix_h(chart("AI 讓板子變多厚：各類板的層數",
                        "".join(out),
                        "數字全是影片口述：CPU 板從「頂多 12～16 層」到「20 層起跳」、Switch 板 30 層、機櫃板最高 34 層、"
                        "光模塊板 10～18 層。CPU 板的 26 層只是畫圖用的延伸長度，原文只說「20 層以上」。"), 260)


def svg_supply_chain():
    """需求→板→PCB／載板廠→設備／測試 的關係圖（原文提到的角色，不加額外公司）。"""
    o = []
    # 左：需求端
    o.append(box(10, 20, 150, 200, "var(--card)", "var(--accent)"))
    o.append(T(85, 42, "需求端", 12, "var(--accent)", "middle", 700))
    for i, s in enumerate(["美系雲端大廠（CSP）", "AI 伺服器機櫃", "光模塊：800G→1.6T", "→ NPO／XPO（→CPO）"]):
        o.append(T(85, 72 + i * 32, s, 11, "var(--ink)", "middle"))
    # 中：板子
    o.append(box(200, 20, 200, 200, "var(--card)", "#F5B841"))
    o.append(T(300, 42, "板子怎麼變", 12, "#F5B841", "middle", 700))
    for i, s in enumerate(["層數↑：24～34 層", "面積↑：整片機櫃板", "UBB＋GPU 併成高階 HDI", "後板＋HDI（壓 4 次、雷射 4 次）", "載板：晶片變大、層數變多"]):
        o.append(T(300, 70 + i * 28, s, 11, "var(--ink)", "middle"))
    # 右：設備
    o.append(box(440, 20, 190, 200, "var(--card)", "var(--up)"))
    o.append(T(535, 42, "設備瓶頸", 12, "var(--up)", "middle", 700))
    eq = [("壓合：噸數 45→90", "長廣（載板壓模機）"), ("鑽孔／背鑽：用量↑", "大量（鑽孔設備）"),
          ("光學檢測：CoWoS 類", "大量（切入）"), ("電測／阻抗／插入損耗", "測試設備：採購 1～2 年")]
    for i, (a, b) in enumerate(eq):
        o.append(T(535, 68 + i * 38, a, 11, "var(--ink)", "middle"))
        o.append(T(535, 82 + i * 38, b, 10, "var(--up)", "middle"))
    o.append(arrow(162, 120, 198, 120, "var(--dim)", 2))
    o.append(arrow(402, 120, 438, 120, "var(--dim)", 2))
    # 下：PCB 廠條
    o.append(box(200, 232, 200, 34, "var(--surface)", "var(--accent)"))
    o.append(T(300, 254, "PCB／載板廠：臻鼎-KY 等（擴產）", 11.5, "var(--ink)", "middle", 700))
    o.append(arrow(300, 222, 300, 232, "var(--dim)", 1.6))
    o.append(T(535, 244, "PCB 廠擴產 → 設備需求同步爆發", 10.5, "var(--muted)", "middle"))
    return _fix_h(chart("產業關係圖：AI 需求怎麼一路傳到設備廠", "".join(o),
                        "只畫影片有提到的角色。公司與設備的對應（大量＝鑽孔與光學檢測、長廣＝載板壓模機）是影片口述；"
                        "「CoWoS 類」是字幕聽成 CoAZ/CoPos 的還原（2.5D／3D 先進封裝）。"), 275)


def svg_optics():
    """光模塊速率路線：並行而非取代。"""
    o = []
    cols = [("800G", "2025 起出貨", "插拔式（有金手指）", "var(--dim)"),
            ("1.6T", "2026 下半年成主流", "插拔式（有金手指）", "var(--accent)"),
            ("NPO", "2026 Q4 量產", "機櫃內 Scale-Up：光纖取代銅纜", "#F5B841"),
            ("XPO", "最快 2027 年底（口述）", "熱插拔的新聯盟：一盒 12.8T", "var(--up)"),
            ("CPO", "更後面", "光模塊直接封進晶片旁", "var(--muted)")]
    w = 118
    for i, (a, b, c, col) in enumerate(cols):
        x = 8 + i * (w + 8)
        o.append(box(x, 30, w, 150, "var(--card)", col, 8, 1.6))
        o.append(T(x + w / 2, 62, a, 20, col, "middle", 800))
        o.append(T(x + w / 2, 88, b, 10.5, "var(--ink)", "middle"))
        # 分行
        for j, seg in enumerate(_wrap(c, 9)):
            o.append(T(x + w / 2, 116 + j * 16, seg, 10.5, "var(--muted)", "middle"))
        if i < len(cols) - 1:
            o.append(arrow(x + w, 105, x + w + 8, 105, "var(--dim)", 1.6))
    o.append(T(320, 205, "重點：它們是疊代／並行，不是誰取代誰——1.6T 與 NPO 下半年同時起量，明年都還在", 11, "var(--ink)", "middle", 700))
    o.append(T(320, 226, "NPO 屬於「新增市場」：原本機櫃內用銅纜，速率到 1.6T～3.2T 以上，銅纜發熱與損耗吃不消，才換成光", 10.5, "var(--muted)", "middle"))
    return _fix_h(chart("光模塊路線圖：800G → 1.6T → NPO／XPO → CPO", "".join(o),
                        "時間點全是影片口述（臻鼎的說法為 800G 去年進入市場、1.6T 今年下半年成主流、NPO 今年 Q4 量產）；"
                        "XPO 一段是主持人自己補充 3 月 OFC 的觀察，不是臻鼎說的。"), 245)


def _wrap(s, n):
    out, cur = [], ""
    for ch in s:
        cur += ch
        if len(cur) >= n and ch in "：，、 ）":
            out.append(cur); cur = ""
        elif len(cur) >= n + 3:
            out.append(cur); cur = ""
    if cur:
        out.append(cur)
    return out[:3]


def svg_xpo():
    """XPO 機盒：8 根光纖 × 8 通道 = 64 通道。"""
    o = []
    o.append(box(10, 20, 250, 150, "var(--card)", "var(--up)", 10, 1.6))
    o.append(T(135, 42, "XPO 機盒（主持人 3 月 OFC 觀察）", 11.5, "var(--up)", "middle", 700))
    for r in range(8):
        for c in range(8):
            o.append(f'<circle cx="{40 + c*24}" cy="{62 + r*13}" r="4.2" fill="var(--up)" opacity="{0.35 + 0.08*((r+c)%5)}"/>')
    o.append(T(135, 184, "8 根光纖 × 8 通道 = 64 通道", 11, "var(--ink)", "middle", 700))
    # 右邊算式
    rows = [("單通道 200G × 64", "12.8T／盒", "var(--up)"),
            ("單通道 400G × 64", "25.6T／盒", "#F5B841"),
            ("對照：一根插拔模塊", "1.6T～3.2T", "var(--dim)")]
    for i, (a, b, col) in enumerate(rows):
        y = 40 + i * 44
        o.append(box(290, y, 340, 34, "var(--card)", col, 6, 1.2))
        o.append(T(304, y + 22, a, 12, "var(--ink)"))
        o.append(T(618, y + 22, b, 13, col, "end", 800))
    o.append(T(290, 176, "機櫃空間：8 個 Switch 機櫃 → 2 個（口述「省 70%」）", 10.5, "var(--muted)"))
    o.append(T(290, 192, "液冷、晶片直貼冷板、三奈米 DSP", 10.5, "var(--muted)"))
    return _fix_h(chart("XPO 機盒的算式：為什麼一盒抵好幾根", "".join(o),
                        "影片說法：100 多家公司加入這個聯盟、機櫃與現有機櫃不太相容所以最快明年底才實現。"
                        "算式我自己重算：64×200G＝12.8T ✓；64×400G＝25.6T（影片講 25.4T，見查證區）。"), 215)


def svg_expansion(capex):
    """臻鼎：工廠座數（口述）＋資本支出（FinMind）。"""
    o = []
    tot = 57.0
    x0, w = 20, 600
    segs = [("已完工 28", 28, "var(--up)"), ("在建 13", 13, "#F5B841"), ("計畫 16", 16, "var(--dim)")]
    xx = x0
    o.append(T(x0, 22, "全球工廠座數（2030 年目標 57 座）", 12, "var(--ink)", weight=700))
    for name, n, col in segs:
        ww = w * n / tot
        o.append(f'<rect x="{xx:.1f}" y="32" width="{ww:.1f}" height="34" fill="{col}" opacity="0.85"/>')
        o.append(T(xx + ww / 2, 54, name, 12, "#0B1220", "middle", 800))
        xx += ww
    o.append(T(x0, 86, "在建 13 座中約 2／3 做 AI 機櫃板（口述）", 10.5, "var(--muted)"))
    # 資本支出長條
    o.append(T(x0, 118, "資本支出（取得不動產廠房設備，億元新台幣；FinMind 現金流量表）", 12, "var(--ink)", weight=700))
    items = [("2024 全年", capex.get("2024-12-31"), "var(--dim)"),
             ("2025 全年", capex.get("2025-12-31"), "var(--accent)"),
             ("2026 上半年", capex.get("2026-06-30"), "#F5B841"),
             ("影片：2026 全年", 800.0, "var(--up)")]
    mx = 1100.0
    for i, (nm, v, col) in enumerate(items):
        y = 134 + i * 30
        o.append(T(x0 + 92, y + 15, nm, 11, "var(--ink)", "end"))
        if v is None:
            continue
        bw = (w - 150) * v / mx
        op_ = 0.45 if "影片" in nm else 0.9
        dash = ' stroke="var(--up)" stroke-dasharray="4 3"' if "影片" in nm else ""
        o.append(f'<rect x="{x0+100}" y="{y+2}" width="{bw:.1f}" height="18" rx="3" fill="{col}" opacity="{op_}"{dash}/>')
        o.append(T(x0 + 106 + bw, y + 16, f"{v:,.0f}" + ("（口述，口徑未確認）" if "影片" in nm else ""), 11, col, weight=700))
    return _fix_h(chart("臻鼎擴產：座數與錢", "".join(o),
                        "28＋13＋16＝57 座，與影片口述的 2030 年 57 座一致。資本支出用 FinMind 累計值還原成單期："
                        "上半年已 292 億，若全年真是 800 億，下半年要再花約 508 億。", 640), 265)


def svg_process():
    """板子的製程瓶頸：一個板廠要走過的關卡與對應設備。"""
    o = []
    steps = [("壓合", "每壓一次就是產能瓶頸", "長廣：載板壓模機"),
             ("鑽孔／背鑽", "淮安 A 園區 > 500 台", "大量：鑽孔設備"),
             ("電鍍", "縱橫比已到 1：30", "又細又深要鍍勻"),
             ("測試", "電測／阻抗／插入損耗／背鑽孔", "採購 1～2 年"),
             ("光學檢測", "2.5D／3D 先進封裝", "大量：切入中")]
    w = 116
    for i, (a, b, c) in enumerate(steps):
        x = 6 + i * (w + 10)
        col = ["#F5B841", "var(--accent)", "var(--up)", "var(--down)", "var(--muted)"][i]
        o.append(box(x, 26, w, 128, "var(--card)", col, 8, 1.6))
        o.append(T(x + w / 2, 52, a, 14, col, "middle", 800))
        for j, s in enumerate(_wrap(b, 8)):
            o.append(T(x + w / 2, 78 + j * 15, s, 10.5, "var(--ink)", "middle"))
        o.append(T(x + w / 2, 142, c, 10, "var(--muted)", "middle"))
        if i < len(steps) - 1:
            o.append(arrow(x + w, 90, x + w + 10, 90, "var(--dim)", 1.6))
    o.append(T(320, 182, "HDI 難度差：壓 1 次＋雷射 2 次（簡單） vs 壓 4 次＋雷射 4 次（難，現在的高階板）", 11, "var(--ink)", "middle", 700))
    return _fix_h(chart("一塊 AI 板要闖的關卡與卡在哪", "".join(o),
                        "影片重點：板廠最大的瓶頸是壓合；設備採購動輒一年以上、部分測試設備長達兩年，"
                        "所以擴產一啟動，設備商的訂單能見度也跟著被拉長。", 640), 200)


def svg_press():
    """長廣：壓模機噸數與段數。"""
    o = []
    o.append(T(20, 22, "壓模機噸數", 12, "var(--ink)", weight=700))
    for i, (nm, v, col) in enumerate([("舊：45 噸", 45, "var(--dim)"), ("新：90 噸", 90, "var(--up)")]):
        y = 34 + i * 34
        o.append(T(100, y + 17, nm, 11.5, "var(--ink)", "end"))
        o.append(f'<rect x="108" y="{y+3}" width="{v*3.2:.1f}" height="20" rx="4" fill="{col}" opacity="0.85"/>')
    o.append(T(20, 126, "壓合段數（一次壓幾層板）", 12, "var(--ink)", weight=700))
    for i, (nm, n) in enumerate([("一段式", 1), ("二段式", 2), ("三段式", 3)]):
        x = 30 + i * 150
        for k in range(n):
            o.append(f'<rect x="{x}" y="{176-k*12}" width="90" height="8" rx="2" fill="var(--up)" opacity="{0.55+0.15*k}"/>')
        o.append(f'<rect x="{x-6}" y="{176+10}" width="102" height="5" rx="2" fill="var(--dim)"/>')
        o.append(T(x + 45, 208, nm, 11.5, "var(--ink)", "middle"))
        if i < 2:
            o.append(arrow(x + 100, 170, x + 140, 170, "var(--dim)", 1.6))
    return _fix_h(chart("長廣：載板壓模機的規格升級", "".join(o),
                        "原文口述：因應晶片尺寸變大、層數變多，壓模機噸數從 45 往 90 噸走，壓合從一段式演進到二段、三段式。", 640), 225)


# ───────────────────────── 財報／技術圖 ─────────────────────────

def svg_months(months):
    w, h = 640, 220
    pad_l, pad_r, pad_t, pad_b = 30, 30, 22, 44
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(months)
    revs = [m["revenue"] / 1e8 for m in months]
    rmax = max(revs) * 1.2
    step = plot_w / n
    bw = step * 0.55
    out = []
    for i, (m, rev) in enumerate(zip(months, revs)):
        cx = pad_l + step * i + step / 2
        bh = plot_h * (rev / rmax)
        by = pad_t + plot_h - bh
        hot = i >= n - 2
        out.append(f'<rect x="{cx-bw/2:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" '
                   f'fill="{"#F5B841" if hot else "var(--accent)"}" opacity="{0.85 if hot else 0.5}"/>')
        out.append(T(cx, by - 6, f"{rev:.2f}", 10, "var(--ink)", "middle"))
        out.append(T(cx, pad_t + plot_h + 16, f'{m["period"][5:]}月', 10, "var(--dim)", "middle"))
        yoy = m.get("yoy")
        if yoy is not None:
            out.append(T(cx, pad_t + plot_h + 32, f"{yoy:+.0f}%", 10,
                         "var(--up)" if yoy >= 0 else "var(--down)", "middle", 700))
    return _fix_h(chart("近 8 個月：月營收（億元）與年增率", "".join(out),
                        "柱頂＝月營收（億元）；柱下＝月份與年增率；黃色＝最近兩個月。"), h)


def svg_quarters(quarters):
    w, h = 640, 260
    pad_l, pad_r, pad_t, pad_b = 30, 30, 20, 34
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(quarters)
    revs = [q["revenue"] / 1e8 for q in quarters]
    gms = [q["gross_margin"] for q in quarters]
    rev_max = max(revs) * 1.05
    bar_h = plot_h * 0.58                      # 長條只用下面 58%，上面留給毛利率折線，兩者不再疊在一起
    gm_lo, gm_hi = min(gms) - 1.5, max(gms) + 1.5
    if gm_hi - gm_lo < 4:
        gm_hi = gm_lo + 4
    step = plot_w / n
    bw = step * 0.55
    bars, dots, labels, pts = [], [], [], []
    for i, (q, rev, gm) in enumerate(zip(quarters, revs, gms)):
        cx = pad_l + step * i + step / 2
        bh = bar_h * (rev / rev_max)
        by = pad_t + plot_h - bh
        bars.append(f'<rect x="{cx-bw/2:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" '
                    f'fill="var(--accent)" opacity="0.55"/>')
        labels.append(T(cx, pad_t + plot_h + 16, q["period"][2:], 10, "var(--dim)", "middle"))
        labels.append(T(cx, by - 5, f"{rev:.1f}", 9.5, "var(--ink)", "middle"))
        gy = pad_t + 14 + plot_h * 0.22 * (1 - (gm - gm_lo) / (gm_hi - gm_lo))
        pts.append((cx, gy))
        dots.append(T(cx, gy - 8, f"{gm:.1f}%", 10, "#F5B841", "middle", 700))
    line = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="#F5B841"/>' for x, y in pts)
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return _fix_h(chart("近 8 季：單季營收（億元）與毛利率", f'<path d="{path}" fill="none" stroke="#F5B841" stroke-width="2"/>'
                        + "".join(bars) + line + "".join(dots) + "".join(labels),
                        "柱＝單季營收（億元）；黃線＝單季毛利率（%，上方帶狀區，只看高低走勢）。"), h)


def _supertrend_series(hi, lo, cl, period=10, mult=3.0):
    """Wilder SuperTrend，回 (線, 方向)；跟 paper_portfolio._supertrend_dir 同一套算法，只是把整條線留下來畫圖。"""
    n = len(cl)
    tr = [hi[0] - lo[0]]
    for i in range(1, n):
        tr.append(max(hi[i] - lo[i], abs(hi[i] - cl[i - 1]), abs(lo[i] - cl[i - 1])))
    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    line, dirs = [None] * n, [0] * n
    up = lo_b = None
    dr = 1
    for i in range(period - 1, n):
        hl2 = (hi[i] + lo[i]) / 2
        bu, bl = hl2 + mult * atr[i], hl2 - mult * atr[i]
        if up is None:
            up, lo_b = bu, bl
            dr = 1 if cl[i] >= hl2 else -1
        else:
            nu = bu if (bu < up or cl[i - 1] > up) else up
            nl = bl if (bl > lo_b or cl[i - 1] < lo_b) else lo_b
            if cl[i] > up:
                dr = 1
            elif cl[i] < lo_b:
                dr = -1
            up, lo_b = nu, nl
        line[i] = lo_b if dr == 1 else up
        dirs[i] = dr
    return line, dirs


def svg_tech(code, name, sym):
    """日K蠟燭＋SuperTrend（日線 Wilder 10,3）＋60MA，近 130 根；另附週線方向（跟趨勢倉同一套）。"""
    import yfinance as yf
    import paper_portfolio as pp
    df = yf.Ticker(sym).history(period="2y", auto_adjust=True)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df = df[df.index.dayofweek < 5]
    if len(df) < 80:
        return "", None
    hi, lo, cl = df["High"].tolist(), df["Low"].tolist(), df["Close"].tolist()
    import technical_indicators as ti
    st = ti.double_typhoon(hi, lo, cl)              # 站內顯示層／燈號用的 SMA-ATR 版（與戰情室 st_line 同一條）
    line = [None if v is None else float(v) for v in st["st"]]
    dirs = [0 if v is None else int(v) for v in st["dir"]]
    ma = [None] * len(cl)
    for i in range(59, len(cl)):
        ma[i] = sum(cl[i - 59:i + 1]) / 60
    wk = pp._dir_of(df, True)
    N = 130
    s = len(cl) - N
    o_ = df["Open"].tolist()[s:]
    H, L, C = hi[s:], lo[s:], cl[s:]
    ln, dr, mm = line[s:], dirs[s:], ma[s:]
    dates = [d.strftime("%m/%d") for d in df.index[s:]]
    w, h = 640, 290
    pl, pr, pt, pb = 46, 16, 14, 24
    pw, ph = w - pl - pr, h - pt - pb
    vals = [v for v in H + L + [x for x in ln if x] + [x for x in mm if x]]
    ymin, ymax = min(vals) * 0.98, max(vals) * 1.02
    def Y(v):
        return pt + ph * (1 - (v - ymin) / (ymax - ymin))
    step = pw / N
    o = []
    for k in range(5):
        v = ymin + (ymax - ymin) * k / 4
        o.append(f'<line x1="{pl}" y1="{Y(v):.1f}" x2="{w-pr}" y2="{Y(v):.1f}" stroke="var(--line)" stroke-width="0.6"/>')
        o.append(T(pl - 5, Y(v) + 3, f"{v:,.0f}", 9.5, "var(--dim)", "end"))
    for i in range(N):
        x = pl + step * i + step / 2
        up_ = C[i] >= o_[i]
        col = "var(--up)" if up_ else "var(--down)"
        o.append(f'<line x1="{x:.1f}" y1="{Y(H[i]):.1f}" x2="{x:.1f}" y2="{Y(L[i]):.1f}" stroke="{col}" stroke-width="1"/>')
        top, bot = Y(max(o_[i], C[i])), Y(min(o_[i], C[i]))
        o.append(f'<rect x="{x-step*0.32:.1f}" y="{top:.1f}" width="{step*0.64:.1f}" height="{max(bot-top,1):.1f}" fill="{col}"/>')
    # SuperTrend 線：分段上色
    seg = []
    for i in range(N):
        if ln[i] is None:
            continue
        x = pl + step * i + step / 2
        if seg and seg[-1][0] != dr[i]:
            seg.append([dr[i], []])
        if not seg:
            seg.append([dr[i], []])
        seg[-1][1].append((x, Y(ln[i])))
    for d_, pts in seg:
        if len(pts) > 1:
            o.append('<path d="M' + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) +
                     f'" fill="none" stroke="{"#facc15" if d_ == 1 else "#c084fc"}" stroke-width="1.8" opacity="0.95"/>')
    mpts = [(pl + step * i + step / 2, Y(v)) for i, v in enumerate(mm) if v]
    if len(mpts) > 1:
        o.append('<path d="M' + " L".join(f"{x:.1f},{y:.1f}" for x, y in mpts) +
                 '" fill="none" stroke="#F5B841" stroke-width="1.2" stroke-dasharray="4 3"/>')
    for i in range(0, N, 22):
        o.append(T(pl + step * i + step / 2, h - 8, dates[i], 9.5, "var(--dim)", "middle"))
    last = C[-1]
    o.append(T(w - pr, pt + 10, f"收 {last:,.1f}", 11, "var(--ink)", "end", 700))
    cap = (f"日 K 蠟燭（漲綠跌紅）＋SuperTrend（黃＝多方支撐、紫＝空方壓力，站內統一配色與算法，跟燈號同一條）＋60 日均線（橘虛線）。"
           f"最新方向：{'多方' if dr[-1] == 1 else '空方'}，SuperTrend 線 {ln[-1]:,.1f}；"
           f"<b>週線</b>方向（模擬倉趨勢倉用的 Wilder 版，算法與日線這條不同）：{'多方' if wk == 1 else '空方'}。資料到 {df.index[-1].strftime('%Y-%m-%d')}。")
    return _fix_h(chart(f"{code} {name}：技術圖", "".join(o), cap), h), {"dir_d": dr[-1], "st": ln[-1], "wk": wk, "last": last}


# ───────────────────────── 主體 ─────────────────────────

def _quad_txt(q):
    m = {"leading": "領先", "weakening": "轉弱", "lagging": "落後", "improving": "改善"}
    if not q:
        return "—"
    return "／".join(f"{k}日{m.get(v, v)}" for k, v in q.items())


def build():
    import tw_symbol
    import lamp_lookup
    data = {}
    for code, name, _t in CORE:
        q = _tw_quarterly(code, n=8)
        mo = _tw_monthly(code, n=8)
        cf = {x["date"]: -x["value"] / 1e8 for x in _fm("TaiwanStockCashFlowsStatement", code, "2024-01-01")
              if x["type"] == "PropertyAndPlantAndEquipment"}
        try:
            lv = lamp_lookup.lookup(code, live=False) or {}
        except Exception:                                   # noqa: BLE001
            lv = {}
        sym = tw_symbol.resolve(code)
        tech_html, tinfo = svg_tech(code, name, sym)
        data[code] = dict(q=q, mo=mo, cf=cf, lv=lv, tech=tech_html, tinfo=tinfo)
    pm = {c: _tw_monthly(c, n=2) for c, _, _ in PEERS}

    import json
    br = {}
    try:
        for x in json.load(open("state/base_rate.json", encoding="utf-8"))["checks"]:
            br[x["ticker"].split(".")[0]] = x
    except Exception:                                       # noqa: BLE001
        pass

    def cell(k, v, cls=""):
        return f'<div class="c"><div class="k">{k}</div><div class="v {cls}">{v}</div></div>'

    def ttm_eps(c):
        q = data[c]["q"]
        return sum(x["eps"] for x in q[-4:]) if len(q) >= 4 else None

    body = []
    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒TL;DR</div>'
        '<p>統一投顧逛半導體展，發現 PCB 與半導體越來越像（所謂 <b>PCB 半導體化</b>）：AI 讓板子<b>更厚（層數多）、更大（面積大）、'
        '孔更深（縱橫比到 1：30）</b>，載板則跟著晶片變大而要求更高。結果是<b>壓合、鑽孔／背鑽、測試</b>這些設備同步缺貨、'
        '採購動輒 1～2 年。影片點名三家：<b>臻鼎-KY（PCB 龍頭，到 2030 年 57 座廠）、大量（鑽孔設備轉做光學檢測，'
        '計畫把半導體設備分割成子公司）、長廣（載板壓模機，45 噸→90 噸）</b>。</p>'
        '<p>核對重點：座數 28＋13＋16＝57 對得上；臻鼎資本支出上半年已 292 億、2025 全年 331 億，說「今年 800 億」方向合理；'
        '影片說「XPO 單通道 400G 可達 25.4T」，我重算是 25.6T。<b>這三檔都不在我們的守備清單裡</b>；'
        '系統另外算的「載板同業」期待值已經很高（欣興、南電的月營收要求是歷史從未出現過的水準），是這條題材最需要留意的地方。</p></div>')

    body.append(
        '<div class="rpt-sec"><h2>技術背景：什麼是「PCB 半導體化」</h2>'
        '<p>過去電路板是「多層板、線寬寬鬆」的工業品；AI 伺服器把它推向<b>半導體的規格</b>：層數從十來層跳到二、三十層，'
        '整片機櫃板面積變大，鑽孔又細又深（影片舉例板厚 5 mm、鍍孔縱橫比 1：30，需要非常好的設備與製程才鍍得均勻），'
        '阻抗要控制在 ±7%、甚至喊到 ±5%，還要做光學／插入損耗檢測——這些原本是半導體廠的事。</p>'
        '<p>影片也點出一個趨勢：AI 加速卡的板子，原本是 UBB（通用基板）加 GPU 板，之後會<b>合併成一塊高階 HDI 板</b>；'
        '能同時做 HDI 又能做厚板的，只剩前三到前五大 PCB 廠。這解釋了為什麼擴產集中在少數龍頭手上，'
        '也是設備需求「不是平均分布、而是集中爆發」的原因。</p></div>')
    body.append(svg_layers())
    body.append(svg_supply_chain())
    body.append(svg_process())

    body.append(
        '<div class="rpt-sec"><h2>光模塊：為什麼板廠也受惠</h2>'
        '<p>臻鼎的光模塊板用的是細線路的半加成製程（字幕聽成「NSAF」，我推測是 mSAP），層數 10～18 層；'
        '800G 去年已進市場，1.6T 今年下半年變主流，<b>NPO</b> 則是取代<b>機櫃內</b>的銅纜（Scale-Up 應用），今年 Q4 量產。'
        '原因很物理：速率到 1.6T～3.2T 以上，銅纜發熱與損耗吃不消。影片特別強調 NPO 是<b>新增市場</b>，'
        '而且與 1.6T 是並行——機櫃裡銅纜的數量遠多於外部連線，所以 NPO 的量後來可能比 1.6T 更大。</p>'
        '<p>主持人另外補了 3 月 OFC 看到的 <b>XPO</b>（由 Arista 牽頭、100 多家公司加入的插拔式新規格）：一個盒子 8 根光纖、'
        '每根 8 通道共 64 通道，單通道 200G 時一盒 12.8T，用液冷；因為與現有機櫃不相容，最快明年底才會實現。'
        '對板廠的意義是：疊層更多、阻抗更嚴（無 DSP 的 LPO 設計要到 ±7%～±5%）、中間層更厚且不能有空洞。</p></div>')
    body.append(svg_optics())
    body.append(svg_xpo())

    cf4958 = data["4958"]["cf"]
    cx = {k: v for k, v in cf4958.items()}
    # 累計值還原成單期年度：年底那筆＝全年，6/30 那筆＝上半年
    body.append(
        '<div class="rpt-sec"><h2>臻鼎：擴產的規模與錢</h2>'
        '<p>影片口述：今年<b>完工 28 座</b>、<b>在建 13 座</b>、<b>計畫 16 座</b>，2030 年全球 57 座；在建的約三分之二做 AI 機櫃板'
        '（Switch／CPU／GPU 板，層數 24～34）。淮安園區光 A 區的鑽孔機加背鑽機就超過 500 台。集團今年投資 800 億、明年約當。</p></div>')
    body.append(svg_expansion(cx))

    body.append(
        '<div class="rpt-sec"><h2>設備廠：大量與長廣在賣什麼</h2>'
        '<p><b>大量</b>：本業是 PCB 鑽孔設備；AI 板很厚，鑽孔需要精準對位，因此往<b>光學檢測</b>延伸，'
        '切進 2.5D／3D 先進封裝的檢測，也進了台灣半導體供應鏈；公司透露未來會把半導體相關設備<b>分割成子公司</b>，之後有機會獨立掛牌。'
        '<b>長廣</b>：做載板用的壓模（壓合）機，跟著晶片尺寸與層數上升，噸數從 45 走向 90 噸、壓合從一段式演進到二、三段式；'
        '載板廠接下來大擴廠，它的機台需求會被帶動。</p></div>')
    body.append(svg_press())

    # ── 相關個股 ──
    body.append('<div class="rpt-sec"><h2>相關個股：財務與技術面（我另外查的）</h2></div>')
    for code, name, tag in CORE:
        d = data[code]
        q, mo, lv = d["q"], d["mo"], d["lv"]
        a, b = mo[-1], mo[-2]
        eps = ttm_eps(code)
        px = lv.get("price")
        pe = f"{px/eps:.0f} 倍" if (px and eps and eps > 0) else "—"
        tgt = lv.get("target")
        tinfo = d["tinfo"] or {}
        card = (f'<div class="stk-card"><div class="h"><b>{code} {name}</b><span class="tag">{esc(tag)}</span></div>'
                '<div class="stk-grid">'
                + cell("最新月營收", f'{a["revenue"]/1e8:.2f}億（{a["period"][5:]}月）')
                + cell("月營收年增", f'{a["yoy"]:+.1f}%' if a["yoy"] is not None else "—",
                       "up" if (a["yoy"] or 0) >= 20 else "")
                + cell("上一個月", f'{b["revenue"]/1e8:.2f}億　{b["yoy"]:+.1f}%' if b["yoy"] is not None else "—")
                + cell("最新季毛利率", f'{q[-1]["gross_margin"]:.1f}%（{q[-1]["period"][2:]}）')
                + cell("近四季 EPS", f"{eps:.2f} 元" if eps is not None else "—")
                + cell("現價／本益比", f'{px:,.1f}／{pe}' if px else "—")
                + cell("市場共識目標價", f"{tgt:,.0f} 元（{(tgt/px-1)*100:+.0f}%）" if (tgt and px) else "查無（Yahoo 無分析師）")
                + cell("四燈／週線", f'{lv.get("lit","—")}／4　週線{"多方" if tinfo.get("wk")==1 else "空方"}')
                + '</div>'
                f'<div class="d">RS60 {lv.get("rs_short", 0):+.1f}%（相對大盤）；產業輪動象限：{_quad_txt(lv.get("quad"))}'
                f'（類股：{esc(str(lv.get("industry") or "—"))}）。</div></div>')
        body.append(card)
        body.append(d["tech"])
        body.append(svg_months(mo))
        if code == "7795":
            # 長廣 2025-12 才掛牌，之前的財報是半年報（24-06、24-12、25-06），跟單季混畫會誤導
            q_ok = [x for x in q if x["period"] >= "2025-09"]
            body.append(svg_quarters(q_ok).replace("近 8 季：", "掛牌後 4 季："))
            body.append('<div class="rpt-note" style="border:0;margin-top:-8px">長廣上市櫃時間不長（FinMind 月營收資料從 2025 年底才有），'
                        '更早的財報是半年報，不能與單季比；月營收也沒有去年同期可算年增。</div>')
        else:
            body.append(svg_quarters(q))

    # ── 三檔現況（資料算出來的，影片沒提）──
    def eps_year(c, yr):
        return sum(x["eps"] for x in data[c]["q"] if x["period"].startswith(str(yr)))
    dq, tq, lq = data["3167"]["q"], data["4958"]["q"], data["7795"]["q"]
    dmo, tmo = data["3167"]["mo"], data["4958"]["mo"]
    body.append(
        '<div class="rpt-mine"><div class="lbl">📊 我另外算的：這三家現在的財務體質（影片沒提）</div>'
        f'<p><b>大量</b>：月營收連 {len(dmo)} 個月年增 {min(m["yoy"] for m in dmo):.0f}%～{max(m["yoy"] for m in dmo):.0f}%，'
        f'毛利率從 {dq[0]["gross_margin"]:.0f}%（{dq[0]["period"][2:]}）爬到 {dq[-1]["gross_margin"]:.1f}%，'
        f'單季 EPS {dq[-1]["eps"]:.2f} 元已接近 2025 全年（{eps_year("3167", 2025):.2f} 元）的 {dq[-1]["eps"]/eps_year("3167", 2025)*100:.0f}%。'
        '影片講的「鑽孔設備需求被 AI 厚板拉動」在它的財報上已經看得到，不是只有故事。'
        f'但股價已反映：現價約 {data["3167"]["lv"].get("price", 0):,.0f} 元，本益比約 '
        f'{data["3167"]["lv"].get("price", 0)/ttm_eps("3167"):.0f} 倍（近四季 EPS）；日線 SuperTrend 是多方、週線卻是空方，短中期訊號不一致。</p>'
        f'<p><b>臻鼎-KY</b>：8 月營收 {tmo[-1]["revenue"]/1e8:.0f} 億、年增 {tmo[-1]["yoy"]:.0f}%（5～8 月年增介於 +32%～+41%），'
        f'但毛利率只有 {tq[-1]["gross_margin"]:.1f}%、單季 EPS {tq[-1]["eps"]:.2f} 元，還低於 2024 年 Q3 的 {tq[0]["eps"]:.2f} 元——'
        '營收成長還沒完全轉成獲利；我推測是擴產期費用與折舊走在營收前面（資本支出上半年 292 億，見上圖），但這是推測，沒有查費用明細。</p>'
        f'<p><b>長廣</b>：上市櫃未滿一年（FinMind 月營收資料從 2025 年底才有），近四季 EPS {ttm_eps("7795"):.2f} 元、本益比約 '
        f'{data["7795"]["lv"].get("price", 0)/ttm_eps("7795"):.0f} 倍；8 月營收 {data["7795"]["mo"][-1]["revenue"]/1e8:.2f} 億約為 7 月的 2 倍，'
        '但這是單月跳升，需要看 9 月是否延續。毛利率一直在 39%～47% 之間，本身不是問題，問題是規模小、估值高。</p></div>')

    # ── 同賽道旁證 ──
    rows = []
    for c, n, t in PEERS:
        m = pm[c][-1] if pm[c] else None
        if not m:
            continue
        rows.append(f'<tr><td>{c} {n}</td><td>{esc(t)}</td><td class="r">{m["revenue"]/1e8:.1f}億</td>'
                    f'<td class="r {"up" if (m["yoy"] or 0)>=30 else ""}">{m["yoy"]:+.0f}%</td></tr>')
    body.append(
        '<div class="rpt-sec"><h2>同賽道旁證與系統的估值對照（影片沒提，我另外查的）</h2>'
        '<table class="pe"><tr><th>公司</th><th>類別</th><th class="r">最新月營收</th><th class="r">年增</th></tr>'
        + "".join(rows) + '</table></div>')

    brl = []
    for c, n, _t in PEERS[:3]:
        x = br.get(c)
        if not x:
            continue
        r = x["requirement"]
        brl.append(f'<tr><td>{c} {n}</td><td class="r">{r["need_yoy"]*100:+.0f}%</td>'
                   f'<td class="r">{r["yoy_max"]*100:+.0f}%</td><td>{r["tier"]}</td>'
                   f'<td class="r">{x["pe"].get("forward_pe", 0):.0f}</td></tr>')
    body.append(
        '<div class="rpt-mine"><div class="lbl">📊 系統自己算的答案：市場對載板題材「期待」堆到多高</div>'
        '<p>影片講的是<b>載板升級＋擴產</b>，這題我們系統早就有「共識預估要求什麼」的檢查（base_rate）。'
        '下表是 ABF 載板三家：要達成分析師共識的全年營收，<b>剩下月份的月營收年增率要平均多少</b>，對照過去 20 個月最高只有多少。</p>'
        '<table class="pe"><tr><th>公司</th><th class="r">還需年增</th><th class="r">歷史最高年增</th><th>級別</th><th class="r">預估本益比</th></tr>'
        + "".join(brl) + '</table>'
        '<p>欣興、南電被標為 <b>unprecedented（史無前例）</b>：要達標，剩餘月份的年增率要比歷史最高值再高一大截。'
        '這不代表題材錯，而是<b>好消息已經被寫進價格與預估</b>；投資上要看的是「有沒有比共識更好」。'
        '臻鼎、大量、長廣三檔目前<b>不在 base_rate 的追蹤名單</b>（分析師覆蓋少或沒有），所以沒有同樣的對照可用。</p></div>')

    # ── 查證 ──
    q4 = data["4958"]["cf"]
    body.append(
        '<div class="rpt-verify"><div class="lbl">✅ 查證結果：這些對得上</div>'
        '<p><b>座數</b>：28＋13＋16＝57，與口述的 2030 年 57 座一致。</p>'
        f'<p><b>臻鼎資本支出</b>（FinMind 累計值還原）：2024 全年 {q4.get("2024-12-31", 0):.0f} 億 → 2025 全年 {q4.get("2025-12-31", 0):.0f} 億 → '
        f'2026 上半年 {q4.get("2026-06-30", 0):.0f} 億。影片說「集團今年投資 800 億」：上半年已花掉約 '
        f'{q4.get("2026-06-30", 0)/800*100:.0f}%，全年 800 億需要下半年再花約 {800-q4.get("2026-06-30", 0):.0f} 億，方向與量級合理。</p>'
        '<p><b>XPO 通道數與速率</b>：8 根×8 通道＝64；64×200G＝12.8T，對上口述。</p>'
        '<p><b>代號</b>：字幕聽成「真頂／大量／長廣」，已用名稱反查系統名單確認 4958 臻鼎-KY、3167 大量、7795 長廣（避免上次沛亨的代號聽打錯誤）。</p></div>')
    body.append(
        '<div class="rpt-warn"><div class="lbl">⚠️ 對不上、或無法核對的地方</div>'
        '<p><b>① 25.4T 應為 25.6T</b>：影片說「單通道 200G 換成 400G 就兩倍，25.4T」。12.8T 的兩倍是 25.6T——'
        '很可能是口誤或字幕誤聽；我在圖中用 25.6T。</p>'
        '<p><b>② 「省 70% 空間」是取整</b>：8 個機櫃縮成 2 個，實際是省 75%。</p>'
        '<p><b>③ 800 億口徑未確認</b>：不確定是新台幣還是人民幣、是集團合併還是含未上市單位。FinMind 的資本支出是上市公司合併報表、新台幣，'
        '只能檢查量級。</p>'
        '<p><b>④ 「AIS-2」沒還原</b>：字幕出現「AIS-2」，上下文是美系雲端客戶的機櫃板（Switch／CPU／GPU），我不確定原字，報告中沒有沿用這個詞。</p>'
        '<p><b>⑤ 其他語音辨識錯字</b>：陳數＝層數、宅板＝載板、磚孔＝鑽孔、壓核＝壓合、CoAZ／CoPos＝CoWoS 一類先進封裝、'
        '光徑銅退＝光進銅退。影片沒有字幕，逐字稿由本機語音辨識產生，公司與數字建議回聽再確認。</p>'
        '<p><b>⑥ 影片沒給的東西</b>：沒有任何目標價、評等、獲利預估；純產業分享（標題已寫非投資建議）。'
        '所以本頁的「投顧怎麼看」只有產業觀點，沒有估值結論。</p></div>')

    body.append(
        '<div class="rpt-sec"><h2>結論與可追蹤的點</h2>'
        '<ul><li><b>先行指標</b>：臻鼎的資本支出（每季現金流量表）與在建廠進度，是設備需求強度的先行指標。</li>'
        '<li><b>大量的分割上市</b>：若確定 Spin Off 半導體設備事業，要留意公司公告時程與評價。</li>'
        '<li><b>NPO Q4 量產</b>：驗證光通訊進入機櫃內的時間點，看供應鏈訂單是否放量。</li>'
        '<li><b>設備採購週期 1～2 年</b>：可用來判斷設備廠訂單能見度與營收認列節奏（大量、長廣的合約負債／存貨可追）。</li>'
        '<li><b>10 月 TPCA 電路板展</b>：影片預告頻道會出更深入的 PCB 解析，值得回來補這頁。</li></ul></div>')

    body.append(
        '<div class="rpt-note">來源：評論改寫自 ' + esc(SOURCE_COMMENT) + f'（<a href="{SOURCE_URL}" style="color:var(--accent)">連結</a>），'
        '逐字稿為本機語音辨識，可能有錯字；數字未經第三方查證，僅供內部參考，不代表任何投資建議；'
        f'財務與行情資料來自 {esc(SOURCE_DATA)}，查證時間 {CHECK_DATE}。</div>')

    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS
            + "</style></head><body><div class=\"wrap\">"
            + header("chip", TITLE, f"統一投顧《投其所展》整理＋FinMind 核對，{CHECK_DATE}", [], eyebrow="INDUSTRY NOTE")
            + "".join(body) + "</div></body></html>")
    return html, data


def main():
    html, data = build()
    dst = op.archive("2026-09-22_PCB半導體化_載板與設備廠.html")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")
    return data


if __name__ == "__main__":
    main()
