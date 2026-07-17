"""在 GitHub Actions 跑全市場巴菲特掃描 → buffett_watch.json。

取代 Zeabur /bsp500（Zeabur 共用 IP 被 yfinance 限流跑不動）。Actions IP 乾淨、每次輪替。
免 DB、免 /bsync：直接產 buffett_watch.json 給 buffett_html.py / buy_digest.py 用。

流程：Stage1 TV-Screener 全市場預篩(市值+ROE≥15%+PE≤合理) → Stage2 yfinance 4年回溯
（含盈再率）→ 龍頭排名 → 只留 BUY/WATCH（洪瑞泰品質，盈再率<80%）→ 寫 json。

用法:python buffett_scan.py [--max-candidates 200]
"""
import json
import argparse
from datetime import datetime
import os
from buffett_sp500 import stage1_prefilter, stage1_prefilter_tw, stage2_yfinance
from buffett_screener import inject_leader_ranks


def _tw_name_map():
    """FinMind TaiwanStockInfo → {代號: 中文名}。抓失敗回空 dict（退回英文名）。"""
    import requests
    params = {"dataset": "TaiwanStockInfo"}
    tok = os.environ.get("FINMIND_TOKEN")
    if tok:
        params["token"] = tok
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data", params=params, timeout=30)
        data = r.json().get("data", [])
        return {d["stock_id"]: d["stock_name"] for d in data
                if d.get("stock_id") and d.get("stock_name")}
    except Exception as e:
        print(f"[FinMind 中文名] 失敗：{e}")
        return {}


def _collect(results, market, today, out):
    """把某市場的 BUY/WATCH 結果併入 out（標 market）。"""
    inject_leader_ranks(results)          # 龍頭排名在同市場內算
    n = 0
    for r in results:
        if r.get("signal") not in ("BUY", "WATCH"):
            continue
        out[r["ticker"]] = {
            "market": market,
            "name": r.get("name") or r.get("name_full"),
            "sector": r.get("sector"), "rank": r.get("leader_rank"),
            "eps": r.get("eps_ttm"), "roe": r.get("roe_current"),
            "payout": r.get("payout_ratio"), "reinvest": r.get("reinvest_ratio"),
            "cheap": r.get("cheap_price"), "fair": r.get("fair_price"),
            "expensive": r.get("exp_price"), "trap_flags": r.get("trap_flags"),
            "updated": today,
        }
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cap", type=float, default=2e9)          # 美股 USD
    ap.add_argument("--max-candidates", type=int, default=200)     # 美股 stage2 上限
    ap.add_argument("--tw-min-cap", type=float, default=5e9)       # 台股 50 億 TWD（含中小型高 ROE）
    ap.add_argument("--tw-max-candidates", type=int, default=200)  # 台股 stage2 上限（涵蓋過關全部）
    ap.add_argument("--markets", default="us,tw",
                    help="要掃的市場，逗號分隔（us / tw）")
    args = ap.parse_args()

    markets = [m.strip().lower() for m in args.markets.split(",") if m.strip()]
    today = datetime.now().strftime("%Y-%m-%d")
    out = {}

    if "us" in markets:
        tickers = stage1_prefilter(min_market_cap=args.min_cap, max_candidates=args.max_candidates)
        us = [r for r in stage2_yfinance(tickers) if r]
        n_us = _collect(us, "US", today, out)
        print(f"── 美股 BUY/WATCH：{n_us} 檔")

    if "tw" in markets:
        tw_tk = stage1_prefilter_tw(min_market_cap=args.tw_min_cap, max_candidates=args.tw_max_candidates)
        tw = [r for r in stage2_yfinance(tw_tk) if r]
        n_tw = _collect(tw, "TW", today, out)
        zh = _tw_name_map()                      # 代號→中文名
        if zh:
            for tk, v in out.items():
                if v.get("market") == "TW":
                    code = tk[:-3] if tk.endswith(".TW") else tk
                    v["name"] = zh.get(code, v.get("name"))
        print(f"── 台股 BUY/WATCH：{n_tw} 檔（中文名 {len(zh)} 檔對照）")

    json.dump(out, open("buffett_watch.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ranked = sum(1 for v in out.values() if v.get("rank"))
    n_tw_total = sum(1 for v in out.values() if v.get("market") == "TW")
    print(f"✅ buffett_watch.json：{len(out)} 檔 BUY/WATCH（美 {len(out)-n_tw_total} / 台 {n_tw_total}、龍頭 {ranked}）")


if __name__ == "__main__":
    main()
