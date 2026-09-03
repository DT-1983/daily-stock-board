# -*- coding: utf-8 -*-
"""查任意股票的視覺化頁面（2026-09-03，Leo：「可以做成像 html 的圖這樣嗎」）。

`/查` 這個 Discord 指令回的是純文字（燈號 emoji ＋一行數字）。這支把同一份查詢
結果畫成網頁：上面一排關鍵數字，下面接技術面卡片＋四張圖（K線/成交量/動能/RS）。

## 不重造輪子的兩個重用點

1. **數字來源＝`lamp_lookup.lookup()`**——跟 `/查` 完全同一支，所以網頁跟 Discord
   不可能給出不一樣的燈號。它自己會先查今日掃描快取（179 檔秒回），沒有才即時算。
2. **圖表＝`technical_indicators.build()`**——跟產業鏈看板／進出燈號頁／財報卡
   同一套產生器（9/2 才統一過蠟燭圖＋SuperTrend 配色＋縮放平移），版面不用重設計。

## 刻意沒做的：投顧目標價與 3倍/4倍停損

Leo 給的參考畫面（`Documents\\Investment\\8996_高力_3家券商共識.html`）左側有
「投顧目標 1500.00」「停損3倍/4倍」。**實查專案內沒有任何函式產生這些數字**
（grep `stop3`/`to_flip_pct` 全專案無；`trade_plan.supertrend_invalidation()` 只回
`st_bearish`/`rs60_broken`），那份是該案例的客製分析。所以這頁不畫那一塊——
沒有的功能不假裝有（見 [[feedback_no_false_product_claims]]）。

這頁能給的目標價是 `combo_scan.price_targets()` 的**市場共識**（yfinance
analyst_price_targets 均值），語意不同，所以標籤就寫「分析師共識目標價」，
不寫「投顧目標」。要真的做 ATR 倍數停損是另一個功能，而且倍數要 Leo 訂
（不自行發明投資門檻）。

## 掛在哪

掛在 `discord_bot.py` 已經常駐的 aiohttp server（127.0.0.1:8030）上，
路由 `/lookup?ticker=2454`。不另開服務——那支本來就有健康檢查端點在跑，
且已經掛進 `service_health_check.py` 自動重啟。

⚠️ 即時查一檔要抓 3 年 OHLC ＋算多組指標，實測比 `/查` 的 3-8 秒更久
（`technical_indicators.build()` 預設 disp_days=756）。守備清單內的走快取會快很多。

用法（不經 bot 也能單獨測）：
    python lookup_page.py 2454 -o out.html
"""
import io
import os
import sys
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from urllib.parse import quote as _q                        # noqa: E402

from board_theme import (BASE_CSS, LOOKUP_CSS, esc, header,   # noqa: E402
                         nav_abs)

Q = chr(34)

# ── 對外開放的門檻（2026-09-03，Leo 要手機能開）──────────────────────
# 這頁本身沒有個資（只有公開市場資料），但**每次查詢都會在 Leo 的電腦上抓 3 年
# 資料＋算指標**——完全不設防等於把運算資源開放給任何掃到這個網域的人。
#
# 作法：`?key=<LOOKUP_TOKEN>` 進來一次就種 90 天 cookie，之後手機直接開。
# 沒有 token 也沒有 cookie 一律回 **404**（不是 403）——403 等於告訴對方
# 「這裡有東西只是你沒權限」，404 什麼都不透露。
#
# `LOOKUP_TOKEN` 空白＝不設防。這是給「只在本機用、沒對外開」的情況；
# 服務本來就只綁 127.0.0.1，沒接 tunnel 的話外面連不到。
COOKIE = "lk"
COOKIE_DAYS = 90

# 健康檢查端點被外部打到時回這個——那個端點是給本機 service_health_check 用的，
# 對外沒有任何用途，所以維持「什麼都不透露」的乾 404（跟查股頁不同：查股頁的
# 入口已經公開寫在投資站上了，藏它只會害真正的使用者以為壞掉）。
BARE_404 = "<!doctype html><meta charset=utf-8><title>404</title><h1>404 Not Found</h1>"


