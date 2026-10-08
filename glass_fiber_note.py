# -*- coding: utf-8 -*-
"""玻纖布專題產業筆記（2026-10-08）。

來源（皆公開）：
  · 數位時代文章圖卡「玻纖布是用來做什麼的？」（圖中標示資料來源 DOOSAN）
  · 老墨 XQ 直播（2026-10-08）投影片三張：「供應鏈位置｜主板材料與 IC 載板分層」「綜合判讀」（資料截至 2026-10-07）
評論一律改寫成自己的話；圖表自己重畫。

流程照 industry-note-intake：名稱反查代號 → FinMind 財報／月營收 → 系統燈號 → 存 obis 04_AI Report。
用法: python glass_fiber_note.py
"""
import io
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                   # noqa: E402
from fundamentals_reality import _fm, _tw_quarterly             # noqa: E402
from pcb_semi_expo_note import CSS, F, T, box, arrow, chart, _fix_h   # noqa: E402

TITLE = "玻纖布專題：CCL 的骨架與 T-Glass"
CHECK_DATE = dt.date.today().isoformat()
SRC_DS = "數位時代圖卡「玻纖布是用來做什麼的？」（資料來源標示 DOOSAN）"
SRC_LIVE = "XQ 直播（老墨，2026-10-08）投影片「玻纖布專題」（資料截至 2026-10-07）"

# 五檔：代號 → (名稱, 定位)。名稱已用系統名單反查（1303 南亞、1802 台玻、1815 富喬、5340 建榮、5475 德宏）
FIVE = [("1303", "南亞", "集團多元（塑化、電子材料）；玻纖布是其中一塊"),
        ("1802", "台玻", "玻璃本業；高階玻纖布擴產中"),
        ("1815", "富喬", "紗布垂直整合；E 布轉 Low Dk"),
        ("5340", "建榮", "日東紡（Nittobo）為最大股東；主力 Low Dk 布"),
        ("5475", "德宏", "玻纖布；營收規模小、成長最陡")]


# ───────────────────────── 重畫的圖 ─────────────────────────

def svg_ccl_stack():
    """CCL 剖面：銅箔／樹脂含浸玻纖布／銅箔，旁邊四個角色。"""
    s = []
    x0, w = 30, 250
    layers = [("銅箔", "#D97706", 22), ("樹脂", "#F5B841", 30), ("玻纖布", "#93C5FD", 26), ("樹脂", "#F5B841", 30), ("銅箔", "#D97706", 22)]
    y = 24
    mids = {}
    for name, col, h in layers:
        s.append(box(x0, y, w, h, fill=col, stroke="none", rx=3, extra='fill-opacity="0.8"'))
        if name == "玻纖布":                       # 玻纖布畫成交織的條紋
            for k in range(0, w, 14):
                s.append(f'<line x1="{x0+k+4}" y1="{y+3}" x2="{x0+k+4}" y2="{y+h-3}" stroke="#1D4ED8" stroke-width="2" stroke-opacity=".7"/>')
        mids.setdefault(name, []).append(y + h / 2)
        y += h + 3
    labels = [("銅箔", mids["銅箔"][0], "導電層：線路最後蝕刻在這一層"),
              ("樹脂", mids["樹脂"][0], "耐熱、絕緣，把各層黏在一起"),
              ("玻纖布", mids["玻纖布"][0], "骨架：撐住厚度與尺寸，高溫下不變形")]
    ty = [34, 74, 112]                              # 三組說明的文字基線（避免相鄰層的說明互相蓋到）
    for (n, ym, d), yy in zip(labels, ty):
        s.append(f'<polyline points="{x0+w+6},{ym:.1f} {x0+w+20},{ym:.1f} {x0+w+30},{yy-4}" fill="none" stroke="var(--dim)"/>')
        s.append(T(x0 + w + 36, yy, n, 12, weight=700))
        s.append(T(x0 + w + 36, yy + 15, d, 10.5, fill="var(--muted)"))
    s.append(T(x0, y + 18, "CCL（銅箔基板）剖面示意：外面兩層銅、中間是樹脂浸過的玻纖布", 10.5, fill="var(--dim)"))
    return _fix_h(chart("玻纖布在 CCL 裡的位置", "".join(s),
                        f"改畫自 {esc(SRC_DS)}；原圖另有「灌漿系統」（部分絕緣層、確保穩定）一項，這裡併入樹脂層。"), 195)


