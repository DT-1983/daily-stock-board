# -*- coding: utf-8 -*-
"""台指期夜盤（電子盤）收盤——期交所開放資料，免費、免金鑰、零 AI。

2026-10-02 Leo：美國非農公布後電子盤直接噴一波，問「有在監查嗎」→ 完全沒有。
這支把「前一晚電子盤收在哪、漲跌多少」放進 08:45 戰情 ① 當台股開盤前的參考。

資料：openapi.taifex.com.tw/v1/DailyMarketReportFut（期貨每日行情，含「一般」「盤後」兩個交易時段）
  · 盤後時段＝夜盤（歸屬交易日 D，15:00 開到 D+1 05:00）；期交所收盤後才彙整，**不是即時**。
  · 取臺指期（TX）、成交量最大的月份合約（近月，排除週選）的盤後列；漲跌用期交所自己給的欄位。
⚠️ 日期要標在訊息上：資料沒更新時不會把舊的當成昨晚的（超過 4 天直接不顯示並印警告）。
"""
import datetime as dt
import sys

URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
ALERT_PCT = 1.5          # 夜盤漲跌超過這個幅度就特別標出來（只是「看得見」，不是交易訊號）


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def fetch():
    """回 {date:'YYYYMMDD', month, last, change, pct, volume}；取不到回 None（會印原因，不靜默）。"""
    import requests
    try:
        r = requests.get(URL, headers={"accept": "application/json"}, timeout=40)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:                                   # noqa: BLE001
        print(f"[night] 期交所資料取得失敗：{str(e)[:80]}")
        return None
    tx = [x for x in rows
          if x.get("Contract") == "TX" and "盤後" in str(x.get("TradingSession", ""))
          and str(x.get("ContractMonth(Week)", "")).isdigit() and len(str(x["ContractMonth(Week)"])) == 6
          and _num(x.get("Last")) is not None]
    if not tx:
        print("[night] 期交所資料裡沒有台指期盤後列（可能還沒彙整）")
        return None
    d = max(x["Date"] for x in tx)
    cand = [x for x in tx if x["Date"] == d]
    x = max(cand, key=lambda r: _num(r.get("Volume")) or 0)
    pct = _num(str(x.get("%", "")).replace("%", ""))
    return {"date": d, "month": x["ContractMonth(Week)"], "last": _num(x["Last"]),
            "change": _num(x.get("Change")), "pct": pct, "volume": _num(x.get("Volume"))}


def summary_line(today=None):
    """給戰情 ① 用的一行；取不到或資料太舊回空字串（原因已印在 log）。"""
    t = dt.date.fromisoformat(today) if today else dt.date.today()
    s = fetch()
    if not s:
        return ""
    d = dt.datetime.strptime(s["date"], "%Y%m%d").date()
    if (t - d).days > 4:
        print(f"[night] 最新夜盤資料是 {d}，距今超過 4 天，不顯示")
        return ""
    end = d + dt.timedelta(days=1)                            # 夜盤跨日，05:00 收
    # 預期的最新一場＝今天之前最近的平日（週一早上＝上週五夜盤）；比它舊代表期交所還沒彙整較新的，
    # 要講出來，不然會把前天的夜盤當成昨晚的。（國定假日會誤報，所以語氣只寫「最新只到」，不下結論。）
    exp = t - dt.timedelta(days=1)
    while exp.weekday() >= 5:
        exp -= dt.timedelta(days=1)
    stale = f"　⚠️ 期交所資料最新只到 {d:%m/%d}，較新的夜盤還沒彙整" if d < exp else ""
    if s["pct"] is None or s["change"] is None:
        return f"🌙 **台指電子盤**（{d:%m/%d} 15:00～{end:%m/%d} 05:00）收 {s['last']:,.0f}{stale}"
    arrow = "🔺" if s["pct"] > 0 else ("🔻" if s["pct"] < 0 else "▪️")
    flag = "　⚠️ 幅度大" if abs(s["pct"]) >= ALERT_PCT else ""
    return (f"🌙 **台指電子盤**　收 {s['last']:,.0f}　{arrow}{s['change']:+,.0f}（{s['pct']:+.2f}%）{flag}{stale}"
            f"　-# {d:%m/%d} 15:00～{end:%m/%d} 05:00 夜盤・期交所收盤後彙整、非即時・不是買賣訊號")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    print(fetch())
    print(summary_line())
