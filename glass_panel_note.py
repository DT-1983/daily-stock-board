# -*- coding: utf-8 -*-
"""面板廠逆襲：玻璃基板／CoPoS 產業筆記（2026-09-25）。

來源（皆公開，可進 repo）：
  · histockhero（股海小英雄）IG 圖卡「面板廠逆襲」1～7/8（8/8 未收到）
  · 科技新報 圖卡「瑞銀力挺聯發科 7,300 元目標價」（引瑞銀 2026-09-23 報告）
  · STOCKFEEL 圖卡「PCB 族群漲跌幅統整」（9/24 收盤）
評論一律改寫成自己的話；圖表用原文數據點、自己的樣式重畫。

流程照 industry-note-intake：名稱反查代號 → FinMind 財報／月營收／股價核對 →
系統燈號／base_rate 對照 → 存 obis 04_AI Report。
用法: python glass_panel_note.py
"""
import io
import os
import sys
import json
import math
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                   # noqa: E402
from fundamentals_reality import _fm, _tw_quarterly             # noqa: E402
from pcb_semi_expo_note import CSS, F, T, box, arrow, chart, _fix_h   # noqa: E402

TITLE = "面板廠逆襲：玻璃基板與 CoPoS"
CHECK_DATE = dt.date.today().isoformat()
SRC_IG = "histockhero（股海小英雄）Instagram 圖卡「面板廠逆襲」1～7/8"
SRC_TN = "科技新報圖卡「瑞銀力挺聯發科 7,300 元目標價」（引瑞銀 2026-09-23 研究報告）"
SRC_SF = "STOCKFEEL 圖卡「PCB 族群漲跌幅統整」（9/24 收盤）"

GLASS = [("2409", "友達", "唯一湊齊大玻璃＋Micro LED＋整組元件"),
         ("3481", "群創", "面板級封裝實績最前面"),
         ("3714", "富采", "Micro LED 發光（友達集團）"),
         ("2426", "鼎元", "光電二極體 PD 收光（友達集團）"),
         ("5234", "達興材料", "介電材（友達集團）"),
         ("1595", "川寶", "TGV 填孔設備（最難那段）"),
         ("8027", "鈦昇", "TGV 設備")]
PCB = [("3037", "欣興", 1185, 20.80), ("6213", "聯茂", 595, 17.82), ("3189", "景碩", 962, 15.62),
       ("8046", "南電", 1240, 12.73), ("6274", "台燿", 1495, 9.12), ("2368", "金像電", 1105, 8.33),
       ("8155", "博智", 336, 4.02), ("3044", "健鼎", 538, 3.86), ("3715", "定穎投控", 123, 3.80),
       ("2383", "台光電", 5050, 3.27)]


# ───────────────────────── 技術圖 ─────────────────────────

def svg_reticle():
    """AI 封裝面積用「光罩倍數」算（1 光罩≈26×33 mm）。"""
    data = [("Blackwell", 3.3), ("Rubin", 4.0), ("Rubin Ultra（估）", 9.0), ("台積電 2028 規劃", 14.0)]
    x0, y0, w, bh, gap = 150, 30, 430, 26, 14
    s = []
    for i, (n, v) in enumerate(data):
        y = y0 + i * (bh + gap)
        bw = w * v / 14
        hot = v >= 9
        s.append(T(x0 - 10, y + 17, n, 11.5, anchor="end"))
        s.append(box(x0, y, bw, bh, fill="#EF4444" if hot else "#3B82F6", stroke="none", rx=4, extra='fill-opacity="0.75"'))
        s.append(T(x0 + bw + 8, y + 17, f"{v:g}×", 12, weight=700))
    s.append(T(x0, y0 + 4 * (bh + gap) + 8, "1× = 26×33 mm ≈ 858 mm²；14× ≈ 1.2 萬 mm²（約 11 公分見方）", 10.5, fill="var(--dim)"))
    return _fix_h(chart("晶片封裝越做越大（以光罩倍數計）", "".join(s),
                        "2028 規劃裝 20 顆 HBM；面積變大後，圓形晶圓與塑膠載板兩個老問題同時爆發。"), 205)


def svg_wafer_vs_panel():
    """圓的放方塊，邊角浪費；方的面板排滿。"""
    s = []
    cx, cy, r = 150, 120, 90
    s.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--dim)" stroke-width="1.5"/>')
    a = 26
    for i in range(-4, 4):
        for j in range(-4, 4):
            x, y = cx + i * a, cy + j * a
            corners = [(x, y), (x + a, y), (x, y + a), (x + a, y + a)]
            if all((px - cx) ** 2 + (py - cy) ** 2 <= r * r for px, py in corners):
                s.append(box(x + 1, y + 1, a - 2, a - 2, fill="#F5B841", stroke="none", rx=2))
    s.append(T(cx, 232, "12 吋圓晶圓：利用率 < 70%", 11.5, anchor="middle"))
    s.append(arrow(260, 120, 320, 120))
    px, py, pw = 340, 30, 180
    s.append(box(px, py, pw, pw, fill="none", stroke="var(--dim)", rx=2, sw=1.5))
    for i in range(6):
        for j in range(6):
            s.append(box(px + 3 + i * 29.5, py + 3 + j * 29.5, 27, 27, fill="#F5B841", stroke="none", rx=2))
    s.append(T(px + pw / 2, 232, "方形面板：利用率 > 90%", 11.5, anchor="middle"))
    return _fix_h(chart("問題一：圓的裝不下", "".join(s),
                        "原文例子：9.5 倍光罩的封裝，一片 12 吋晶圓只放得下 4 顆。"), 245)


