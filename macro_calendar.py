"""總經行事曆——FOMC/CPI/非農/台灣央行的「哪天開會/發布」是官方提前公布的排定行程，
不需要每天叫 AI+WebSearch 重新查一次。這份表 2026-08-26 用 WebSearch 查證過一次
（來源見各常數註解），之後每季手動核對一次官方頁面更新即可，平常呼叫這個模組零成本零AI。

跟 researcher_macro.py 的分工：這裡只回答「哪天有事」，不回答「發布的數字是多少／
有沒有意外」——後者才需要真的花錢叫 AI 查證，且只在這裡判斷「最近有事」時才觸發。
"""
import os
import sys
import json
from datetime import date, timedelta, datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

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


TPE = timezone(timedelta(hours=8))
NEWS_API = "https://api.cnyes.com/media/api/v1/newslist/category/{cat}?limit={n}"


def macro_headlines(n=5):
    """免費、非LLM：鉅亨網 tw_macro／wd_macro 分類（總經新聞，跟 market_fetch.py 用的
    tw_stock/wd_stock 是不同分類，這兩個才是總經導向）。2026-08-26查證：這個公開JSON
    API 不用登入不用key，跟 market_fetch.py 已經在正式環境穩定用的是同一個端點/機制。
    查失敗要老實回空list，不要讓整個researcher_macro因為新聞抓不到而中斷。"""
    import requests
    out = []
    for cat, mkt in (("tw_macro", "TW"), ("wd_macro", "global")):
        try:
            r = requests.get(NEWS_API.format(cat=cat, n=n), timeout=15)
            r.raise_for_status()
            items = r.json()["items"]["data"]
            for it in items[:n]:
                ts = datetime.fromtimestamp(it["publishAt"], tz=TPE)
                out.append({"title": it["title"], "market": mkt,
                            "url": f'https://news.cnyes.com/news/id/{it["newsId"]}',
                            "ts": ts.strftime("%Y-%m-%d %H:%M")})
        except Exception as e:
            out.append({"title": f"（{cat} 新聞抓取失敗：{e}）", "market": mkt, "url": "", "ts": ""})
    return out


def needs_verification(today_str=None, window_days=1):
    """判斷要不要花錢叫AI查證——只有「今天前後window_days天內有排定事件」才需要，
    平常查表就好，不用每天都花$0.7。"""
    events = upcoming_events(today_str, days_before=window_days, days_after=window_days)
    return events


# ── 沒排定的重大事件觀測（2026-08-26 加）─────────────────────────────
# 行事曆只涵蓋「排定好的」事件（FOMC/CPI/非農/央行）。關稅戰、戰爭、制裁、信用事件
# 這類沒排定的東西不會出現在行事曆上，但一樣會撼動大盤——原本這些新聞有抓回來
# 存進 research_notes.jsonl，卻沒有任何人讀它（行事曆說沒事，AI 根本沒被呼叫），
# 等於抓了等於沒抓。這裡補兩個零成本觸發器。

INDEX_MOVE_PCT = 2.0     # 主要指數單日漲跌超過這個幅度就算異常
YIELD_MOVE_BP = 15       # 10年期公債殖利率單日變動超過這麼多bp就算異常

# 精簡的關鍵字清單：抓「市場還沒反應、但明顯要出事」的情況。刻意不寫長——
# 清單再長也一定會漏掉沒想到的詞（2020年沒人會事先把「疫情」放進來），
# 真正的防線是上面的市場異常偵測（重大事件市場一定會反應），這裡只是輔助。
ALERT_KEYWORDS = [
    "關稅", "制裁", "禁運", "出口管制", "戰爭", "停火", "衝突",
    "違約", "倒閉", "破產", "崩盤", "熔斷", "股災",
    "升息", "降息", "緊急會議", "政變", "封鎖",
]


LIVE_INDICES = {"^GSPC": "S&P 500", "^IXIC": "那斯達克", "^DJI": "道瓊工業",
                "^SOX": "費城半導體", "^TWII": "台股加權"}
YIELD_SYM, YIELD_NAME = "^TNX", "美債 10 年殖利率"

# 各市場的「當地時區 UTC 偏移, 收盤時間」。用來判斷 yfinance 給的最後一根日 K
# 是不是**還沒收完的當日盤中 bar**——盤中 bar 的日期已經是今天，但數字還會變，
# 拿它去比 2% 門檻等於用半截資料判異常。2026-08-31 22:19（美東 10:19 開盤中）
# 實測就抓到 ^SOX 的「08/31 -3.03%」，那是盤中值不是收盤。
# 排程在 07:00/08:45 跑時美股早就收了，所以正常情況不會踩到；這道是給臨時手動
# 執行和之後可能改時間用的（見 memory unexecuted_code_paths：沒守的路徑遲早會走到）。
_CLOSE_RULE = {"^TWII": (8, 13, 30)}          # 台股 13:30 收
_US_CLOSE = (-4, 16, 0)                       # 美股 16:00 ET（夏令 UTC-4）


def _session_done(sym, bar_date):
    """這根 bar 代表的交易日收完了沒。"""
    off, hh, mm = _CLOSE_RULE.get(sym, _US_CLOSE)
    now_local = datetime.now(timezone(timedelta(hours=off)))
    if bar_date < now_local.date():
        return True
    if bar_date > now_local.date():
        return False
    return (now_local.hour, now_local.minute) >= (hh, mm)


