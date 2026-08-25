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

import json
import ssl
import urllib.request

import data_tv
from buffett_screener import (
    fetch_fundamentals, evaluate, write_to_db, inject_leader_ranks,
    PE_CHEAP, PE_FAIR, PE_EXPENSIVE, ROE_MIN,
)

# ── Stage 1 預篩門檻：依洪瑞泰講稿原文（2026-08-25 對齊）──────────────
# 講稿 1190-1206 行他親口講篩選器怎麼設：
#   台股（網龍大富翁）：ROE 最近 3 年至少 15%、本益比 < 15
#   美股（Finviz）    ：S&P 500、本益比 < 15、ROE 10% 以上
#                       「為什麼 10%？初步篩選條件放寬一點。」
#
# ⚠️ 這裡的 PE 15 是**初步篩選**用的，跟賣出線 PE_EXPENSIVE=30（貴價）不同層次，
#    兩個都要存在。先前把預篩門檻設成 30 是拿賣出線當篩選線——
#    等於把「快到賣點」的股票也收進觀察池，觀察它沒有意義。
PE_SCREEN     = 15     # 初篩本益比上限（講稿：兩國都是 15）
ROE_SCREEN_US = 0.10   # 美股初篩 ROE（他刻意放寬到 10%，真正把關在盈再表那關）
ROE_SCREEN_TW = 0.15   # 台股初篩 ROE
# ⚠️ 2026-08-25 查證：講稿台股條件是「最近3年至少15%」，
#   但 TradingView 快照**沒有近3年 ROE 欄位**，只有當期值
#   （試過 return_on_equity|1Y / _fy_h / ROEfy1 等命名，全部回 None，非 TV 支援範圍）。
#   所以這裡只能先用當期值快篩，真正的「近4年至少3年達標」硬關卡在 Stage2
#   （evaluate() 的 roe_pass_years >= ROE_YEARS，見下方 stage2_yfinance）。
#   代價：極少數當期 ROE 剛好一年不達標的公司，會在 Stage1 就被濾掉、進不了 Stage2
#   複查——目前未觀察到實際案例。若要根治需 Stage1 也逐檔查 yfinance 歷史，
#   但那會讓 Stage1 失去「快速預篩」的意義（等於整批候選都先跑一次 Stage2 的成本）。
#   2026-08-25 已與用戶討論，維持現狀。

_SP500_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".fm_cache", "sp500_members.json")
_SP500_TTL = 30 * 86400      # 成分股一季才調整一次，快取 30 天


def sp500_members():
    """S&P 500 成分股代號集合。抓不到回 None（呼叫端要當「不知道」處理，不是空集合）。

    洪瑞泰美股篩選器限定 S&P 500。我們先前掃全市場（NASDAQ+NYSE+AMEX 1,674 檔），
    結果清單長成一堆 ADR（NVO/ITUB/CIG）＋航運（BWLP/HAFN/TRMD）＋MLP——
    這些在他的篩選器裡本來就進不來。

    TradingView 的 index / indexes_tickers 欄位實測是空的，只能另外抓成分股清單。
    """
    try:
        if time.time() - os.path.getmtime(_SP500_CACHE) < _SP500_TTL:
            with open(_SP500_CACHE, encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    try:
        import pandas as pd
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=45, context=ctx).read().decode("utf-8")
        tbl = pd.read_html(io.StringIO(html))[0]
        syms = {str(s).strip().upper() for s in tbl["Symbol"]}
        # BRK.B / BF.B：Wikipedia 用點、各家資料源有用 dash 的，兩種都收
        syms |= {s.replace(".", "-") for s in syms if "." in s}
        if len(syms) < 400:                     # 明顯抓壞就當失敗，不要用半套清單去篩
            return None
        os.makedirs(os.path.dirname(_SP500_CACHE), exist_ok=True)
        with open(_SP500_CACHE, "w", encoding="utf-8") as f:
            json.dump(sorted(syms), f)
        return syms
    except Exception as e:                      # noqa: BLE001
        print(f"⚠️ 抓 S&P 500 成分股失敗：{e}")
        return None