def svg_supply_chain():
    """兩條線：PCB 主板材料／IC 載板；玻纖布三級。"""
    s = []
    s.append(T(10, 18, "PCB 主板材料", 12, weight=700, fill="#0F766E"))
    steps = ["玻纖布＋樹脂＋銅箔", "CCL 銅箔基板", "PCB 製程", "PCB 主板"]
    bw, gap = 130, 36
    for i, n in enumerate(steps):
        x = 10 + i * (bw + gap)
        hot = i == 1
        s.append(box(x, 28, bw, 44, fill="var(--card)", stroke="#0F766E" if hot else "var(--dim)", sw=2 if hot else 1))
        s.append(T(x + bw / 2, 55, n, 11.5, anchor="middle", weight=700 if hot else None))
        if i < 3:
            s.append(arrow(x + bw + 3, 50, x + bw + gap - 3, 50))
    s.append(T(10, 96, "玻纖布的三個等級（由便宜到貴）", 11, fill="var(--muted)"))
    tiers = [("E-glass", "一般電子級", "var(--dim)"), ("Low-Dk", "高速、低損耗", "#0F766E"), ("T-Glass", "低熱膨脹（最高階）", "#F59E0B")]
    for i, (a, b, col) in enumerate(tiers):
        x = 10 + i * 200
        s.append(box(x, 104, 188, 40, fill="var(--card)", stroke=col, sw=1.6))
        s.append(T(x + 10, 123, a, 12, weight=700, fill=col))
        s.append(T(x + 10, 138, b, 10.5, fill="var(--muted)"))
        if i < 2:
            s.append(arrow(x + 190, 124, x + 198, 124))
    s.append(T(10, 178, "IC 載板封裝材料（另一條線，別混）", 12, weight=700, fill="#EA580C"))
    steps2 = ["GPU／CPU 晶片", "IC 載板（ABF／BT）", "PCB 主板"]
    for i, n in enumerate(steps2):
        x = 10 + i * (bw + gap + 20)
        hot = i == 1
        s.append(box(x, 188, bw + 20, 40, fill="var(--card)", stroke="#EA580C" if hot else "var(--dim)", sw=2 if hot else 1))
        s.append(T(x + (bw + 20) / 2, 213, n, 11.5, anchor="middle", weight=700 if hot else None))
        if i < 2:
            s.append(arrow(x + bw + 23, 208, x + bw + gap + 17, 208))
    s.append(box(10, 240, 470, 28, fill="#F59E0B", stroke="none", rx=6, extra='fill-opacity="0.15"'))
    s.append(T(245, 259, "ABF ＝ 味之素的增層絕緣膜，不是玻纖布", 11.5, anchor="middle", weight=700, fill="#B45309"))
    return _fix_h(chart("玻纖布在供應鏈的位置", "".join(s),
                        f"改畫自 {esc(SRC_LIVE)}。直播圖把 T-Glass 與 IC 載板都用橘色標示，可能暗示兩者有關，"
                        "但圖上沒有明說（這是我的推測）；圖上明講的只有「ABF 不是玻纖布」。", w=640), 280)


# ───────────────────────── 組頁 ─────────────────────────

def _monthly(code):
    """回 (營收月份 'YYYY-MM', 億元, 前一個月億元)。FinMind 的 date 是公布月，營收月份＝公布月 −1。"""
    rows = _fm("TaiwanStockMonthRevenue", code, "2026-03-01")
    last, prev = rows[-1], rows[-2]
    y, m = int(last["date"][:4]), int(last["date"][5:7])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y}-{m:02d}", last["revenue"] / 1e8, prev["revenue"] / 1e8