def svg_cte():
    """熱膨脹係數（ppm/°C）：玻璃可以調到貼近矽，塑膠差 5 倍。"""
    x0, w, lo, hi = 110, 460, 0, 18
    def X(v): return x0 + w * (v - lo) / (hi - lo)
    s = [f'<line x1="{x0}" y1="130" x2="{x0+w}" y2="130" stroke="var(--line)"/>']
    for v in range(0, 19, 3):
        s.append(f'<line x1="{X(v):.1f}" y1="130" x2="{X(v):.1f}" y2="135" stroke="var(--dim)"/>')
        s.append(T(X(v), 150, str(v), 10, fill="var(--dim)", anchor="middle"))
    rows = [("矽", 2.6, 2.6, "#3B82F6", "2.6"), ("玻璃", 3, 9, "#22C55E", "3–9（可調）"), ("塑膠 ABF", 12, 17, "#EF4444", "12–17")]
    for i, (n, a, b, c, lab) in enumerate(rows):
        y = 22 + i * 32
        s.append(T(x0 - 10, y + 13, n, 12, anchor="end"))
        if a == b:
            s.append(f'<circle cx="{X(a):.1f}" cy="{y+9}" r="6" fill="{c}"/>')
            s.append(T(X(a) + 12, y + 13, lab, 11, weight=700))
        else:
            s.append(box(X(a), y + 2, X(b) - X(a), 14, fill=c, stroke="none", rx=7, extra='fill-opacity="0.75"'))
            s.append(T(X(b) + 8, y + 13, lab, 11, weight=700))
    s.append(T(x0 + w / 2, 168, "熱膨脹係數 CTE（ppm/°C）", 10.5, fill="var(--dim)", anchor="middle"))
    return _fix_h(chart("問題二：塑膠一熱就翹", "".join(s),
                        "回焊爐 250–260°C，塑膠載板比矽多脹 5 倍上下，金屬片彎曲、邊角錫球脫開就報廢。"
                        "邊長放大 1.7 倍，翹曲放大約 2.9 倍（1.7²≈2.89，翹曲跟邊長平方成正比，數字自洽）。"), 180)


def svg_panel_sizes():
    """同比例畫 7.5 代玻璃、5 代玻璃、CoPoS 面板、12 吋晶圓。"""
    k = 0.12
    s = []
    x0, y0 = 20, 20
    W, H = 1950 * k, 2250 * k
    s.append(box(x0, y0, W, H, fill="#F5B841", stroke="#B8860B", rx=3, extra='fill-opacity="0.18"'))
    s.append(T(x0 + 8, y0 + 18, "7.5 代 1950×2250（友達中科 L7）", 11, weight=700))
    w5, h5 = 1100 * k, 1300 * k
    s.append(box(x0 + 8, y0 + H - h5 - 8, w5, h5, fill="#F5B841", stroke="#B8860B", rx=3, extra='fill-opacity="0.25"'))
    s.append(T(x0 + 14, y0 + H - h5 + 10, "5 代 1100×1300", 10.5))
    cw, ch = 510 * k, 515 * k
    s.append(box(x0 + 14, y0 + H - ch - 14, cw, ch, fill="#3B82F6", stroke="#1D4ED8", rx=2, extra='fill-opacity="0.35"'))
    s.append(T(x0 + 14 + cw / 2, y0 + H - 14 - ch / 2 + 4, "CoPoS", 9.5, anchor="middle", weight=700))
    rr = 150 * k
    s.append(f'<circle cx="{x0+14+cw+rr+10:.1f}" cy="{y0+H-14-rr:.1f}" r="{rr:.1f}" fill="none" stroke="var(--ink)" stroke-width="1.2"/>')
    s.append(T(x0 + 14 + cw + rr + 10, y0 + H - 14 - rr + 4, "12吋", 9, anchor="middle"))
    tx = x0 + W + 24
    lines = [("CoPoS 面板 510×515 mm", True), ("＝台積電下一代封裝，P＝Panel", False), ("", False),
             ("7.5 代一片（面積換算）", True), ("≈ 16.7 片 CoPoS", False), ("≈ 62 片 12 吋晶圓", False), ("", False),
             ("但實際切割（整片排格子）", True), ("只排得下 3×4＝12 片 CoPoS", False),
             ("「16 片」是面積比、不是排版數", False)]
    for i, (t, b) in enumerate(lines):
        if t:
            s.append(T(tx, y0 + 18 + i * 20, t, 11.5 if b else 11, weight=700 if b else None,
                       fill="var(--ink)" if b else "var(--muted)"))
    return _fix_h(chart("為什麼是面板廠：半導體的「超大」，對面板廠是「小片」", "".join(s),
                        "同一比例畫出：半導體設備的極限是 300 mm 圓片，面板廠日常處理的是兩公尺見方的玻璃。"
                        "面積換算：1950×2250 ÷（510×515）＝16.7；÷（π×150²）＝62.1，原文「16 片／62 片」是面積比。"), 300)


