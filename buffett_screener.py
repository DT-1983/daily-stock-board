"""
洪瑞泰巴菲特選股篩選器 (Buffett Screener)
==========================================
篩選範圍：S&P 500、Dow Jones 30、S&P 600 小型股
評估標準：洪瑞泰巴菲特方法（ROE、EPS、負債、配息、俗貴價）
產業龍頭：依市值自動排名（同 sector 前三名）

使用方式：
    python buffett_screener.py
    python buffett_screener.py --universe sp500       # 只跑 S&P 500
    python buffett_screener.py --universe dj          # 只跑道瓊 30
    python buffett_screener.py --universe smallcap    # 只跑小型股
    python buffett_screener.py --limit 50             # 只抓前 50 支（測試用）
    python buffett_screener.py --output result.csv    # 指定輸出檔名
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import argparse
import time
import os
from datetime import datetime

# ── 常數設定（洪瑞泰美股版正確倍率，2026-06-10 校正） ──────────────────────
ROE_MIN          = 0.15   # ROE 門檻：15%
ROE_YEARS        = 3      # 連續幾年 ROE 需達標
DEBT_RATIO_MAX   = 1.0    # 負債/淨值比門檻（D/E，yfinance 單位為 %/100）
EPS_LOSS_MAX     = 0      # 近幾年可容忍虧損次數
PE_CHEAP         = 12     # 俗價（EPS×12，預期報酬15%）
PE_FAIR          = 20     # 合理價（EPS×20，報酬6.7%＝定存）— 講稿原文，非 15
PE_EXPENSIVE     = 30     # 貴價（EPS×30，報酬0%）— 講稿原文，非 20
REINVEST_IDEAL   = 0.40   # 盈再率理想門檻（< 40% = 真洪瑞泰）
REINVEST_MAX     = 0.80   # 盈再率上限（> 80% 拒絕）
LEADER_TOP_N     = 3      # 產業龍頭顯示前幾名

OUTPUT_DIR       = "screener_output"

# ── DB 整合 ───────────────────────────────────────────

def get_db_position_tickers() -> list[str]:
    """從 DB 取得 Firstrade 持倉 tickers"""
    import db
    db.init_db()
    positions = db.get_positions()
    tickers = [row[0] for row in positions]
    print(f"[DB Positions] {len(tickers)} 支持倉")
    return tickers

def write_to_db(results: list[dict], update_positions: bool, auto_watchlist: bool):
    """將評估結果寫回 DB"""
    import db
    db.init_db()
    pos_count = wl_count = 0

    for r in results:
        if not r:
            continue
        ticker = r.get("ticker")

        if update_positions:
            db.update_position_fundamentals(
                ticker=ticker,
                sector=r.get("sector"),
                eps=r.get("eps_ttm"),
                roe=r.get("roe_current"),
                payout_ratio=r.get("payout_ratio"),
                reinvestment_ratio=r.get("reinvest_ratio"),
                cheap_price=r.get("cheap_price"),
                fair_price=r.get("fair_price"),
                expensive_price=r.get("exp_price"),
            )
            db.set_position_rank(ticker, r.get("leader_rank"))   # 龍頭排名（含清空非龍頭）
            db.set_position_trap(ticker, r.get("trap_flags"))    # 照妖鏡標籤（含清空）
            pos_count += 1

        if auto_watchlist and r.get("signal") in ("BUY", "WATCH"):
            db.upsert_watchlist(
                ticker=ticker,
                sector=r.get("sector"),
                rank=r.get("leader_rank"),                       # ← 補上龍頭排名
                eps=r.get("eps_ttm"),
                roe=r.get("roe_current"),
                payout_ratio=r.get("payout_ratio"),
                reinvestment_ratio=r.get("reinvest_ratio"),
                cheap_price=r.get("cheap_price"),
                fair_price=r.get("fair_price"),
                expensive_price=r.get("exp_price"),
                trap_flags=r.get("trap_flags"),                  # ← 照妖鏡標籤
            )
            wl_count += 1

    if update_positions:
        print(f"[DB] 更新 {pos_count} 筆持倉基本面")
    if auto_watchlist:
        print(f"[DB] 新增/更新 {wl_count} 筆觀察清單（BUY+WATCH）")
        # 清掉「本次掃到、但已掉出 BUY/WATCH」的舊標的（盈再率關卡淘汰的地雷等）
        keep = {r.get("ticker") for r in results if r and r.get("signal") in ("BUY", "WATCH")}
        scanned = {r.get("ticker") for r in results if r}
        removed = 0
        for row in db.get_watchlist():
            tk = row[0]
            if tk in scanned and tk not in keep:
                db.remove_from_watchlist(tk)
                removed += 1
        if removed:
            print(f"[DB] 移除 {removed} 筆已掉出 BUY/WATCH 的舊標的（含盈再率地雷）")

# ── 股票池來源 ─────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    """從 Wikipedia 抓 S&P 500 成份股清單"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=15)
        resp.raise_for_status()
        from io import StringIO
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0]
        tickers = df["Symbol"].tolist()
        tickers = [t.replace(".", "-") for t in tickers]
        print(f"[S&P 500] 取得 {len(tickers)} 支")
        return tickers
    except Exception as e:
        print(f"[S&P 500] 無法取得清單：{e}")
        return []

