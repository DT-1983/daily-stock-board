# -*- coding: utf-8 -*-
"""任意股票的即時燈號 + RRG 象限查詢（2026-09-02，Leo：「進 discord 輸入某隻股票，
跑出 rrg 狀況跟燈號」）。

這支只負責「查一檔」，不管 Discord bot 本身怎麼接——bot 端還沒開始做（要先申請
Discord Bot Token、常駐監聽服務），這支先把核心邏輯做好、獨立可測試，bot 寫好後
直接呼叫 lookup() 就有結果，不用等 bot 架構定案才能開發這一半。

邏輯完全借用 combo_scan.py（同一套四燈判定、同一套象限對應），不重算第二份、
不會跟每日燈號頁的結果漂移：
  1) 先查 state/combo_result.json 今天的快取（守備清單/持股/自訂觀察 179 檔）——
     這些是每天 07:00 已經算好的，命中就秒回，不用再抓一次 yfinance。
  2) 沒命中（真正「任意」輸入的股票）才即時抓算，跟 combo_scan.scan_one() 同一條路，
     只是只算這一檔——由於要抓 3 年 OHLC + 大盤基準，實測約 3-8 秒，Discord bot
     那端要用非同步/先回覆「查詢中」再補發結果，不能當同步指令直接等。

用法（CLI 測試用，不牽涉 Discord）：
    python lamp_lookup.py 2454
    python lamp_lookup.py COST
"""
import re
import sys
import json
import os

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

import combo_scan as CS

RESULT_PATH = CS.RESULT_PATH
CACHE_MAX_AGE_DAYS = 4   # 跟 paper_portfolio.LAMP_MAX_AGE_DAYS 同標準——快取太舊就不用，直接即時算


def _norm(raw):
    """使用者輸入什麼都收：純數字（台股）、.TW/.TWO、美股代號、小寫。"""
    t = raw.strip().upper()
    if re.match(r"^\d{4,6}[A-Z]?$", t):
        return t   # 純數字台股代號，combo_scan._is_tw 認得，sym 由 tw_symbol.resolve 決定
    return t.replace(".", "-") if not t.endswith((".TW", ".TWO")) else t


def _from_cache(ticker):
    if not os.path.exists(RESULT_PATH):
        return None
    from datetime import date as _d
    d = json.load(open(RESULT_PATH, encoding="utf-8"))
    try:
        if (_d.today() - _d.fromisoformat(d["date"])).days > CACHE_MAX_AGE_DAYS:
            return None
    except Exception:                                   # noqa: BLE001
        return None
    for r in d["rows"]:
        if r["ticker"] == ticker:
            return r
    return None


def lookup(raw_ticker):
    """回一筆跟 combo_result.json 同格式的 dict（含 sector_zh/quad），查不到回 None。
    附加 "src": "cache" 或 "live" 供呼叫端判斷是不是秒回。"""
    ticker = _norm(raw_ticker)
    cached = _from_cache(ticker)
    if cached:
        cached = dict(cached)
        cached["src"] = "cache"
        return cached

    import price_store
    import tw_symbol
    is_tw = CS._is_tw(ticker)
    sym = tw_symbol.resolve(ticker) if is_tw else ticker
    bench = "^TWII" if is_tw else "^GSPC"
    closes = price_store.get_closes([bench], period="3y")
    b = closes.get(bench)
    if b is None or b.empty:
        return None
    ohlc = price_store.get_ohlc([sym], period="3y")
    df = ohlc.get(sym)
    if df is None or df.empty:
        return None
    row = CS.scan_one(ticker, sym, df, b.dropna().tolist())
    if row is None:
        return None
    row["name"] = None
    if is_tw:
        row["name"] = CS._tw_names().get(ticker)
    row["src_list"] = []   # 不在守備清單/持股/自訂清單裡——這是即時查詢，不進每日掃描母體
    tgt = CS.price_targets([ticker])
    CS.add_rr(row, tgt.get(ticker))
    CS.attach_sector([row])
    row["src"] = "live"
    return row


def format_discord(row):
    """轉成 Discord 訊息文字（跟 combo.html 同一套象限色標/燈號語意，emoji 版）。"""
    if row is None:
        return "查無資料——代號打錯，或這檔資料量不足（新掛牌/太冷門）。"
    lamps = row.get("lamps") or {}
    lamp_line = "".join("🟢" if v else "⚫" for v in lamps.values())
    rr = row.get("rr")
    if rr is None:
        rr_line = "風報比：無目標價"
    elif row.get("bull"):
        rr_line = f"風報比：{rr:.2f}" + ("　⭐打點成立" if row.get("combo") and rr >= 1 else "")
    else:
        gap = row.get("gap_pct")
        rr_line = f"（空方）站上 {row['st_line']:,.1f} 才翻多" + (f"（還要 {abs(gap):.1f}%）" if gap else "")
    quad = row.get("quad") or {}
    q60 = quad.get("60")
    QLAB = {"leading": "🔵領先", "improving": "🟢改善", "weakening": "🟡弱化", "lagging": "🔴落後"}
    quad_line = f"類股象限（60日）：{QLAB.get(q60, '—')}" + (f"（{row.get('sector_zh')}）" if row.get("sector_zh") else "")
    src_note = "（今日掃描快取）" if row.get("src") == "cache" else "（即時查詢）"
    name = row.get("name") or ""
    return (
        f"**{row['ticker']}** {name}\n"
        f"現價 {row.get('price')}　{'🔴多方' if row.get('bull') else '🟢空方'}\n"
        f"四燈 {lamp_line}（{row.get('lit')}/4）\n"
        f"{rr_line}\n"
        f"RS60 {row.get('rs_short')}%\n"
        f"{quad_line}\n"
        f"{src_note}"
    )


def main():
    if len(sys.argv) < 2:
        print("用法：python lamp_lookup.py <代號>　例：python lamp_lookup.py 2454")
        return 1
    row = lookup(sys.argv[1])
    print(json.dumps(row, ensure_ascii=False, indent=1) if row else "查無資料")
    print()
    print(format_discord(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
