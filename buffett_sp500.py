"""
buffett_sp500.py — Plan C: TV-Screener 預篩 + yfinance 4 年回溯
====================================================================
與 buffett_screener.py 的差別：
  - 範圍：全美股市值 ≥ 20 億 → 預篩 PE≤15 + ROE≥15% → 取前 N 檔
  - Stage 1 用 TV snapshot 2 秒篩出 100-300 檔候選
  - Stage 2 對候選跑 yfinance 4 年回溯（拿 reinvest_ratio）
  - 結果寫 DB watchlist（含盈再率）→ /bstatus 觀察清單會顯示 ✅/⚠️/❌

用法：
    python buffett_sp500.py                       # 預設 max=150
    python buffett_sp500.py --max-candidates 100
    python buffett_sp500.py --min-cap 5e9         # 只看 ≥ 50 億市值
"""
import sys, io, os, argparse, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import data_tv
from buffett_screener import (
    fetch_fundamentals, evaluate, write_to_db, inject_leader_ranks,
    PE_CHEAP, PE_FAIR, PE_EXPENSIVE, ROE_MIN,
)


def stage1_prefilter(min_market_cap: float, max_candidates: int) -> list:
    """Stage 1: TV snapshot 全市場 → PE≤15 + ROE≥15% 候選清單"""
    print("=" * 70)
    print(f"  Plan C - Stage 1: TV-Screener 預篩")
    print(f"  市值 ≥ ${min_market_cap:,.0f}, ROE ≥ {ROE_MIN*100:.0f}%, PE ≤ {PE_FAIR}")
    print("=" * 70)

    t0 = time.time()
    count, df = data_tv.get_buffett_snapshot_full_market(
        min_market_cap=min_market_cap,
        min_price=5.0,
        require_positive_eps=True,
    )
    print(f"\n[TV] 拉回 {count} 列原始資料，耗時 {time.time()-t0:.2f} 秒")

    if df is None or df.empty:
        print("⚠️ TV 沒回任何資料")
        return []

    # client-side 篩 ROE + PE
    before = len(df)
    df = df[(df['roe_current'] >= ROE_MIN) & (df['eps_ttm'] > 0)].copy()
    df['pe_implied'] = df['price'] / df['eps_ttm']
    df = df[df['pe_implied'] <= PE_FAIR]   # 還在合理價以下
    df = df.sort_values('pe_implied')

    print(f"[篩選] {before} → {len(df)} 檔（ROE ≥ 15% + PE ≤ {PE_FAIR}）")

    tickers = df['ticker'].head(max_candidates).tolist()
    print(f"[取樣] PE 最低 {len(tickers)} 檔進入 Stage 2\n")
    return tickers


def stage2_yfinance(tickers: list) -> list:
    """Stage 2: yfinance 4 年回溯 + 評估（含盈再率）"""
    print("=" * 70)
    print(f"  Plan C - Stage 2: yfinance 4 年回溯 + 盈再率")
    print(f"  {len(tickers)} 檔，每檔 3-5 秒，預估 {len(tickers)*4/60:.1f} 分鐘")
    print("=" * 70)

    results = []
    total = len(tickers)
    for i, t in enumerate(tickers, 1):
        print(f"  [{i}/{total}] {t} ...", end=" ", flush=True)
        data = fetch_fundamentals(t)
        if data:
            data['universe'] = 'TV_Prefilter'
            ev = evaluate(data)
            results.append(ev)
            print(ev.get('signal', '?'))
        else:
            print("SKIP")
        time.sleep(0.8)   # 拉長間隔降低 yfinance 429 限流（Zeabur 共用 IP）
    return results


def stage3_summary(results: list):
    """Stage 3: 統計 + 寫 DB watchlist"""
    print("\n" + "=" * 70)
    print(f"  Plan C - Stage 3: 寫入 DB 觀察清單")
    print("=" * 70)

    inject_leader_ranks(results)   # 同 sector 依市值標龍頭#1/#2/#3（修排名漏寫）
    write_to_db(results, update_positions=False, auto_watchlist=True)

    # 瘦身：刪掉 >150 天沒被刷新的殭屍標的（upsert 只增不刪，會累積）
    import db
    n_pruned, pruned = db.prune_stale_watchlist(days=150)
    if n_pruned:
        print(f"[瘦身] 移除 {n_pruned} 檔過時觀察標的：{', '.join(pruned[:20])}"
              + (" …" if n_pruned > 20 else ""))

    buy = [r for r in results if r and r.get('signal') == 'BUY']
    watch = [r for r in results if r and r.get('signal') == 'WATCH']

    def is_hong(r):
        rr = r.get('reinvest_ratio')
        return rr is not None and rr < 0.40

    hong_buy = [r for r in buy if is_hong(r)]
    hong_watch = [r for r in watch if is_hong(r)]

    print("\n" + "=" * 70)
    print("  📊 Plan C 完成 — 全市場掃描結果")
    print("=" * 70)
    print(f"  🟢 BUY (現價 ≤ 俗價): {len(buy)} 檔")
    print(f"     └─ 含 ✅ 鐵桿（盈再 < 40%): {len(hong_buy)} 檔")
    print(f"  🟡 WATCH (俗價~合理價): {len(watch)} 檔")
    print(f"     └─ 含 ✅ 鐵桿: {len(hong_watch)} 檔")

    if hong_buy:
        print(f"\n── ✅ 真鐵桿 BUY 清單（推薦優先） ──")
        for r in sorted(hong_buy, key=lambda x: x.get('reinvest_ratio') or 1):
            print(f"  {r['ticker']:<8} 盈再 {r['reinvest_ratio']*100:>5.1f}%  "
                  f"現價 ${r.get('price', 0):>7.2f}  俗價 ${r.get('cheap_price', 0):>7.2f}  "
                  f"{r.get('sector', '')}")

    print(f"\n👉 發 /bwatch 看完整觀察清單（鐵桿股會帶 ✅ 標籤）")


def main():
    ap = argparse.ArgumentParser(description="Plan C: TV-Screener 預篩 + yfinance 回溯")
    ap.add_argument("--min-cap", type=float, default=2e9,
                    help="最小市值（預設 2e9 = 20 億）")
    ap.add_argument("--max-candidates", type=int, default=150,
                    help="Stage 2 處理上限（預設 150 檔，避免 yfinance rate limit）")
    args = ap.parse_args()

    t0 = time.time()

    # Stage 1
    tickers = stage1_prefilter(args.min_cap, args.max_candidates)
    if not tickers:
        return

    # Stage 2
    results = stage2_yfinance(tickers)

    # Stage 3
    stage3_summary(results)

    print(f"\n總耗時 {(time.time()-t0)/60:.1f} 分鐘")


if __name__ == "__main__":
    main()