def _token():
    from dotenv import dotenv_values
    here = os.path.dirname(os.path.abspath(__file__))
    return (dotenv_values(os.path.join(here, ".env")) or {}).get("LOOKUP_TOKEN", "") or ""


def gate(key, cookie_val):
    """回 (是否放行, 要不要種 cookie)。token 沒設就一律放行。"""
    tk = _token()
    if not tk:
        return True, False
    if key and key == tk:
        return True, True          # 帶對 key → 放行並種 cookie
    return (cookie_val == tk), False


def not_found_html():
    """擋下來時回的頁面。

    2026-09-03 改版：原本刻意回一個乾巴巴的 404「不提示這裡有服務」。但入口已經
    公開寫在投資站的燈號頁上了，**存在與否早就不是秘密**，藏它只會害真正的使用者
    以為壞掉——Leo 從手機點進來就是看到這個空白 404，回報「跑不出來」。
    真正的保護是 token 本身，不是隱藏。所以改成講清楚怎麼授權。

    ⚠️ 仍然**不顯示 token**（那是 .env 裡的東西），只說明去哪拿。
    """
    return (
        "<!doctype html><html lang=" + Q + "zh-Hant" + Q + "><head><meta charset=" + Q + "utf-8" + Q + ">"
        "<meta name=" + Q + "viewport" + Q + " content=" + Q + "width=device-width,initial-scale=1" + Q + ">"
        "<title>需要授權</title><style>" + BASE_CSS + PAGE_CSS +
        "body{padding:0}.wrap{max-width:560px}" + "</style></head><body><div class=" + Q + "wrap" + Q + ">"
        "<h1>🔒 這台裝置還沒授權</h1>"
        "<div class=" + Q + "lk-err" + Q + ">"
        "查股頁需要一次性授權，<b>每台裝置各授權一次</b>（手機、平板、桌機分開算），"
        "之後記住 90 天。<br><br>"
        "作法：用帶 <code>?key=</code> 的網址開一次這個頁面就好——"
        "那串 key 在 <code>daily_stock_analysis/.env</code> 的 <code>LOOKUP_TOKEN</code>，"
        "或直接問 Claude 要。<br><br>"
        "<span style=" + Q + "color:var(--muted);font-size:12.5px" + Q + ">"
        "為什麼要授權：這頁每次查詢都會在家裡那台電腦上抓三年資料、算指標。"
        "不設防的話任何掃到這個網域的人都能叫它算。</span>"
        "</div></div></body></html>")

# 缺任何一個圖表都畫不出來——technical_indicators 產的是「畫圖的程式碼」不是圖片。
# hammerjs 是 chartjs-plugin-zoom 的 peer dep，少了它滾輪縮放能動但**拖曳完全沒反應**
# （9/2 踩過，見 investment_site_ui_standard 記憶）。順序不能換。
CDN = [
    "https://cdn.jsdelivr.net/npm/chart.js@4",
    "https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js",
    "https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js",
    "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js",
]

QLAB = {"leading": ("🔵", "領先"), "improving": ("🟢", "改善"),
        "weakening": ("🟡", "弱化"), "lagging": ("🔴", "落後")}

