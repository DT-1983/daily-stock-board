# -*- coding: utf-8 -*-
"""盤中即時報價（2026-10-07，Leo：「盤中即時報價做的到嗎？戰情室」）——零成本，不用任何券商帳戶。

資料源（都實測過）：
  · 台股：證交所即時行情 mis.twse.com.tw/stock/api/getStockInfo.jsp（網頁自己用的服務，**非正式文件化 API**）。
          盤中約每 5 秒更新；一次可帶多檔（上市 tse_／上櫃 otc_）。回 z 最新成交價（尚無成交是 "-"）、
          o 開、h 高、l 低、y 昨收、t 時間。→ 抓取頻率要克制（呼叫端 15～60 秒一次、這裡有 8 秒快取）。
  · 美股：yfinance fast_info（現價／昨收／日高低），detail=True 再補 1 分鐘線最後一根的時間（落後約 1 分鐘內）。

回傳 {代號: {px, prev, chg, hi, lo, op, time, state, src}}；state = "盤中"／"收盤"／"非正常盤"。
抓不到的代號不在結果裡（呼叫端要保留原本的收盤價，不能顯示空白或 0）。
"""
import concurrent.futures as _cf
import datetime as _dt
import json
import re
import time
import urllib.request

_MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
_CACHE = {}
_TTL = 8.0


def _is_tw(tk):
    return bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(tk).upper()))


def _tw_open(now=None):
    """台股正常盤 09:00～13:30（台北時間，週一至週五）。國定假日這裡不知道——靠回傳資料日期補判。"""
    n = now or _dt.datetime.now()
    return n.weekday() < 5 and _dt.time(9, 0) <= n.time() <= _dt.time(13, 30)


def _us_open(now=None):
    """美股正常盤 09:30～16:00（美東）。夏令時自動處理。"""
    try:
        from zoneinfo import ZoneInfo
        n = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    except Exception:                                       # noqa: BLE001
        return False
    return n.weekday() < 5 and _dt.time(9, 30) <= n.time() <= _dt.time(16, 0)


def _num(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _tw_channel(tk):
    if str(tk).upper() == "^TWII":                          # 台股加權指數（證交所即時服務的代號是 t00）
        return "tse_t00.tw"
    import tw_symbol
    code = str(tk).upper().split(".")[0]
    sym = tw_symbol.resolve(code)
    return ("otc_" if str(sym).upper().endswith(".TWO") else "tse_") + code.lower() + ".tw"


def tw_quotes(tickers):
    out = {}
    chans = {}
    for tk in tickers:
        try:
            chans[_tw_channel(tk)] = tk
        except Exception:                                   # noqa: BLE001
            continue
    keys = list(chans)
    for i in range(0, len(keys), 60):
        part = keys[i:i + 60]
        url = f"{_MIS}?ex_ch={'|'.join(part)}&json=1&delay=0&_={int(time.time() * 1000)}"
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=12))
        except Exception:                                   # noqa: BLE001
            continue
        for a in r.get("msgArray") or []:
            ch = f"{a.get('ex')}_{str(a.get('c', '')).lower()}.tw"
            tk = chans.get(ch)
            if not tk:
                continue
            prev = _num(a.get("y"))
            px = _num(a.get("z"))
            if px is None:                                  # 還沒有成交（開盤前／剛開盤）：不硬湊，用昨收
                continue
            hi, lo, op = _num(a.get("h")), _num(a.get("l")), _num(a.get("o"))
            d = str(a.get("d") or "")
            today = _dt.date.today().strftime("%Y%m%d")
            state = "盤中" if (_tw_open() and d == today) else "收盤"
            out[tk] = {"px": px, "prev": prev, "chg": (px / prev - 1) * 100 if prev else None,
                       "hi": hi, "lo": lo, "op": op, "time": a.get("t"), "date": d,
                       "state": state, "src": "證交所即時"}
    return out


def _us_one(tk, detail):
    import yfinance as yf
    sym = str(tk).upper().replace(".", "-")
    try:
        t = yf.Ticker(sym)
        fi = t.fast_info
        px, prev = _num(fi.get("lastPrice")), _num(fi.get("previousClose"))
        if px is None:
            return tk, None
        rec = {"px": px, "prev": prev, "chg": (px / prev - 1) * 100 if prev else None,
               "hi": _num(fi.get("dayHigh")), "lo": _num(fi.get("dayLow")), "op": _num(fi.get("open")),
               "time": None, "state": "盤中" if _us_open() else "收盤", "src": "yfinance"}
        if detail:
            h = t.history(period="1d", interval="1m", prepost=True)
            if len(h):
                last = h.index[-1]
                rec["time"] = last.strftime("%H:%M") + " 美東"
                lag = (_dt.datetime.now(last.tzinfo) - last).total_seconds() / 60
                if not _us_open() and lag < 30:
                    rec["state"] = "非正常盤"             # 盤前／盤後仍有成交
        return tk, rec
    except Exception:                                       # noqa: BLE001
        return tk, None


def us_quotes(tickers, detail=False):
    out = {}
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        for tk, rec in ex.map(lambda t: _us_one(t, detail), tickers):
            if rec:
                out[tk] = rec
    return out


def quotes(tickers, detail=False):
    """tickers：任何寫法的代號清單。回 {原代號: 報價}。8 秒快取，避免多個畫面同時打爆來源。"""
    tickers = [t for t in dict.fromkeys(str(x).strip() for x in tickers) if t][:200]
    key = (tuple(sorted(tickers)), bool(detail))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    tw = [t for t in tickers if _is_tw(t) or t.upper() == "^TWII"]
    us = [t for t in tickers if t not in tw]
    out = {}
    if tw:
        out.update(tw_quotes(tw))
    if us:
        out.update(us_quotes(us, detail))
    _CACHE[key] = (time.time(), out)
    if len(_CACHE) > 60:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:20]:
            _CACHE.pop(k, None)
    return out


if __name__ == "__main__":
    import sys
    r = quotes(sys.argv[1:] or ["2308", "2330", "NVDA", "MRVL"], detail=True)
    for k, v in r.items():
        print(k, v)
