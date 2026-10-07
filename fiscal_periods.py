# -*- coding: utf-8 -*-
"""某個會計期間「已公布」了沒（2026-10-07，交接 INVESTMENT_AUDIT_FIX：景碩／MRVL）

為什麼需要：券商報告的預估表把年度、季度一律當「預估」處理——
  · 景碩 2Q26 EPS 2.49：Q2 早已公布（官方基本 EPS 2.57／稀釋 2.56），查核表卻還寫「等該季財報公布」；
  · MRVL 2024／2025／2026 EPS 1.51／1.57／2.84：是已公布的 non-GAAP 財年實績，卻被列「券商財務預估」，
    「2025 空白年」還被解讀成「現在還在等未來」。
判斷原則：**用資料說話，不用日曆猜**——
  · 台股：FinMind 損益表有那個季底（年底）日期的資料＝已公布；
  · 其他：公司財年底（yfinance lastFiscalYearEnd 的月份，財年以「結束那年」命名）之後，
    earnings_calendar 的最近一次公布日 >= 該財年底＝已公布。
查不到一律回 None（不知道），呼叫端要維持原本「預估」的說法，不能硬猜成已公布。
"""
import datetime as dt
import json
import os
import re

_CAL = "state/earnings_calendar.json"
_TW_CACHE = {}
_FYE_CACHE = {}


def _is_tw(ticker):
    return bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(ticker).upper()))


def tw_statements(code):
    """{季底日期: {type: value}}（FinMind TaiwanStockFinancialStatements，近 3 年）。失敗回 {}。"""
    code = str(code).upper().split(".")[0]
    if code in _TW_CACHE:
        return _TW_CACHE[code]
    out = {}
    try:
        import fundamentals_reality as FR
        start = (dt.date.today() - dt.timedelta(days=3 * 365 + 60)).isoformat()
        for r in FR._fm("TaiwanStockFinancialStatements", code, start):
            out.setdefault(r["date"], {})[r["type"]] = r["value"]
    except Exception:                                       # noqa: BLE001
        out = {}
    _TW_CACHE[code] = out
    return out


def parse_quarter(q):
    """'2Q26'／'Q2 2026'／'2026Q2'／'2Q26E' → (2026, 2)；認不得回 None。"""
    s = str(q or "").upper().replace(" ", "")
    m = re.match(r"^([1-4])Q(\d{2,4})", s) or re.match(r"^Q([1-4])(\d{2,4})", s)
    if m:
        qn, y = int(m.group(1)), int(m.group(2))
    else:
        m = re.match(r"^(\d{4})Q([1-4])", s)
        if not m:
            return None
        y, qn = int(m.group(1)), int(m.group(2))
    return (2000 + y if y < 100 else y), qn


def quarter_end(year, qn):
    return {1: f"{year}-03-31", 2: f"{year}-06-30", 3: f"{year}-09-30", 4: f"{year}-12-31"}[qn]


def tw_quarter_actual(ticker, q):
    """台股（日曆年度）某季的官方實績：{'date','eps'(基本EPS，單季)}；還沒公布／查不到回 None。"""
    pq = parse_quarter(q)
    if not pq or not _is_tw(ticker):
        return None
    d = quarter_end(*pq)
    row = tw_statements(ticker).get(d)
    if not row or row.get("EPS") is None:
        return None
    return {"date": d, "eps": float(row["EPS"])}


def _fye_month(ticker):
    t = str(ticker).upper()
    if _is_tw(t):
        return 12
    if t in _FYE_CACHE:
        return _FYE_CACHE[t]
    m = None
    try:
        import yfinance as yf
        ts = yf.Ticker(t.replace(".", "-")).info.get("lastFiscalYearEnd")
        if ts:
            m = (dt.date.fromtimestamp(float(ts)) - dt.timedelta(days=5)).month   # 退 5 天：財年底常落在月初（2/1）
    except Exception:                                       # noqa: BLE001
        m = None
    _FYE_CACHE[t] = m
    return m


def _last_report(ticker):
    t = str(ticker).upper()
    try:
        cal = json.load(open(_CAL, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return None
    for k in (t, t + ".TW", t + ".TWO"):
        v = cal.get(k)
        if isinstance(v, dict) and v.get("last"):
            try:
                return dt.date.fromisoformat(v["last"])
            except ValueError:
                return None
    return None


def year_published(ticker, year_label):
    """該（財）年度的全年數字公司已公布了嗎？True／False／None（不知道）。"""
    m = re.match(r"^\s*(\d{4})", str(year_label))
    if not m:
        return None
    y = int(m.group(1))
    if _is_tw(ticker):
        st = tw_statements(ticker)
        if not st:
            return None
        return f"{y}-12-31" in st
    fm = _fye_month(ticker)
    last = _last_report(ticker)
    if not fm or not last:
        return None
    nxt_month_first = dt.date(y + (1 if fm == 12 else 0), 1 if fm == 12 else fm + 1, 1)
    fy_end = nxt_month_first - dt.timedelta(days=1)
    return last >= fy_end
