# -*- coding: utf-8 -*-
"""12吋光罩／High NA EUV 產業筆記（2026-09-16，Leo 提供第三方 TechNews IG 圖卡）。

來源：IG 帳號「technewsinside」（TechNews 科技新報）的 High NA EUV 光罩系列圖卡
（7張＋貼文全文）。內容框架已改寫成自己的話，不逐句照搬對方文案／版面設計。
個股財務數字另用 FinMind 官方申報逐筆核對過；查到原文沒提到的重要對比：
**台灣光罩雖然消息面跳空漲停，但本業其實在惡化**（8月營收年減、Q2營益率轉負）
——題材熱度領先基本面的案例；探針卡雙雄（穎崴／中華精測）成長力道其實遠強於
光罩本身，但那是 AI 先進封裝／HBM 測試需求驅動，不是這則光罩新聞的直接受惠者。

這份內容不是機密（公開 IG 貼文），所以這支腳本不用進 gitignore。
沒有掛進既有產業鏈報告——查過 chain_reports_src 現有 9 條產業鏈都沒有涵蓋
半導體前段設備／光罩這個主題，硬掛不如只做獨立筆記準確（industry-note-intake
skill 的原則：不確定就不要硬掛）。

用法: python photomask_note.py
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                  # noqa: E402
from fundamentals_reality import _fm, _tw_quarterly            # noqa: E402

TITLE = "12吋光罩／High NA EUV"
SOURCE_COMMENT = "IG「TechNews科技新報」High NA EUV光罩系列圖卡（7張），內容已改寫非逐句照搬"
SOURCE_DATA = "FinMind TaiwanStockMonthRevenue／TaiwanStockFinancialStatements"

CSS = """
.rpt-sec{margin:22px 0}
.rpt-sec h2{font-size:16px;font-weight:800;color:#93C5FD;margin-bottom:10px}
.rpt-sec p{font-size:13.5px;line-height:1.9;color:var(--ink);margin:0 0 10px}
.rpt-sec ul{margin:0 0 10px 18px;font-size:13.5px;line-height:1.85;color:var(--ink)}
.rpt-sec li{margin-bottom:8px}
.rpt-sec b{color:#F5B841}
.rpt-tldr{background:var(--card);border:1px solid var(--accent);border-radius:12px;
  padding:16px 18px;margin:18px 0 28px}
.rpt-tldr .lbl{font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--accent);
  margin-bottom:8px}
.rpt-tldr p{font-size:14px;line-height:1.9;color:var(--ink);margin:0}
.rpt-tldr b{color:#F5B841}
.rpt-note{font-size:12px;color:var(--dim);border-top:1px solid var(--line);
  padding-top:10px;margin-top:22px;line-height:1.7}
.rpt-sub{font-size:12.5px;font-weight:700;color:var(--dim);letter-spacing:.04em;
  margin:16px 0 8px}
.stk-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:13px 15px;margin:10px 0}
.stk-card .h{display:flex;gap:8px;align-items:baseline;margin-bottom:6px}
.stk-card b{font-size:15px;color:#93C5FD}
.stk-card .tag{font-size:11px;color:var(--dim);background:var(--card);
  padding:2px 8px;border-radius:6px}
.stk-card .num{font-family:'IBM Plex Mono',ui-monospace,monospace;
  font-variant-numeric:tabular-nums;color:var(--ink)}
.stk-card .up{color:var(--up)}.stk-card .down{color:var(--down)}
.stk-card .hi{color:#F5B841;font-weight:700}
.stk-card .warn{color:var(--down);font-weight:700}
.stk-card .d{font-size:12.5px;line-height:1.75;color:var(--muted);margin-top:4px}
"""


def fetch(code):
    m = None
    try:
        d = _fm("TaiwanStockMonthRevenue", code, "2022-01-01")
        d = sorted(d, key=lambda x: (x["revenue_year"], x["revenue_month"]))
        by_ym = {(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in d}
        last = d[-1]
        y, mo = last["revenue_year"], last["revenue_month"]
        rev = last["revenue"]
        prev_y = by_ym.get((y - 1, mo))
        m = {"period": f"{y}-{mo:02d}", "revenue": rev,
             "yoy": ((rev / prev_y - 1) * 100) if prev_y else None,
             "record_high": rev == max(x["revenue"] for x in d if x["revenue"] is not None)}
    except Exception:                                           # noqa: BLE001
        pass
    q = None
    try:
        rows = _tw_quarterly(code, n=2)
        q = rows[-2:] if rows and len(rows) >= 2 else (rows or None)
    except Exception:                                           # noqa: BLE001
        pass
    time.sleep(0.2)
    return m, q


# (代號, 名稱, 分類, 角色, 質化評論)
GROUP1 = "一、光罩載具／光罩設備／製程量檢／自動化"
GROUP2 = "二、電性測試與探針卡"

STOCKS = [
    ("3680", "家登", GROUP1, "光罩載具龍頭，這次倡議最直接受惠者",
     "8月營收年增近五成，Q2 EPS較Q1翻倍——消息面漲停有基本面支撐，不是純題材"
     "拉抬；但光罩尺寸放大要 2031 年才建試產線，這是長線故事，不是明年就轉單。"),
    ("6953", "家碩", GROUP1, "家登集團旗下，光罩相關設備",
     "8月營收年增37%，Q2毛利率、營益率雙雙優於Q1，成長動能同步家登。"),
    ("2338", "台灣光罩", GROUP1, "光罩製造／驗證，9/9同步跳空漲停",
     "★本篇FinMind核實的重要對比：8月營收年減8.9%，Q2營益率由Q1的+0.9%轉為"
     "-0.8%、EPS從0.52驟降到0.12，獲利主要靠業外收益撐著——本業目前其實在"
     "衰退，這波漲停是題材（大尺寸光罩布局）領先基本面的案例，不是營運已經"
     "反轉向上。"),
    ("3583", "辛耘", GROUP1, "製程量測檢測設備",
     "8月營收創歷史單月新高，YoY+18%，Q2 EPS、毛利率、營益率同步優於Q1，"
     "成長穩健。"),
    ("3455", "由田", GROUP1, "製程量測檢測設備",
     "Q1單季虧損（EPS -0.81），Q2轉盈但營益率僅0.6%，剛從虧轉盈、還算不上"
     "穩健復甦；8月營收年增22%但這點財報體質要繼續觀察。"),
    ("3563", "牧德", GROUP1, "自動化光學檢測（AOI）",
     "8月營收創歷史單月新高，YoY+36%，Q2營益率近39%，是這份清單裡獲利率"
     "最高的一檔。"),
    ("6196", "帆宣", GROUP1, "設備整合與自動化搬運系統整合商",
     "8月營收年增84%，規模最大（單月72億），但系統整合廠本業毛利率結構性"
     "偏低（約13-14%），營收暴增不等於獲利率同步跳升。"),
    ("2464", "盟立", GROUP1, "自動化搬運系統整合商",
     "8月營收年增74%，Q2營益率回升到6.2%，但仍是這份清單中獲利率偏低的一檔"
     "（系統整合商共同特徵）。"),
    ("6223", "旺矽", GROUP2, "探針卡；同時受惠先進封裝/HBM測試需求",
     "8月營收創歷史單月新高，YoY+70%，Q2 EPS 15.55、營益率34%——成長力道"
     "其實遠強於光罩概念股本身，但驅動力主要是AI先進封裝測試需求，不是這則"
     "光罩新聞的直接受惠者，讀者容易把兩件事混在一起。"),
    ("6515", "穎崴", GROUP2, "測試介面卡；AI晶片測試需求指標股",
     "★8月營收年增233%、創歷史新高，是本篇查到的所有個股裡成長最猛的一檔，"
     "Q2 EPS較Q1略降但仍達18.7；同旺矽，這是AI晶片測試熱度而非光罩題材。"),
    ("6510", "中華精測", GROUP2, "探針卡雙雄之一",
     "8月營收創歷史單月新高，YoY+54%，Q2 EPS 較Q1從10.43成長到15.02，"
     "逐季加速；同樣是AI測試需求驅動，非光罩直接受惠股。"),
    ("3289", "宜特", GROUP2, "零組件驗證分析服務",
     "8月營收年減7.9%，但Q2營益率由負轉正（-6.8%→6.0%），獲利結構在改善，"
     "本業還在調整中。"),
]

SKIPPED_NOTE = ("原文另提到「景美科技（興櫃）」「漢民測試（未上市）」「中砂」——"
                "興櫃股與未上市公司 FinMind 涵蓋有限，中砂則只在貼文全文出現、"
                "沒進slide 7的正式分類表，三者本次都未逐一核實，供讀者自行留意。")


def _stock_card(code, name, role, comment, m, q):
    def _pct(v, warn_if_neg=True):
        if v is None:
            return "—"
        cls = "up" if v >= 0 else ("down" if warn_if_neg else "up")
        return f'<span class="num {cls}">{v:+.1f}%</span>'
    facts = []
    if m:
        hi = ' <span class="hi">★歷史單月新高</span>' if m["record_high"] else ""
        facts.append(f'<span class="num">{m["period"]} 營收 {m["revenue"]/1e8:,.2f}億</span>'
                     f'　YoY {_pct(m["yoy"])}{hi}')
    if q:
        parts = []
        for row in q:
            if row.get("op_margin") is None:
                continue
            parts.append(f'{row["period"]} 營益率<span class="num">{row["op_margin"]:.1f}%</span>')
        if parts:
            facts.append("　→　".join(parts))
        last = q[-1] if q else {}
        if last.get("eps") is not None:
            facts.append(f'{last["period"]} EPS <span class="num">{last["eps"]}</span>'
                         + (f'　毛利率 <span class="num">{last["gross_margin"]:.1f}%</span>'
                            if last.get("gross_margin") is not None else ""))
    facts_html = "　｜　".join(facts) if facts else "（FinMind 查無資料）"
    return (f'<div class="stk-card"><div class="h"><b>{esc(name)}</b>'
           f'<span class="tag">{esc(code)}</span></div>'
           f'<div class="d">{esc(role)}</div>'
           f'<div class="d">{facts_html}</div>'
           f'<div class="d">{comment}</div></div>')


def build():
    rows_by_group = {GROUP1: [], GROUP2: []}
    for code, name, group, role, comment in STOCKS:
        m, q = fetch(code)
        rows_by_group[group].append(_stock_card(code, name, role, comment, m, q))

    sub = (esc(SOURCE_COMMENT) + "<br>個股數字另以 " + esc(SOURCE_DATA) + " 逐筆核對")

    body = []
    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒看懂</div>'
        '<p>EUV 微影 40 年來第一次要換光罩尺寸。High NA EUV 把數值孔徑從0.33拉高到'
        '0.55，解析度提升67%，代價是曝光視野縮小——大面積 AI 晶片得切成兩次曝光'
        '再拼接，接合線（stitching）拖累良率跟產能。解法是把光罩從沿用數十年的'
        '<b>6吋放大到12吋</b>，讓大晶粒一次成像、免除拼接，ASML估算生產力最高可'
        '提升四成。台積電9/8宣布跟ASML共同發起產業倡議，Intel、三星也加入，'
        '時程：2030年先進製程導入HighNA、2031年前建12吋光罩試產線、2033年前'
        '大型光罩微影系統全面就緒。消息一出，<b>光罩載具龍頭家登、台灣光罩</b>'
        '9/9雙雙跳空漲停，但本篇核實發現兩者體質不同——家登有營收動能撐著，'
        '台灣光罩本業其實在衰退，是題材先跑。</p></div>')

    body.append('<div class="rpt-sec"><h2>技術背景</h2>'
        '<p>公式 <b>CD = k1 × λ / NA</b>（k1製程係數、λ波長、NA數值孔徑）決定'
        '微影能刻多細的線寬。EUV波長13.5nm四十年沒變，這波是靠拉高NA吃解析度——'
        'ASML的七個微影世代從g-Line（NA 0.38）一路推到 High NA（理論可達0.75），'
        '鏡頭尺寸也跟著愈做愈大。NA拉高的物理代價是曝光視野縮小一半，這對記憶體'
        '這類小面積重複圖案影響不大，但對「一次曝光要蓋住整顆大面積AI晶片」的'
        '先進邏輯製程是硬傷——現行做法是切兩次曝光、中間留一條接合線（紅色虛線'
        '那條），大型光罩免除這道手續。</p>'
        '<p>能撐住更高解析度單次曝光支援更多層數，靠的是<b>金屬氧化物光阻'
        '（MOR）＋乾式顯影（Dry Development）</b>這組新技術，ASML規劃的節點：'
        '單次曝光可支援層數十年間要從2層（1.0nm製程）拉高到8層以上（0.5nm）。'
        '名詞解釋——<b>EPE</b>：邊緣放置誤差（微影套準精度）；<b>OPO</b>：產品'
        '疊對；<b>MMO</b>：機台匹配疊對；<b>WpH</b>：每小時晶圓產出（產能指標）。'
        '</p></div>')

    for group in (GROUP1, GROUP2):
        body.append(f'<div class="rpt-sec"><h2>相關台股（已核對 FinMind 數字）</h2>'
                    f'<div class="rpt-sub">{esc(group)}</div>'
                    + "".join(rows_by_group[group]) + '</div>')

    body.append(f'<div class="rpt-note">{esc(SKIPPED_NOTE)}<br>'
        '來源：' + esc(SOURCE_COMMENT) + '。'
        '財務數字來自 ' + esc(SOURCE_DATA) + '，查證時間 2026-09-16。'
        '個股資訊僅為產業鏈整理，非投資建議。'
        '<br>未掛進既有產業鏈深度報告——查過現有9條產業鏈都沒有涵蓋半導體前段'
        '設備／光罩這個主題，判斷不硬掛比較準確。</div>')

    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS
            + "</style></head><body><div class=\"wrap\">"
            + header("chip", TITLE, sub, [], eyebrow="INDUSTRY NOTE")
            + "".join(body) + "</div></body></html>")
    return html


def main():
    html = build()
    dst = op.archive("12吋光罩HighNA_EUV產業筆記.html")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")


if __name__ == "__main__":
    main()
