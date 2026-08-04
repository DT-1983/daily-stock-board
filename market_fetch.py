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

# 2026-08-04 用戶定版 8 格（2 排 × 4）：第一排美股、第二排台股+總經。
# 第 7 格＝三大法人買賣超（TWSE API，另抓）、第 8 格＝美債 10 年殖利率（^TNX，取代 VIX）。
INDICES = [
    ("^GSPC", "S&P 500", "US"),
    ("^IXIC", "那斯達克", "US"),
    ("^DJI", "道瓊工業", "US"),
    ("^SOX", "費城半導體", "US"),
    ("^TWII", "台股加權", "TW"),
    ("TWD=X", "美元/台幣", "FX"),
    ("^TNX", "美債 10 年殖利率", "US"),
]
TWSE_INST = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
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
            row = {"sym": sym, "name": name, "grp": grp,
                   "date": closes.index[-1].strftime("%m/%d")}
            if sym == "^TNX":  # yfinance 的 ^TNX 直接報 %（實測 4.7＝4.7%），漲跌用 bp 才有感
                row.update({"close": round(last, 2), "fmt": "yield",
                            "chg_bp": round((last - prev) * 100, 1)})
            else:
                row.update({"close": round(last, 2),
                            "chg_pct": round((last / prev - 1) * 100, 2)})
            out.append(row)
        except Exception as e:
            print(f"⚠️ {sym} 抓取失敗：{e}")
    return out


def fetch_inst():
    """證交所三大法人買賣金額（上市）。單位元 → 億。約 15:00 公布當日值。"""
    r = requests.get(TWSE_INST, headers=UA, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("stat") != "OK":
        raise RuntimeError(f"TWSE stat={d.get('stat')}")
    rows = {row[0]: float(row[3].replace(",", "")) / 1e8 for row in d["data"]}
    dt = d.get("date", "")
    return {
        "date": f"{dt[4:6]}/{dt[6:8]}" if len(dt) == 8 else dt,
        "total_yi": round(rows.get("合計", 0), 1),
        "foreign_yi": round(rows.get("外資及陸資(不含外資自營商)", 0), 1),
        "trust_yi": round(rows.get("投信", 0), 1),
    }


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
        data["inst"] = fetch_inst()
    except Exception as e:
        print(f"⚠️ 三大法人抓取失敗：{e}")
        data["inst"] = None
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