PAGE_CSS = """
/* 2026-09-03 Leo：「查任意股風格不一致，請改成跟燈號風格一致」。
   原本這頁自己寫了一組灰褐色系（#1a1d23 / #2a2e35），跟投資站的深藍
   （--surface #0F172A / --line #1E293B）並排一看就是兩個網站。
   規則：**這頁不准出現寫死的色碼**，一律用 BASE_CSS 的變數；
   搜尋框直接沿用站上的 .lkbox（LOOKUP_CSS），兩邊必定一致。 */
.lk-form{margin:12px 0 16px}
.lk-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:14px 0 2px}
.lk-tk{font-size:26px;font-weight:800;color:var(--ink);
 font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums;letter-spacing:-.5px}
.lk-nm{font-size:15px;color:var(--muted)}
.lk-src{font-size:11.5px;color:var(--dim);margin-left:auto}
.lk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:12px 0 4px}
.lk-c{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.lk-k{font-size:10.5px;color:var(--dim);font-weight:600;letter-spacing:.3px}
.lk-v{font-size:18px;font-weight:700;color:var(--ink);margin-top:3px;line-height:1.25;
 font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums}
.lk-v.zh{font-family:inherit}          /* 「🟢 空方」這種中文值不要用等寬字 */
.lk-s{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.5}
.lk-lamps{font-size:19px;letter-spacing:2px}
.lk-note{font-size:12px;color:var(--dim);margin-top:18px;line-height:1.7;
 border-top:1px solid var(--line);padding-top:11px}
.lk-err{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--down);
 border-radius:10px;padding:15px 17px;color:#FCA5A5;font-size:13.5px;line-height:1.75;margin:12px 0}
.lk-rf{font-size:12.5px;color:#93C5FD;margin:2px 0 6px}
.lk-picks{display:flex;flex-direction:column;gap:7px;margin-top:10px}
.lk-pick{display:flex;gap:10px;align-items:baseline;padding:11px 13px;border-radius:9px;
 background:var(--surface);border:1px solid var(--line);text-decoration:none;color:var(--ink);
 transition:border-color .18s,background .18s}
.lk-pick:hover{border-color:var(--accent);background:#152238}
.lk-pick b{font-size:15px;color:#93C5FD}
.lk-pick span{font-size:12.5px;color:var(--muted)}
.bk{background:var(--surface);border:1px solid var(--line);border-radius:11px;
 padding:12px 14px;margin:14px 0}
.bk-h{font-size:13.5px;font-weight:700;color:#F5B841}
.bk-n{font-size:11.5px;font-weight:400;color:var(--dim)}
.bk-r{font-size:12.5px;color:var(--muted);line-height:1.7;padding:7px 0;
 border-top:1px solid var(--line)}
.bk-r b{color:var(--ink)}
.bk-t{font-family:'Fira Code',monospace;color:var(--ink);font-weight:700}
.bk-b{font-size:11.5px;color:var(--dim);margin-top:2px;line-height:1.6}
.bk-w{font-size:12px;color:#FCD34D;line-height:1.7;margin-top:7px}
.bk-up{color:var(--up);font-weight:600}
.bk-dn{color:var(--down);font-weight:600}
.bk-o{color:var(--dim);font-weight:400;font-size:11px}

/* 電腦版：7 張小卡排成一排（Leo 9/3）。board_theme 的 .wrap 是 1100px，
   7 張 minmax(150px) 只差幾像素塞不下就換行，變成 6+1 很難看。
   這頁本來就該比列表頁寬（有四張圖），所以連 .wrap 一起放寬。 */
@media(min-width:1180px){
  .wrap{max-width:1440px}
  .lk-grid{grid-template-columns:repeat(7,minmax(0,1fr))}
  .lk-c{padding:10px 11px}
  .lk-s{font-size:11px}
}
@media(min-width:900px) and (max-width:1179px){
  .lk-grid{grid-template-columns:repeat(4,minmax(0,1fr))}
}
"""


def _card(k, v, s="", zh=False):
    """zh=True 代表值是中文/文字（「🟢 空方」「🟡 弱化」），不套等寬數字字體——
    等寬字體是給數字對齊用的，套在中文上字距會很怪。"""
    return (f'<div class="lk-c"><div class="lk-k">{esc(k)}</div>'
            f'<div class="lk-v{" zh" if zh else ""}">{v}</div>'
            f'<div class="lk-s">{s}</div></div>')


def _form(ticker=""):
    """搜尋框＝投資站首頁／進出燈號頁上那一顆（board_theme 的 .lkbox），
    只是 action 指回自己。兩邊各寫一份必然會漂移，所以連 class 都沿用。"""
    return (f'<form class="lkbox lk-form" method="get" action="/lookup">'
            f'<span class="lkl">🔍 查任意股票</span>'
            f'<input name="ticker" value="{esc(ticker)}" '
            f'placeholder="代號或名稱：2454 / 台積電 / COST" '
            f'autocomplete="off" autocapitalize="characters">'
            f'<button type="submit">查燈號＋圖表</button></form>')