def build():
    combo = {r["ticker"]: r for r in json.load(open("state/combo_result.json", encoding="utf-8"))["rows"]}

    def cell(k, v, cls=""):
        return f'<div class="c"><div class="k">{k}</div><div class="v {cls}">{v}</div></div>'

    notes = {
        "1303": ("<b>媒體說法</b>：南亞 1 月說與日東紡就特殊玻纖布的協助織造多次交流測試、近期正式投產。<br>"
                 "<b>我查的</b>：這家公司什麼都賣——Q2 EPS 3.37 元，但營業利益 113.6 億、業外 194.1 億（轉投資收益），"
                 "<b>獲利大半來自業外</b>；玻纖布占營收多少我沒查到，不能把它的成長歸給這個題材。"),
        "1802": ("<b>媒體說法</b>：高階玻纖布產線由 4 條擴到 12 條、2026 年產能倍增；Low CTE 已通過主要客戶製程認證。<br>"
                 "<b>我查的</b>：毛利率一年內 10.0% → 23.3%，營益率 12.6%，本業轉好是真的；"
                 "但現價 65.7 元已高於共識目標價 63.0 元，系統四燈全亮、風報比為負。公司業務不只玻纖布。"),
        "1815": ("<b>我查的</b>：本業最漂亮的一檔——毛利率一年內 24.5% → 40.0%，營益率 25.7%，四季營收一路墊高；"
                 "最新 9 月營收 9.39 億，連續兩個月創高。"
                 "系統三燈（RS60 +22.1%）、現價 132.5 元，風報比查無（空方不算）。"),
        "5340": ("<b>媒體說法</b>：日東紡持股約 47.65%；有報導說靠母公司技術移轉 2026 年陸續量產 T-Glass，"
                 "也有報導說 2023 年底 Low Dk 布已通過大客戶認證、T-Glass 仍在準備——<b>兩種說法不一致</b>。<br>"
                 "<b>我查的</b>：本業穩定（營益率 18.4%、毛利率 23.0%），8 月營收 2.85 億連續墊高；規模小。"
                 "<b>直播說「T-Glass 已通過認證並小量出貨」我沒有查到出處</b>，先當成待證實。"),
        "5475": ("<b>我查的</b>：Q2 EPS 0.95 元（一年前 −0.12），毛利率 16.4% → 36.6%、營益率從虧損到 23.7%，"
                 "8 月營收 2.55 億創高；成長幅度最大，但營收規模只有富喬的四分之一左右。"
                 "有沒有 Low DK 2／T-Glass 產品我沒查到。"),
    }
    cards = []
    stat = {}
    for code, name, tag in FIVE:
        q = _tw_quarterly(code, n=4)[-1]
        mon, rev, prev = _monthly(code)
        r = combo.get(code, {})
        lit = r.get("lit")
        tgt, px = r.get("target"), r.get("price")
        stat[code] = (q, mon, rev)
        cards.append(
            f'<div class="stk-card"><div class="h"><b>{code} {name}</b><span class="tag">{esc(tag)}</span></div>'
            '<div class="stk-grid">'
            + cell("最新季 EPS", f'{q["eps"]:.2f} 元（{q["period"][2:]}）', "up" if q["eps"] > 0 else "dn")
            + cell("毛利率／營益率", f'{q["gross_margin"]:.1f}%／{q["op_margin"]:.1f}%', "up" if q["op_margin"] > 0 else "dn")
            + cell("獲利來源", "業外為主" if q["non_op_dominant"] else "本業為主", "dn" if q["non_op_dominant"] else "up")
            + cell(f"最新月營收（{int(mon[5:])}月）", f"{rev:,.2f} 億（月增 {(rev/prev-1)*100:+.0f}%）", "up" if rev >= prev else "dn")
            + (cell("四燈／風報比", f'{lit}/4　' + (f'{r["rr"]:.2f}' if r.get("rr") is not None else "—"), "up" if (lit or 0) >= 3 else "")
               if r else cell("四燈", "不在掃描母體", ""))
            + (cell("現價 vs 共識目標", f'{px:,.1f}／{tgt:,.1f}（{(tgt/px-1)*100:+.0f}%）', "up" if tgt > px else "dn")
               if (tgt and px) else "")
            + f'</div><div class="d">{notes[code]}</div></div>')

    body = []
    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒TL;DR</div>'
        '<p>玻纖布是 CCL（銅箔基板）的骨架，AI 伺服器的板子要跑更高的速度、更高的溫度，就要把玻纖布從一般的 E-glass 升到 Low-Dk，'
        '最高階是<b>低熱膨脹的 T-Glass</b>。這不是新題材：我們的「AI 材料」產業鏈裡已經有玻纖紗布一列，'
        '但只列了富喬一檔。</p>'
        '<p>老墨的結論是「<b>需求主線強、公文利多範圍窄</b>」：AI 伺服器→高階 PCB→T-Glass 的需求是真的，'
        '但他提到的「中國大陸製停止輸入」政策，五檔布廠目前沒有直接訂單證據，先別當成直接利多。</p>'
        '<p><b>我查到、直播沒講的三件事</b>：①這五檔裡<b>本業真的在賺錢、而且一路變好的是富喬、台玻、建榮、德宏</b>，'
        '南亞的獲利大半來自業外轉投資；②台玻和南亞股價已經貼近或高於共識目標價（風報比為負）；'
        '③<b>「指定矽質套管、中國大陸製停止輸入」那份公文我搜了兩輪找不到</b>，不知道品項是不是玻纖類、也不知道日期，在這份筆記裡列為「未證實」。</p></div>')

    body.append(
        '<div class="rpt-sec"><h2>基本概念：玻纖布是什麼</h2>'
        '<p>CCL 是做電路板（PCB）的底板，由三種東西壓成：<b>銅箔</b>（最後被蝕刻成線路的導電層）、'
        '<b>樹脂</b>（耐熱、絕緣、負責黏合）、<b>玻纖布</b>（織好的玻璃纖維布，負責撐住厚度與尺寸，讓板子在高溫高負載下不容易變形）。'
        '可以把它想成鋼筋混凝土：樹脂是混凝土、玻纖布是鋼筋。</p></div>')
    body.append(svg_ccl_stack())
    body.append(
        '<div class="rpt-sec"><h2>供應鏈位置與三個等級</h2>'
        '<p>玻纖布先跟樹脂、銅箔一起做成 CCL，CCL 再進 PCB 廠鑽孔、蝕刻、做線路，變成 PCB 主板。'
        '玻纖布依性能分三級：<b>E-glass</b>（一般電子級，便宜）→ <b>Low-Dk</b>（介電常數低，高速訊號損耗小）→ '
        '<b>T-Glass</b>（熱膨脹係數低，板子受熱不易翹，最高階）。越往上越難做、越缺貨、也越貴。</p>'
        '<p>直播特別提醒一個容易混的點：<b>IC 載板那條線用的是 ABF（味之素增層絕緣膜）或 BT 樹脂，不是玻纖布</b>；'
        '玻纖布主要在 PCB 主板這條線；T-Glass 和高階載板的關係，直播圖只用同色暗示、沒有明說，我沒有查證。</p></div>')
    body.append(svg_supply_chain())

    body.append(
        '<div class="rpt-sec"><h2>五檔觀察名單：直播點名＋我查的財報與燈號</h2>'
        '<p>直播列出的五檔是南亞、台玻、富喬、建榮、德宏。名稱已用系統名單反查代號（1303／1802／1815／5340／5475）。'
        '財報用 FinMind，月營收的「月份」是營收所屬月（FinMind 的日期是公布月，已換算），燈號用系統今早掃描結果。'
        '<b>建榮、德宏目前不在系統的燈號掃描母體，所以沒有四燈。</b></p></div>')
    body.extend(cards)

    body.append(
        '<div class="rpt-sec"><h2>兩條線的差別：需求主線 vs 政策支線</h2><ul>'
        '<li><b>需求主線（AI 高階材料）</b>：AI 伺服器 → 高階 PCB → T-Glass。直播的判斷是需求偏正向，'
        '但<b>受惠要看規格、認證與實際出貨</b>，不是有玻纖布就會漲。上面五檔的財報確實在變好（毛利率都在爬），'
        '但差別在誰真的賣得到高階。</li>'
        '<li><b>政策支線（公文）</b>：直播投影片寫「指定矽質套管、中國大陸製停止輸入」，同品項替代的廠商可能受惠，'
        '但<b>五檔布廠目前沒有直接訂單證據</b>。我自己查：搜尋沒有找到這份公文（找到的是別的品項：2023 年的矽質鼻胃管禁令、'
        '2025 年底的陸製玻璃開放延長），所以<b>品項範圍、日期、是否涵蓋玻纖都未證實</b>。</li></ul></div>')

    body.append(
        '<div class="rpt-sec"><h2>老墨怎麼看：結論與建議</h2><ul>'
        '<li><b>為什麼是現在</b>：資料截至 10/7，AI 高階材料的需求主線還在，公文是新增的政策消息。</li>'
        '<li><b>排序</b>：直播沒有給五檔的先後順序，只是列為觀察名單；唯一有點名細節的是建榮（T-Glass 已認證、小量出貨）。</li>'
        '<li><b>點名的風險／觀察點</b>：公文利多範圍窄，五檔沒有直接訂單證據；受惠要看規格、認證與出貨。</li>'
        '<li><b>操作建議</b>：「先看供需，公文先別當成五檔的直接利多」——原話的意思是不要因為公文去追，等認證與出貨的證據。</li></ul></div>')

    body.append(
        '<div class="rpt-verify"><div class="lbl">✅ 查證結果：這些對得上</div>'
        '<p><b>五檔代號與名稱</b>：用系統名單反查一致。<b>財報與月營收</b>：全部取自 FinMind，台玻 8 月 45.92 億、'
        '德宏 8 月 2.55 億、富喬 9 月 9.39 億，跟 9/30 做富喬筆記時核對過的數字一致。'
        '<b>建榮與日東紡的關係</b>：技術新報（technews）報導日東紡持股約 47.65%；日東紡是最高階 T-Glass 的主要供應商，'
        '多篇報導的說法一致。<b>台玻擴產</b>：高階布產線 4→12 條、Low CTE 通過認證，來自媒體報導（數位時代），不是公司公告。</p></div>')
    body.append(
        '<div class="rpt-warn"><div class="lbl">⚠️ 查不到、或需要打折看的地方</div>'
        '<p><b>① 「指定矽質套管、中國大陸製停止輸入」公文</b>：搜尋兩輪都找不到，品項、日期、是否涵蓋玻纖都未證實。'
        '建議看經濟部國際貿易署的公告或請老墨提供公文字號，再決定這條線算不算數。</p>'
        '<p><b>② 「建榮 T-Glass 已通過認證並小量出貨」</b>：找不到出處；媒體說法互相矛盾（一說 2026 年靠技術移轉陸續量產，'
        '一說 Low Dk 布 2023 年底通過認證、T-Glass 仍在準備）。要以建榮的重大訊息或法說會為準。</p>'
        '<p><b>③ 玻纖布占各公司營收的比重</b>：南亞、台玻我都沒查到，所以不能把整家公司的獲利成長都算成這個題材。</p>'
        '<p><b>④ 直播圖卡的作者與日期</b>：投影片頁尾寫「玻纖布專題｜資料截至 2026/10/07」，沒寫製作者；'
        '第一張圖是數位時代的文章圖卡（引用 DOOSAN），不是直播原創。</p></div>')
    body.append(
        '<div class="rpt-note">來源：評論改寫自 ' + esc(SRC_DS) + '、' + esc(SRC_LIVE) +
        '；圖表自行重畫。財務與月營收來自 FinMind，燈號來自系統掃描（state/combo_result.json），媒體說法來自公開新聞搜尋'
        '（技術新報、今周刊、數位時代、經濟日報等，皆為二手報導）。查證時間 ' + CHECK_DATE + '。僅供內部參考，不構成投資建議。</div>')

    return ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS
            + ".rpt-chart-row .rpt-chart{flex:1 1 300px}</style></head><body><div class=\"wrap\">"
            + header("rotation", TITLE, f"數位時代圖卡＋老墨直播投影片，FinMind 核對 {CHECK_DATE}", [], eyebrow="INDUSTRY NOTE")
            + "".join(body) + "</div></body></html>"), stat


def main():
    html, stat = build()
    dst = op.archive(f"{CHECK_DATE}_玻纖布專題_CCL與T-Glass.html", sub="產業筆記")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")
    return dst


if __name__ == "__main__":
    main()
