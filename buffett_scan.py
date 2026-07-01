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
from buffett_sp500 import stage1_prefilter, stage2_yfinance
from buffett_screener import inject_leader_ranks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cap", type=float, default=2e9)
    ap.add_argument("--max-candidates", type=int, default=200)  # Actions 不怕限流，可放寬
    args = ap.parse_args()

    tickers = stage1_prefilter(min_market_cap=args.min_cap, max_candidates=args.max_candidates)
    results = [r for r in stage2_yfinance(tickers) if r]
    inject_leader_ranks(results)

    today = datetime.now().strftime("%Y-%m-%d")
    out = {}
    for r in results:
        if r.get("signal") not in ("BUY", "WATCH"):   # 觀察清單=洪瑞泰品質過關的買進候選
            continue
        out[r["ticker"]] = {
            "sector": r.get("sector"), "rank": r.get("leader_rank"),
            "eps": r.get("eps_ttm"), "roe": r.get("roe_current"),
            "payout": r.get("payout_ratio"), "reinvest": r.get("reinvest_ratio"),
            "cheap": r.get("cheap_price"), "fair": r.get("fair_price"),
            "expensive": r.get("exp_price"), "trap_flags": r.get("trap_flags"),
            "updated": today,
        }
    json.dump(out, open("buffett_watch.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ranked = sum(1 for v in out.values() if v.get("rank"))
    print(f"✅ buffett_watch.json：{len(out)} 檔 BUY/WATCH（龍頭 {ranked}）")


if __name__ == "__main__":
    main()
