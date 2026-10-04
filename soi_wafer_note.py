# -*- coding: utf-8 -*-
"""矽光子晶圓（Photonics-SOI／鍺磊晶）產業筆記（2026-10-05，Leo 提供 IG「股海小英雄」histockhero 圖卡 8 張，缺 9/9 不補）。

來源是公開社群貼文（非機密），所以這支腳本不用進 gitignore。內容已改寫成自己的話、技術圖自己重畫，不逐句照搬。
個股數字另用 FinMind 官方申報逐筆核對：聯亞 2Q26 毛利率 57.5%／EPS 4.62 與貼文一致；
另外查到貼文沒提的：嘉晶 8 月營收創歷史新高（YoY +57.8%）但矽光子只占約 1%；
環球晶 2Q26 EPS 7.90 是業外收益撐起來的（業外 31.6 億 > 本業 14.2 億）；環球晶 8 月營收 YoY 只有 +7.6%、離歷史高點（2023-12）還遠。

用法: python soi_wafer_note.py            # 產生 HTML 存 obis 存檔
      python soi_wafer_note.py --record   # 另外把個股重點寫進軍師資料庫（industry_notes）
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                  # noqa: E402
from fundamentals_reality import _fm, _tw_quarterly            # noqa: E402

TITLE = "矽光子晶圓（SOI）"
SOURCE_COMMENT = "IG「股海小英雄」矽光子晶圓圖卡（共 9 張，取得 1–8 張，缺 9/9 不補），內容已改寫、技術圖自行重畫"
SOURCE_DATA = "FinMind TaiwanStockMonthRevenue／TaiwanStockFinancialStatements"
VERIFIED = "2026-10-05"

CSS = """
.rpt-sec{margin:22px 0}
.rpt-sec h2{font-size:16px;font-weight:800;color:#93C5FD;margin-bottom:10px}
.rpt-sec p{font-size:13.5px;line-height:1.9;color:var(--ink);margin:0 0 10px}
.rpt-sec ul{margin:0 0 10px 18px;font-size:13.5px;line-height:1.85;color:var(--ink)}
.rpt-sec li{margin-bottom:8px}
.rpt-sec b{color:#F5B841}
.rpt-tldr{background:var(--card);border:1px solid var(--accent);border-radius:12px;
  padding:16px 18px;margin:18px 0 28px}
.rpt-tldr .lbl{font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--accent);margin-bottom:8px}
.rpt-tldr p{font-size:14px;line-height:1.9;color:var(--ink);margin:0}
.rpt-tldr b{color:#F5B841}
.rpt-note{font-size:12px;color:var(--dim);border-top:1px solid var(--line);
  padding-top:10px;margin-top:22px;line-height:1.7}
.stk-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:13px 15px;margin:10px 0}
.stk-card .h{display:flex;gap:8px;align-items:baseline;margin-bottom:6px}
.stk-card b{font-size:15px;color:#93C5FD}
.stk-card .tag{font-size:11px;color:var(--dim);background:var(--card);padding:2px 8px;border-radius:6px}
.stk-card .num{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums;color:var(--ink)}
.stk-card .up{color:var(--up)}.stk-card .hi{color:#F5B841;font-weight:700}
.stk-card .warn{color:var(--down);font-weight:700}
.stk-card .d{font-size:12.5px;line-height:1.75;color:var(--muted);margin-top:4px}
.rpt-chart{margin:14px 0 18px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.rpt-chart.narrow{max-width:460px;margin-left:auto;margin-right:auto}
.rpt-chart.mid{max-width:720px;margin-left:auto;margin-right:auto}
.rpt-chart .cap{font-size:11.5px;color:var(--dim);margin-top:8px;line-height:1.6}
.rpt-chart svg{width:100%;height:auto;display:block}
"""


def _svg_soi_layers():
    """SOI 三層晶圓剖面：薄矽（走光）／二氧化矽（管壁，折射率低＝光走得快，光被彈回）／矽基板（支撐）。
    左邊畫三層，右邊各層的說明放在獨立的右欄、每層一行，不跟色塊內文字共用同一條 y。"""
    x0, w = 14, 190
    layers = [  # (y, h, fill, 區塊內小字, 右欄標題, 右欄說明)
        (20, 40, "var(--warn)", "", "上：薄矽 220 nm（n 3.48，光走得慢）", "光在這一層裡走，厚度要均勻到 ±3 nm"),
        (60, 56, "var(--accent)", "n 1.44（光走得快）", "中：二氧化矽 2–3 µm", "當管壁，把光彈回薄矽（全反射）"),
        (116, 70, "var(--card)", "n 3.48", "下：矽基板 700 多 µm", "只負責支撐"),
    ]
    parts = []
    for y, h, fill, inner, t1, t2 in layers:
        op_ = "0.55" if fill != "var(--card)" else "1"
        parts.append(f'<rect x="{x0}" y="{y}" width="{w}" height="{h}" fill="{fill}" opacity="{op_}" '
                     f'stroke="var(--line)"/>')
        parts.append(f'<text x="{x0 + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle" font-size="10.5" '
                     f'fill="var(--ink)">{esc(inner)}</text>')
        parts.append(f'<text x="{x0 + w + 16}" y="{y + h / 2 - 2}" font-size="12" font-weight="700" '
                     f'fill="var(--ink)">{esc(t1)}</text>')
        parts.append(f'<text x="{x0 + w + 16}" y="{y + h / 2 + 14}" font-size="10.5" '
                     f'fill="var(--muted)">{esc(t2)}</text>')
    # 光路：在薄矽裡折線前進（畫在薄矽色塊內，不碰文字）
    parts.append(f'<polyline points="{x0 + 12},52 {x0 + 42},28 {x0 + 72},52 {x0 + 102},28 '
                 f'{x0 + 132},52 {x0 + 162},28" fill="none" stroke="var(--ink)" stroke-width="1.6" opacity="0.85"/>')
    return ('<div class="rpt-chart narrow"><svg viewBox="0 0 470 206" xmlns="http://www.w3.org/2000/svg">'
            + "".join(parts) + '</svg><div class="cap">SOI（絕緣層上覆矽）晶圓剖面示意，厚度比例已壓縮、不按真實比例。'
            '重點：中間那層二氧化矽讓光在薄矽裡被反覆彈回、不往下漏；專給矽光子用的規格叫 Photonics-SOI。</div></div>')


def _svg_flow():
    """從晶圓到光晶片的五步：四步在晶圓上、第五步雷射在晶圓外。每個框內公司名獨立一行。"""
    boxes = [
        (10, "① SOI 晶圓", "Soitec（法）", "環球晶追兵"),
        (158, "② 畫光路", "台積電 65 奈米", "水管＋水龍頭"),
        (306, "③ 長鍺", "嘉晶", "光偵測器（水表）"),
        (454, "④ 疊電子晶片", "台積電 COUPE", "6 奈米 EIC"),
    ]
    parts = []
    for x, t, a, b in boxes:
        parts.append(f'<rect x="{x}" y="22" width="132" height="86" rx="8" fill="var(--card)" stroke="var(--line)"/>')
        parts.append(f'<text x="{x + 66}" y="46" text-anchor="middle" font-size="12" font-weight="800" fill="var(--ink)">{esc(t)}</text>')
        parts.append(f'<text x="{x + 66}" y="70" text-anchor="middle" font-size="11" fill="var(--accent)">{esc(a)}</text>')
        parts.append(f'<text x="{x + 66}" y="90" text-anchor="middle" font-size="10.5" fill="var(--muted)">{esc(b)}</text>')
    for x in (142, 290, 438):
        parts.append(f'<line x1="{x}" y1="65" x2="{x + 14}" y2="65" stroke="var(--dim)" stroke-width="2"/>')
        parts.append(f'<polygon points="{x + 14},60 {x + 20},65 {x + 14},70" fill="var(--dim)"/>')
    # 第五步：雷射在晶圓外，虛線框、放在下排
    parts.append('<rect x="130" y="136" width="360" height="56" rx="8" fill="none" stroke="var(--warn)" stroke-dasharray="5,4"/>')
    parts.append('<text x="310" y="158" text-anchor="middle" font-size="12" font-weight="800" fill="var(--warn)">⑤ 雷射在晶圓外（磷化銦 CW 雷射外置）</text>')
    parts.append('<text x="310" y="178" text-anchor="middle" font-size="10.5" fill="var(--muted)">聯亞（磊晶）／穩懋（代工），貼文標示 2027 驗證中</text>')
    return ('<div class="rpt-chart mid"><svg viewBox="0 0 600 206" xmlns="http://www.w3.org/2000/svg">'
            + "".join(parts) + '</svg><div class="cap">光晶片製作流程與台股位置（依貼文整理）：前四步在同一片 SOI 晶圓上完成，'
            '雷射因為矽不會發光而外置，是另一條供應鏈。</div></div>')


def fetch(code):
    m = None
    try:
        d = _fm("TaiwanStockMonthRevenue", code, "2022-01-01")
        d = sorted(d, key=lambda x: (x["revenue_year"], x["revenue_month"]))
        by = {(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in d}
        last = d[-1]
        y, mo = last["revenue_year"], last["revenue_month"]
        rev = last["revenue"]
        py = by.get((y - 1, mo))
        peak = max(by.items(), key=lambda kv: kv[1])
        m = {"period": f"{y}-{mo:02d}", "revenue": rev, "yoy": ((rev / py - 1) * 100) if py else None,
             "record_high": rev == peak[1], "peak_ym": f"{peak[0][0]}-{peak[0][1]:02d}"}
    except Exception:                                           # noqa: BLE001
        pass
    q = None
    try:
        rows = _tw_quarterly(code, n=1)
        q = rows[-1] if rows else None
    except Exception:                                           # noqa: BLE001
        pass
    time.sleep(0.2)
    return m, q


# (代號, 名稱, 在鏈上的位置, 貼文說法, 我們的查證／提醒)
STOCKS = [
    ("3016", "嘉晶", "晶圓上長鍺（光偵測器＝水表）的磊晶代工",
     "貼文：2Q26 量產、良率客戶端 98%／線上 99%；上半年矽光子只占營收約 1%，年底拚單月 3–5%；2027 產能約現在的 3.5–4 倍；客戶未點名。",
     "整間公司 8 月營收創歷史新高（FinMind 核實，貼文沒提），2Q26 毛利率從去年 9 月季的 7.8% 爬到 23.5%——"
     "但矽光子現在只占約 1%，目前的營收與毛利成長主要來自其他產品；貼文的良率與占比是公司說法，FinMind 無法核對。"),
    ("3081", "聯亞", "雷射磊晶（水塔，不在晶圓上）",
     "貼文：2Q26 毛利率 57%、EPS 4.62；矽光子連續波（CW）雷射是最大品項；2027 產能 2.5 倍。",
     "✅ 毛利率與 EPS 跟 FinMind 官方申報一致（57.5%／4.62）；8 月營收年增 +180.9% 並創歷史新高。"
     "產能 2.5 倍是公司說法，無法核對。"),
    ("2330", "台積電", "在晶圓上畫光路、量產 COUPE（疊電子晶片）",
     "貼文：7 月法說已開始生產；3.2T（2026）→ 6.4T（2027）；CPO 占營收仍小。",
     "8 月營收 YoY +53.3%、創歷史新高，2Q26 毛利率 67.7%；這些主要來自先進製程與 AI 需求，矽光子占比貼文自己說仍小。"),
    ("6488", "環球晶", "SOI 晶圓第二供應商候選（管壁）",
     "貼文：美國 12 吋 SOI 小量生產、客戶排隊、看 2027 放量；SOI 占營收 <10%；是否進台積電未揭露。",
     "8 月營收 YoY 只有 +7.6%，離歷史高點（2023-12）還遠；2Q26 EPS 7.90 是「業外」撐起來的（業外 31.6 億 > 本業營業利益 14.2 億）。"
     "也就是說，矽光子 SOI 對它的獲利目前不是主因（貼文自己也說占比 <10%）。"),
    ("3105", "穩懋", "磷化銦雷射代工（2027 驗證中）",
     "貼文：目前量產的是 InP 光偵測器（舊路線的水表）；CW 雷射仍在驗證——別寫成「已量產」。",
     "8 月營收 YoY +30.6%、創歷史新高，2Q26 毛利率 28.2%、EPS 2.30；成長目前不是來自貼文所說的矽光 CW 雷射（還在驗證）。"),
]


def _stock_card(code, name, role, claim, check, m, q):
    def _pct(v):
        return "—" if v is None else f'<span class="num {"up" if v >= 0 else "warn"}">{v:+.1f}%</span>'
    facts = []
    if m:
        hi = ' <span class="hi">★歷史單月新高</span>' if m["record_high"] else f'（歷史高點 {m["peak_ym"]}）'
        facts.append(f'<span class="num">{m["period"]} 營收 {m["revenue"] / 1e8:,.2f}億</span>　YoY {_pct(m["yoy"])}{hi}')
    if q and q.get("gross_margin") is not None:
        facts.append(f'<span class="num">{q["period"]} 毛利率 {q["gross_margin"]:.1f}%</span>'
                     + (f'　營益率 <span class="num">{q["op_margin"]:.1f}%</span>' if q.get("op_margin") is not None else "")
                     + (f'　EPS <span class="num">{q["eps"]}</span>' if q.get("eps") is not None else ""))
    facts_html = "　｜　".join(facts) if facts else "（FinMind 查無資料）"
    return (f'<div class="stk-card"><div class="h"><b>{esc(name)}</b><span class="tag">{esc(code)}</span></div>'
            f'<div class="d">{esc(role)}</div><div class="d">{esc(claim)}</div>'
            f'<div class="d">{facts_html}</div><div class="d">{esc(check)}</div></div>')


def build():
    cards = []
    for code, name, role, claim, check in STOCKS:
        m, q = fetch(code)
        cards.append(_stock_card(code, name, role, claim, check, m, q))
    sub = esc(SOURCE_COMMENT) + "<br>個股數字另以 " + esc(SOURCE_DATA) + f" 逐筆核對（{VERIFIED}）"
    body = []
    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒看懂</div>'
        '<p>AI 把資料傳輸速率一路推高（800G→1.6T→3.2T），銅線撐不住，改用光；而且新做法是把光路<b>直接畫在一片 12 吋晶圓上</b>'
        '（矽光子），擴產就等於「多開一片晶圓」。但這片晶圓不能是普通矽晶圓，要用<b>三層結構的 SOI 晶圓</b>，'
        '貼文說光子級 SOI 約 95% 在法國 Soitec 手上、單片價格約普通 12 吋的 5–6 倍（標「非官方」），客戶還排隊簽多年訂單。'
        '台廠位置：<b>環球晶</b>是 SOI 追兵（占營收 &lt;10%）、<b>嘉晶</b>做長鍺（矽光子只占約 1%）、'
        '<b>聯亞、穩懋</b>做外置雷射（2027 才驗證）、<b>台積電</b>負責畫光路。'
        '我們查證後的重點：貼文的數字大多對得上，但<b>這五檔現在的營收成長，幾乎都還不是來自矽光子</b>。</p></div>')
    body.append(_svg_soi_layers())
    body.append('<div class="rpt-sec"><h2>為什麼不能用普通矽晶圓</h2>'
                '<p>普通矽晶圓有三件事做不到：</p><ul>'
                '<li><b>不會發光</b>：矽是「間接能隙」，電子要掉回低能階得同時湊齊三個條件（含晶格振動），機率極低、能量多半變成熱。所以雷射不能做在矽上，要外接。</li>'
                '<li><b>看不見通訊用的光</b>：矽只吸收約 1,100 nm 以下的光，資料中心用的 1,310／1,550 nm 直接穿過去。要在晶圓上另外長一層會吸光的材料——<b>鍺</b>（能隙 0.66 eV，吸收可到 1,550 nm 附近）。</li>'
                '<li><b>連「走光」都會漏</b>：普通晶圓上下都是矽，光沒有邊界，會往下散進晶圓底部。要先在矽底下鋪一層折射率低的二氧化矽當管壁。</li></ul></div>')
    body.append('<div class="rpt-sec"><h2>SOI 晶圓難在哪</h2>'
                '<p>薄矽層只有約 220 nm（約頭髮的 1/300），整片 12 吋要均勻到 ±3 nm；厚度一變，光速就變，同一片晶圓上的光路就對不上波長。'
                '貼文介紹的做法是 Soitec 的 <b>Smart Cut</b> 四步：氫離子植入（在固定深度埋一把「刀」）→ 鍵合到另一片矽上 → 加熱沿裂縫劈開、留下薄矽 → 拋光到 ±3 nm。'
                '光子級規格比一般射頻用 SOI 更嚴，所以貼文說「幾乎獨家」。</p></div>')
    body.append(_svg_flow())
    body.append('<div class="rpt-sec"><h2>從晶圓到光晶片：為什麼 65 奈米就夠</h2>'
                '<p>光元件的大小由光的波長決定：1,310 nm 的光，水管（波導）要約 500 nm 寬才關得住，用 65 奈米製程畫就綽綽有餘，不需要 3 奈米。'
                '所以台積電畫光晶片用的是成熟的 65 奈米製程。難點不在線畫得多細，而在<b>晶圓鋪得多平、材料長得多好</b>：'
                '水管內壁毛邊會刮光、晶圓厚度 ±3 nm、鍺與矽的原子間距差 4.2% 容易產生差排（造成暗電流）、'
                '微環調變器遇熱會漂移（要加熱器鎖波長）。</p></div>')
    body.append('<div class="rpt-sec"><h2>相關台股（已核對 FinMind 數字）</h2>' + "".join(cards) + '</div>')
    body.append('<div class="rpt-sec"><h2>這則貼文怎麼看：結論與建議</h2>'
                '<p><b>為什麼是現在</b>：貼文引用台積電 7 月法說，COUPE 已開始生產，速率目標從 2026 年的 3.2T 到 2027 年的 6.4T；嘉晶、聯亞在 2Q26 量產或放量；環球晶、穩懋的矽光相關產品則多數看 2027。</p>'
                '<p><b>貼文自己的排序（供給鏈位置）</b>：最稀缺的是 SOI 晶圓本身（Soitec 近乎獨家）；台廠是「追兵」（環球晶）、「代工／磊晶」（嘉晶、聯亞）、「晶圓廠」（台積電）、「外置雷射」（穩懋）。'
                '貼文特別提醒的修正：<b>穩懋不要寫成「已量產」矽光雷射</b>（量產中的是舊路線光偵測器）；環球晶是否進台積電供應鏈<b>未揭露</b>；嘉晶、環球晶的矽光占營收都很小。</p>'
                '<p><b>貼文自己點名的風險／觀察點</b>：客戶多半未點名；產能擴張（嘉晶 2027 約 3.5–4 倍、聯亞 2.5 倍、Soitec 新廠要到 2029 年）能不能如期；鍺磊晶良率；CW 雷射驗證結果；CPO 占台積電營收仍小。</p>'
                '<p><b>操作建議</b>：貼文沒有給買賣建議，結尾寫「個股僅為產業鏈整理，非投資建議」。本頁也不加。')
    body.append('</p></div>')
    body.append('<div class="rpt-note">來源：' + esc(SOURCE_COMMENT) + '。財務數字來自 ' + esc(SOURCE_DATA)
                + f'，查證時間 {VERIFIED}。貼文內的產能、良率、營收占比、Soitec 市占與價格，都是貼文／公司說法，'
                '我們用公開資料無法核對的都標明了；「非官方」「官方」的標示沿用貼文。個股資訊僅為產業鏈整理，非投資建議。</div>')
    return ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS + "</style></head><body><div class=\"wrap\">"
            + header("rotation", TITLE, sub, [], eyebrow="INDUSTRY NOTE") + "".join(body) + "</div></body></html>")


def record():
    """把每檔重點寫進軍師資料庫（industry_notes）。"""
    import industry_notes
    topic = "矽光子晶圓（SOI／鍺磊晶）"
    path = op.archive("2026-10-05_矽光子晶圓SOI產業筆記.html", sub="產業筆記")
    src = "IG 股海小英雄 矽光子晶圓圖卡（1–8/9）＋FinMind 核對"
    facts = {
        "3016": "嘉晶：晶圓上長鍺（光偵測器）磊晶代工；2Q26 量產、貼文稱矽光子占上半年營收約 1%、年底拚單月 3–5%；FinMind：8 月營收 YoY +57.8% 創歷史新高、2Q26 毛利率 23.5%（去年 9 月季 7.8%）——成長主要不是矽光子。",
        "3081": "聯亞：雷射磊晶（外置雷射，不在晶圓上）；FinMind 核實 2Q26 毛利率 57.5%、EPS 4.62（與貼文一致）、8 月營收 YoY +180.9% 創歷史新高；貼文稱 2027 產能 2.5 倍（無法核對）。",
        "2330": "台積電：65 奈米畫光路、COUPE 已開始生產（貼文引 7 月法說）；3.2T（2026）→6.4T（2027）；CPO 占營收仍小。FinMind：8 月營收 YoY +53.3%、2Q26 毛利率 67.7%。",
        "6488": "環球晶：SOI 晶圓第二供應商候選；貼文稱 SOI 占營收 <10%、是否進台積電未揭露；FinMind：8 月營收 YoY 僅 +7.6%、2Q26 EPS 7.90 為業外撐起（業外 31.6 億 > 本業 14.2 億）。",
        "3105": "穩懋：磷化銦雷射代工；貼文稱 CW 雷射 2027 驗證中、目前量產的是舊路線光偵測器（別寫成已量產）；FinMind：8 月營收 YoY +30.6% 創歷史新高、2Q26 EPS 2.30。",
    }
    names = {"3016": "嘉晶", "3081": "聯亞", "2330": "台積電", "6488": "環球晶", "3105": "穩懋"}
    for tk, s in facts.items():
        industry_notes.record(tk, names[tk], topic, s, source=src, report_path=path, date="2026-10-05")
    print("已寫入軍師資料庫（industry_notes）5 檔；請接著跑 advisor_db_export.py")


def main():
    html = build()
    dst = op.archive("2026-10-05_矽光子晶圓SOI產業筆記.html", sub="產業筆記")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")
    if "--record" in sys.argv:
        record()


if __name__ == "__main__":
    main()