def _summary(row):
    """上排關鍵數字。每個欄位都直接來自 lookup() 的結果，不另外算第二份。"""
    lamps = row.get("lamps") or {}
    lit = row.get("lit")
    lamp_str = "".join("🟢" if v else "⚫" for v in lamps.values())
    lamp_names = "／".join(k.split(" ", 1)[-1] for k in lamps)

    bull = row.get("bull")
    st_line = row.get("st_line")
    gap = row.get("gap_pct")
    if bull:
        st_v, st_s = "🔴 多方", (f"停損參考線 {st_line:,.2f}"
                                 + (f"（現價高於 {gap:+.1f}%）" if gap is not None else ""))
    else:
        # ⚠️ 空方時那條線是壓力不是停損——語意不同，標籤要分開講（同 combo_scan 的處理）
        st_v, st_s = "🟢 空方", (f"站上 {st_line:,.2f} 才翻多"
                                 + (f"（還要 {abs(gap):.1f}%）" if gap is not None else ""))

    tgt, rr = row.get("target"), row.get("rr")
    if tgt is None:
        tg_v, tg_s = "—", "查無分析師共識目標價"
    else:
        lo, hi = row.get("target_low"), row.get("target_high")
        rng = f"區間 {lo:,.0f}–{hi:,.0f}" if lo and hi else ""
        tg_v = f"{tgt:,.2f}"
        up = (tgt - row["price"]) / row["price"] * 100 if row.get("price") else None
        tg_s = (f"距現價 {up:+.1f}%　{rng}" if up is not None else rng)

    rr_v = f"{rr:.2f}" if rr is not None else "—"
    rr_s = ("⭐ 打點成立（≥3燈且風報比≥1）" if row.get("combo") and rr and rr >= 1
            else ("空方不計風報比" if not bull else "無目標價則不計"))

    rs = row.get("rs_short")
    rs_v = f"{rs:+.2f}%" if rs is not None else "—"
    rs_s = ("高於自身 60 日均線" if rs and rs > 0 else
            "低於自身 60 日均線" if rs is not None else "")

    quad = (row.get("quad") or {}).get("60")
    qi, ql = QLAB.get(quad, ("—", "無對應類股"))
    q_s = esc(row.get("sector_zh") or "") or "類股未對應到輪動圖"

    price = row.get("price")
    # 資料日提示：**掃描是早上 07:00 跑的，當天還沒收盤**，所以快取拿到的一定是
    # 前一個交易日的收盤——跟看盤軟體的即時報價天生差一天。落後兩天以上（假日除外）
    # 通常代表那一檔在 yfinance 缺資料，要明講而不是讓人自己發現數字對不上。
    asof = str(row.get("asof") or "")
    days = _stale_days(asof)
    sub = f"資料日 {esc(asof or '—')}"
    if days is not None and days >= 2:
        sub += f'　<span style="color:#EAB308">⚠️ 落後 {days} 天</span>'
    return (
        '<div class="lk-grid">'
        + _card("現價", f"{price:,.2f}" if price is not None else "—", sub)
        + _card("SuperTrend", st_v, st_s, zh=True)
        + _card("四燈", f'<span class="lk-lamps">{lamp_str}</span>',
                f"{lit}/4　{esc(lamp_names)}", zh=True)
        + _card("分析師共識目標價", tg_v, tg_s)
        + _card("風報比", rr_v, rr_s)
        + _card("RS60 乖離", rs_v, rs_s)
        + _card("類股象限（60日）", f"{qi} {ql}", q_s, zh=True)
        + "</div>")



