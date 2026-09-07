# -*- coding: utf-8 -*-
"""財報「實際發布日」與「下次發布日」（2026-09-07 Leo：「可以用發布時間排序?
（還是要用更新時間?）可以補上下次發布時間嗎?」）。

## 三個日期不要搞混

| 日期 | 是什麼 | 適合拿來做什麼 |
|---|---|---|
| **發布日** | 公司**實際公布財報**那天 | ⭐ **排序用這個**——「哪一份是最新的消息」 |
| 會計期間截至 | 這份財報涵蓋到哪一天（例 2026-06-30） | 標示是哪一季，不適合排序（同一季一大票同日） |
| 更新時間 | **我們產出卡片**的時間（現在的排序） | 只說明我們什麼時候跑的，跟消息新舊無關 |

⭐ 現在的排序用的是最沒有意義的那一個：`os.path.getmtime`。
   重跑一次全部卡片，排序就整個重洗，但財報本身一份都沒變。

## 資料來源

`yfinance.Ticker.get_earnings_dates()`——**earnings_watch.py 本來就在用這支**，
不另外接來源。它同時給過去（已公布，帶 EPS）與未來（預估日期，EPS 是 NaN）。

⚠️ **未來的日期是預估**，公司隨時可能改。所以顯示時要標「預估」，
   不要讓人以為那是公司公告過的確定日期。

## 快取

`state/earnings_calendar.json`，預設 7 天內不重查（財報日不會天天變）。
走 yfinance 免費，零成本。
"""
import argparse
import datetime as dt
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "state", "earnings_calendar.json")
TTL_DAYS = 7


def _load():
    try:
        return json.load(io.open(CACHE, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}


def _save(d):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(
        json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True))
    os.replace(tmp, CACHE)


def _yf_symbol(ticker):
    import re
    if re.match(r"^[0-9]{4,6}[A-Z]?$", str(ticker)):
        try:
            import tw_symbol
            return tw_symbol.resolve(ticker)
        except Exception:                                   # noqa: BLE001
            return f"{ticker}.TW"
    return str(ticker)


def fetch(ticker):
    """回 {last: 已公布的最近一次, next: 下一次(預估)}，查不到的欄位是 None。

    ⚠️ 判斷「已公布 vs 未來」用**日期**，不是用 EPS 有沒有值——
    有些已公布的列 EPS 也是空的（估計值缺、或當季沒有共識），
    拿 EPS 當旗標會把已公布的誤判成未來。
    """
    try:
        import yfinance as yf
        df = yf.Ticker(_yf_symbol(ticker)).get_earnings_dates(limit=16)
    except Exception:                                       # noqa: BLE001
        return {"last": None, "next": None}
    if df is None or getattr(df, "empty", True):
        return {"last": None, "next": None}
    today = dt.date.today()
    past, future = [], []
    for idx in df.index:
        try:
            d = idx.date()
        except Exception:                                   # noqa: BLE001
            continue
        (past if d <= today else future).append(d)
    return {"last": max(past).isoformat() if past else None,
            "next": min(future).isoformat() if future else None}


def get(ticker, force=False):
    """帶快取。回同 fetch()。"""
    key = str(ticker).upper()
    c = _load()
    hit = c.get(key)
    if hit and not force:
        try:
            age = (dt.date.today()
                   - dt.date.fromisoformat(hit.get("fetched", "1970-01-01"))).days
            if age < TTL_DAYS:
                return {"last": hit.get("last"), "next": hit.get("next")}
        except Exception:                                   # noqa: BLE001
            pass
    r = fetch(ticker)
    # ⚠️ 查失敗（兩個都 None）**不要覆蓋掉舊值**——一次網路逾時就把
    # 好好的日期洗成「沒資料」，而且之後 7 天都用那個空的
    # （記憶 cache_negative_result_bug 記過同一件事）。
    if not r["last"] and not r["next"] and hit:
        return {"last": hit.get("last"), "next": hit.get("next")}
    c[key] = dict(r, fetched=dt.date.today().isoformat())
    _save(c)
    return r


def days_until(iso):
    if not iso:
        return None
    try:
        return (dt.date.fromisoformat(iso) - dt.date.today()).days
    except Exception:                                       # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description="財報發布日／下次發布日")
    ap.add_argument("tickers", nargs="*", help="不給就掃 docs/earnings_*.html 那批")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    tks = a.tickers
    if not tks:
        import glob
        import re
        tks = sorted({os.path.basename(f)[9:-5].replace("_", ".")
                      for f in glob.glob(os.path.join(HERE, "docs", "earnings_*.html"))
                      if not re.search(r"earnings_index", f)})
    for t in tks:
        r = get(t, force=a.force)
        n = days_until(r["next"])
        print(f"{t:10} 上次 {r['last'] or '—':12} 下次 {r['next'] or '—':12}"
              + (f"（{n} 天後）" if n is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
