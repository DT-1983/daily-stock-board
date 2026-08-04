"""首頁儀表板資料層 → market_data.json

- 指數/匯率收盤：yfinance（美股 4 大 + 台股加權 + VIX + 美元/台幣）
- 新聞頭條：鉅亨網 JSON API（台股 5 條 + 國際股 5 條，照發布時間新→舊）
  https://api.cnyes.com/media/api/v1/newslist/category/{tw_stock|wd_stock}

用法：python market_fetch.py
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "market_data.json")
TPE = timezone(timedelta(hours=8))

INDICES = [
    ("^TWII", "台股加權", "TW"),
    ("^GSPC", "S&P 500", "US"),
    ("^IXIC", "那斯達克", "US"),
    ("^DJI", "道瓊工業", "US"),
    ("^SOX", "費城半導體", "US"),
    ("^VIX", "VIX 恐慌指數", "US"),
    ("TWD=X", "美元/台幣", "FX"),
]
NEWS_API = "https://api.cnyes.com/media/api/v1/newslist/category/{cat}?limit={n}"
UA = {"User-Agent": "Mozilla/5.0"}


def fetch_indices():
    syms = [s for s, _, _ in INDICES]
    data = yf.download(syms, period="7d", progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    out = []
    for sym, name, grp in INDICES:
        try:
            closes = data[sym]["Close"].dropna()
            last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
            out.append({
                "sym": sym, "name": name, "grp": grp,
                "close": round(last, 2),
                "chg_pct": round((last / prev - 1) * 100, 2),
                "date": closes.index[-1].strftime("%m/%d"),
            })
        except Exception as e:
            print(f"⚠️ {sym} 抓取失敗：{e}")
    return out


def fetch_news(cat, n=5, mkt="TW"):
    r = requests.get(NEWS_API.format(cat=cat, n=n), headers=UA, timeout=20)
    r.raise_for_status()
    items = r.json()["items"]["data"]
    out = []
    for it in items[:n]:
        ts = datetime.fromtimestamp(it["publishAt"], tz=TPE)
        out.append({
            "title": it["title"], "mkt": mkt,
            "url": f'https://news.cnyes.com/news/id/{it["newsId"]}',
            "ts": ts.strftime("%m/%d %H:%M"), "_sort": it["publishAt"],
        })
    return out


def main():
    data = {"updated": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
            "indices": fetch_indices(), "news": []}
    try:
        news = fetch_news("tw_stock", 5, "TW") + fetch_news("wd_stock", 5, "US")
        news.sort(key=lambda x: x["_sort"], reverse=True)
        for x in news:
            x.pop("_sort", None)
        data["news"] = news
    except Exception as e:
        print(f"⚠️ 新聞抓取失敗：{e}")

    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已存 {OUT}：指數 {len(data['indices'])} 檔、新聞 {len(data['news'])} 條")


if __name__ == "__main__":
    main()