def _live_index_moves():
    """自己抓指數最近一個交易日的漲跌幅。回 [(名稱, pct, bp, MM/DD)]；抓不到回 None。

    2026-08-31 加。原本只讀 market_data.json，但那份檔案的更新權在 GitHub Actions
    手上，而 07:00 這批比 Actions 早跑——實測當天讀到的是**兩個交易日前**的資料：
    拿 8/27 的費半 +2.33% 當「今日異常」去叫 AI 查證，而 8/28 實際是 -3.47%，
    等於查了一個已經被隔日行情推翻的事件，AI 回來的筆記還把日期寫成 8/28，
    那筆錯誤事實直接進了 research_notes.jsonl 被投資長讀走。

    自己抓一樣零成本（yfinance），而且不再依賴那條本來就常漏跑的 Actions 排程。
    """
    try:
        import yfinance as yf
    except Exception:
        return None
    syms = list(LIVE_INDICES) + [YIELD_SYM]
    try:
        data = yf.download(syms, period="5d", progress=False, threads=False,
                           auto_adjust=True, group_by="ticker")
    except Exception:
        return None
    out = []
    for s in syms:
        try:
            c = data[s]["Close"].dropna()
            # 最後一根還在盤中就往前退一根，只用收完的交易日
            if len(c) and not _session_done(s, c.index[-1].date()):
                c = c.iloc[:-1]
            if len(c) < 2:
                continue
            last, prev = float(c.iloc[-1]), float(c.iloc[-2])
            when = c.index[-1].strftime("%m/%d")
            if s == YIELD_SYM:
                out.append((YIELD_NAME, None, (last - prev) * 100, when))
            else:
                out.append((LIVE_INDICES[s], (last / prev - 1) * 100, None, when))
        except Exception:
            continue
    return out or None


def _rows_from_file(market_data_path):
    """market_data.json 的同格式列表。不在這裡判新鮮度，交給 `market_anomaly` 統一比。"""
    if not os.path.exists(market_data_path):
        return None
    try:
        data = json.load(open(market_data_path, encoding="utf-8"))
    except Exception:
        return None
    return [(idx.get("name", idx.get("sym", "")), idx.get("chg_pct"),
             idx.get("chg_bp"), str(idx.get("date") or ""))
            for idx in data.get("indices", [])]


MAX_STALE_DAYS = 3       # 週一讀週五收盤＝3 天，是正常的上限


def _as_date(mmdd, today):
    """"08/28" → date。跨年時（12月的日期配到1月的今天）自動退一年。"""
    try:
        mm, dd = (int(x) for x in str(mmdd).split("/"))
    except Exception:
        return None
    try:
        d = datetime(today.year, mm, dd).date()
    except ValueError:
        return None
    return d.replace(year=today.year - 1) if (d - today).days > 300 else d


def market_anomaly(market_data_path="market_data.json"):
    """零成本：判斷主要指數/殖利率有沒有異常波動。回傳觸發原因清單，空list=正常。

    **兩個來源逐指數取比較新的那一個**，然後丟掉太舊的。為什麼要這樣：

    · 只讀 market_data.json 不行——那份檔案的更新權在 GitHub Actions 手上，而 07:00
      這批比 Actions 早跑。2026-08-31 實測讀到兩個交易日前的資料：拿 8/27 的費半
      +2.33% 當「今日異常」去叫 AI 查證，而 8/28 實際是 -3.47%，等於查一個已經被
      隔日行情推翻的事件，AI 回來的筆記還把日期寫成 8/28，錯誤事實進了
      research_notes.jsonl 被投資長讀走。
    · 只自己抓也不行——同一天實測，本機 yfinance 對所有美股標的都只到 8/27（8/30
      還抓得到 8/28，隔天反而退化），但 Actions 上的同一支 market_fetch.py 抓得到。
      **自己抓不是解法，只是換一個地方過期**，而且它不會知道自己過期了。

    所以真正的防線是「帶著日期比較」而不是「換來源」。日期也一併寫進觸發原因
    （例如「費城半導體 08/28 單日跌 3.47%」），日報①段的「今日觸發」就不會再跟
    同一段的指數行情自相矛盾。
    """
    today = datetime.now(TPE).date()
    best = {}
    for rows in (_live_index_moves(), _rows_from_file(market_data_path)):
        for nm, pct, bp, when in rows or []:
            d = _as_date(when, today)
            if d is None:
                continue
            if nm not in best or d > best[nm][0]:
                best[nm] = (d, pct, bp, when)

    hits, stale = [], []
    for nm, (d, pct, bp, when) in sorted(best.items()):
        if (today - d).days > MAX_STALE_DAYS:
            stale.append(f"{nm}({when})")
            continue
        if pct is not None and abs(pct) >= INDEX_MOVE_PCT:
            hits.append(f"{nm} {when} 單日{'漲' if pct > 0 else '跌'} {abs(pct):.2f}%")
        if bp is not None and abs(bp) >= YIELD_MOVE_BP:
            hits.append(f"{nm} {when} 單日變動 {bp:+.1f}bp")
    if stale:
        # 寧可漏報也不要謊報：兩個來源都給不出夠新的資料時，說出來，不要靜靜跳過。
        print("  ⚠️ 兩個來源都過期，這幾筆不列入異常判斷：" + "、".join(stale))
    return hits


def keyword_hits(headlines):
    """零成本：關鍵字命中檢查。回 [(關鍵字, 標題), ...]。"""
    hits = []
    for h in headlines or []:
        title = h.get("title", "")
        for kw in ALERT_KEYWORDS:
            if kw in title:
                hits.append((kw, title))
                break        # 一則新聞算一次就好，不重複計數
    return hits


if __name__ == "__main__":
    import json
    print(json.dumps(upcoming_events(), ensure_ascii=False, indent=2))
