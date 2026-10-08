# -*- coding: utf-8 -*-
"""台指期（TX 近月）K 線資料——期交所「每日期貨逐筆成交」，免費、免金鑰、零 AI。

來源：https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_YYYY_MM_DD.zip
  · 檔名日期 D 的檔＝「D-1 夜盤（15:00 起）＋ D 的凌晨夜盤尾巴＋ D 日盤（08:45～13:45）」；D 的晚上夜盤要等 D+1 的檔才有。
  · D 日盤收盤後（約 14:00 起）就能下載（2026-10-08 實測 17:00 已有完整 10/8 日盤）。
  · 假日／未開市日下載會 404，略過。
產出（data/gex/bars.json，gitignore）：
  m：1 分 K  {秒數: [開,高,低,收,量]}（時間把台北時間當 UTC 編碼，圖上直接顯示台北時間；只留最近 8 個交易日）
  d：日 K（只算日盤 08:45～13:45，收盤價＝官方日盤收盤）{YYYYMMDD: [開,高,低,收,量]}
近月＝當天逐筆裡成交筆數最多的 6 位數月份（價差單的月份欄位不是 6 位數，自動排除）。
"""
import calendar
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "gex", "bars.json")
URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_{y}_{m}_{d}.zip"
KEEP_MIN_DAYS = 8          # 1 分 K 只留最近幾個「檔案日」
KEEP_DAILY = 160           # 日 K 最多留幾根


def _load():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"m": {}, "d": {}, "files": []}


def _download(day):
    """回 zip 內 CSV 的 bytes；該日沒檔（假日）回 None；其他錯誤丟例外。"""
    import requests
    u = URL.format(y=day.year, m=f"{day.month:02d}", d=f"{day.day:02d}")
    last = None
    for _ in range(3):
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=180)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            return z.read(z.namelist()[0])
        except zipfile.BadZipFile as e:      # 假日有時回 200 的錯誤頁
            last = e
            return None
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"逐筆成交下載失敗 {day}：{str(last)[:80]}")


def _ticks(raw):
    """→ (月份, [(YYYYMMDD, HHMMSS, 價, 量), ...])；只取 TX 近月單腿成交。"""
    txt = raw.decode("big5", "replace")
    by_month = {}
    for line in txt.splitlines():
        if ",TX" not in line[:24]:
            continue
        p = line.split(",")
        if len(p) < 6 or p[1].strip() != "TX":
            continue
        mo = p[2].strip()
        if not re.fullmatch(r"\d{6}", mo):
            continue
        try:
            by_month.setdefault(mo, []).append((p[0].strip(), p[3].strip().zfill(6), float(p[4]), int(float(p[5]))))
        except ValueError:
            continue
    if not by_month:
        return None, []
    mo = max(by_month, key=lambda k: len(by_month[k]))
    return mo, by_month[mo]


def _epoch(date, hhmmss):
    t = dt.datetime.strptime(date + hhmmss[:4], "%Y%m%d%H%M")
    return calendar.timegm(t.timetuple())


def merge_day(store, day):
    raw = _download(day)
    if raw is None:
        return False
    mo, ticks = _ticks(raw)
    if not ticks:
        return False
    mins, dailies = {}, {}
    for date, hms, px, q in ticks:                      # 檔內順序即時間順序
        k = _epoch(date, hms)
        b = mins.get(k)
        if b is None:
            mins[k] = [px, px, px, px, q]
        else:
            b[1] = max(b[1], px); b[2] = min(b[2], px); b[3] = px; b[4] += q
        if "084500" <= hms <= "134500":                 # 日盤
            d = dailies.get(date)
            if d is None:
                dailies[date] = [px, px, px, px, q]
            else:
                d[1] = max(d[1], px); d[2] = min(d[2], px); d[3] = px; d[4] += q
    for k, b in mins.items():                           # 後來的檔覆蓋同一分鐘
        store["m"][str(k)] = b
    for date, b in dailies.items():
        if date == day.strftime("%Y%m%d"):              # 只信「檔名日」那天的日盤（完整）
            store["d"][date] = b
    store["files"] = sorted(set(store["files"]) | {day.strftime("%Y%m%d")})
    return True


def update(backfill_days=10, refresh_last=2, today=None):
    """補齊最近 backfill_days 個工作日的檔；最近 refresh_last 個檔案日每次重抓（較新的檔會補上前一晚夜盤）。"""
    t = today or dt.date.today()
    store = _load()
    days = []
    d = t
    while len(days) < backfill_days:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    have = set(store["files"])
    fresh = 0
    err = []
    for i, day in enumerate(sorted(days)):
        tag = day.strftime("%Y%m%d")
        recent = i >= len(days) - refresh_last
        if tag in have and not recent:
            continue
        try:
            if merge_day(store, day):
                fresh += 1
        except Exception as e:  # noqa: BLE001
            err.append(str(e)[:100])
    # 修剪
    files = sorted(store["files"])
    if len(files) > KEEP_MIN_DAYS:
        cut = files[-KEEP_MIN_DAYS]
        cut_ts = calendar.timegm(dt.datetime.strptime(cut, "%Y%m%d").timetuple()) - 9 * 3600   # 含前一晚夜盤
        store["m"] = {k: v for k, v in store["m"].items() if int(k) >= cut_ts}
    ds = sorted(store["d"])
    store["d"] = {k: store["d"][k] for k in ds[-KEEP_DAILY:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, allow_nan=False)
    return {"fresh_files": fresh, "minutes": len(store["m"]), "daily": len(store["d"]),
            "last_file": max(store["files"]) if store["files"] else None, "errors": err}


def payload(spot=None):
    """給網頁用：1 分 K 緊湊陣列（依時間排序）＋日 K。"""
    s = _load()
    m = sorted((int(k), v) for k, v in s["m"].items())
    return {"m": [[k, *v] for k, v in m],
            "d": [[dt.datetime.strptime(k, "%Y%m%d").strftime("%Y-%m-%d"), *v] for k, v in sorted(s["d"].items())]}


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(update(backfill_days=n))
