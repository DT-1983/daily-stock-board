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
import re
import requests
import argparse
import time
import json
import os
from datetime import datetime

# ── 常數設定（洪瑞泰美股版正確倍率，2026-06-10 校正） ──────────────────────
ROE_MIN          = 0.15   # ROE 門檻：15%
ROE_YEARS        = 3      # 連續幾年 ROE 需達標
DEBT_RATIO_MAX   = 1.0    # 負債/淨值比門檻（D/E，yfinance 單位為 %/100）
EPS_LOSS_MAX     = 0      # 近幾年可容忍虧損次數
PE_CHEAP         = 12     # 【2026-08-27 起棄用於訊號】舊俗價倍數（EPS×12）。
                          #   對照 MIKEON 官方盈再表 5 檔實測後發現官方淑價=貴價÷1.15^8
                          #   （≈EPS×9.81，8年年化15%的折現，跟他部落格「房子8年漲3.05倍」
                          #   同一邏輯），×12 是二手簡化版。常數保留給舊報表相容。
PE_FAIR          = 20     # 合理價（EPS×20）— 2026-07-31 起【不參與訊號判斷】，僅保留給
                          #   Stage1 預篩的向下相容；洪瑞泰只設俗/貴兩條線
PE_EXPENSIVE     = 30     # 貴價（EPS×30，報酬0%）＝ 賣出線
CHEAP_DISCOUNT   = 1.15 ** 8   # 淑價 = 貴價 ÷ 1.15^8（=3.059）。2026-08-27 用 Leo 跑的
                          #   MIKEON 官方盈再表（BMY/PSX/DAL/TROW/VZ）逆推驗證：
                          #   4/5 檔精確吻合（TROW 疑似觸發 NAV 地板規則，未實作，
                          #   影響方向是我們略保守，安全側）。
REINVEST_IDEAL   = 0.40   # 盈再率理想門檻（< 40% = 真洪瑞泰）
REINVEST_MAX     = 0.80   # 盈再率上限（> 80% 拒絕）
REINVEST_ABSURD  = 3.00   # |盈再率| > 300% 視為「structural change」不可用於判斷。
                          #   2026-08-24：實測 2105 正新 −431%、1216 統一 +332%。
                          #   數學上沒錯（固資四年少了 261 億、四年淨利才 60 億），
                          #   但它反映的是「公司結構大變動（處分資產/併購）」，
                          #   不是「資本效率好壞」——拿去比 80% 門檻會篩出錯的東西。
                          #   洪瑞泰官方表用「常利」平滑掉這種情況，我們沒有那個欄位，
                          #   所以改成明講「無法判斷」並附異常原因。
PAYOUT_MIN       = 0.40   # 配息率下限（洪瑞泰：配息 < 40% 代表盈餘可能是假的）

# ── 配息率快取（2026-08-27）：yfinance 的 payoutRatio 時有時無，缺值時回退上次的值 ──
_PAYOUT_CACHE_PATH = "state/payout_cache.json"
_PAYOUT_CACHE = None


def _payout_cache():
    global _PAYOUT_CACHE
    if _PAYOUT_CACHE is None:
        try:
            with open(_PAYOUT_CACHE_PATH, encoding="utf-8") as f:
                _PAYOUT_CACHE = json.load(f)
        except Exception:
            _PAYOUT_CACHE = {}
    return _PAYOUT_CACHE