def _broker(row):
    """券商研究報告卡（2026-09-03）。

    ⚠️ 為什麼放在查股頁：Leo 問「這個是要幹嘛？投資長會看到嗎？個股資訊看得到嗎？」
    ——原本兩個都看不到，那份資料就會是沒人經過的死路（同
    tide_learnings_and_chip_layer 的「覆蓋擴大≠決策增益」）。
    所以接了兩個真正會被走到的出口：投資長的判斷材料、以及這裡。

    這頁本來只有「分析師共識目標價」（yfinance 的一個平均數）。券商報告多的是
    **推導過程**——同一檔不同家用不同倍數、不同年份 EPS，答案可以差三成。
    """
    try:
        import advisor_reports
        store = advisor_reports._load(advisor_reports.STORE, {}) or {}
    except Exception:                                       # noqa: BLE001
        return ""
    import re as _re
    want = _re.sub(r"\.(TW|TWO)$", "", str(row.get("ticker", "")).upper()).replace(".", "-")
    rs = [r for r in store.values()
          if str(r.get("ticker", "")).upper().replace(".", "-") == want
          and not r.get("_notreport")]
    if not rs:
        return ""
    # 已被同一家新版取代的舊報告仍然顯示，但標明「已被取代」——目標價的調整軌跡
    # 本身有資訊（國泰金 93 → 117），只是不該再拿它的假設當現行判斷。
    rs.sort(key=lambda r: str(r.get("date")), reverse=True)
    px = row.get("price")
    items = []
    for r in rs:
        tg = r.get("target")
        up = f"（距現價 {(tg / px - 1) * 100:+.1f}%）" if tg and px else ""
        # 目標價調升/調降軌跡
        tp = r.get("target_prev")
        mv = ""
        if tg and tp:
            d = (tg / tp - 1) * 100
            mv = (f'　<span class="bk-{"up" if d > 0 else "dn"}">'
                  f'{"↑調升" if d > 0 else "↓調降"} {abs(d):.0f}%（前次 {tp:,.0f}）</span>')
        old = ('　<span class="bk-o">已被同一家新版取代</span>'
               if r.get("_superseded_by") else "")
        head_ = (f'<b>{esc(r.get("broker"))}</b>　{esc(r.get("date"))}　'
                 f'{esc(r.get("rating") or "無評等")}　'
                 + (f'目標 <span class="bk-t">{tg:,.0f}</span>{esc(up)}'
                    if tg else "無目標價（Note 類）") + mv + old)
        basis = (f'<div class="bk-b">依據：{esc(r["valuation_basis"])}</div>'
                 if r.get("valuation_basis") else "")
        # 估值前提檢查：市場現在給幾倍 vs 報告假設幾倍
        vm = ""
        try:
            im = advisor_reports.implied_multiple(r, px)
            if im:
                now, want_, how = im
                kind = (r.get("valuation_kind") or "").upper()
                cls = "bk-dn" if now >= want_ else "bk-up"
                vm = (f'<div class="bk-b">估值前提：市場現在給 '
                      f'<span class="{cls}">{now:.1f} 倍{esc(kind)}</span>，'
                      f'報告假設 {want_:.1f} 倍'
                      + (f'——<b>前提已用完</b>' if now >= want_
                         else f'（還差 {(want_ / now - 1) * 100:.0f}%）')
                      + f'　<span class="bk-o">{esc(how)}</span></div>')
        except Exception:                                   # noqa: BLE001
            pass
        thesis = (f'<div class="bk-b">論點：{esc(r["thesis"])}</div>'
                  if r.get("thesis") else "")
        risks = (f'<div class="bk-b">報告自列風險：{esc("、".join(r["risks"]))}</div>'
                 if r.get("risks") else "")
        items.append(f'<div class="bk-r">{head_}{basis}{vm}{thesis}{risks}</div>')
    warn = ""
    tgs = [r["target"] for r in rs if r.get("target")]
    if len(rs) >= 3 and len(tgs) >= 2:
        warn = (f'<div class="bk-w">⚠️ {len(rs)} 家券商同時出報告，目標價 '
                f'{min(tgs):,.0f}～{max(tgs):,.0f}（差 {(max(tgs) / min(tgs) - 1) * 100:.0f}%）'
                f'——差異多半來自<b>倍數與用哪一年 EPS</b>，不是基本面。'
                f'多家同時推代表這個看法已經擁擠。</div>')
    return (f'<div class="bk"><div class="bk-h">券商研究報告　'
            f'<span class="bk-n">{len(rs)} 份，各家自己的推導，不是市場共識平均</span>'
            f'</div>{warn}{"".join(items)}</div>')


def _shell(title, body):
    scripts = "".join(f'<script src={Q}{u}{Q}></script>' for u in CDN)
    try:
        import technical_indicators as ti
        ti_css = ti.CSS
    except Exception:                                       # noqa: BLE001
        ti_css = ""
    return ("<!doctype html><html lang=" + Q + "zh-Hant" + Q + "><head><meta charset=" + Q + "utf-8" + Q + ">"
            "<meta name=" + Q + "viewport" + Q + " content=" + Q
            + "width=device-width,initial-scale=1" + Q + ">"
            f"<title>{esc(title)}</title>" + scripts
            + "<style>" + BASE_CSS + LOOKUP_CSS + PAGE_CSS + ti_css
            + "</style></head><body>"
            "<div class=" + Q + "wrap" + Q + ">" + _HEADER + body + "</div></body></html>")