def svg_copos_flow():
    """CoPoS 四步：誰的本行。"""
    steps = [("① 大玻璃承盤", "搬送・清洗・平整", "面板廠本行", "#F5B841"),
             ("② 面板上做 RDL", "黃光・電鍍・介電", "面板廠本行", "#F5B841"),
             ("③ 放晶片與 HBM", "放置・鍵合・測試", "台積電核心", "#3B82F6"),
             ("④ 玻璃核心載板", "TGV 核心＋ABF", "友達試產", "#22C55E")]
    s = []
    bw, gap = 140, 20
    for i, (a, b, c, col) in enumerate(steps):
        x = 10 + i * (bw + gap)
        s.append(box(x, 20, bw, 92, fill="var(--card)", stroke=col, sw=1.6))
        s.append(T(x + bw / 2, 44, a, 12, anchor="middle", weight=700))
        s.append(T(x + bw / 2, 68, b, 10.5, anchor="middle", fill="var(--muted)"))
        s.append(T(x + bw / 2, 96, c, 11, anchor="middle", fill=col, weight=700))
        if i < 3:
            s.append(arrow(x + bw + 2, 66, x + bw + gap - 2, 66))
    return _fix_h(chart("CoPoS 面板級封裝：四步裡有三步是面板廠的語言", "".join(s),
                        "原文觀點：真正的核心（③放晶片）在台積電手上，面板廠是「供給廠房＋玻璃製程」，不搶封裝主角。"
                        "這條路線目前仍是傳聞，沒有簽約。"), 125)


def svg_tgv():
    """TGV 三道關與各自的死法。"""
    s = []
    names = [("① 雷射改質", "能量不穩 → 孔徑忽大忽小"),
             ("② 濕蝕刻成孔", "10 μm 小孔，蝕刻液進不去"),
             ("③ 鍍銅填孔", "填不滿留空洞 → 斷路")]
    for i, (a, b) in enumerate(names):
        x = 20 + i * 205
        s.append(box(x, 30, 170, 50, fill="var(--card)", stroke="var(--dim)", rx=3))
        cx = x + 85
        if i == 0:
            s.append(box(cx - 4, 30, 8, 50, fill="#F5B841", stroke="none", rx=0, extra='fill-opacity="0.6"'))
            s.append(f'<line x1="{cx}" y1="10" x2="{cx}" y2="30" stroke="#EF4444" stroke-width="2"/>')
        elif i == 1:
            s.append(f'<polygon points="{cx-9},30 {cx+9},30 {cx+5},80 {cx-5},80" fill="var(--surface)" stroke="var(--dim)"/>')
        else:
            s.append(box(x, 26, 170, 5, fill="#D97706", stroke="none", rx=0))
            s.append(box(x, 79, 170, 5, fill="#D97706", stroke="none", rx=0))
            s.append(f'<polygon points="{cx-9},30 {cx+9},30 {cx+5},80 {cx-5},80" fill="#D97706"/>')
        s.append(T(cx, 104, a, 12, anchor="middle", weight=700))
        s.append(T(cx, 124, b, 10.5, anchor="middle", fill="#EF4444"))
        if i < 2:
            s.append(arrow(x + 175, 55, x + 200, 55))
    return _fix_h(chart("TGV 玻璃穿孔：三道關，每道都可能整片報廢", "".join(s),
                        "另外兩個硬傷：玻璃脆（微裂紋在高溫多層堆疊下擴大）、導熱差（玻璃約 1 W/m·K，矽約 150，差 150 倍）。"
                        "川寶做的就是第③段填孔。"), 140)