def _payout_cache_put(ticker, value):
    """只存「真的抓到」的值——失敗的空結果不寫進快取
    （記憶庫 cache_negative_result_bug：一次逾時會被永久記成「沒資料」）。"""
    c = _payout_cache()
    prev = c.get(ticker) or {}
    if prev.get("value") == value:
        return
    c[ticker] = {"value": value, "date": datetime.now().strftime("%Y-%m-%d")}
    try:
        os.makedirs("state", exist_ok=True)
        with open(_PAYOUT_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


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

# ── 台股盈再率：走 FinMind ─────────────────────────────
# yfinance 的資產負債表拿不到 4 年前那一期（第 5 期一律 NaN，AAPL/9904 實測皆然），
# 而盈再率的定義就是「今年 vs 四年前」，少了期初根本算不了。
# FinMind 台股有完整 6 期年報，欄位也直接對應公式，所以台股一律走這裡。

# .env 裡有 FINMIND_TOKEN（付費額度），但本模組原本沒載入 .env，
# 於是一直用免費額度 → 2026-08-24 重掃 200 檔時中途撞 HTTP 402 被限流。
# 有 token 的額度高很多，載進來才用得到。
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

_FINMIND_API = "https://api.finmindtrade.com/api/v4/data"
_FM_CACHE: dict = {}
_FM_DISK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fm_cache")
_FM_DISK_TTL = 7 * 86400   # 財報是年報，一年才變四次，快取 7 天綽綽有餘


def _disk_path(dataset, sid):
    return os.path.join(_FM_DISK_DIR, f"{dataset}_{sid}.json")


def _disk_get(dataset, sid):
    """讀磁碟快取。過期或壞掉一律當沒有。"""
    fp = _disk_path(dataset, sid)
    try:
        if time.time() - os.path.getmtime(fp) > _FM_DISK_TTL:
            return None
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _disk_put(dataset, sid, data):
    """只存**成功抓到**的資料。空結果不存——空可能是失敗也可能是真的沒有，
    存了就分不出來，而且會把一次失敗變成七天的錯誤答案。"""
    if not data:
        return
    try:
        os.makedirs(_FM_DISK_DIR, exist_ok=True)
        tmp = _disk_path(dataset, sid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _disk_path(dataset, sid))   # 原子換檔，避免寫到一半被讀到
    except Exception:
        pass


_FM_ERRORS: list = []      # 連線失敗紀錄（跟『真的沒資料』分開）
_FM_RATE_LIMITED = False   # 被限流過就設 True，讓結果能標示「拿不到」而非「沒有」


def _fm(dataset: str, sid: str):
    """FinMind 查詢 + 行程內快取（同一檔會被盈再率/其他欄位重複查）。"""
    key = (dataset, sid)
    if key in _FM_CACHE:
        return _FM_CACHE[key]
    # 2026-08-25：FinMind 免費額度是**每小時**上限，而一次全市場掃描要打 400 次。
    # 同一天連跑三次就被 402 擋掉，台股官方公式從 41 檔掉回 11 檔。
    # 財報是年報（一年才變四次），沒有理由每次掃描都重抓 → 落地成磁碟快取。
    cached = _disk_get(dataset, sid)
    if cached is not None:
        _FM_CACHE[key] = cached
        return cached
    try:
        params = {"dataset": dataset, "data_id": sid, "start_date": "2018-01-01"}
        tok = os.environ.get("FINMIND_TOKEN")
        if tok:
            params["token"] = tok
        r = requests.get(_FINMIND_API, params=params, timeout=30)
        # 402 = 免費額度用完。**這是「拿不到」不是「沒有」**——
        # 2026-08-24 踩過：重掃 200 檔時中途被限流，43 檔安靜退回 capex_fallback，
        # 看起來像「這些公司資料不全」，其實是我們被擋了。
        # 全域旗標讓呼叫端能分辨，不要把限流偽裝成資料不足。
        if r.status_code == 402 or "upper limit" in (r.text or "")[:200]:
            global _FM_RATE_LIMITED
            if not _FM_RATE_LIMITED:
                print("  ⚠️ FinMind 免費額度已用完（HTTP 402）——"
                      "後續台股盈再率一律標 rate_limited，不是資料缺")
            _FM_RATE_LIMITED = True
            _FM_CACHE[key] = []
            return []
        data = r.json().get("data") or []
    except Exception as e:                      # noqa: BLE001
        # 2026-08-25 修：原本例外時 data=[] 並且**照樣寫進快取**，
        # 等於把一次網路逾時永久記成「這家公司沒有財報」。
        # 實測：單獨跑 9910/2404/2421 都算得出 official_tw，
        # 但在 200 檔的長掃描裡同樣三檔卻退回 capex_fallback——
        # 差別只在掃描途中有過短暫失敗，而失敗被快取了。
        # 現在：重試一次，仍失敗就回空但**不快取**，並計數讓掃描結束能報出來。
        try:
            time.sleep(2)
            r = requests.get(_FINMIND_API, params=params, timeout=45)
            data = r.json().get("data") or []
        except Exception:
            _FM_ERRORS.append((dataset, sid, str(e)[:60]))
            return []                            # 不進快取，下次還有機會
    _FM_CACHE[key] = data
    _disk_put(dataset, sid, data)
    return data


def fm_error_report():
    """掃描結束時呼叫：把「抓失敗」跟「真的沒資料」分開講。"""
    if _FM_RATE_LIMITED:
        print("  ⚠️ 本次掃描曾被 FinMind 限流，部分台股盈再率是『拿不到』不是『沒有』")
    if _FM_ERRORS:
        print(f"  ⚠️ FinMind 連線失敗 {len(_FM_ERRORS)} 次（重試後仍失敗），"
              f"這些檔的盈再率會退回 capex_fallback：")
        for ds, sid, msg in _FM_ERRORS[:10]:
            print(f"      {sid} {ds}: {msg}")


def _reinvest_tw(code: str):
    """台股盈再率。回 (值, 方法)；算不出來回 (None, None) 讓呼叫端退回 fallback。

    公式（洪瑞泰講稿原文，公開資料）：
        (期末固資+長投 − 期初固資+長投) ÷ 近 4 年稅後淨利
    期末＝最新年報，期初＝4 年前年報。缺任一期就不算，不用 0 代替。
    """
    bs = _fm("TaiwanStockBalanceSheet", code)
    fs = _fm("TaiwanStockFinancialStatements", code)
    if not bs or not fs:
        return (None, "rate_limited") if _FM_RATE_LIMITED else (None, None)
    years = sorted({x["date"][:4] for x in bs if x["date"].endswith("12-31")})
    if len(years) < 5:
        return None, None
    end_y, start_y = int(years[-1]), int(years[-1]) - 4
    if str(start_y) not in years:
        return None, None

    def bval(y, typ):
        for x in bs:
            if x["date"] == f"{y}-12-31" and x["type"] == typ:
                return x["value"]
        return None

    def base(y):
        ppe = bval(y, "PropertyPlantAndEquipment")
        if ppe is None:
            return None                      # 固資缺 → 整個算式作廢
        lti = bval(y, "InvestmentAccountedForUsingEquityMethod")
        return ppe + (lti or 0)              # 長投缺視為 0（很多公司本來就沒有）

    e, s = base(end_y), base(start_y)
    if e is None or s is None:
        return None, None

    # 分母用合併稅後淨利（TotalConsolidatedProfitForThePeriod）：
    # 2026-08-24 實測寶成 9904，IncomeAfterTaxes（歸屬母公司）只有官方「常利」的一半，
    # 合併口徑才對得上數量級——資產負債表是合併的，分母也要合併才一致。
    ni = 0.0
    got = 0
    for y in range(end_y - 3, end_y + 1):
        v = None
        for fld in ("TotalConsolidatedProfitForThePeriod", "IncomeAfterTaxes"):
            v = next((x["value"] for x in fs
                      if x["date"] == f"{y}-12-31" and x["type"] == fld), None)
            if v is not None:
                break
        if v is None:
            return None, None                # 四年淨利缺任一年就不算
        ni += v
        got += 1
    if got < 4 or ni <= 0:
        return None, None
    return round(float((e - s) / ni), 4), "official_tw"


def _reinvest_grade(ratio, method):
    """把盈再率轉成分級 + 異常原因。回 {reinvest_grade, reinvest_note}。

    2026-08-24 用戶指示：算不出來或數字異常時，要**寫清楚哪裡異常**，
    不要只丟一個「無法判斷」讓人不知道發生什麼事。
    """
    if ratio is None:
        return {"reinvest_grade": "unknown",
                "reinvest_note": "無法判斷：抓不到固定資產或四年淨利（資料源缺該期年報）"}
    if abs(ratio) > REINVEST_ABSURD:
        why = ("固資/長投大幅減少（可能處分資產或分割），分子為大額負值"
               if ratio < 0 else
               "四年淨利偏低而投資額極大（可能大擴張或獲利低基期），分母被稀釋")
        return {"reinvest_grade": "unknown",
                "reinvest_note": f"無法判斷：數值 {ratio*100:.0f}% 超出合理範圍——{why}。"
                                 f"這反映公司結構變動，不是資本效率，不納入門檻比較"}
    if method == "rate_limited":
        return {"reinvest_grade": "unknown",
                "reinvest_note": "無法判斷：FinMind 免費額度用完（HTTP 402），"
                                 "拿不到資料，不是公司沒有資料——換日或加 token 後重掃即可"}
    if method == "capex_fallback":
        # 2026-08-25：這句話我訂正過兩次。先寫「可能低估」、再寫「系統性高估」，
        # 都是拿單邊樣本講死方向。實測兩個方向都有（美股 CPB +56%→+14% 高估、
        # 台股 9917 +59%→+174% 低估），因為毛支出拉高與漏長投壓低是兩個反向誤差。
        # 正確的說法是：它跟官方公式偏差方向不定，不能當近似值。
        base = {"reinvest_note": "僅供參考：用 CapEx÷淨利 的替代算法（缺 4 年前資產負債表）。"
                                 "與官方公式偏差方向不定（實測高估、低估都出現過，"
                                 "最大差距達 115pp），不可視為近似值"}
    elif method and method.endswith("_nolti"):
        base = {"reinvest_note": "已用官方公式（SEC EDGAR 申報資料），"
                                 "但該公司財報無長期投資科目，分子僅含固定資產"}
    else:
        base = {"reinvest_note": ""}
    if ratio < 0:
        # 2026-08-24：負盈再率＝四年來固資+長投「淨減少」，代表公司在縮表
        #（處分廠房/收掉事業），不是「資本效率好」。歸到 ideal 會讓收縮中的公司
        # 被當成優質標的，方向完全相反 → 單獨一級，要人看過再決定。
        base["reinvest_grade"] = "shrinking"
        # 2026-08-25：原本「已有 method 說明就不寫縮表說明」，
        # 結果 PGR 只顯示「無長投科目」，完全沒提到它是負值——最重要的那句被吃掉。
        # 兩段講的是不同的事，要並存。
        warn = (f"注意：盈再率為負（{ratio*100:.0f}%），"
                f"代表四年來固定資產+長期投資淨減少，"
                f"公司在縮減規模而非擴張——不等於資本效率好")
        prev = base.get("reinvest_note")
        base["reinvest_note"] = f"{warn}（{prev}）" if prev else warn
    elif ratio < REINVEST_IDEAL:
        base["reinvest_grade"] = "ideal"        # 0~40%
    elif ratio < REINVEST_MAX:
        base["reinvest_grade"] = "acceptable"   # 40~80%
    else:
        base["reinvest_grade"] = "warn"         # >= 80%
    return base


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
        # 2026-08-27 Leo 拍板「漏資料就用上次的資料（但要說明是上次的）」：
        # 實測同一檔 PSX 兩次呼叫，一次回 payoutRatio=None、一次回 0.282——
        # 缺值時舊邏輯「放行」等於讓它矇混過關，同一檔股票因此在清單裡飄進飄出。
        # 改成回退上次成功抓到的值（state/payout_cache.json），並標記 payout_stale
        # 讓下游/頁面能標示「此配息率為前次資料」。
        payout_from_cache = False
        _pc = _payout_cache()
        if payout_ratio is None:
            cached = _pc.get(ticker)
            if cached and cached.get("value") is not None:
                payout_ratio = cached["value"]
                payout_from_cache = True
        elif payout_ratio is not None:
            _payout_cache_put(ticker, payout_ratio)

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

        # 常利 EPS（2026-08-27 加，MIKEON 官方盈再表同款公式）：
        # 預期常利 = 近2年平均×0.7 + 近5年中位數×0.3，
        # 其中「近2年」=［過去4季TTM, 去年年度］、「近5年」=［TTM, 前4個年度］。
        # 這條公式用 Leo 跑的官方盈再表 5 檔（BMY/PSX/DAL/TROW/VZ）逐檔驗證，
        # 官方「預期常利」欄位 5/5 精確吻合（誤差<0.1%），不是猜的。
        # 常利用 Normalized Income（剔除一次性損益的近似），沒有才退 Net Income——
        # 官方常利是人工調整值，Normalized Income 是最接近的自動化欄位
        # （實測 PSX 幾乎全中；BMY 這種大額減損/併購費用多的還有差距，已知限制）。
        changli_eps = None
        changli_basis = None
        try:
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            inc = stock.income_stmt
            if shares and shares > 0 and inc is not None and not inc.empty:
                fld = "Normalized Income" if "Normalized Income" in inc.index else (
                    "Net Income" if "Net Income" in inc.index else None)
                if fld:
                    ann = [float(x) for x in inc.loc[fld].dropna().iloc[:4]]
                    # TTM 淨利：quarterly Normalized 為主（準——會剔除一次性損益，
                    # PSX 用 GAAP TTM 會把煉油暴利算回來、俗價偏高16%）；
                    # 抓不到才退 eps_ttm×股數（info 裡現成，零額外呼叫，GAAP 近似）。
                    # 429 限流問題不在這裡犧牲準確度解，改由 stage2 加大間隔+重試處理
                    # （2026-08-27 Actions 全掃被打爆 201/236 檔的教訓）。
                    ttm_ni = None
                    try:
                        q = stock.quarterly_income_stmt
                        qf = "Normalized Income" if (q is not None and not q.empty and
                                                     "Normalized Income" in q.index) else (
                            "Net Income" if (q is not None and not q.empty and
                                             "Net Income" in q.index) else None)
                        if qf:
                            qs = q.loc[qf].dropna()
                            if len(qs) >= 4:
                                ttm_ni = float(qs.iloc[:4].sum())
                    except Exception:
                        pass
                    if ttm_ni is None and info.get("trailingEps"):
                        ttm_ni = float(info["trailingEps"]) * float(shares)
                    vals = ([ttm_ni] + ann)[:5] if ttm_ni is not None else ann[:5]
                    if len(vals) >= 3:   # 至少要3期才算得出有意義的中位數，太少不硬算
                        changli = float(np.mean(vals[:2]) * 0.7 + np.median(vals) * 0.3)
                        if changli > 0:
                            changli_eps = round(changli / float(shares), 4)
                            changli_basis = "normalized" if fld == "Normalized Income" else "net_income"
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

        # 盈再率（洪瑞泰核心指標）：（期末固資+長投 − 期初固資+長投）÷ 近 4 年稅後淨利
        # < 40% = 理想；< 80% = 可接受；>= 80% = 拒絕
        #
        # 2026-08-24 兩次修正的完整經過（很重要，別再踩）：
        # ① 原本用 |CapEx 累積| ÷ 淨利累積 當替代算法，**漏掉長期投資**——
        #    盈再率要抓的地雷之一正是「靠長投亂擴張」的公司。
        # ② 改成正式公式後仍對不上官方，追下去才發現真因：
        #    **yfinance 的第 5 期（4 年前）幾乎一律是 NaN**（AAPL、9904 實測皆然），
        #    而當時的取值函式把缺值當 0 → 期初基數＝0
        #    → 等於宣稱「這四年把全部固資長投從零蓋起來」→ 9904 算出 272%（官方 −4%）。
        #    **所以「正式公式」從頭到尾沒真正算對過**，先前顯示 official 的都是假數字。
        # ③ 結論：yfinance 拿不到 4 年前資產負債表 → **台股改走 FinMind**（實測有 6 期年報，
        #    欄位 PropertyPlantAndEquipment / InvestmentAccountedForUsingEquityMethod）。
        #    美股 FinMind 沒有財報（只有 USStockInfo 清單）→ 2026-08-25 改走 SEC EDGAR，
        #    見 sec_edgar.py；EDGAR 也拿不到才退回 CapEx 版並標記。
        # 缺資料一律標 capex_fallback，不硬算——寧可標「資料不足」也不要給看似精確的錯數字。
        reinvest_ratio = None
        reinvest_method = None
        tw_code = None
        _m = re.match(r"^(\d{4,5})\.TWO?$", ticker.upper()) if ticker else None
        if _m:
            tw_code = _m.group(1)
        if tw_code:
            reinvest_ratio, reinvest_method = _reinvest_tw(tw_code)
        else:
            # 美股走 SEC EDGAR（官方申報，免費、歷史完整）。
            # 原因同上：yfinance 拿不到「4 年前」那一期資產負債表，正式公式根本算不了，
            # 只能退回 CapEx÷淨利。實測那算法高估、低估都出現過（毛支出拉高、漏長投壓低，
            # 兩個反向誤差），**不是近似值而是另一個東西**。詳見 sec_edgar.py 開頭。
            # ⚠️ 這只是「算得更正確」，不代表「跟洪瑞泰官方數字一致」——
            # 他的分母是自訂的常利（無公開定義），且他的美股頁抓不到，無從驗證。
            try:
                from sec_edgar import reinvest_us
                reinvest_ratio, reinvest_method = reinvest_us(ticker)
            except Exception:
                reinvest_ratio, reinvest_method = None, None
        try:
            if reinvest_ratio is not None:
                raise StopIteration              # 台股已用 FinMind 算出，跳過 yfinance 這段
            bs = stock.balance_sheet
            fi = stock.financials
            ni_label = next((r for r in fi.index if r.lower() == "net income"), None)

            def _row(labels):
                for want in labels:
                    for r in bs.index:
                        if r.lower() == want.lower():
                            return r
                return None

            # 固資取 Net PPE（淨額，已扣折舊）；長投優先取 Long Term Equity Investment，
            # 沒有就退 Investments And Advances（美股常見的合併科目）
            ppe_label = _row(["Net PPE"])
            lti_label = _row(["Long Term Equity Investment", "Investments And Advances"])

            if (bs is not None and not bs.empty and fi is not None and not fi.empty
                    and ni_label and ppe_label and len(bs.columns) >= 5):
                cols = list(bs.columns)[:5]          # [0]=最新, [4]=4 年前

                # 2026-08-24 修：原本查無資料一律回 0.0，等於把「不知道」當成「是零」。
                # yfinance 台股第 5 期（4 年前）常常是空的 → 期初基數變 0
                # → 「這四年把全部固資長投都當成新增投資」→ 9904 算出 272%（實際官方 −4%）。
                # 現在區分兩種 None：
                #   固資缺 → 整個算式作廢（回 None，由呼叫端退回 fallback 並標記）
                #   長投缺 → 視為 0（很多公司本來就沒有長期投資，這是合理的預設）
                def _v(label, col, required):
                    if not label:
                        return None if required else 0.0
                    try:
                        v = bs.loc[label, col]
                        if v != v:                             # v!=v 抓 NaN
                            return None if required else 0.0
                        return float(v)
                    except Exception:
                        return None if required else 0.0

                ppe_end, ppe_start = _v(ppe_label, cols[0], True), _v(ppe_label, cols[4], True)
                lti_end, lti_start = _v(lti_label, cols[0], False), _v(lti_label, cols[4], False)
                # 期末或期初的固資任一缺 → 這檔算不出正式盈再率，不硬湊
                if ppe_end is not None and ppe_start is not None:
                    ni_4y = fi.loc[ni_label].dropna()[:4].sum()
                    if ni_4y > 0:
                        reinvest_ratio = round(
                            float(((ppe_end + lti_end) - (ppe_start + lti_start)) / ni_4y), 4)
                        reinvest_method = "official"     # 正式公式（含長投）

            if reinvest_ratio is None:               # 退回舊算法，但標記出來
                cf = stock.cashflow
                capex_label = next((r for r in cf.index
                                    if "capital expenditure" in r.lower()), None)
                if capex_label and ni_label and not cf.empty:
                    capex_sum = abs(cf.loc[capex_label].dropna()).sum()
                    ni_sum = fi.loc[ni_label].dropna().sum()
                    if ni_sum > 0:
                        reinvest_ratio = round(float(capex_sum / ni_sum), 4)
                        reinvest_method = "capex_fallback"   # 資料不足，僅供參考
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
            "changli_eps":   changli_eps,      # 常利EPS（MIKEON同款公式），優先用於俗貴價
            "changli_basis": changli_basis,    # normalized / net_income
            "debt_to_equity": debt_to_equity,  # yfinance 單位：% (150 = 150%)
            "dividend_yield": dividend_yield,
            "payout_ratio":  payout_ratio,
            "payout_stale":  payout_from_cache,   # True＝此配息率取自前次快取，非本次抓到
            "reinvest_ratio": reinvest_ratio,  # 洪瑞泰盈再率
            "reinvest_method": reinvest_method,  # official_tw=FinMind正式 / official_us=EDGAR正式
            # official_us_nolti=EDGAR但該公司無長投科目 / capex_fallback=資料不足退回
            **_reinvest_grade(reinvest_ratio, reinvest_method),
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

    roe  = data.get("roe_current") or 0
    d_e  = data.get("debt_to_equity") or 0
    price = data.get("price") or 0

    # ── 1. 俗價 / 貴價 ──────────────────────────────────
    # 2026-08-27 起【對齊 MIKEON 官方盈再表】（Leo 跑官方工具 5 檔對照後定案）：
    # ① EPS 基礎優先用「常利EPS」（近2年平均×0.7＋近5年中位數×0.3，見 fetch_fundamentals
    #    的 changli_eps）——舊做法（美股 forward、台股 ttm）對 PSX 這種景氣循環股會把
    #    暴利年當常態，俗貴價比官方高 20%~112%，5 檔全部誤判成「可買」（官方全是觀望）。
    # ② 貴價 = EPS×30 不變；俗價改成 貴價÷1.15^8（≈EPS×9.81）——官方淑價的真實定義
    #    是「8年後漲到貴價、年化15%」的折現價，不是 EPS×12（那是二手簡化）。
    # ③ 常利算不出來（資料不足）才退回舊鏈：美股 forward→ttm、台股 ttm，並標記 basis。
    # 改動影響範圍：巴菲特看板、valuation_alert 翻貴警示、投資長價值角度、assets-dashboard。
    # 換線當天 valuation_alert 可能噴一批新翻貴警示（舊線沒過、新線已過），一次性現象。
    eps_ttm_v = data.get("eps_ttm") or 0
    eps_fwd_v = data.get("eps_forward") or 0
    changli_v = data.get("changli_eps") or 0
    _is_tw = bool(re.match(r"^\d{4,5}\.TWO?$", str(data.get("ticker", "")).upper()))
    if changli_v > 0:
        eps, eps_basis = changli_v, f"changli_{data.get('changli_basis') or ''}"
    elif _is_tw:
        eps, eps_basis = eps_ttm_v, "ttm"
    else:
        # 美股優先預期；沒有預期值才退回實績並標記（不要因為缺值就整檔消失）
        eps, eps_basis = (eps_fwd_v, "forward") if eps_fwd_v > 0 else (eps_ttm_v, "ttm_fallback")
    result["eps_basis"] = eps_basis
    result["eps_used"] = eps if eps > 0 else None

    exp_price   = round(eps * PE_EXPENSIVE, 2) if eps > 0 else None
    cheap_price = round(eps * PE_EXPENSIVE / CHEAP_DISCOUNT, 2) if eps > 0 else None
    fair_price  = round(eps * PE_FAIR,  2) if eps > 0 else None

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

    # ── 5. 配息評估（洪瑞泰：配息率 > 40%）──────────────────
    # 只會賺錢不配息 → 盈餘可能是帳面的，現金沒有真的進來
    div_yield = data.get("dividend_yield") or 0
    payout    = data.get("payout_ratio")
    result["has_dividend"] = div_yield > 0
    result["dividend_pct"] = f"{div_yield*100:.2f}%" if div_yield else "無配息"
    result["payout_ratio"] = payout
    if payout is not None:
        payout_ok = payout >= PAYOUT_MIN         # 有數字 → 照門檻
    else:
        payout_ok = div_yield > 0                # 沒數字但有配息 → 資料缺，放行；完全不配息 → 擋
    result["payout_pass"] = payout_ok
    result["payout_stale"] = bool(data.get("payout_stale"))

    # ── 6. 綜合訊號 ──────────────────────────────────────
    # 訊號邏輯（洪瑞泰，2026-07-31 校正：拿掉合理價、補 ROE 穩定與配息率）：
    #   品質關 = ROE當年≥15% + ROE近4年至少3年達標 + EPS正 + 盈再率<80% + 配息率≥40%
    #   BUY  = 品質關過 + 現價 <= 俗價
    #   WATCH= 品質關過 + 俗價 < 現價 <= 貴價
    #   SELL = 現價 > 貴價
    #   SKIP = 品質關沒過（含盈再率地雷、只賺不配、ROE 只有今年好看）
    # 盈再率關卡改吃分級（2026-08-24）——原本只比 `rr < 0.80`，會有兩個漏洞：
    #   ① 「無法判斷」(unknown) 的極端值被當成合格（-431% < 0.80 成立）
    #   ② 「縮表中」(shrinking) 的負值也被當成資本效率好
    # 現在只有 ideal / acceptable 才算過關；unknown / shrinking 不自動淘汰也不自動放行，
    # 標記 needs_review 讓人看過再決定（避免用錯的數字做非黑即白的判斷）。
    rr = data.get("reinvest_ratio")
    grade = data.get("reinvest_grade")
    # 2026-08-25：拿掉 `or rr is None` 的放行漏洞。原本「抓不到資料」比「抓到但異常」
    # 還容易過關——一無所知反而放行，方向是反的。當時這樣寫是因為盈再率涵蓋率只有 6 成，
    # 硬擋會誤殺太多；今天接完 SEC EDGAR + 修好 FinMind 快取後涵蓋率 97.6%
    # （41 檔只剩 1 檔抓不到），代價已經很小，同一天已經在 paper_portfolio.py 用同樣邏輯堵過。
    reinvest_ok = is_financial or grade in ("ideal", "acceptable")
    result["needs_review"] = (not is_financial) and grade in ("unknown", "shrinking")
    roe_stable  = roe_pass_years >= ROE_YEARS          # 近 4 年至少 3 年 ROE ≥ 15%
    quality_ok  = (roe_pass_current and roe_stable and eps > 0
                   and reinvest_ok and payout_ok)
    result["roe_stable"]  = roe_stable
    result["quality_ok"]  = quality_ok

    signal = "SKIP"
    if price and cheap_price and exp_price:
        if price > exp_price:
            signal = "SELL"                            # 太貴一律先講，不管品質
        elif quality_ok:
            signal = "BUY" if price <= cheap_price else "WATCH"
    elif roe_pass_current and eps > 0:
        signal = "DATA_MISSING"

    signal_emoji = {
        "BUY":          "🟢 低於俗價，可買進",
        "WATCH":        "🟡 俗價~貴價，觀察",
        "SELL":         "🔴 高於貴價，考慮賣出",
        "SKIP":         "⬜ 品質關沒過",
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