# 頁首＝全站共用的 board_theme.header()，導覽列用 nav_abs()（絕對網址）——
# 這頁跑在 stock.talentxtrend.com，用 NAV 的相對路徑會連到自己那台的
# /combo.html（不存在）。current=None：這頁不在 NAV 裡，不亮任何一顆。
_HEADER = header(
    "search", "查任意股票",
    "不限掃描母體 · 燈號與 <b>Discord /查</b> 同一個來源 · 台股可打中文名",
    nav_abs())


NOTE = (
    '<div class="lk-note">'
    '數字與 Discord <code>/查</code> 同一個來源（lamp_lookup），不會出現兩種說法。'
    '守備清單內走今日掃描快取、其餘即時計算（較慢）。<br>'
    '圖表：K線用雙重颱風三色、SuperTrend 黃多紫空，滾輪縮放、拖曳平移，四張圖連動。<br>'
    '⚠️ 這頁沒有「投顧目標價」與「3倍/4倍停損」——那是參考畫面裡該案例的客製分析，'
    '本系統沒有對應的通用資料源，不做假的欄位。'
    '</div>')


def _tw_by_name(q):
    """中文公司名 → 台股代號。用 `combo_scan._tw_names()`（證交所＋櫃買的官方中文名），
    不另外接查詢服務——那份資料本來就在，而且 Yahoo 的搜尋對中文幾乎查不到
    （實測「台積電」回空清單）。

    先找完全相同，再找包含（「台積」也要找得到台積電）。
    """
    try:
        import combo_scan as CS
        names = CS._tw_names() or {}
    except Exception:                                       # noqa: BLE001
        return []
    q = q.strip()
    exact = [(c, n) for c, n in names.items() if n == q]
    if exact:
        return exact[:5]
    return [(c, n) for c, n in names.items() if q and q in n][:5]


def resolve(q):
    """輸入 → 候選 [(代號, 顯示名)]。輸入本來就是代號時回空清單（不用解析）。

    ⚠️ **解析出來的結果一定要顯示給使用者看**（「P&G → PG」），不能安靜地換一檔
    然後把數字端上去——那會變成「看起來查了 A、其實給你 B 的數字」。

    實測（2026-09-03）Yahoo 搜尋的能力邊界：`Procter Gamble`／`apple`／`AT&T`／
    `Johnson & Johnson` 都查得到；**`P&G` 這種太短的縮寫查不到**（回一堆匯率/期貨）；
    中文名一律查不到 → 中文走本地 `_tw_names()`。
    """
    q = (q or "").strip()
    if not q:
        return []
    # 中文（含任何非 ASCII）先走本地台股名冊
    if any(ord(c) > 127 for c in q):
        return _tw_by_name(q)
    try:
        import yfinance as yf
        quotes = yf.Search(q, max_results=8).quotes or []
    except Exception:                                       # noqa: BLE001
        return []
    out = []
    for x in quotes:
        if x.get("quoteType") not in ("EQUITY", "ETF"):
            continue                                        # 排掉匯率/期貨/指數
        sym = x.get("symbol")
        nm = (x.get("shortname") or x.get("longname") or "").strip()
        if sym:
            out.append((sym, nm))
    return out[:5]


def _pick_list(q, cands):
    items = "".join(
        f'<a class="lk-pick" href="/lookup?ticker={esc(c)}">'
        f'<b>{esc(c)}</b> <span>{esc(n)}</span></a>' for c, n in cands)
    return (f'<div class="lk-err">「{esc(q)}」看起來是公司名不是代號。'
            f'你要查哪一檔？</div><div class="lk-picks">{items}</div>')


def _stale_days(asof):
    """資料日距今幾個「日曆天」。只做粗略提示，不算交易日——分不出假日不影響
    「這個數字是不是今天的」這個判斷。"""
    import datetime as _dt
    try:
        return (_dt.date.today() - _dt.date.fromisoformat(str(asof)[:10])).days
    except Exception:                                       # noqa: BLE001
        return None


