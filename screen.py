"""客觀守備清單篩選器：市值 + 成長 + 進場（法人/動能），每鏈取 top N。不含 CANSLIM。

美股候選池 = 各鏈 ETF 成分股（top holdings 合併）
台股候選池 = 各鏈產業鏈龍頭池
三因子各自排名正規化加總 → 每鏈取最強 N 檔
輸出:screen_result.json
用法:python screen.py
"""
import json
import time
from datetime import datetime, timedelta
import requests
import yfinance as yf

FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOPN = 6

US_ETFS = {
    "AI 伺服器": ["SMH", "SOXX", "DTCR", "SKYY"],
    "矽光子/光通訊": ["XSD", "IGN"],
    "低軌衛星": ["UFO", "ARKX", "ROKT"],
    "太陽能": ["TAN", "ICLN"],
    "Bitcoin→AI 機房": ["WGMI", "MNRS"],
    "AI 電力/核能": ["URA", "NLR", "GRID"],
    "機器人": ["BOTZ", "KOID", "ROBO"],
}
TW_POOL = {
    "AI 伺服器": ["2330", "2317", "2382", "6669", "3231", "3017", "3324", "2376",
                "2356", "2308", "2368", "3037", "8046", "3533"],
    "矽光子/光通訊": ["4979", "3450", "4908", "3105", "3081", "3363", "3163", "2345"],
    "機器人": ["2049", "1536", "6188", "2359", "4576", "1504", "3023", "1597", "4540"],
    "低軌衛星": ["3491", "6285", "2314", "3105", "2454", "6271"],
    "太陽能": ["6443", "5483", "6182", "3576"],
    "AI 電力/核能": ["1513", "1503", "1504", "1519", "1605"],
}
NAME = {}  # code → name 快取


def us_pool():
    pool = {}
    for chain, etfs in US_ETFS.items():
        s = set()
        for e in etfs:
            try:
                df = yf.Ticker(e).funds_data.top_holdings
                for sym in df.index:
                    if isinstance(sym, str) and sym.replace("-", "").isalpha() and len(sym) <= 5:
                        s.add(sym)
                        NAME[sym] = df.loc[sym].get("Name", sym)
            except Exception:
                pass
            time.sleep(0.5)
        pool[chain] = sorted(s)
    return pool


def us_metrics(tk):
    try:
        t = yf.Ticker(tk)
        info = t.info
        mc = info.get("marketCap") or 0
        g = info.get("revenueGrowth") or 0
        NAME.setdefault(tk, info.get("shortName", tk))
        h = t.history(period="3mo")
        mom = (h["Close"].iloc[-1] / h["Close"].iloc[0] - 1) if len(h) > 5 else 0
        return {"mktcap": mc, "growth": g, "inflow": mom}
    except Exception:
        return None


def fm(ds, sid, start):
    try:
        return requests.get(FINMIND, params={"dataset": ds, "data_id": sid,
                            "start_date": start}, timeout=15).json().get("data", [])
    except Exception:
        return []


def tw_metrics(code):
    try:
        info = yf.Ticker(code + ".TW").info
        mc = info.get("marketCap") or 0
        NAME.setdefault(code, info.get("shortName", code))
    except Exception:
        mc = 0
    rev = fm("TaiwanStockMonthRevenue", code, (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    g = 0
    if len(rev) >= 13 and rev[-13].get("revenue"):
        g = rev[-1]["revenue"] / rev[-13]["revenue"] - 1
    inst = fm("TaiwanStockInstitutionalInvestorsBuySell", code,
              (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    foreign = sum(d["buy"] - d["sell"] for d in inst if d["name"] == "Foreign_Investor") // 1000
    return {"mktcap": mc, "growth": g, "inflow": foreign}


def composite(metrics):
    """三因子各自排名正規化(0-1)加總。metrics: {code: {mktcap,growth,inflow}}"""
    scores = {k: 0.0 for k in metrics}
    for key in ("mktcap", "growth", "inflow"):
        vals = sorted(metrics.items(), key=lambda kv: kv[1].get(key, 0) or 0)
        n = len(vals)
        for rank, (k, _) in enumerate(vals):
            scores[k] += rank / (n - 1) if n > 1 else 0.5
    return scores


def screen(pool, metric_fn, label):
    result = {}
    for chain, codes in pool.items():
        print(f"[{label}] {chain}: {len(codes)} 候選...")
        metrics = {}
        for c in codes:
            m = metric_fn(c)
            if m:
                metrics[c] = m
            time.sleep(0.3)
        if not metrics:
            result[chain] = []
            continue
        sc = composite(metrics)
        top = sorted(sc, key=lambda k: sc[k], reverse=True)[:TOPN]
        result[chain] = [{"code": c, "name": NAME.get(c, c), **metrics[c],
                          "score": round(sc[c], 2)} for c in top]
    return result


def main():
    print("=== 美股候選池(ETF 成分股)===")
    upool = us_pool()
    for c, l in upool.items():
        print(f"  {c}: {len(l)} 檔")
    us = screen(upool, us_metrics, "US")
    tw = screen(TW_POOL, tw_metrics, "TW")
    out = {"date": datetime.now().strftime("%Y-%m-%d"), "us": us, "tw": tw}
    json.dump(out, open("screen_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 印出守備清單
    print("\n===== 篩選結果 =====")
    for mkt, data in [("美股", us), ("台股", tw)]:
        print(f"\n【{mkt}】")
        for chain, lst in data.items():
            print(f"  {chain}: " + ", ".join(f"{x['code']}({x['name'][:6]})" for x in lst))
    print("\n✅ → screen_result.json")


if __name__ == "__main__":
    main()
