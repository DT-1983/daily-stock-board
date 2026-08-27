"""在 GitHub Actions 跑全市場巴菲特掃描 → buffett_watch.json。

取代 Zeabur /bsp500（Zeabur 共用 IP 被 yfinance 限流跑不動）。Actions IP 乾淨、每次輪替。
免 DB、免 /bsync：直接產 buffett_watch.json 給 buffett_html.py / buy_digest.py 用。

流程：Stage1 TV-Screener 全市場預篩(市值+ROE≥15%+PE≤合理) → Stage2 yfinance 4年回溯
（含盈再率）→ 龍頭排名 → 只留 BUY/WATCH（洪瑞泰品質，盈再率<80%）→ 寫 json。

用法:python buffett_scan.py [--max-candidates 200]
"""
import sys
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
            # 2026-08-27：True＝配息率取自前次快取（Yahoo 這次沒給），頁面會標「前次」
            "payout_stale": bool(r.get("payout_stale")),
            # official_tw=FinMind / official_us(_ifrs)(_nolti)=SEC EDGAR
            # capex_fallback=資料不足退回舊算法，僅供參考
            "reinvest_method": r.get("reinvest_method"),
            # 2026-08-25：grade/note 之前算了卻沒寫出去，JSON 裡永遠是 None，
            # 等於「說清楚哪裡異常」這個需求做了一半——前端根本拿不到。
            "reinvest_grade": r.get("reinvest_grade"),
            "reinvest_note": r.get("reinvest_note"),
            "cheap": r.get("cheap_price"), "roe_years": r.get("roe_pass_years"),
            "expensive": r.get("exp_price"), "trap_flags": r.get("trap_flags"),
            "updated": today,
        }
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cap", type=float, default=2e9)          # 美股 USD
    ap.add_argument("--max-candidates", type=int, default=0)       # 0=過篩的全評估（2026-08-25 起）
    ap.add_argument("--tw-min-cap", type=float, default=5e9)       # 台股 50 億 TWD（含中小型高 ROE）
    ap.add_argument("--tw-max-candidates", type=int, default=0)    # 0=過篩的全評估
    ap.add_argument("--markets", default="us,tw",
                    help="要掃的市場，逗號分隔（us / tw）")
    args = ap.parse_args()

    markets = [m.strip().lower() for m in args.markets.split(",") if m.strip()]
    today = datetime.now().strftime("%Y-%m-%d")
    out = {}
    fetch_stats = {}   # market -> (候選數, 評估成功數)

    if "us" in markets:
        tickers = stage1_prefilter(min_market_cap=args.min_cap, max_candidates=args.max_candidates)
        us = [r for r in stage2_yfinance(tickers) if r]
        fetch_stats["US"] = (len(tickers), len(us))
        n_us = _collect(us, "US", today, out)
        print(f"── 美股 BUY/WATCH：{n_us} 檔")

    if "tw" in markets:
        tw_tk = stage1_prefilter_tw(min_market_cap=args.tw_min_cap, max_candidates=args.tw_max_candidates)
        tw = [r for r in stage2_yfinance(tw_tk) if r]
        fetch_stats["TW"] = (len(tw_tk), len(tw))
        n_tw = _collect(tw, "TW", today, out)
        zh = _tw_name_map()                      # 代號→中文名
        if zh:
            for tk, v in out.items():
                if v.get("market") == "TW":
                    code = tk.rsplit(".", 1)[0]           # .TW / .TWO 都剝掉
                    v["name"] = zh.get(code, v.get("name"))
        print(f"── 台股 BUY/WATCH：{n_tw} 檔（中文名 {len(zh)} 檔對照）")

    # ── 完整性防線（2026-08-27，Leo：「跑出來是錯的比沒跑出來嚴重」）──────────
    # 任一市場的資料抓取成功率 < MIN_FETCH_RATE → 整批不寫檔，沿用上一版清單。
    # 背景：8/27 全掃 236 檔有 201 檔被 Yahoo 429 打掉、清單 41→22——SKIP 是
    # 「抓不到資料」不是「品質淘汰」，殘缺清單會讓下游（到俗價觸發/buy_digest/
    # 投資長）把「限流」誤讀成「這些股票不合格/消失」。寧可舊而完整，不要新而殘缺。
    MIN_FETCH_RATE = 0.70
    bad = {m: (c, s) for m, (c, s) in fetch_stats.items() if c > 0 and s / c < MIN_FETCH_RATE}
    if bad:
        detail = "；".join(f"{m} 候選{c}檔只評估到{s}檔（{s/c*100:.0f}%）" for m, (c, s) in bad.items())
        print(f"🔴 完整性防線觸發：{detail} → 不覆蓋 buffett_watch.json，沿用上一版")
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if tok and chat:
            import requests as _rq
            _rq.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                     json={"chat_id": chat, "parse_mode": "HTML",
                           "text": f"🔴 <b>巴菲特掃描資料不完整，本週清單未更新</b>\n{detail}\n"
                                   f"疑似資料源限流，沿用上一版清單（寧舊勿殘）。"},
                     timeout=20)
        sys.exit(0)   # 刻意 exit 0：這是防線正常運作不是程式錯誤，別讓 workflow 紅燈

    json.dump(out, open("buffett_watch.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ranked = sum(1 for v in out.values() if v.get("rank"))
    n_tw_total = sum(1 for v in out.values() if v.get("market") == "TW")
    print(f"✅ buffett_watch.json：{len(out)} 檔 BUY/WATCH（美 {len(out)-n_tw_total} / 台 {n_tw_total}、龍頭 {ranked}）")

    # 盈再率是用哪個方法算的，一定要印出來。
    # 2026-08-24/25 兩次踩到：一批股票安靜退回 capex_fallback，
    # 掃描照樣 exit 0、檔案照樣產生，看起來完全正常，
    # 但那批數字其實是**漏算長期投資的替代算法**。不印出來就發現不了。
    import collections as _c
    from buffett_screener import fm_error_report
    _m = _c.Counter(v.get("reinvest_method") or "無" for v in out.values())
    print("   盈再率來源：" + "、".join(f"{k} {n}" for k, n in _m.most_common()))
    fm_error_report()


if __name__ == "__main__":
    main()