def svg_keys():
    """四把鑰匙 → 三扇門。"""
    keys = ["① 大玻璃多層線路（TFT→RDL）", "② 巨量轉移（Micro LED）", "③ TGV 玻璃穿孔", "④ 集團元件＋現金"]
    doors = [("Micro LED CPO", "友達自己的路・送樣中", "①②③④"),
             ("CoPoS 面板級封裝", "台積電要廠・傳聞", "①③④（②不用）"),
             ("LED 嵌進玻璃基板", "英特爾專利・傳聞", "①②③④")]
    s = []
    for i, k in enumerate(keys):
        y = 20 + i * 44
        s.append(box(10, y, 235, 32, fill="var(--card)", stroke="#F5B841"))
        s.append(T(22, y + 21, k, 11.5))
    for i, (a, b, c) in enumerate(doors):
        y = 22 + i * 58
        s.append(box(370, y, 250, 48, fill="var(--card)", stroke="#3B82F6"))
        s.append(T(382, y + 20, a, 12, weight=700))
        s.append(T(382, y + 38, f"{b}｜用到 {c}", 10, fill="var(--muted)"))
    for i in range(4):
        for j in range(3):
            if j == 1 and i == 1:
                continue
            s.append(f'<line x1="245" y1="{36+i*44}" x2="370" y2="{46+j*58}" stroke="var(--line)" stroke-width="1"/>')
    return _fix_h(chart("面板廠的四把鑰匙，開三扇門", "".join(s),
                        "原文結論：三條路線面板廠都沾得到，但三條都還在送樣或傳聞階段。"
                        "友達是唯一四把鑰匙都有（集團內有富采發光、鼎元收光、達興介電材）。"), 200)


def svg_tpu():
    """瑞銀：Google TPU 營收預估（億美元）與占聯發科營收比重。"""
    d = [(2026, 21, None, "10%"), (2027, 180, None, "46%"), (2028, 435, 350, "65%"),
         (2029, 525, 400, "68%"), (2030, 600, None, "69%")]
    x0, y0, h, bw = 60, 20, 170, 56
    s = [f'<line x1="{x0}" y1="{y0+h}" x2="{x0+5*100}" y2="{y0+h}" stroke="var(--line)"/>']
    for i, (yr, v, old, pct) in enumerate(d):
        x = x0 + 22 + i * 100
        bh = h * v / 600
        if old:
            oh = h * old / 600
            s.append(box(x - 12, y0 + h - oh, bw, oh, fill="none", stroke="var(--dim)", rx=3,
                         extra='stroke-dasharray="4 3"'))
            s.append(T(x - 12 + bw / 2, y0 + h - oh - 6, str(old), 10, fill="var(--dim)", anchor="middle"))
        s.append(box(x, y0 + h - bh, bw, bh, fill="#3B82F6", stroke="none", rx=3, extra='fill-opacity="0.8"'))
        s.append(T(x + bw / 2, y0 + h - bh - 6, str(v), 12, anchor="middle", weight=700))
        s.append(T(x + bw / 2, y0 + h + 16, str(yr), 11, anchor="middle"))
        s.append(T(x + bw / 2, y0 + h + 32, f"占營收 {pct}", 10, anchor="middle", fill="var(--dim)"))
    return _fix_h(chart("瑞銀：聯發科 Google TPU 營收預估（億美元）", "".join(s),
                        "實心＝瑞銀新預估，虛線＝原預估（2028 年 350→435、2029 年 400→525）。"
                        "2026 年只有 21 億美元，真正放量在 2027 年之後。"), 240)


def svg_eps():
    """瑞銀 EPS vs 市場共識。"""
    d = [(2026, 67.63, 66.93), (2027, 177.51, 130.71), (2028, 363.36, 252.85)]
    x0, w = 70, 470
    s = []
    for i, (yr, u, c) in enumerate(d):
        y = 18 + i * 50
        s.append(T(x0 - 10, y + 22, str(yr), 12, anchor="end", weight=700))
        s.append(box(x0, y, w * u / 380, 16, fill="#3B82F6", stroke="none", rx=3, extra='fill-opacity="0.85"'))
        s.append(T(x0 + w * u / 380 + 6, y + 13, f"瑞銀 {u:.2f}（+{(u/c-1)*100:.0f}%）", 11, weight=700))
        s.append(box(x0, y + 20, w * c / 380, 12, fill="var(--dim)", stroke="none", rx=3, extra='fill-opacity="0.55"'))
        s.append(T(x0 + w * c / 380 + 6, y + 31, f"共識 {c:.2f}", 10, fill="var(--muted)"))
    return _fix_h(chart("瑞銀 EPS 預估 vs 市場共識（元）", "".join(s),
                        "今年幾乎等於共識，差距全在 2027～2028；目標價就是押在這兩年。"), 175)


# ───────────────────────── 組頁 ─────────────────────────

