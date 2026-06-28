"""台股 AI 分析模組:FinMind 抓資料(股價+法人籌碼+月營收) + Gemini 決策 → tw_analysis.json

台股自建版（daily_stock_analysis 不支援台股）。輸出給 board_html.py 用。
用法:python tw_analyze.py
需環境變數 GEMINI_API_KEY
"""
import os
import re
import json
from datetime import datetime, timedelta
import requests
import litellm

FINMIND = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")   # 可選，提高額度
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("TW_LLM_MODEL", "gemini/gemini-3-flash-preview")

# 台股守備清單：優先讀客觀篩選結果 screen_result.json（每鏈 top N），無則用 fallback
def _load_tw_watch():
    try:
        d = json.load(open("screen_result.json", encoding="utf-8"))
        return {chain: [(x["code"], x.get("name", x["code"])) for x in lst]
                for chain, lst in d["tw"].items()}
    except Exception:
        return {
            "AI 伺服器": [("2330", "台積電"), ("2317", "鴻海"), ("2382", "廣達")],
            "機器人": [("2049", "上銀"), ("1536", "和大"), ("2359", "所羅門")],
        }


TW_WATCH = _load_tw_watch()
SIG_EMOJI = {"買進": "🟢", "賣出": "🔴", "觀望": "⚪", "持有": "🔵"}


def fm(dataset, sid, start):
    params = {"dataset": dataset, "data_id": sid, "start_date": start}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
    try:
        return requests.get(FINMIND, params=params, timeout=20).json().get("data", [])
    except Exception:
        return []


def fetch(sid):
    d120 = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    d10 = (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d")
    d400 = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    d200 = (datetime.now() - timedelta(days=250)).strftime("%Y-%m-%d")
    return (fm("TaiwanStockPrice", sid, d120),
            fm("TaiwanStockInstitutionalInvestorsBuySell", sid, d10),
            fm("TaiwanStockMonthRevenue", sid, d400),
            fm("TaiwanStockPER", sid, d10),
            fm("TaiwanStockFinancialStatements", sid, d200))


def _fin_latest(fin):
    """從財報抽最新季的 EPS / 毛利率。"""
    if not fin:
        return None, None
    dates = sorted(set(d["date"] for d in fin))
    last = dates[-1]
    byt = {d["type"]: d["value"] for d in fin if d["date"] == last}
    eps = byt.get("EPS")
    rev, gp = byt.get("Revenue"), byt.get("GrossProfit")
    gm = round(gp / rev * 100, 1) if rev and gp else None
    return eps, gm


def analyze(code, name, chain):
    price, inst, rev, per, fin = fetch(code)
    if not price:
        return None
    closes = [d["close"] for d in price]
    last = closes[-1]
    ma = lambda n: round(sum(closes[-n:]) / n, 1) if len(closes) >= n else None
    foreign = sum(d["buy"] - d["sell"] for d in inst if d["name"] == "Foreign_Investor") // 1000
    trust = sum(d["buy"] - d["sell"] for d in inst if d["name"] == "Investment_Trust") // 1000
    rev_yoy = None
    if len(rev) >= 13 and rev[-13]["revenue"]:
        rev_yoy = round((rev[-1]["revenue"] / rev[-13]["revenue"] - 1) * 100, 1)
    pe = per[-1].get("PER") if per else None
    pb = per[-1].get("PBR") if per else None
    yld = per[-1].get("dividend_yield") if per else None
    eps, gm = _fin_latest(fin)
    # 當日行情
    t = price[-1]
    chg = round((t["close"] / price[-2]["close"] - 1) * 100, 2) if len(price) >= 2 and price[-2]["close"] else None

    ctx = (f"股票:{name}({code}) 產業鏈:{chain}\n"
           f"今日: 開{t['open']} 高{t['max']} 低{t['min']} 收{last} 漲跌{chg}% 量{t.get('Trading_Volume',0)//1000}張\n"
           f"均線: MA5 {ma(5)} MA10 {ma(10)} MA20 {ma(20)}｜近10日收盤 {closes[-10:]}\n"
           f"籌碼: 外資近12日 {foreign} 張、投信 {trust} 張\n"
           f"基本面: 月營收YoY {rev_yoy}%、EPS {eps}、毛利率 {gm}%、PER {pe}、PBR {pb}、殖利率 {yld}%")
    prompt = (f"你是台股短線分析師。依資料用繁體中文台灣用語給操作決策,綜合均線型態、法人籌碼、營收/估值。\n{ctx}\n\n"
              f"只回 JSON:\n"
              f'{{"signal":"買進或賣出或觀望","score":0到100整數,"oneliner":"一句話決策30字內",'
              f'"reason":"理由80字內提到籌碼與均線","risk":"主要風險40字內",'
              f'"buy_point":"理想買點(價位或條件)","stop_loss":"停損位(價位)","target":"目標價位",'
              f'"checklist":["檢查項1正or負","檢查項2","檢查項3"]}}')
    try:
        resp = litellm.completion(model=MODEL, api_key=GEMINI_KEY, temperature=0.3,
                                  messages=[{"role": "user", "content": prompt}])
        m = re.search(r"\{.*\}", resp.choices[0].message.content, re.S)
        d = json.loads(m.group(0))
    except Exception as e:
        print(f"  [{code}] LLM 失敗:{e}")
        d = {"signal": "觀望", "score": 50, "oneliner": "資料分析失敗", "reason": "", "risk": ""}
    d.update({
        "code": code, "name": name, "chain": chain, "last": last,
        "ma5": ma(5), "ma10": ma(10), "ma20": ma(20),
        "foreign": foreign, "trust": trust, "rev_yoy": rev_yoy,
        "open": t["open"], "high": t["max"], "low": t["min"], "chg": chg,
        "vol": t.get("Trading_Volume", 0) // 1000,
        "eps": eps, "gross_margin": gm, "pe": pe, "pb": pb, "yield": yld,
        "emoji": SIG_EMOJI.get(d.get("signal", "觀望"), "⚪"),
        "dates": [x["date"][5:] for x in price[-60:]],
        "closes": closes[-60:],
        "highs": [x["max"] for x in price[-60:]],
        "lows": [x["min"] for x in price[-60:]],
    })
    return d


def main():
    results = []
    for chain, lst in TW_WATCH.items():
        for code, name in lst:
            print(f"分析 {code} {name} ({chain})...")
            r = analyze(code, name, chain)
            if r:
                results.append(r)
    out = "tw_analysis.json"
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ 台股分析完成 {len(results)} 檔 → {out}")


if __name__ == "__main__":
    main()