def _take_candidates(df, max_candidates, label):
    """決定哪些過篩股票進 Stage 2。

    2026-08-25 修：原本是 `df.sort_values('pe_implied').head(200)`——
    **拿便宜當主排序再截斷**。美股過篩 585 檔卻只算最便宜的 200 檔，385 檔連算都沒算；
    台股 305 → 200。被砍掉的正好是 PE 相對高、但品質可能更好的那一段。

    這正是記憶庫「跑偏史 ②」那條通則：
      「永遠不用便宜／折價當主排序，便宜是最後一關買點不是選股標準」
    洪瑞泰的順序是**先挑好公司、再等便宜**。
    ROE≥15% 與 PE≤30 都已經是他自己的條件（PE≤30 就是貴價線），
    過關的就該全部評估，不該再用第三個標準（便宜程度）去砍。

    max_candidates <= 0 → 全部取用（現在的預設）。
    真要設上限就改用 **ROE 由高到低**（品質優先），而且**一定要印出砍掉多少**——
    靜默截斷會讓人以為「全掃過了」。
    """
    df = df.sort_values("roe_current", ascending=False)
    if max_candidates and 0 < max_candidates < len(df):
        kept = df.head(max_candidates)
        print(f"[取樣] ⚠️ 上限 {max_candidates} 檔（ROE 由高到低），"
              f"**{len(df) - max_candidates} 檔未評估**"
              f"——最低被保留的 ROE={kept['roe_current'].iloc[-1]:.1%}")
        return kept["ticker"].tolist()
    print(f"[取樣] {label}過篩 {len(df)} 檔全部進入 Stage 2（未截斷）")
    return df["ticker"].tolist()


def stage1_prefilter(min_market_cap: float, max_candidates: int) -> list:
    """Stage 1（美股）：S&P 500 + PE < 15 + ROE ≥ 10%（洪瑞泰 Finviz 設定）"""
    print("=" * 70)
    print(f"  Plan C - Stage 1: TV-Screener 預篩（對齊洪瑞泰講稿）")
    print(f"  S&P 500 + 市值 ≥ ${min_market_cap:,.0f}"
          f"，ROE ≥ {ROE_SCREEN_US*100:.0f}%，PE ≤ {PE_SCREEN}")
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

    # client-side 篩 S&P 500 + ROE + PE（順序照講稿：先限指數成分，再看品質與價格）
    before = len(df)
    members = sp500_members()
    if members:
        df = df[df['ticker'].astype(str).str.upper().isin(members)].copy()
        print(f"[S&P500] {before} → {len(df)} 檔（限指數成分股）")
    else:
        # 抓不到成分股就照實說並掃全市場，不要假裝篩過了
        print("⚠️ 拿不到 S&P 500 成分股，本次改掃全市場——"
              "清單會混入 ADR/航運/MLP，與洪瑞泰篩選器不一致")
    df = df[(df['roe_current'] >= ROE_SCREEN_US) & (df['eps_ttm'] > 0)].copy()
    df['pe_implied'] = df['price'] / df['eps_ttm']
    df = df[df['pe_implied'] <= PE_SCREEN]
    print(f"[篩選] {before} → {len(df)} 檔"
          f"（ROE ≥ {ROE_SCREEN_US*100:.0f}% + PE ≤ {PE_SCREEN}）")
    return _take_candidates(df, max_candidates, "美股")


def stage1_prefilter_tw(min_market_cap: float, max_candidates: int) -> list:
    """Stage 1（台股）：PE < 15 + ROE ≥ 15%（洪瑞泰網龍大富翁設定）"""
    print("=" * 70)
    print(f"  台股 Stage 1: TV-Screener 預篩（TWSE+TPEX，對齊洪瑞泰講稿）")
    print(f"  市值 ≥ NT${min_market_cap:,.0f}"
          f"，ROE ≥ {ROE_SCREEN_TW*100:.0f}%，PE ≤ {PE_SCREEN}")
    print("=" * 70)
    t0 = time.time()
    count, df = data_tv.get_buffett_snapshot_taiwan(
        min_market_cap=min_market_cap, min_price=5.0, require_positive_eps=True)
    print(f"\n[TV] 拉回 {count} 列台股，耗時 {time.time()-t0:.2f} 秒")
    if df is None or df.empty:
        print("⚠️ TV 台股沒回資料")
        return []
    before = len(df)
    df = df[(df['roe_current'] >= ROE_SCREEN_TW) & (df['eps_ttm'] > 0)].copy()
    df['pe_implied'] = df['price'] / df['eps_ttm']
    df = df[df['pe_implied'] <= PE_SCREEN]
    print(f"[篩選] {before} → {len(df)} 檔"
          f"（ROE ≥ {ROE_SCREEN_TW*100:.0f}% + PE ≤ {PE_SCREEN}）")
    return _take_candidates(df, max_candidates, "台股")


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
    print(f"  🟡 WATCH (俗價~貴價): {len(watch)} 檔")
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