def build():
    combo = {r["ticker"]: r for r in json.load(open("state/combo_result.json", encoding="utf-8"))["rows"]}
    br = {}
    try:
        for x in json.load(open("state/base_rate.json", encoding="utf-8"))["checks"]:
            br[x["ticker"].split(".")[0]] = x
    except Exception:                                       # noqa: BLE001
        pass
    q = {c: _tw_quarterly(c, n=4) for c, _, _ in GLASS}
    q["2454"] = _tw_quarterly("2454", n=4)

    def fin(c):
        d = _fm("TaiwanStockFinancialStatements", c, "2026-04-01")
        return {x["type"]: x["value"] for x in d if x["date"].startswith("2026-06")}

    def cell(k, v, cls=""):
        return f'<div class="c"><div class="k">{k}</div><div class="v {cls}">{v}</div></div>'

    body = []
    auo = fin("2409")
    auo_op, auo_nop = auo.get("OperatingIncome", 0) / 1e8, auo.get("TotalNonoperatingIncomeAndExpense", 0) / 1e8
    epi = fin("3714")
    epi_op, epi_nop = epi.get("OperatingIncome", 0) / 1e8, epi.get("TotalNonoperatingIncomeAndExpense", 0) / 1e8
    a = combo.get("2409", {})

    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒TL;DR</div>'
        '<p>AI 晶片封裝越做越大（台積電 2028 規劃到 14 倍光罩），碰到兩個老問題：<b>圓的晶圓裝不下方晶片</b>、'
        '<b>塑膠載板一熱就翹</b>。解法是換成<b>方形的大玻璃</b>，而會處理兩公尺大玻璃、在玻璃上做多層線路的，'
        '是做了 30 年電視面板的面板廠——這就是「面板廠逆襲」的故事，台積電的下一代封裝叫 <b>CoPoS</b>（P＝Panel）。</p>'
        '<p>但原文自己的結論是：<b>2026 是驗證年、不是量產年</b>，三條路線都還在送樣或傳聞，台積電／英特爾／康寧的合作'
        '「三方都不評論、都沒簽約」。</p>'
        f'<p><b>我查到原文沒講的三件事</b>：①友達 Q2 EPS 0.18 元，本業（營業利益）只有 {auo_op:.1f} 億，業外 {auo_nop:.1f} 億，'
        f'<b>獲利幾乎全靠業外</b>；②友達股價 {a.get("price", 0):.1f} 元，已經比分析師共識目標價 {a.get("target", 0):.1f} 元高 '
        f'{(a.get("price", 0)/a.get("target", 1)-1)*100:.0f}%，四燈全亮但風報比是負的；③這條鏈裡<b>本業真的在賺錢的只有達興材料</b>'
        '（毛利率 43%）。另附 PCB 族群本週大漲與瑞銀上調聯發科目標價兩張圖卡的核對。</p></div>')

    body.append(
        '<div class="rpt-sec"><h2>技術背景：AI 晶片為什麼要換成玻璃</h2>'
        '<p>AI 晶片把運算晶片、好幾顆 HBM（堆疊的高速記憶體）、I/O 晶片全部放在一片「中介層」上，這就是台積電的 CoWoS。'
        '中介層的大小用「光罩倍數」算，每一代都在變大。變大之後，兩個原本可以忍受的問題變成致命傷：</p></div>')
    body.append(svg_reticle())
    body.append('<div class="rpt-chart-row" style="display:flex;gap:16px;flex-wrap:wrap">'
                + svg_wafer_vs_panel() + svg_cte() + '</div>')
    body.append(
        '<div class="rpt-sec"><h2>為什麼是玻璃、為什麼是面板廠</h2>'
        '<p>玻璃剛好同時滿足五個條件：<b>平整</b>（整面奈米級平，大面板也能一次曝光）、<b>耐溫</b>（260°C 回焊尺寸幾乎不變）、'
        '<b>不翹</b>（熱膨脹係數可以調到貼近矽）、<b>乾淨</b>（高頻訊號損耗低）、<b>透光</b>（同一片可以走電也可以走光，'
        '矽和塑膠都做不到——這點讓封裝和光通訊都要它）。</p>'
        '<p>而半導體廠從沒處理過這麼大的玻璃，面板廠做了 30 年。面板的 TFT 陣列（像素後面的小開關）本來就是在玻璃上'
        '「鍍膜→黃光曝光→蝕刻」堆 5～8 層，跟封裝要的 RDL（重布線層）做法同一套，差別只在規格：線寬要從 3～5 μm 壓到 2 μm 以下。</p></div>')
    body.append(svg_panel_sizes())
    body.append(svg_keys())
    body.append(
        '<div class="rpt-sec"><h2>四把鑰匙各是什麼</h2><ul>'
        '<li><b>① 大玻璃多層線路</b>：面板 TFT 陣列＝封裝 RDL，同一套製程，差在線寬。</li>'
        '<li><b>② 巨量轉移</b>：Micro LED 要把幾百萬顆比頭髮還細的 LED 放上玻璃並對準、檢測、修復（2020 年一次轉 550 萬顆、'
        '2023 年手錶量產）。顯示器一顆 LED＝一個像素，光通訊一顆 LED＝一條通道，是同一套本事。</li>'
        '<li><b>③ TGV 玻璃穿孔</b>：在玻璃打孔填銅，讓上下層通電；低軌衛星玻璃天線 SatGlass 已在 CES 2026 發表，'
        'TGV／RDL／玻璃核心試產線下半年建。</li>'
        '<li><b>④ 集團元件＋現金</b>：富采（發光）、鼎元（收光 PD）、達興（介電材），今年賣三座廠共 347 億。</li></ul></div>')
    body.append(svg_copos_flow())
    body.append(
        '<div class="rpt-sec"><h2>難在哪：2026 是驗證年</h2>'
        '<p>玻璃的缺點跟優點一樣明顯：<b>脆</b>（一條微裂紋在高溫多層堆疊下會擴大，面板越大、孔越多，機率越高）、'
        '<b>TGV 三道關每道都會死</b>（見下圖）、<b>導熱差</b>（散熱更難），以及 Micro LED 路線要幾十上百條通道同時對準、'
        '通過 3,000 小時（約 125 天不中斷）可靠度驗證，而且產業還沒有標準。</p></div>')
    body.append(svg_tgv())

    # ── 相關個股 ──
    body.append('<div class="rpt-sec"><h2>相關台股：原文點名＋我查的財報與燈號</h2>'
                '<p>原文提醒：目前唯一真正成交的是 2024 年台積電 171.4 億買下群創南科廠——但那座廠做的是矽的 CoWoS，不是玻璃。'
                '台積電×友達中科廠（300 億以上）、英特爾×友達、群創×康寧×輝達，三方都不評論、都未簽約。</p></div>')
    notes = {
        "2409": (f"原文：唯一湊齊大玻璃＋Micro LED 光源＋整組元件，但 CPO／玻璃基板營收目前是 0；Q2 EPS 0.18，"
                 "賣廠 176 億處分利益 Q3 才入帳、屬業外。<br>"
                 f"<b>我查的</b>：Q2 營業利益只有 {auo_op:.1f} 億、業外 {auo_nop:.1f} 億，稅前獲利約 9 成來自業外——"
                 "原文說「0.18 是本業」跟財報對不上，本業其實接近打平（營益率 0.3%）。Q3 再加上賣廠利益，EPS 會好看，但那不是本業轉好。"),
        "3481": ("原文：面板級封裝實績走在友達前面（chip-first 月出貨逾 4,000 萬顆、滿載），但半導體只占營收 1～3%；"
                 "光通訊走矽光子＋玻璃光通道，TGV 玻璃基板最快 2028。<br><b>我查的</b>：兩季 EPS 從 0.20 升到 0.57、"
                 "毛利率 14.6%，本業已經在賺（業外不主導），是這群面板股裡基本面轉好最明確的一家。"),
        "3714": (f"原文：友達集團的 Micro LED 發光。<br><b>我查的</b>：Q2 EPS 1.69 看起來亮眼，但營業利益是 {epi_op:.1f} 億（虧損），"
                 f"業外 {epi_nop:+.1f} 億——<b>本業還在虧</b>，EPS 全靠業外。"),
        "2426": ("原文：友達集團的光電二極體（PD，收光）。<br><b>我查的</b>：規模很小（月營收約 2.5 億），但轉虧為盈，"
                 "毛利率從 10.5% 爬到 22.5%、營益率 8%，趨勢是對的。"),
        "5234": ("原文：友達集團的介電材。<br><b>我查的</b>：這條鏈裡<b>唯一本業穩定賺錢</b>的：毛利率 43%、營益率 20%、"
                 "每季 EPS 約 2.2 元，四季一路小升；它賺的是既有材料生意，玻璃基板若放量是加分，不是全部押注。"),
        "1595": ("原文：TGV 填孔設備，「卡最難那段」。<br><b>我查的</b>：連續四季虧損（Q2 EPS −0.24、營益率 −10.8%），"
                 "月營收 1 億上下。技術卡位對，但還沒轉成營收。"),
        "8027": ("原文：TGV 設備。<br><b>我查的</b>：近兩季都虧損，月營收從 7 月 2.5 億掉到 8 月 1.5 億；"
                 "系統四燈 0/4、RS60 −12.6%，技術面也最弱。"),
    }
    for code, name, tag in GLASS:
        qq = q[code][-1]
        r = combo.get(code, {})
        lit = r.get("lit")
        tgt, px = r.get("target"), r.get("price")
        card = (f'<div class="stk-card"><div class="h"><b>{code} {name}</b><span class="tag">{esc(tag)}</span></div>'
                '<div class="stk-grid">'
                + cell("最新季 EPS", f'{qq["eps"]:.2f} 元（{qq["period"][2:]}）', "up" if qq["eps"] > 0 else "dn")
                + cell("毛利率／營益率", f'{qq["gross_margin"]:.1f}%／{qq["op_margin"]:.1f}%',
                       "up" if qq["op_margin"] > 0 else "dn")
                + cell("獲利來源", "業外為主" if qq["non_op_dominant"] else "本業為主",
                       "dn" if qq["non_op_dominant"] else "up")
                + (cell("四燈／風報比", f'{lit}/4　{r.get("rr"):.2f}' if r.get("rr") is not None else f"{lit}/4　—",
                        "up" if (lit or 0) >= 3 else "")
                   if r else cell("四燈", "不在掃描母體", ""))
                + (cell("現價 vs 共識目標", f'{px:,.1f}／{tgt:,.1f}（{(tgt/px-1)*100:+.0f}%）',
                        "up" if tgt > px else "dn") if (tgt and px) else "")
                + '</div>'
                f'<div class="d">{notes[code]}</div></div>')
        body.append(card)

    # ── PCB 週表 ──
    rows = []
    for c, n, close, wk in PCB:
        r = combo.get(c, {})
        rr = r.get("rr")
        rrs = "—" if rr is None else f"{rr:.2f}"
        cls = "" if rr is None else ("up" if rr >= 1 else "dn")
        lit = r.get("lit")
        rows.append(f'<tr><td>{c} {n}</td><td class="r">{close:,}</td><td class="r up">+{wk:.2f}%</td>'
                    f'<td class="r">{"—" if lit is None else f"{lit}/4"}</td><td class="r {cls}">{rrs}</td></tr>')
    bl = []
    for c, n in (("3037", "欣興"), ("8046", "南電")):
        x = br.get(c)
        if x:
            rq = x["requirement"]
            bl.append(f'{n}：剩餘月份月營收年增要 {rq["need_yoy"]*100:+.0f}%，歷史最高 {rq["yoy_max"]*100:+.0f}%（{rq["tier"]}）')
    body.append(
        '<div class="rpt-sec"><h2>PCB 族群本週大漲：核對＋系統怎麼看</h2>'
        f'<p>{esc(SRC_SF)}：ABF 載板、CCL 需求升溫，欣興、聯茂、景碩領漲。<b>核對結果</b>：9/24 收盤價全部對得上；'
        '週漲幅是跟<b>上週五（9/18）</b>收盤比，我逐檔重算數字一致。欣興、南電、景碩同時在我們的「PCB/ABF 載板」與'
        '「玻璃基板/TGV」兩條鏈裡。</p>'
        '<table class="pe"><tr><th>公司</th><th class="r">9/24 收盤</th><th class="r">週漲幅</th>'
        '<th class="r">系統四燈</th><th class="r">風報比</th></tr>' + "".join(rows) + '</table>'
        '<p><b>系統的看法</b>：漲最多的三檔燈號都亮 3 盞，但風報比全部小於 1（欣興 0.62、景碩 0.33、聯茂已超過共識目標價）——'
        '<b>趨勢對、價位不划算</b>，照進出燈號的規則不算打點。'
        + (("另外，系統的預估前提檢查顯示期待已經很滿：" + "；".join(bl) + "。") if bl else "")
        + '空白的是不在掃描母體裡的股票。</p></div>')

    # ── 聯發科 ──
    m = combo.get("2454", {})
    mq = q["2454"]
    h1 = sum(x["eps"] for x in mq if x["period"] in ("2026-03", "2026-06"))
    tp_calc = 27 * (177.51 + 363.36) / 2
    body.append(
        '<div class="rpt-sec"><h2>聯發科：瑞銀目標價 6,500 → 7,300</h2>'
        f'<p>{esc(SRC_TN)}：評等買進，目標價調高到 7,300 元（較 9/23 收盤 5,185 元有 +40.8% 空間），'
        '估值基礎是 2027～28 年平均 EPS × 27 倍本益比。主軸是 Google TPU：瑞銀把 2028、2029 年的 TPU 營收預估上調，'
        '2030 年 TPU 將占聯發科營收近七成；另有新 ASIC 專案可望近月敲定（SpaceX Dojo 3 用台積電 N2＋SoW、特斯拉 AI6），'
        '合計潛在營收 100～150 億美元。</p></div>')
    body.append(svg_tpu())
    body.append(svg_eps())
    body.append(
        '<div class="rpt-mine"><div class="lbl">📊 我核對的</div>'
        f'<p><b>目標價算式</b>：27 ×（177.51＋363.36）÷ 2 ＝ {tp_calc:,.0f} 元，跟 7,300 元對得上。</p>'
        f'<p><b>收盤價</b>：9/23 收 {m.get("price", 0):,.0f} 元，對得上。系統四燈 {m.get("lit")}/4、RS60 {m.get("rs_short", 0):+.1f}%，'
        '趨勢在多方。</p>'
        f'<p><b>今年 EPS</b>：上半年實際 {h1:.2f} 元；瑞銀全年 67.63 元，等於下半年要 {67.63-h1:.2f} 元（比上半年多 '
        f'{((67.63-h1)/h1-1)*100:.0f}%），跟共識 66.93 元幾乎一樣，今年不是爭點。</p>'
        '<p><b>真正的爭點在 2027～28</b>：瑞銀 2027 年 EPS 177.51 元，是今年的 2.6 倍、比共識高 36%；2028 年再比共識高 44%。'
        '目標價完全押在「TPU 放量真的發生、而且發生得比市場想的快」。</p></div>')

    # ── 原文怎麼看 ──
    body.append(
        '<div class="rpt-sec"><h2>原文怎麼看：結論與建議</h2>'
        '<p><b>histockhero（面板廠逆襲）</b></p><ul>'
        '<li><b>為什麼是現在</b>：AI 晶片面積一路放大到 14 倍光罩，圓晶圓與塑膠載板同時碰到極限，大玻璃是目前最可行的解，'
        '而大玻璃是面板廠的本行。</li>'
        '<li><b>排序</b>：友達是「唯一湊齊」四把鑰匙的；群創是「實績走在前面」的——兩家定位不同，原文沒有說誰比較好買。</li>'
        '<li><b>原文點名的風險</b>：2026 是驗證年不是量產年，<b>外資買的是產能、不是訂單</b>；三條路線都還在送樣或傳聞；'
        '友達的 CPO／玻璃基板營收目前是 0；群創半導體只占營收 1～3%、TGV 最快 2028。原文特別舉友達 2010 年喊太陽能營收'
        '100～200 億、結果連虧 7 年、2026 年以 7.8 億處分作為前車之鑑。</li>'
        '<li><b>操作建議</b>：原文沒有給買賣建議，給的是判斷方法——<b>轉型成不成，看客戶認證與訂單，不看股東會上的信心</b>。</li></ul>'
        '<p><b>瑞銀（聯發科）</b>：買進，目標價 6,500 → 7,300 元，理由是 Google TPU 營收預估上調與新 ASIC 專案；'
        '圖卡沒有列出風險。</p>'
        '<p><b>STOCKFEEL（PCB 週表）</b>：ABF 載板與 CCL 需求重新升溫，PCB 是本週 AI 供應鏈的主攻族群；是行情整理，沒有建議。</p></div>')

    body.append(
        '<div class="rpt-verify"><div class="lbl">✅ 查證結果：這些對得上</div>'
        '<p><b>友達 Q2 EPS 0.18</b>、<b>聯發科 9/23 收盤 5,185</b>、<b>PCB 表 10 檔 9/24 收盤</b>，與 FinMind 一致；'
        'PCB 週漲幅以 9/18 收盤為基準，抽驗 4 檔完全一致。</p>'
        '<p><b>算式自洽</b>：翹曲放大 2.9 倍＝邊長 1.7 倍的平方；7.5 代玻璃＝62 片 12 吋晶圓（面積比 62.1）；'
        '3,000 小時＝125 天；瑞銀目標價 27×兩年平均 EPS＝7,302。</p>'
        '<p><b>代號</b>：原文代號全部用系統名單反查確認（2409 友達、3481 群創、3714 富采、2426 鼎元、5234 達興材料、'
        '1595 川寶、8027 鈦昇、2454 聯發科）。</p></div>')
    body.append(
        '<div class="rpt-warn"><div class="lbl">⚠️ 對不上、或需要打折看的地方</div>'
        f'<p><b>① 「友達 Q2 EPS 0.18 是本業」對不上財報</b>：營業利益 {auo_op:.1f} 億、業外 {auo_nop:.1f} 億，本業只占稅前獲利約一成。</p>'
        '<p><b>② 「7.5 代一片＝16 片 CoPoS」是面積比</b>：面積換算 16.7 片，但整片切格子只排得下 3×4＝12 片，實際產出要看排版與邊料。</p>'
        '<p><b>③ 賣廠金額兩個數字</b>：第 4 張寫「今年賣三廠 347 億」、第 7 張寫「賣廠 176 億處分利益」——前者應是售價、後者是處分利益，'
        '不是同一個東西；我沒有查到公告原文，兩個數字都照原文轉述。</p>'
        '<p><b>④ 缺第 8 張</b>：IG 貼文共 8 張，只收到 1～7 張。</p>'
        '<p><b>⑤ 聯發科目標價已更新進系統</b>：原本系統顯示的投顧目標價是舊的 4,430 元（Leo 自行彙整）；'
        '這張圖卡已走券商報告管線解析，查燈號現在顯示瑞銀 7,300 元，並產出個股整合報告。</p></div>')

    body.append(
        '<div class="rpt-note">來源：評論改寫自 ' + esc(SRC_IG) + '、' + esc(SRC_TN) + '、' + esc(SRC_SF) +
        '；圖表用原文數據點自行重畫。財務與行情資料來自 FinMind（財報、股價）與系統燈號掃描（state/combo_result.json），'
        f'查證時間 {CHECK_DATE}。僅供內部參考，不構成投資建議。</div>')

    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS
            + ".rpt-chart-row .rpt-chart{flex:1 1 300px}</style></head><body><div class=\"wrap\">"
            + header("rotation", TITLE, f"histockhero 圖卡＋瑞銀聯發科＋PCB 週表，FinMind 核對 {CHECK_DATE}", [],
                     eyebrow="INDUSTRY NOTE")
            + "".join(body) + "</div></body></html>")
    return html


def main():
    html = build()
    dst = op.archive(f"{CHECK_DATE}_面板廠逆襲_玻璃基板與CoPoS.html")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")


if __name__ == "__main__":
    main()
