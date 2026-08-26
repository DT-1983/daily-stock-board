"""總經行事曆——FOMC/CPI/非農/台灣央行的「哪天開會/發布」是官方提前公布的排定行程，
不需要每天叫 AI+WebSearch 重新查一次。這份表 2026-08-26 用 WebSearch 查證過一次
（來源見各常數註解），之後每季手動核對一次官方頁面更新即可，平常呼叫這個模組零成本零AI。

跟 researcher_macro.py 的分工：這裡只回答「哪天有事」，不回答「發布的數字是多少／
有沒有意外」——後者才需要真的花錢叫 AI 查證，且只在這裡判斷「最近有事」時才觸發。
"""
from datetime import date, timedelta

# 來源：federalreserve.gov 2026 FOMC 會議公告（2024-08-09 發布的暫定時程）
# https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm
# 政策聲明：會議第二天 14:00 ET；主席記者會：同日 14:30 ET
FOMC_2026 = [
    ("2026-01-27", "2026-01-28"), ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"), ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"), ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"), ("2026-12-08", "2026-12-09"),
]

# 來源：usinflationcalculator.com（引用 BLS 官方時程），2026-08-26 查證。發布時間皆 8:30 ET。
# 值＝發布日期；涵蓋月份見 CPI_2026 對照，不影響行事曆判斷用不到就不存。
CPI_2026 = [
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
    "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
]

# 來源：Massachusetts EOLWD 轉引 BLS 全國 Employment Situation 時程，2026-08-26 查證。
# 11-12月官方時程查證時還沒公布，用「每月第一個週五」規則推算，標記為 computed（低信心）。
NFP_2026_CONFIRMED = [
    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05",
    "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06",
]


def _first_friday(year, month):
    d = date(year, month, 1)
    while d.weekday() != 4:  # 4=週五
        d += timedelta(days=1)
    return d.isoformat()


NFP_2026_COMPUTED = {_first_friday(2026, 12)}  # 12月官方時程未查到，推算值

# 來源：中央銀行 2024-12-18 第213號新聞稿「115年理監事聯席會議預定日期」，2026-08-26 查證
# https://www.cbc.gov.tw/tw/cp-302-189514-82841-1.html
TW_CBC_2026 = ["2026-03-19", "2026-06-18", "2026-09-17", "2026-12-17"]


def upcoming_events(today_str=None, days_before=3, days_after=7):
    """回今天前後窗口內的行事曆事件，純查表零成本。
    回傳 [{market, event, date, status, confidence}, ...]，status: released(已過)/scheduled(未到)。"""
    today = date.fromisoformat(today_str) if today_str else date.today()
    lo, hi = today - timedelta(days=days_before), today + timedelta(days=days_after)
    out = []

    for start, end in FOMC_2026:
        d = date.fromisoformat(end)   # 政策聲明在會議第二天
        if lo <= d <= hi:
            out.append({"market": "US", "event": f"FOMC利率決議（會議{start}~{end}，聲明14:00 ET）",
                        "date": end, "status": "released" if d < today else "scheduled", "confidence": "high"})

    for ds in CPI_2026:
        d = date.fromisoformat(ds)
        if lo <= d <= hi:
            out.append({"market": "US", "event": "美國CPI消費者物價指數公布（8:30 ET）",
                        "date": ds, "status": "released" if d < today else "scheduled", "confidence": "high"})

    for ds in NFP_2026_CONFIRMED:
        d = date.fromisoformat(ds)
        if lo <= d <= hi:
            out.append({"market": "US", "event": "美國非農就業報告公布（8:30 ET）",
                        "date": ds, "status": "released" if d < today else "scheduled", "confidence": "high"})
    for ds in NFP_2026_COMPUTED:
        d = date.fromisoformat(ds)
        if lo <= d <= hi:
            out.append({"market": "US", "event": "美國非農就業報告公布（推算日期，未查到官方確認）",
                        "date": ds, "status": "released" if d < today else "scheduled", "confidence": "low"})

    for ds in TW_CBC_2026:
        d = date.fromisoformat(ds)
        if lo <= d <= hi:
            out.append({"market": "TW", "event": "台灣中央銀行理監事聯席會議",
                        "date": ds, "status": "released" if d < today else "scheduled", "confidence": "high"})

    out.sort(key=lambda e: e["date"])
    return out


def needs_verification(today_str=None, window_days=1):
    """判斷要不要花錢叫AI查證——只有「今天前後window_days天內有排定事件」才需要，
    平常查表就好，不用每天都花$0.7。"""
    events = upcoming_events(today_str, days_before=window_days, days_after=window_days)
    return events


if __name__ == "__main__":
    import json
    print(json.dumps(upcoming_events(), ensure_ascii=False, indent=2))
