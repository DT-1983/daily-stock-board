# -*- coding: utf-8 -*-
"""台指期夜盤（電子盤）收盤——期交所開放資料，免費、免金鑰、零 AI。

2026-10-02 Leo：美國非農公布後電子盤直接噴一波，問「有在監查嗎」→ 完全沒有。
這支把「前一晚電子盤收在哪、漲跌多少」放進 08:45 戰情 ① 當台股開盤前的參考。

資料：openapi.taifex.com.tw/v1/DailyMarketReportFut（期貨每日行情，含「一般」「盤後」兩個交易時段）
  · 🔴 2026-10-09 更正：「盤後」列的日期 D＝這一晚**歸屬**的交易日，夜盤是「前一個交易日 15:00 → D 的 05:00」，
    不是「D 15:00 → D+1 05:00」。所以 OpenAPI 的最新檔永遠比「昨晚」少一晚。
    現在主要用 latest_night()（逐筆成交檔，夜盤收完約 05:10 就有），OpenAPI 只當備援。
  · 取臺指期（TX）、成交量最大的月份合約（近月，排除週選）的盤後列；漲跌用期交所自己給的欄位。

🔴 2026-10-04 實測：**同一個網址的回傳格式會變**——10/2 晚上是 JSON（英文欄名），10/4 變成 CSV（中文欄名，
   Content-Type 是 application/octet-stream）。原本只認 JSON，週一早上會靜默失敗、那一行直接消失。
   現在兩種格式都吃（欄名對照表 _KEYS），取不到時**戰情裡會明講「這次取不到」**，不再靜默略過。
⚠️ 日期要標在訊息上：資料沒更新時不會把舊的當成昨晚的（超過 4 天直接不顯示並印警告）。
"""
import csv
import datetime as dt
import io
import json
import sys

URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
ALERT_PCT = 1.5          # 夜盤漲跌超過這個幅度就特別標出來（只是「看得見」，不是交易訊號）
# 兩種格式的欄名對照（英文＝JSON、中文＝CSV）
_KEYS = {
    "date": ("Date", "日期"),
    "contract": ("Contract", "契約代號"),
    "month": ("ContractMonth(Week)", "到期月份(週別)"),
    "last": ("Last", "最後成交價"),
    "change": ("Change", "漲跌價"),
    "pct": ("%", "漲跌%"),
    "volume": ("Volume", "合計成交量"),
    "session": ("TradingSession", "交易時段"),
}


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def _get(row, name):
    for k in _KEYS[name]:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return ""


def _load_rows(raw):
    """原始回應 → list[dict]。JSON 或 CSV 都吃；認不得就丟例外（呼叫端會印出來）。"""
    txt = raw.decode("utf-8-sig", "replace") if isinstance(raw, bytes) else raw
    head = txt.lstrip()[:1]
    if head in ("[", "{"):
        data = json.loads(txt)
        return data if isinstance(data, list) else data.get("data", [])
    rows = list(csv.DictReader(io.StringIO(txt)))
    if not rows or not any(k in rows[0] for names in _KEYS.values() for k in names):
        raise ValueError("回傳既不是 JSON 也不是認得的 CSV（前 80 字：%r）" % txt[:80])
    return rows


def fetch(error_out=None):
    """回 {date:'YYYYMMDD', month, last, change, pct, volume}；取不到回 None（會印原因，不靜默）。
    error_out：給一個 list 就把失敗原因（一句話）放進去，讓呼叫端能在訊息裡明講。"""
    import requests
    err = ""
    rows = None
    for _ in range(2):                                        # 失敗重試一次
        try:
            r = requests.get(URL, headers={"accept": "application/json"}, timeout=40)
            r.raise_for_status()
            rows = _load_rows(r.content)
            break
        except Exception as e:                                # noqa: BLE001
            err = str(e)[:100]
    if rows is None:
        print(f"[night] 期交所資料取得失敗：{err}")
        if error_out is not None:
            error_out.append(f"期交所資料取得失敗（{err}）")
        return None
    tx = [x for x in rows
          if _get(x, "contract") == "TX" and "盤後" in _get(x, "session")
          and _get(x, "month").isdigit() and len(_get(x, "month")) == 6
          and _num(_get(x, "last")) is not None]
    if not tx:
        print("[night] 期交所資料裡沒有台指期盤後列（可能還沒彙整）")
        if error_out is not None:
            error_out.append("期交所資料裡還沒有台指期盤後列")
        return None
    d = max(_get(x, "date") for x in tx)
    cand = [x for x in tx if _get(x, "date") == d]
    x = max(cand, key=lambda r: _num(_get(r, "volume")) or 0)
    return {"date": d, "month": _get(x, "month"), "last": _num(_get(x, "last")),
            "change": _num(_get(x, "change")), "pct": _num(_get(x, "pct")), "volume": _num(_get(x, "volume"))}


def _night_ticks(raw):
    """逐筆成交 → 這個檔裡屬於「夜盤」的成交（15:00～隔天 05:00），依時間排序；(月份, [(日期, 時間, 價, 量)])。"""
    import gex_bars
    mo, ticks = gex_bars._ticks(raw)
    night = [t for t in ticks if t[1] >= "150000" or t[1] < "050100"]
    night.sort(key=lambda t: (t[0], t[1]))
    return mo, night