def get_dj_tickers() -> list[str]:
    """道瓊 30 成份股（固定清單）"""
    tickers = [
        "AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW",
        "GS","HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM",
        "MRK","MSFT","NKE","PG","TRV","UNH","V","VZ","WBA","WMT"
    ]
    print(f"[Dow Jones] {len(tickers)} 支")
    return tickers

def get_smallcap_tickers() -> list[str]:
    """從 Wikipedia 抓 S&P 600 小型股成份股"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
    try:
        tables = pd.read_html(url)
        # 嘗試找包含 Ticker 欄位的 table
        for t in tables:
            cols = [c.lower() for c in t.columns]
            if any("ticker" in c or "symbol" in c for c in cols):
                col = next(c for c in t.columns if "ticker" in c.lower() or "symbol" in c.lower())
                tickers = t[col].dropna().tolist()
                tickers = [str(x).replace(".", "-") for x in tickers]
                print(f"[S&P 600 Small Cap] 取得 {len(tickers)} 支")
                return tickers
        print("[S&P 600] 找不到 Ticker 欄位，改用備用清單")
        return _smallcap_fallback()
    except Exception as e:
        print(f"[S&P 600] 無法取得清單：{e}，改用備用清單")
        return _smallcap_fallback()

def _smallcap_fallback() -> list[str]:
    """S&P 600 備用（部分代表性小型股）"""
    return [
        "ACLS","AEIS","AGIO","ALKS","AMSF","ANDE","ANF","APOG","ARI","AWR",
        "BANF","BCPC","BDC","BOOT","BRC","CAKE","CALM","CATO","CBRL","CBT",
        "CENTA","CFB","CHCO","CLFD","CMCO","CNXN","COLL","CPK","CROX","CSWI",
        "CUBI","DAN","DCOM","DLX","DSGN","EFC","EGP","EME","ENVA","ESE",
        "FCFS","FHB","FISI","FIZZ","FLXS","FULT","GFF","GIII","GMS","GPOR",
        "HAIN","HAYN","HCSG","HELE","HIFS","HMN","HONE","HRLY","HZO","IBP",
        "IIIN","INVA","IOSP","JACK","JBSS","JOUT","KAR","KELYA","KMPR","KTOS",
        "LANC","LMAT","LNDC","LQDT","LSTR","LWAY","MANT","MASI","MGEE","MGRC",
        "MINI","MMI","MNSB","MNST","MOG-A","MRTN","MTRN","NATR","NBTB","NKSH",
    ]

def get_combined_universe(include: list[str], limit: int = 0) -> pd.DataFrame:
    """合併多個股票池，標記來源，去重"""
    records = []
    if "sp500" in include:
        for t in get_sp500_tickers():
            records.append({"ticker": t, "universe": "S&P500"})
    if "dj" in include:
        for t in get_dj_tickers():
            records.append({"ticker": t, "universe": "DJ30"})
    if "smallcap" in include:
        for t in get_smallcap_tickers():
            records.append({"ticker": t, "universe": "SmallCap"})

    if not records:
        print("[Universe] 無法取得任何股票池，請檢查網路")
        return pd.DataFrame(columns=["ticker", "universe"])

    df = pd.DataFrame(records)
    # 若同一 ticker 出現在多個池，合併標記（例如 AAPL → "DJ30,S&P500"）
    df = df.groupby("ticker")["universe"].apply(lambda x: ",".join(sorted(set(x)))).reset_index()

    if limit > 0:
        df = df.head(limit)
        print(f"[限制模式] 只處理前 {limit} 支")

    print(f"[Universe] 合計 {len(df)} 支（去重後）")
    return df

# ── 基本面資料抓取 ─────────────────────────────────────

def fetch_fundamentals(ticker: str) -> dict:
    """
    使用 yfinance 抓取個股基本面資料
    回傳 dict，失敗則回傳 None
    """
    try:
        stock = yf.Ticker(ticker)
        # 429 重試+退避（Zeabur 共用 IP 容易被 yfinance 限流）
        info = None
        for attempt in range(4):
            try:
                info = stock.info
                if info and info.get("symbol"):
                    break
            except Exception as e:
                if "Too Many Requests" not in str(e) and "429" not in str(e):
                    raise
            time.sleep(2 ** attempt)        # 1, 2, 4, 8 秒退避
        if not info:
            print(f"  [{ticker}] 限流重試後仍失敗")
            return None

        # 基本資訊
        name        = info.get("longName") or info.get("shortName", ticker)
        sector      = info.get("sector", "Unknown")
        industry    = info.get("industry", "Unknown")
        market_cap  = info.get("marketCap", 0) or 0
        price       = info.get("currentPrice") or info.get("regularMarketPrice", 0)

        # 當期指標
        roe_current    = info.get("returnOnEquity")         # 小數，例如 0.25 = 25%
        eps_ttm        = info.get("trailingEps")            # 最近四季
        eps_forward    = info.get("forwardEps")             # 未來四季預估（照妖鏡用）
        debt_to_equity = info.get("debtToEquity")           # yfinance 單位是 %（例如 150 = 1.5x）
        dividend_yield = info.get("dividendYield")          # 小數
        payout_ratio   = info.get("payoutRatio")

        # 歷史 EPS（從年度財務報表）
        eps_history = []
        try:
            financials = stock.financials  # 欄位是日期，row 是項目
            if not financials.empty and "Net Income" in financials.index:
                shares_row = None
                # 嘗試從 info 取 shares outstanding
                shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
                if shares and shares > 0:
                    net_income_row = financials.loc["Net Income"].dropna()
                    for ni in net_income_row.values[:4]:  # 最近 4 年
                        eps_history.append(round(float(ni) / float(shares), 4))
        except Exception:
            pass

        # 歷史 ROE（從資產負債表 + 損益表計算）
        roe_history = []
        try:
            balance_sheet = stock.balance_sheet
            fin           = stock.financials
            if not balance_sheet.empty and not fin.empty:
                eq_label = next((r for r in balance_sheet.index
                                 if "stockholder" in r.lower() or "equity" in r.lower()), None)
                ni_label = next((r for r in fin.index
                                 if "net income" in r.lower()), None)
                if eq_label and ni_label:
                    equity_series = balance_sheet.loc[eq_label].dropna()
                    ni_series     = fin.loc[ni_label].dropna()
                    for col in equity_series.index[:4]:
                        if col in ni_series.index:
                            eq = float(equity_series[col])
                            ni = float(ni_series[col])
                            if eq > 0:
                                roe_history.append(round(ni / eq, 4))
        except Exception:
            pass

        # 盈再率（洪瑞泰核心指標）：|CapEx 累積| / Net Income 累積
        # < 40% = 理想；< 80% = 可接受；>= 80% = 拒絕
        reinvest_ratio = None
        try:
            cf = stock.cashflow
            fi = stock.financials
            if not cf.empty and not fi.empty:
                capex_label = next((r for r in cf.index
                                    if "capital expenditure" in r.lower()), None)
                ni_label = next((r for r in fi.index
                                 if "net income" in r.lower()), None)
                if capex_label and ni_label:
                    capex_sum = abs(cf.loc[capex_label].dropna()).sum()
                    ni_sum = fi.loc[ni_label].dropna().sum()
                    if ni_sum > 0:
                        reinvest_ratio = round(float(capex_sum / ni_sum), 4)
        except Exception:
            pass

        return {
            "ticker":        ticker,
            "name":          name,
            "sector":        sector,
            "industry":      industry,
            "market_cap":    market_cap,
            "price":         price,
            "roe_current":   roe_current,
            "roe_history":   roe_history,
            "eps_ttm":       eps_ttm,
            "eps_forward":   eps_forward,
            "eps_history":   eps_history,
            "debt_to_equity": debt_to_equity,  # yfinance 單位：% (150 = 150%)
            "dividend_yield": dividend_yield,
            "payout_ratio":  payout_ratio,
            "reinvest_ratio": reinvest_ratio,  # 洪瑞泰盈再率
        }

    except Exception as e:
        print(f"  [{ticker}] 抓取失敗：{e}")
        return None

# ── 洪瑞泰評估邏輯 ─────────────────────────────────────

def evaluate(data: dict) -> dict:
    """
    對單支股票執行洪瑞泰所有評估項目
    回傳含評分與計算結果的 dict
    """
    result = {**data}

    eps  = data.get("eps_ttm") or 0
    roe  = data.get("roe_current") or 0
    d_e  = data.get("debt_to_equity") or 0
    price = data.get("price") or 0

    # ── 1. 俗價 / 合理價 / 貴價 ──────────────────────────
    # 美股因 NAV 常為負，採 EPS 倍數法
    cheap_price = round(eps * PE_CHEAP, 2) if eps > 0 else None
    fair_price  = round(eps * PE_FAIR,  2) if eps > 0 else None
    exp_price   = round(eps * PE_EXPENSIVE, 2) if eps > 0 else None

    result["cheap_price"] = cheap_price
    result["fair_price"]  = fair_price
    result["exp_price"]   = exp_price

    # 現價 vs 各價位
    if price and cheap_price:
        result["price_vs_cheap"] = round(price / cheap_price, 2)  # < 1 = 低於俗價
    else:
        result["price_vs_cheap"] = None

    # ── 2. ROE 評估 ──────────────────────────────────────
    roe_pass_current = roe >= ROE_MIN if roe else False

    roe_hist = data.get("roe_history", [])
    roe_pass_years = sum(1 for r in roe_hist if r and r >= ROE_MIN)

    result["roe_pass_current"] = roe_pass_current
    result["roe_pass_years"]   = roe_pass_years      # 歷史幾年 ROE > 15%
    result["roe_history_str"]  = " / ".join(f"{r*100:.1f}%" for r in roe_hist) if roe_hist else "N/A"

    # ── 3. EPS 穩定性 ────────────────────────────────────
    eps_hist = data.get("eps_history", [])
    eps_loss_count  = sum(1 for e in eps_hist if e and e < 0)
    eps_growing     = len(eps_hist) >= 2 and all(
        eps_hist[i] <= eps_hist[i+1] for i in range(len(eps_hist)-1)
    ) if eps_hist else False

    result["eps_history_str"] = " / ".join(f"{e:.2f}" for e in eps_hist) if eps_hist else "N/A"
    result["eps_loss_count"]  = eps_loss_count
    result["eps_growing"]     = eps_growing

    # ── 4. 負債評估 ──────────────────────────────────────
    # yfinance debtToEquity 單位為 % (例如 150 代表 D/E = 1.5)
    # 洪瑞泰建議 D/E 不要過高；金融業例外
    debt_ratio_norm = d_e / 100 if d_e else None
    debt_pass = debt_ratio_norm <= DEBT_RATIO_MAX if debt_ratio_norm is not None else None
    is_financial = any(k in (data.get("sector","")).lower()
                       for k in ["financial", "bank", "insurance"])

    result["debt_ratio_norm"] = debt_ratio_norm
    result["debt_pass"]       = debt_pass
    result["is_financial"]    = is_financial  # 金融業負債比標準不同，標記即可

    # ── 照妖鏡（補充層，不改洪瑞泰訊號）──────────────────────
    # 俗價=trailing EPS×12 只回頭看；這裡用 forward EPS + 負債抓「便宜有理由」的價值陷阱
    trap = []
    te, fe = data.get("eps_ttm"), data.get("eps_forward")
    if te and fe and te > 0 and (fe / te) < 0.90:
        trap.append(f"EPS估降{(1-fe/te)*100:.0f}%")
    if d_e and not is_financial and d_e > 250:   # 金融業負債本高，不算
        trap.append(f"高負債{d_e:.0f}%")
    result["trap_flags"] = "、".join(trap) if trap else None

    # ── 5. 配息評估 ──────────────────────────────────────
    div_yield = data.get("dividend_yield") or 0
    result["has_dividend"] = div_yield > 0
    result["dividend_pct"] = f"{div_yield*100:.2f}%" if div_yield else "無配息"

    # ── 6. 綜合訊號 ──────────────────────────────────────
    # 訊號邏輯（洪瑞泰）：
    #   BUY  = ROE達標 + EPS正 + 盈再率<80% + 現價<=俗價
    #   WATCH= ROE達標 + EPS正 + 盈再率<80% + 俗價<現價<=合理價
    #   HOLD = 現價 在合理價~貴價之間
    #   SELL = 現價 >= 貴價
    #   SKIP = 基本面不達標（含盈再率>=80% 的便宜地雷）
    # 盈再率關：>=80%（非金融）= 吃資本爛生意，不給 BUY/WATCH（洪瑞泰核心）
    rr = data.get("reinvest_ratio")
    reinvest_ok = is_financial or rr is None or rr < 0.80
    signal = "SKIP"
    if roe_pass_current and eps > 0:
        if price and cheap_price and exp_price and fair_price:
            if price <= cheap_price:
                signal = "BUY" if reinvest_ok else "SKIP"
            elif price <= fair_price:
                signal = "WATCH" if reinvest_ok else "SKIP"
            elif price < exp_price:
                signal = "HOLD"
            else:
                signal = "SELL"
        else:
            signal = "DATA_MISSING"

    signal_emoji = {
        "BUY":          "🟢 低於俗價，可買進",
        "WATCH":        "🟡 俗價~合理價，觀察",
        "HOLD":         "🔵 合理價~貴價，持有",
        "SELL":         "🔴 高於貴價，考慮賣出",
        "SKIP":         "⬜ 基本面不達標",
        "DATA_MISSING": "❓ 資料不足",
    }.get(signal, signal)

    result["signal"]       = signal
    result["signal_emoji"] = signal_emoji

    return result

# ── 產業龍頭排名 ──────────────────────────────────────

def rank_industry_leaders(df: pd.DataFrame) -> pd.DataFrame:
    """
    在同一 sector 內按市值排名，標記前 LEADER_TOP_N 名為龍頭
    """
    df = df.copy()
    df["leader_rank"] = None

    for sector, group in df.groupby("Sector"):
        if sector in ("Unknown", None, ""):
            continue
        ranked = group.sort_values("MarketCap_B", ascending=False)
        for i, idx in enumerate(ranked.index[:LEADER_TOP_N]):
            df.at[idx, "leader_rank"] = i + 1  # 1 = 龍頭

    return df


def inject_leader_ranks(results: list[dict]) -> None:
    """直接把產業龍頭排名寫進 result dict（同 sector 依市值前 N 名 = 龍頭）。
    原本 rank_industry_leaders 只算進 df（報告用），DB 寫的是 all_results → 排名漏寫。
    這裡就地注入，讓 DB 也拿得到。同市值排名邏輯，不動洪瑞泰估值。"""
    from collections import defaultdict
    bysec = defaultdict(list)
    for r in results:
        if not r:
            continue
        r["leader_rank"] = None  # 先清空 → 每次重評，非龍頭不殘留舊排名
        if r.get("sector") not in ("Unknown", None, "") and r.get("market_cap"):
            bysec[r["sector"]].append(r)
    for sector, group in bysec.items():
        group.sort(key=lambda r: r["market_cap"], reverse=True)
        for i, r in enumerate(group[:LEADER_TOP_N]):
            r["leader_rank"] = i + 1  # 1 = 龍頭

# ── 輸出報告 ──────────────────────────────────────────

def build_report_df(results: list[dict]) -> pd.DataFrame:
    """將評估結果整理成 DataFrame"""
    rows = []
    for r in results:
        if not r:
            continue
        rows.append({
            "Ticker":        r.get("ticker"),
            "Name":          r.get("name"),
            "Universe":      r.get("universe", ""),
            "Sector":        r.get("sector"),
            "Industry":      r.get("industry"),
            "LeaderRank":    r.get("leader_rank"),
            "Signal":        r.get("signal_emoji"),
            "Price":         r.get("price"),
            "CheapPrice":    r.get("cheap_price"),
            "FairPrice":     r.get("fair_price"),
            "ExpPrice":      r.get("exp_price"),
            "Price/Cheap":   r.get("price_vs_cheap"),
            "EPS_TTM":       r.get("eps_ttm"),
            "EPS_History":   r.get("eps_history_str"),
            "EPS_Growing":   r.get("eps_growing"),
            "EPS_LossYears": r.get("eps_loss_count"),
            "ROE_Current":   f"{r['roe_current']*100:.1f}%" if r.get("roe_current") else "N/A",
            "ROE_PassYears": r.get("roe_pass_years"),
            "ROE_History":   r.get("roe_history_str"),
            "DebtRatio_DE":  f"{r['debt_ratio_norm']:.2f}" if r.get("debt_ratio_norm") is not None else "N/A",
            "DebtPass":      r.get("debt_pass"),
            "IsFinancial":   r.get("is_financial"),
            "DividendYield": r.get("dividend_pct"),
            "MarketCap_B":   round(r["market_cap"] / 1e9, 1) if r.get("market_cap") else None,
        })
    return pd.DataFrame(rows)

def print_summary(df: pd.DataFrame):
    """在終端印出重點摘要"""
    print("\n" + "="*60)
    print(f"  篩選完成：共 {len(df)} 支")
    print("="*60)

    signal_counts = df["Signal"].value_counts()
    for sig, cnt in signal_counts.items():
        print(f"  {sig}：{cnt} 支")

    print("\n── 🟢 BUY 清單（現價低於俗價）──")
    buy = df[df["Signal"].str.contains("BUY", na=False)].sort_values("Price/Cheap")
    for _, row in buy.iterrows():
        leader = f" 龍頭#{int(row['LeaderRank'])}" if pd.notna(row['LeaderRank']) else ""
        print(f"  {row['Ticker']:<8} {row['Name']:<30}{leader}")
        print(f"           現價: ${row['Price']:.2f}  俗價: ${row['CheapPrice']:.2f}  "
              f"ROE: {row['ROE_Current']}  EPS: {row['EPS_TTM']:.2f}")

    print("\n── 🟡 WATCH 清單（俗價~合理價）──")
    watch = df[df["Signal"].str.contains("WATCH", na=False)].sort_values("Price/Cheap")
    for _, row in watch.head(20).iterrows():
        leader = f" 龍頭#{int(row['LeaderRank'])}" if pd.notna(row['LeaderRank']) else ""
        print(f"  {row['Ticker']:<8} {row['Name']:<30}{leader}  現價/俗價={row['Price/Cheap']:.2f}")

def save_outputs(df: pd.DataFrame, timestamp: str):
    """儲存 CSV 與 Markdown 摘要"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 全部結果 CSV
    csv_path = os.path.join(OUTPUT_DIR, f"screener_{timestamp}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[輸出] 完整結果：{csv_path}")

    # 只輸出 BUY + WATCH 的摘要 CSV
    actionable = df[df["Signal"].str.contains("BUY|WATCH", na=False)]
    if not actionable.empty:
        action_path = os.path.join(OUTPUT_DIR, f"watchlist_{timestamp}.csv")
        actionable.to_csv(action_path, index=False, encoding="utf-8-sig")
        print(f"[輸出] 觀察清單（BUY+WATCH）：{action_path}")

