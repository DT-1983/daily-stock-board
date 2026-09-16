# -*- coding: utf-8 -*-
"""DWDM 薄膜濾光片產業筆記（2026-09-16，Leo 提供第三方 IG 科普圖卡）。

來源：IG 帳號「股海小英雄」（histockhero）的濾光片科普圖卡（10 張，
內容框架已改寫成自己的話，不逐句照搬對方文案／版面設計）。
個股財務數字另用 FinMind 官方申報逐筆核對過，跟原文能對照的地方
（統新上半年EPS、東典Q2毛利率）數字一致；另外查到原文沒提到的：
光環8月營收創歷史新高、聯一光8月營收YoY只有+0.9%。

跟散裝航運/月營收那兩份不同——**這份內容不是機密**（公開 IG 貼文），
所以這支腳本不用進 gitignore。內容已經同步整合進「矽光子/光通訊」
產業鏈深度報告（chain_reports_src/reports_data/silicon_photonics.json），
這份是給 Leo 自己看的獨立筆記版，存進 obis。

用法: python optical_filter_note.py
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                  # noqa: E402
from fundamentals_reality import _fm, _tw_quarterly            # noqa: E402

TITLE = "DWDM 薄膜濾光片"
SOURCE_COMMENT = "IG「股海小英雄」濾光片科普圖卡（10張），內容已改寫非逐句照搬"
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
.stk-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:13px 15px;margin:10px 0}
.stk-card .h{display:flex;gap:8px;align-items:baseline;margin-bottom:6px}
.stk-card b{font-size:15px;color:#93C5FD}
.stk-card .tag{font-size:11px;color:var(--dim);background:var(--card);
  padding:2px 8px;border-radius:6px}
.stk-card .num{font-family:'IBM Plex Mono',ui-monospace,monospace;
  font-variant-numeric:tabular-nums;color:var(--ink)}
.stk-card .up{color:var(--up)}.stk-card .hi{color:#F5B841;font-weight:700}
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
        rows = _tw_quarterly(code, n=1)
        q = rows[-1] if rows else None
    except Exception:                                           # noqa: BLE001
        pass
    time.sleep(0.2)
    return m, q


STOCKS = [
    ("6426", "統新", "核心：96通道/50GHz兩級濾波，DWDM薄膜濾光片主力廠",
     "50GHz窄門規格全球做得到的廠少，訂單能見度已拉長到4個月、客戶預付"
     "訂金，明年Q1新產線到位是下一個催化劑；風險是目前卡產能不是卡需求，"
     "高毛利仰賴高單價DWDM產品組合，比重若回落毛利率會跟著回落。"),
    ("6588", "東典", "核心：同賽道第二家，營收規模約統新四到五成",
     "享有同樣的DWDM窄門定價權邏輯，成長率高於統新但基期較低、"
     "獲利穩定性仍在追趕（今年Q1曾單季虧損）。"),
    ("3234", "光環", "鄰段：雷射光源供應商，DWDM/CPO光路上游元件",
     "8月營收創歷史單月新高（本篇FinMind核實，原始IG貼文未提及此數字），"
     "但營益率仍為負，已連3季收斂中。"),
    ("3441", "聯一光", "題材≠本業：光學玻璃毛胚廠，CPO題材推動股價",
     "8月營收YoY只有+0.9%——這個數字顯示近期股價翻倍主要是題材熱度，"
     "目前真實營收結構還沒跟上；公司自估CPO要到2027年才占營收約一成，"
     "近期實際成長動能來自既有車用/醫療玻璃本業＋歐洲光學大廠新訂單。"),
]


def _stock_card(code, name, role, comment, m, q):
    def _pct(v):
        return "—" if v is None else f'<span class="num up">{v:+.1f}%</span>'
    facts = []
    if m:
        hi = ' <span class="hi">★歷史單月新高</span>' if m["record_high"] else ""
        facts.append(f'<span class="num">{m["period"]} 營收 {m["revenue"]/1e8:,.2f}億</span>'
                     f'　YoY {_pct(m["yoy"])}{hi}')
    if q and q.get("gross_margin") is not None:
        facts.append(f'<span class="num">{q["period"]} 毛利率 {q["gross_margin"]:.1f}%</span>'
                     + (f'　營益率 <span class="num">{q["op_margin"]:.1f}%</span>'
                        if q.get("op_margin") is not None else "")
                     + (f'　EPS <span class="num">{q["eps"]}</span>'
                        if q.get("eps") is not None else ""))
    facts_html = "　｜　".join(facts) if facts else "（FinMind 查無資料）"
    return (f'<div class="stk-card"><div class="h"><b>{esc(name)}</b>'
           f'<span class="tag">{esc(code)}</span></div>'
           f'<div class="d">{esc(role)}</div>'
           f'<div class="d">{facts_html}</div>'
           f'<div class="d">{esc(comment)}</div></div>')


def build():
    rows = []
    for code, name, role, comment in STOCKS:
        m, q = fetch(code)
        rows.append(_stock_card(code, name, role, comment, m, q))

    sub = (esc(SOURCE_COMMENT) + "<br>個股數字另以 " + esc(SOURCE_DATA) + " 逐筆核對")

    body = []
    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒看懂</div>'
        '<p>AI 資料中心規模大到單一機房蓋不下，解法是拆成多座園區用光纖串連，'
        '一條光纖要同時傳很多路訊號（DWDM），關鍵元件是<b>薄膜濾光片（TFF）</b>'
        '——1.5mm玻璃鍍100~200層薄膜，靠光學共振分色。門開得越窄'
        '（50GHz/0.4nm）能做的廠越少，定價權越強、毛利率越高。跟 CPO'
        '（共同封裝光學）不是對手，是兩條不同的線：CPO解決機櫃內距離，'
        '這個解決的是資料中心之間的長距離。台股相關：<b>統新、東典</b>直接做'
        '濾光片，<b>前鼎、光環</b>在同一條光路上，<b>聯一光</b>則是題材熱度'
        '跑在營收數字前面。</p></div>')

    body.append('<div class="rpt-sec"><h2>技術背景</h2>'
        '<p>三種舊做法各卡一關：CWDM（粗分波）簡單但頻寬不夠，整條光譜塞不下'
        '18色以上；AWG（陣列波導光柵）怕溫度飄移，得靠恆溫供電；單一顏色'
        '一條光纖則是跨園區距離根本拉不起。新做法是50GHz薄膜濾光片＋兩級'
        '架構——不插電、不怕溫飄，且用「先寬門分段、段內再細分」的方式把'
        '最壞情況的訊號損耗次數從95次壓到18次。AWG不是被淘汰，是並存的'
        '另一條路線：玻璃濾光片贏在物理特性，難在良率控制（中心波長誤差要'
        '壓到±0.05nm等級）。</p>'
        '<p>製造門檻：窄門鍍膜（誤差±0.05nm）、15~20年電信級可靠度認證'
        '（Telcordia）、高階鍍膜設備客製化交期長、主要對手在中國但美系客戶'
        '去中化是台廠機會。目前瓶頸是產能不是需求，訂單能見度已拉長到4個月。'
        '</p></div>')

    body.append('<div class="rpt-sec"><h2>相關台股（已核對 FinMind 數字）</h2>'
        + "".join(rows) + '</div>')

    body.append('<div class="rpt-note">來源：' + esc(SOURCE_COMMENT) + '。'
        '財務數字來自 ' + esc(SOURCE_DATA) + '，查證時間 2026-09-16。'
        '個股資訊僅為產業鏈整理，非投資建議。'
        '<br>同一份內容已整合進「矽光子/光通訊」產業鏈深度報告。</div>')

    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS
            + "</style></head><body><div class=\"wrap\">"
            + header("rotation", TITLE, sub, [], eyebrow="INDUSTRY NOTE")
            + "".join(body) + "</div></body></html>")
    return html


def main():
    html = build()
    dst = op.archive("DWDM薄膜濾光片產業筆記.html")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")


if __name__ == "__main__":
    main()