def render(ticker, live=False):
    """回 (html, status)。ticker 空字串就只給搜尋框。live=True 跳過快取即時算。"""
    ticker = (ticker or "").strip()
    if not ticker:
        return _shell("查股", _form() + NOTE), 200

    import lamp_lookup
    try:
        row = lamp_lookup.lookup(ticker, live=live)
    except Exception as e:                                  # noqa: BLE001
        body = (_form(ticker)
                + f'<div class="lk-err">查詢時出錯：{esc(str(e)[:200])}</div>')
        return _shell("查股", body), 500
    if row is None:
        # 當成代號查不到 → 可能本來就是打公司名（Leo 實際輸入過 "P&G"）。
        # 找得到唯一一檔就直接查它並在畫面上標明換算過；多檔就讓人自己選。
        cands = resolve(ticker)
        if len(cands) == 1:
            sym = cands[0][0]
            try:
                row = lamp_lookup.lookup(sym)
            except Exception:                               # noqa: BLE001
                row = None
            if row is not None:
                row["_resolved_from"] = f"{ticker} → {sym}　{cands[0][1]}"
        elif len(cands) > 1:
            return _shell("查股", _form(ticker)
                          + _pick_list(ticker, cands)), 200
    if row is None:
        body = (_form(ticker)
                + '<div class="lk-err">查無資料——代號或公司名查不到。<br>'
                  '· 美股請用代號或完整公司名（<b>P&amp;G 這種縮寫查不到，請打 PG '
                  '或 Procter Gamble</b>）<br>'
                  '· 台股可以直接打中文名（台積電）或代號（2330）<br>'
                  '· 也可能是新掛牌／太冷門，算不出 60 日以上的指標</div>')
        return _shell("查股", body), 404

    # 技術面卡片＋四張圖。抓不到就整區省略，不要讓整頁掛掉——上面那排數字
    # 本身就有價值，沒必要因為圖畫不出來就什麼都不給。
    tech = ""
    try:
        import technical_indicators as ti
        # expanded=True：這頁一次只有一檔，收放鈕只是多一次點擊（Leo 9/3）
        tech = ti.build_html(row.get("symbol") or row["ticker"], expanded=True) or ""
    except Exception as e:                                  # noqa: BLE001
        tech = (f'<div class="lk-err">技術面圖表產生失敗（上面的數字仍然有效）：'
                f'{esc(str(e)[:160])}</div>')

    name = esc(row.get("name") or "")
    if row.get("src") == "cache":
        # 快取＝今天早上 07:00 掃的，內容是前一交易日收盤。給一個強制即時重算的入口，
        # 否則使用者對照看盤軟體發現數字不一樣時，沒有辦法自己確認是不是資料舊了。
        src = ('今日掃描快取（前一交易日收盤）　'
               f'<a href="/lookup?ticker={_q(row["ticker"])}&amp;live=1" '
               'style="color:#93C5FD">🔄 即時重算</a>')
    else:
        src = "即時計算"
    # 有做過名稱→代號的換算就一定要講，不能安靜地端出另一檔的數字
    rf = row.get("_resolved_from")
    rf_html = f'<div class="lk-rf">🔁 {esc(rf)}</div>' if rf else ""
    head = (f'<div class="lk-head"><span class="lk-tk">{esc(row["ticker"])}</span>'
            f'<span class="lk-nm">{name}</span>'
            f'<span class="lk-src">{src}</span></div>' + rf_html)
    # 搜尋框擺在標的名稱**之前**：這頁的第一動作是查下一檔，
    # 跟進出燈號頁「工具列在上、內容在下」的節奏一致。
    body = _form(ticker) + head + _summary(row) + _broker(row) + tech + NOTE
    return _shell(f'{row["ticker"]} 查股', body), 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?", default="")
    ap.add_argument("-o", "--output", default="")
    a = ap.parse_args()
    html, status = render(a.ticker)
    if a.output:
        io.open(a.output, "w", encoding="utf-8").write(html)
        print(f"status={status}　寫入 {a.output}（{len(html):,} bytes）")
    else:
        print(f"status={status}　{len(html):,} bytes（用 -o 指定輸出檔）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
