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

from board_theme import BASE_CSS, esc                       # noqa: E402

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
    """擋下來時回的東西。刻意跟一般 404 長一樣，不提示這裡有服務。"""
    return "<!doctype html><meta charset=utf-8><title>404</title><h1>404 Not Found</h1>"

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
.lk-form{display:flex;gap:8px;margin:14px 0 18px;flex-wrap:wrap}
.lk-form input{flex:1 1 200px;min-width:0;padding:10px 12px;border-radius:9px;
 border:1px solid #2a2e35;background:#12151b;color:#e8eaed;font-size:15px;font-family:inherit}
.lk-form button{padding:10px 18px;border-radius:9px;border:1px solid #2a2e35;
 background:#1a1d23;color:#93C5FD;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}
.lk-form button:hover{border-color:#4a9eff}
.lk-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:2px}
.lk-tk{font-size:26px;font-weight:800;color:#e8eaed}
.lk-nm{font-size:15px;color:#9aa0a6}
.lk-src{font-size:11px;color:#6b7280;margin-left:auto}
.lk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin:12px 0 4px}
.lk-c{background:#1a1d23;border:1px solid #2a2e35;border-radius:10px;padding:10px 12px}
.lk-k{font-size:10.5px;color:#6b7280;font-weight:600;letter-spacing:.3px}
.lk-v{font-size:17px;font-weight:700;color:#e8eaed;margin-top:3px}
.lk-s{font-size:11.5px;color:#9aa0a6;margin-top:2px}
.lk-lamps{font-size:19px;letter-spacing:2px}
.lk-note{font-size:12px;color:#6b7280;margin-top:14px;line-height:1.7;
 border-top:1px solid #16223A;padding-top:10px}
.lk-err{background:#1a1d23;border:1px solid #3a2a2a;border-radius:10px;padding:16px;
 color:#e8b4b4;font-size:14px;line-height:1.7}
"""


def _card(k, v, s=""):
    return (f'<div class="lk-c"><div class="lk-k">{esc(k)}</div>'
            f'<div class="lk-v">{v}</div><div class="lk-s">{s}</div></div>')


def _form(ticker=""):
    return (f'<form class="lk-form" method="get" action="/lookup">'
            f'<input name="ticker" value="{esc(ticker)}" placeholder="輸入代號：2454 / COST / BRK.B" '
            f'autocomplete="off" autocapitalize="characters">'
            f'<button type="submit">查</button></form>')


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
    return (
        '<div class="lk-grid">'
        + _card("現價", f"{price:,.2f}" if price is not None else "—",
                f"資料日 {esc(str(row.get('asof') or '—'))}")
        + _card("SuperTrend", st_v, st_s)
        + _card("四燈", f'<span class="lk-lamps">{lamp_str}</span>',
                f"{lit}/4　{esc(lamp_names)}")
        + _card("分析師共識目標價", tg_v, tg_s)
        + _card("風報比", rr_v, rr_s)
        + _card("RS60 乖離", rs_v, rs_s)
        + _card("類股象限（60日）", f"{qi} {ql}", q_s)
        + "</div>")


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
            + "<style>" + BASE_CSS + PAGE_CSS + ti_css + "</style></head><body>"
            "<div class=" + Q + "wrap" + Q + ">" + body + "</div></body></html>")


NOTE = (
    '<div class="lk-note">'
    '數字與 Discord <code>/查</code> 同一個來源（lamp_lookup），不會出現兩種說法。'
    '守備清單內走今日掃描快取、其餘即時計算（較慢）。<br>'
    '圖表：K線用雙重颱風三色、SuperTrend 黃多紫空，滾輪縮放、拖曳平移，四張圖連動。<br>'
    '⚠️ 這頁沒有「投顧目標價」與「3倍/4倍停損」——那是參考畫面裡該案例的客製分析，'
    '本系統沒有對應的通用資料源，不做假的欄位。'
    '</div>')


def render(ticker):
    """回 (html, status)。ticker 空字串就只給搜尋框。"""
    ticker = (ticker or "").strip()
    if not ticker:
        return _shell("查股", "<h1>查股</h1>" + _form() + NOTE), 200

    import lamp_lookup
    try:
        row = lamp_lookup.lookup(ticker)
    except Exception as e:                                  # noqa: BLE001
        body = ("<h1>查股</h1>" + _form(ticker)
                + f'<div class="lk-err">查詢時出錯：{esc(str(e)[:200])}</div>')
        return _shell("查股", body), 500
    if row is None:
        body = ("<h1>查股</h1>" + _form(ticker)
                + '<div class="lk-err">查無資料——代號打錯，或這檔資料量不足'
                  '（新掛牌／太冷門，算不出 60 日以上的指標）。</div>')
        return _shell("查股", body), 404

    # 技術面卡片＋四張圖。抓不到就整區省略，不要讓整頁掛掉——上面那排數字
    # 本身就有價值，沒必要因為圖畫不出來就什麼都不給。
    tech = ""
    try:
        import technical_indicators as ti
        tech = ti.build_html(row.get("symbol") or row["ticker"]) or ""
    except Exception as e:                                  # noqa: BLE001
        tech = (f'<div class="lk-err">技術面圖表產生失敗（上面的數字仍然有效）：'
                f'{esc(str(e)[:160])}</div>')

    name = esc(row.get("name") or "")
    src = "今日掃描快取" if row.get("src") == "cache" else "即時計算"
    head = (f'<div class="lk-head"><span class="lk-tk">{esc(row["ticker"])}</span>'
            f'<span class="lk-nm">{name}</span>'
            f'<span class="lk-src">{src}</span></div>')
    body = head + _form(ticker) + _summary(row) + tech + NOTE
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