def latest_night(today=None):
    """🔴 2026-10-09 更正：**最新一晚夜盤**要從「下一個交易日」的逐筆成交檔算。
    期交所把夜盤歸屬在它「之後」的那個日盤——例如 10/12（週一）的檔案裡有 10/8 15:00～10/9 05:00 那一晚
    （檔案在夜盤收完後約 05:10 就出現，比 OpenAPI 檔早很多）。
    舊版用 OpenAPI 的「盤後」列，永遠是『前一個日盤之前那一晚』，早上看到的比昨晚少一晚。
    回 {start,end,open,high,low,last,base,change,pct}；base＝前一個交易日日盤收盤（最後一筆日盤成交）。
    任何一步失敗就丟例外，由呼叫端退回舊做法並標明。"""
    import gex_bars
    t = today or dt.date.today()
    got = None
    for k in range(0, 6):                                  # 先往後找（今天、假日後的第一個交易日）
        d = t + dt.timedelta(days=k)
        if d.weekday() >= 5:
            continue
        raw = gex_bars._download(d)
        if raw:
            mo, night = _night_ticks(raw)
            if night:
                got = (d, night)
                break
    if not got:
        raise RuntimeError("找不到最新一晚的逐筆成交檔")
    d, night = got
    base = None
    for j in range(1, 8):                                  # 前一個交易日的日盤收盤
        p = d - dt.timedelta(days=j)
        if p.weekday() >= 5:
            continue
        raw = gex_bars._download(p)
        if raw:
            _, ticks = gex_bars._ticks(raw)
            day = sorted((x for x in ticks if x[0] == p.strftime("%Y%m%d") and "084500" <= x[1] <= "134500"),
                         key=lambda x: x[1])
            if day:
                base = day[-1][2]
                break
    if base is None:
        raise RuntimeError("找不到前一個交易日的日盤收盤價")
    px = [x[2] for x in night]
    last = night[-1][2]
    return {"date": d.strftime("%Y%m%d"), "start": dt.datetime.strptime(night[0][0], "%Y%m%d").date(),
            "end": dt.datetime.strptime(night[-1][0], "%Y%m%d").date(),
            "open": night[0][2], "high": max(px), "low": min(px), "last": last, "base": base,
            "change": last - base, "pct": (last - base) / base * 100}


def summary_line(today=None):
    try:
        n = latest_night(dt.date.fromisoformat(today) if today else None)
        arrow = "🔺" if n["pct"] > 0 else ("🔻" if n["pct"] < 0 else "▪️")
        flag = "　⚠️ 幅度大" if abs(n["pct"]) >= ALERT_PCT else ""
        return (f"🌙 **台指電子盤**　收 {n['last']:,.0f}　{arrow}{n['change']:+,.0f}（{n['pct']:+.2f}%，較日盤收盤 {n['base']:,.0f}）{flag}"
                f"\n-# {n['start']:%m/%d} 15:00～{n['end']:%m/%d} 05:00 夜盤・高 {n['high']:,.0f} 低 {n['low']:,.0f}・期交所逐筆成交、非即時・不是買賣訊號")
    except Exception as e:  # noqa: BLE001
        print(f"[night] 逐筆成交法失敗，改用 OpenAPI（會少一晚）：{str(e)[:80]}")
        line = _summary_line_openapi(today)
        return line + "\n-# ⚠️ 這是較舊的一晚（逐筆資料這次取不到），實際最新一晚可能已不同"


def _summary_line_openapi(today=None):
    """給戰情 ① 用的一行。取不到時回一行「⚠️ 這次取不到」（不再回空字串靜默消失）；
    資料超過 4 天沒更新也明講；沒有資料需求（例如純測試）時呼叫端自己處理。"""
    t = dt.date.fromisoformat(today) if today else dt.date.today()
    why = []
    s = fetch(why)
    if not s:
        return "⚠️ **台指電子盤**：這次取不到——%s" % (why[0] if why else "原因不明")
    d = dt.datetime.strptime(s["date"], "%Y%m%d").date()
    if (t - d).days > 4:
        print(f"[night] 最新夜盤資料是 {d}，距今超過 4 天，不顯示")
        return "⚠️ **台指電子盤**：期交所最新夜盤資料只到 %s（距今超過 4 天），不顯示數字" % d.strftime("%m/%d")
    # 2026-10-09 更正：OpenAPI「盤後」列的日期 d＝這一晚歸屬的交易日，夜盤是「前一個交易日 15:00 → d 的 05:00」
    # （原本寫成 d 15:00 → d+1 05:00，差一天）。假日無法從這份資料得知，前一個交易日只用週末推算。
    end = d
    start = d - dt.timedelta(days=1)
    while start.weekday() >= 5:
        start -= dt.timedelta(days=1)
    # 預期的最新一場＝今天之前最近的平日（週一早上＝上週五夜盤）；比它舊代表期交所還沒彙整較新的，
    # 要講出來，不然會把前天的夜盤當成昨晚的。（國定假日會誤報，所以語氣只寫「最新只到」，不下結論。）
    exp = t - dt.timedelta(days=1)
    while exp.weekday() >= 5:
        exp -= dt.timedelta(days=1)
    stale = f"　⚠️ 期交所資料最新只到 {d:%m/%d}，較新的夜盤還沒彙整" if d < exp else ""
    if s["pct"] is None or s["change"] is None:
        return f"🌙 **台指電子盤**（{start:%m/%d} 15:00～{end:%m/%d} 05:00）收 {s['last']:,.0f}{stale}"
    arrow = "🔺" if s["pct"] > 0 else ("🔻" if s["pct"] < 0 else "▪️")
    flag = "　⚠️ 幅度大" if abs(s["pct"]) >= ALERT_PCT else ""
    return (f"🌙 **台指電子盤**　收 {s['last']:,.0f}　{arrow}{s['change']:+,.0f}（{s['pct']:+.2f}%）{flag}{stale}"
            f"\n-# {start:%m/%d} 15:00～{end:%m/%d} 05:00 夜盤・期交所收盤後彙整、非即時・不是買賣訊號")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    print(fetch())
    print(summary_line())
