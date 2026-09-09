# -*- coding: utf-8 -*-
"""量測：美股收盤資料在台灣時間幾點才真的到齊。

2026-09-09 Leo：「直接先改到 6:00，然後看一下 5:30 是不是資料好了」。

## 為什麼要量而不是用算的

美股 16:00 收盤，換算台灣時間**會隨美國夏令時間變動**：
  · 3–11 月（夏令 EDT）→ 台灣 04:00
  · 11–3 月（冬令 EST）→ 台灣 **05:00**
所以「現在 05:30 抓得到」不代表冬天也抓得到，而且**資料商結算還要時間**。

⭐ 這種錯誤最惡劣的地方是**不會報錯**：抓到前一天的 K 棒，程式照跑、日報照發，
   只是整份判斷都建立在舊資料上。所以不能靠推論，要有量測。

## 做法

同一批代號，在不同時間點各抓一次「最後一根日 K 的日期與收盤價」，
存成一行一筆。之後比對：**同一天的 05:30 跟 07:30 抓到的最後日期一不一樣**。
  · 一樣 → 05:30 資料已到齊，可以安全提早
  · 不一樣 → 05:30 太早，抓到的是前一個交易日

## 用法

    python us_close_probe.py            # 抓一次並附加到紀錄
    python us_close_probe.py --report   # 比對已累積的紀錄
"""
import argparse
import collections
import datetime as dt
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "state", "us_close_probe.jsonl")

# 取樣不用多，但要涵蓋不同流動性——冷門股的資料常常比權值股晚到。
TICKERS = ["SPY", "NVDA", "AAPL", "MSFT", "UNH", "ONTO", "CAMT", "BNY"]


def probe():
    import yfinance as yf
    now = dt.datetime.now()
    rows = []
    for tk in TICKERS:
        last_date = close = None
        try:
            h = yf.Ticker(tk).history(period="5d")[["Close"]].dropna()
            if not h.empty:
                last_date = str(h.index[-1])[:10]
                close = round(float(h["Close"].iloc[-1]), 4)
        except Exception as e:                              # noqa: BLE001
            print(f"  {tk} 抓取失敗：{str(e)[:60]}")
        rows.append({"ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                     "hhmm": now.strftime("%H:%M"),
                     "run_date": now.date().isoformat(),
                     "ticker": tk, "last_date": last_date, "close": close})
        print(f"  {tk:6} 最後日 {last_date}　收盤 {close}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n已記錄 {len(rows)} 筆 → {OUT}")
    return 0


def report():
    if not os.path.exists(OUT):
        print("還沒有任何紀錄")
        return 1
    rows = [json.loads(l) for l in io.open(OUT, encoding="utf-8") if l.strip()]
    by_day = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in rows:
        by_day[r["run_date"]][r["hhmm"]][r["ticker"]] = r["last_date"]

    print("每個執行日、各時間點抓到的「最後一根日K」：\n")
    for day in sorted(by_day):
        slots = sorted(by_day[day])
        if len(slots) < 2:
            print(f"  {day}　只有 {slots} 一個時間點，無法比對")
            continue
        base = slots[-1]                      # 最晚那次當基準（資料最完整）
        print(f"  {day}（基準＝{base} 那次）")
        for s in slots:
            same = sum(1 for t in TICKERS
                       if by_day[day][s].get(t) == by_day[day][base].get(t))
            older = [t for t in TICKERS
                     if by_day[day][s].get(t) != by_day[day][base].get(t)]
            flag = "✅ 一致" if not older else f"⚠️ 落後：{older}"
            print(f"    {s}　{same}/{len(TICKERS)} 相同　{flag}")
        print()
    print("判讀：某個時間點連續幾天都「✅ 一致」，才代表那時候資料已到齊。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="量測美股收盤資料何時到齊")
    ap.add_argument("--report", action="store_true", help="比對已累積的紀錄")
    a = ap.parse_args()
    return report() if a.report else probe()


if __name__ == "__main__":
    raise SystemExit(main())