# ── 主流程 ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="洪瑞泰巴菲特篩選器")
    parser.add_argument("--universe", default="all",
                        help="sp500 / dj / smallcap / all（預設 all）")
    parser.add_argument("--limit", type=int, default=0,
                        help="只處理前 N 支（測試用，0=全部）")
    parser.add_argument("--output", default="",
                        help="輸出 CSV 檔名（預設自動命名）")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="每支股票請求間隔秒數（預設 0.3）")
    parser.add_argument("--positions-only", action="store_true",
                        help="只處理 DB 裡的 Firstrade 持倉（不跑全市場）")
    parser.add_argument("--tickers", default="",
                        help="自訂 ticker 清單（逗號分隔），優先於 --universe / --positions-only")
    parser.add_argument("--tickers-from-csv", default="",
                        help="從 actionable CSV 讀 BUY+WATCH tickers")
    parser.add_argument("--update-db", action="store_true",
                        help="將 EPS/俗貴價結果寫回 DB 持倉（需搭配 --positions-only）")
    parser.add_argument("--auto-watchlist", action="store_true",
                        help="將 BUY+WATCH 訊號自動寫入 DB 觀察清單")
    args = parser.parse_args()

    # 決定股票池
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        universe_df = pd.DataFrame([{"ticker": t, "universe": "Custom"} for t in tickers])
        print(f"[Custom] 自訂 {len(tickers)} 支 ticker")
    elif args.tickers_from_csv:
        csv_df = pd.read_csv(args.tickers_from_csv)
        tickers = csv_df['Ticker'].dropna().unique().tolist()
        universe_df = pd.DataFrame([{"ticker": t, "universe": "FromCSV"} for t in tickers])
        print(f"[FromCSV] 從 {args.tickers_from_csv} 讀 {len(tickers)} 支 ticker")
    elif args.positions_only:
        tickers = get_db_position_tickers()
        universe_df = pd.DataFrame([{"ticker": t, "universe": "Firstrade"} for t in tickers])
    else:
        if args.universe == "all":
            include = ["sp500", "dj", "smallcap"]
        else:
            include = [args.universe]
        universe_df = get_combined_universe(include, limit=args.limit)

    # 逐支抓資料 + 評估
    all_results = []
    total = len(universe_df)
    for i, row in universe_df.iterrows():
        ticker = row["ticker"]
        universe_label = row["universe"]
        print(f"  [{i+1}/{total}] {ticker} ({universe_label}) ...", end=" ", flush=True)

        data = fetch_fundamentals(ticker)
        if data:
            data["universe"] = universe_label
            evaluated = evaluate(data)
            all_results.append(evaluated)
            sig = evaluated.get("signal", "?")
            print(sig)
        else:
            print("SKIP")

        time.sleep(args.delay)

    # 產業龍頭排名：先就地注入 all_results（DB 用），再建 df（報告用）
    inject_leader_ranks(all_results)

    # 整理成 DataFrame
    df = build_report_df(all_results)
    df = rank_industry_leaders(df)   # df 報告再算一次（同邏輯，保險）

    # 寫回 DB（在 print 之前，避免 encoding 問題導致 DB 未更新）
    if args.update_db or args.auto_watchlist:
        write_to_db(all_results,
                    update_positions=args.update_db,
                    auto_watchlist=args.auto_watchlist)

    # 儲存輸出
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    save_outputs(df, timestamp)

    # 印出摘要
    print_summary(df)

if __name__ == "__main__":
    main()
