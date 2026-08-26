# -*- coding: utf-8 -*-
"""產業輪動雷達 RRG（Relative Rotation Graph）

2026-08-25 建立。緣由：老墨的 XQ 官方工具「PROJECT RX 產業輪動雷達」
（mophyfei/MOFI_XQ repo）示範了這張圖的價值——資金輪動到哪個產業一眼看穿，
比在單一個股上猜方向踏實。他的版本吃 XQ 自己維護的台股族群/細產業指數，
我們沒有那份資料，改用可行的替代籃子。

RS-Ratio / RS-Momentum 公式：JdK 原始方法論不公開精確公式（連 RRG 官網自己都不公布），
這裡採業界廣泛引用的開源版本（BennyThadikaran/RRG-Lite wiki 記載的公式）：

    RS          = 籃子指數 ÷ 基準指數 × 100
    RS-Ratio    = 100 + (RS − MA_N(RS)) ÷ StdDev_N(RS)
    RS-Momentum = 100 + z-score(ROC_N(RS))            ← 對 RS 的漲跌幅做同一套正規化

N 是可調期數（20/60/120/240 日，跟老墨的「計算週期」對齊）；他只曝露一個參數，
這裡比照解讀成「z-score 視窗」與「ROC 回看窗」共用同一個 N。

⚠️ 這是照公開文獻重建的方法論，跟老墨官方版數字不會逐點對上——
他的商品池、確切平滑方式都是他的（.DSTX 是編譯格式讀不到），這裡求的是「同一套邏輯」
不是「數字一致」。象限走向、100 中心值、輪動方向這些概念性的東西才是核心。

2026-08-26：美股籃子從「11檔SPDR ETF」改成跟台股同一套方法——直接用 TradingView
自己的 sector 分類，抓成分股歷史股價等權聚合。原因不是喜好，是資料源逼的：
Leo 想要「資金規模泡泡大小」能隨時間真的變化（不是用今天的值套用到過去），
這需要「歷史股數」——SPDR ETF 本身完全查不到歷史股數(yfinance get_shares_full()
對ETF回傳None、TradingView股票掃描器根本不收錄ETF，兩個資料源都查證過)，
只有個股才有歷史股數可查(yfinance對一般股票資料源是內部人申報揭露管道，
ETF的股數變化走申購贖回機制，不是同一種資料)。改用個股聚合後，
「歷史市值=歷史股價(yfinance,真實逐日) × 股數(TradingView現在查一次,假設這段期間
大致不變)」就能算，不用再回填假資料。

⚠️ 代價（Leo 已知情選定 TradingView 分類這條路）：
1. 跟 SPDR 官方版(業界標準、真實可交易、跟StockCharts同一組)脫鉤，
   美股從此也變成「TradingView 20分類的自組籃子」，跟台股同等級的近似值，
   不再是精確對應 GICS 11大類的官方版本。
2. 美股既有 52 週歷史(用XLK真實股價算的)在切換這天出現方法論斷點——
   舊資料跟新資料(TradingView自組合成指數)是兩把不同的尺，接不上，
   拖尾軌跡在切換那一週會看到不連續的假跳動，這是已知且不可逆的代價。
"""
import io
import json
import os
import sys
import time

import numpy as np
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from tradingview_screener import Query, col

PERIODS = [20, 60, 120, 240]
HIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "industry_rotation_history.json")
HIST_KEEP_WEEKS = 52          # 回放範圍最長給「一年」，對齊老墨控制面板的選項

US_BENCHMARK = "^GSPC"          # 跟 technical_indicators._benchmark 美股基準一致
TW_BENCHMARK = "^TWII"
# 2026-08-26：台美股改用同一套（原本叫 TW_BASKET_SIZE/TW_MIN_MEMBERS 只給台股用，
# 現在美股也走同一條路，改名成不分市場的共用常數）。
SECTOR_BASKET_SIZE = 8          # 每個產業取市值前 8 大聚合成籃子（等權）
SECTOR_MIN_MEMBERS = 3          # 成分股不足 3 檔的產業籃子雜訊太大，跳過


# ── 資料：抓籃子的歷史價格序列 ──────────────────────────────────────────

def _fetch_closes(ticker, period="3y"):
    """單檔歷史收盤價。3年緩衝是為了 N=240 的 z-score 還要再疊 ROC 回看窗，
    不留夠緩衝前面一大段會算不出東西（跟財報卡 RS 視窗那次踩過的暖機不足是同一種坑）。"""
    try:
        h = yf.Ticker(ticker).history(period=period)
        if h.empty:
            return None, None
        return h.index.tolist(), h["Close"].tolist()
    except Exception as e:
        print(f"  [industry_rotation] {ticker} 抓取失敗：{e}")
        return None, None


TOP_HOLDINGS_N = 5   # 排行榜「展開看前N大成分股」用（2026-08-26 新功能）


def _sector_members(market, min_market_cap=3e9):
    """某市場（"taiwan" 或 "america"）各 sector 市值前 SECTOR_BASKET_SIZE 大成分股。
    用 TradingView 一次性快照，不逐檔查——這一步快（幾秒），真正貴的是後面逐檔抓歷史價格。

    2026-08-26：原本只給台股用（`_tw_sector_members`），美股改走同一條路後
    通用化成這支——見檔頭說明「為什麼美股也改用個股聚合」。
    美股跟台股的差異只有兩處：market 參數本身、以及美股 ticker 不用補
    .TW/.TWO 後綴（yfinance 美股代號本來就跟 TradingView 一致）。

    回 {sector: {"members": [(ticker, shares_outstanding), ...],
                 "total_cap": 全部合格成分股市值合計, "holdings": top5清單}}
    ——total_cap 只用於 holdings 清單算權重百分比；「資金規模」拖尾動畫用的是
    另一條路（成分股歷史股價 × 股數，見 `_basket_size_series`），不是這個 total_cap。

    company name 用 `description` 欄位（TradingView 給的英文全名，不是中文簡稱）——
    沒有現成、覆蓋夠廣的中文對照表，寧可顯示英文全名也不要瞎猜。

    order_by market_cap 降冪 + limit 拉高到 5000：美股在 $30億市值門檻下
    符合資格的檔數（實測 3698 檔）已經超過台股慣用的 limit(3000)，若沒有
    明確依市值排序，超出 limit 被截掉的可能剛好是某個產業的大型股，
    讓那個產業的籃子選錯成分股——明確排序＋拉高 limit 兩件事都要做才保險。

    2026-08-26 實測踩到的坑：美股不篩交易所會混進同一家公司的多個掛牌
    （OTC ADR、特別股）——例如 AT&T 的 T/T-PA/T-PC 三檔市值幾乎一樣都被算成
    「AT&T的市值」，Deutsche Telekom 的 DTEGF/DTEGY 兩個 OTC ADR 代號也是同一家，
    不篩掉會讓同一家公司在同一個籃子裡被重複計算好幾次，資金規模嚴重灌水。
    修法：只收 NYSE/NASDAQ 主板掛牌（排除 OTC），且排除代號帶 "/" 的特別股
    （TradingView 特別股代號格式是「母股代號/類別」，例如 T/PA）。"""
    base = Query().set_markets(market)
    cols = ["name", "description", "sector", "market_cap_basic", "total_shares_outstanding",
            "close", "exchange"]
    wheres = [col("market_cap_basic") >= min_market_cap, col("close") >= 5.0]
    if market == "taiwan":
        wheres.append(col("exchange").isin(["TWSE", "TPEX"]))
    else:
        wheres.append(col("exchange").isin(["NYSE", "NASDAQ"]))   # 排除 OTC 重複掛牌
    q = base.select(*cols).where(*wheres).order_by("market_cap_basic", ascending=False)
    count, df = q.limit(5000).get_scanner_data()
    if df is None or df.empty:
        return {}
    if market == "taiwan":
        df["ticker"] = df["name"].astype(str) + df["exchange"].map({"TWSE": ".TW", "TPEX": ".TWO"}).fillna(".TW")
    else:
        df["ticker"] = df["name"].astype(str)   # 美股代號本身就是 yfinance 可用格式
        df = df[~df["ticker"].str.contains("/", regex=False)]   # 排除特別股（同一家公司重複計算）
    out = {}
    for sector, grp in df.groupby("sector"):
        if not sector or str(sector).lower() == "nan":
            continue
        top = grp.sort_values("market_cap_basic", ascending=False).head(SECTOR_BASKET_SIZE)
        if len(top) >= SECTOR_MIN_MEMBERS:
            total_cap = float(grp["market_cap_basic"].sum())   # 全部合格成分股，不只前8大
            top5 = top.head(TOP_HOLDINGS_N)
            holdings = [{"ticker": r["name"], "name": r.get("description") or r["name"],
                        "weight_pct": round(float(r["market_cap_basic"]) / total_cap * 100, 1)}
                       for _, r in top5.iterrows()]
            members = [(r["ticker"],
                       float(r["total_shares_outstanding"]) if r.get("total_shares_outstanding") == r.get("total_shares_outstanding") and r.get("total_shares_outstanding") else None)
                      for _, r in top.iterrows()]
            out[sector] = {"members": members, "total_cap": total_cap, "holdings": holdings}
    return out


def _basket_index(member_closes_list):
    """多檔收盤價序列（各自日期可能不完全對齊）→ 等權聚合成一條籃子指數（基期=100）。
    用「每日報酬率等權平均」而非「價格直接平均」——避免高價股的絕對價格量級蓋過其他成分股，
    這是編制指數的標準做法（跟直接平均價格是兩回事，後者會被股價位數不同的成分股扭曲）。
    """
    # 先把每檔轉成 pandas Series 對齊日期（外部已用同市場、同期間抓，索引通常一致；
    # 用 reindex + ffill 處理個別股票偶爾缺一天的情形，不要整檔因為一天缺值就丟掉）
    import pandas as pd
    series_list = [s for s in member_closes_list if s is not None and len(s) > 60]
    if len(series_list) < SECTOR_MIN_MEMBERS:
        return None
    all_idx = sorted(set().union(*[set(s.index) for s in series_list]))
    aligned = [s.reindex(all_idx).ffill() for s in series_list]
    rets = pd.concat([a.pct_change() for a in aligned], axis=1).mean(axis=1, skipna=True)
    idx = (1 + rets.fillna(0)).cumprod() * 100
    idx.iloc[0] = 100.0
    return idx


def _basket_size_series(member_closes_shares):
    """2026-08-26 新增：歷史資金規模序列＝Σ(當時股價 × 股數)。
    member_closes_shares: [(closes_series, shares), ...]。

    股數視為這段期間大致不變——不是偷懶，是查證過沒有更好的資料源可用
    （yfinance 的 get_shares_full() 對美股個股有歷史股數，但這裡股數只查「現在」
    一次，是因為要對齊「當時股價 × 現在股數」這個近似公式；真要抓每一天的
    真實股數，成本會高很多且多數公司股數本來就不常變動，這個近似已經比
    「整段拖尾都用今天的市值回貼」準確得多，見檔頭說明）。

    回傳 pandas Series（索引為日期），抓不到足夠成分股就回 None
    （呼叫端要處理 None，不能假設一定有值）。"""
    import pandas as pd
    series_list = []
    for closes, shares in member_closes_shares:
        if closes is None or len(closes) < 60 or not shares:
            continue
        series_list.append(closes * shares)
    if not series_list:
        return None
    all_idx = sorted(set().union(*[set(s.index) for s in series_list]))
    aligned = [s.reindex(all_idx).ffill() for s in series_list]
    return pd.concat(aligned, axis=1).sum(axis=1, skipna=True)


def _size_at(size_series, ts):
    """取 size_series 在某時間點的值；當天沒有就退回最近的前一個已知值
    （reindex+ffill 的邏輯，跟 _basket_index 對齊日期用的是同一套處理方式）。
    完全沒有可用資料才回 0.0（不留 None，讓下游泡泡半徑算式不用另外判空）。"""
    if size_series is None or len(size_series) == 0:
        return 0.0
    if ts in size_series.index:
        v = size_series.loc[ts]
        if v == v:      # 排除 NaN
            return float(v)
    before = size_series[size_series.index <= ts]
    if len(before):
        v = before.iloc[-1]
        return float(v) if v == v else 0.0
    return 0.0


# ── RS-Ratio / RS-Momentum（查證公式，見檔頭）───────────────────────────

def _zscore_plus100(series, window):
    ma = series.rolling(window).mean()
    sd = series.rolling(window).std(ddof=0)
    return 100 + (series - ma) / sd


def rs_ratio_momentum(basket, bench, periods=PERIODS):
    """回 {period: {"ratio": pd.Series, "momentum": pd.Series}}，索引為日期。
    整段序列都回傳（不是只取最新值）——要畫軌跡尾巴一定要有歷史。"""
    import pandas as pd
    common = basket.index.intersection(bench.index)
    if len(common) < max(periods) + 20:
        return None
    b, k = basket.reindex(common), bench.reindex(common)
    rs = (b / k) * 100
    out = {}
    for n in periods:
        ratio = _zscore_plus100(rs, n)
        roc = rs.pct_change(n) * 100
        momentum = _zscore_plus100(roc, n)
        out[n] = {"ratio": ratio, "momentum": momentum}
    return out


def quadrant(ratio, momentum):
    """RRG 四象限，順時針：改善→領先→弱化→落後→(回改善)。"""
    if ratio is None or momentum is None or np.isnan(ratio) or np.isnan(momentum):
        return None
    if ratio >= 100 and momentum >= 100:
        return "leading"      # 領先
    if ratio < 100 and momentum >= 100:
        return "improving"    # 改善
    if ratio < 100 and momentum < 100:
        return "lagging"      # 落後
    return "weakening"        # 弱化


QUADRANT_LABEL = {"leading": "領先", "improving": "改善", "lagging": "落後", "weakening": "弱化"}
# 2026-08-25 配色重挑：跑過 dataviz skill 的 validate_palette.js（surface #0a1222,
# dark mode）——這 4 色不強求跟下面 8 色籃子色盤有 CVD 級距（那是不同的編碼軸，
# 象限一律搭文字標籤顯示，不單靠顏色分辨，符合 skill 的 status-color 用法）。
# 保留台股慣例：紅＝強／領先（不是西方常見的「紅=差」)。
QUADRANT_COLOR = {"leading": "#e5484d", "improving": "#3987e5", "lagging": "#7d8590", "weakening": "#eda100"}


# ── 快照組裝：算出每個籃子在 4 個週期下的最新座標 ─────────────────────────

# 2026-08-26：拿掉 _spdr_aum()——美股不再用 SPDR ETF 當籃子，AUM 這個概念不適用了
# （資金規模改用成分股市值加總，見 _basket_size_series）。

BACKFILL_WEEKS = 52   # 動畫回填幾週歷史，對齊「回放範圍：一年」。3年資料本來就抓了，回填不用多打任何API

def _periods_at(rm, ts):
    """從已經算好的 rm（{period: {ratio,momentum}} 的 Series）取某個時間點的座標。
    任一 period 在該時間點是 NaN 就跳過那個 period（不是整個時間點作廢）——
    N=240 的 z-score 需要更長暖機期，資料剛開始那段短週期算得出來、長週期還算不出來很正常。"""
    periods = {}
    for n in PERIODS:
        ratio_s, mom_s = rm[n]["ratio"], rm[n]["momentum"]
        if ts not in ratio_s.index:
            continue
        r, m = ratio_s.loc[ts], mom_s.loc[ts]
        if np.isnan(r) or np.isnan(m):
            continue
        periods[n] = {"ratio": round(float(r), 2), "momentum": round(float(m), 2),
                      "quadrant": quadrant(r, m)}
    return periods


def _backfill_points(idx, weeks):
    """從共同日期索引挑週頻回看點（近似每5個交易日=1週，不強求對到日曆週—
    遇到假期本來就會有落差，這裡求「大致每週一格」不是精確對日曆）。
    回傳 [(Timestamp, 'YYYY-MM-DD'), ...] 由舊到新，不含最後一筆（那是「現在」，外面另外處理）。"""
    step = 5
    if len(idx) < step + 1:
        return []
    positions = list(range(len(idx) - 1 - step, -1, -step))[:weeks]
    positions.reverse()
    return [(idx[p], idx[p].strftime("%Y-%m-%d")) for p in positions]


BENCHMARK_LABEL = {"index": "加權指數／S&P500", "equal": "等權類股（全部籃子等權組成）"}

_MARKET_BENCH = {"us": US_BENCHMARK, "tw": TW_BENCHMARK}
_MARKET_TV = {"us": "america", "tw": "taiwan"}   # 我們內部用 us/tw，TradingView 要 america/taiwan


def _fetch_baskets(market):
    """只做網路抓取（貴的部分），回 (baskets, index_bench, holdings)。
    baskets = [(key, name, closes_series, size_series), ...]；
    holdings = {key: [{ticker,name,weight_pct}, ...]}（排行榜展開用）。
    跟 benchmark 選擇無關——「等權類股」基準要用到全部籃子的價格序列，
    所以基準運算要等全部籃子都抓完才能算，抓取本身跟基準選哪個無關，
    拆開後同一批抓來的資料可以算多種基準，不用每切一次基準就重抓一次。

    2026-08-26：美股跟台股合併成同一條路徑——原本美股是抓 SPDR ETF（11檔固定
    ticker，不用聚合），台股是抓 TradingView sector 成分股聚合；現在美股也改用
    TradingView 成分股聚合，兩個市場除了 `_MARKET_TV` 這個名稱轉換，邏輯完全一樣。
    原因見檔頭：要讓「資金規模」真的隨時間變化，需要成分股的歷史股數，
    ETF 本身查不到，只有個股查得到。"""
    if market not in _MARKET_BENCH:
        raise ValueError(f"未知市場：{market}")

    index_bench = yf.Ticker(_MARKET_BENCH[market]).history(period="3y")["Close"]
    members = _sector_members(_MARKET_TV[market])
    baskets, holdings = [], {}
    for sector, info in members.items():
        closes_list, shares_list = [], []
        for tk, shares in info["members"]:
            # TradingView 的特別股代號用句點（BRK.B），yfinance 要連字號（BRK-B）——
            # 2026-08-26 實測踩到：不轉會直接抓不到資料（BRK.A/BRK.B/PBR.A 都是這樣）。
            yf_tk = tk.replace(".", "-") if market == "us" else tk
            h = yf.Ticker(yf_tk).history(period="3y")
            if h.empty:
                continue
            closes_list.append(h["Close"])
            shares_list.append(shares)
        b = _basket_index(closes_list)
        if b is None:
            print(f"  [industry_rotation] {sector} 成分股資料不足（<{SECTOR_MIN_MEMBERS}檔），跳過")
            continue
        size_series = _basket_size_series(list(zip(closes_list, shares_list)))
        baskets.append((sector, SECTOR_TW_LABEL.get(sector, sector), b, size_series))
        holdings[sector] = info["holdings"]
    return baskets, index_bench, holdings


def compute_snapshot(baskets, index_bench, benchmark="index", backfill_weeks=0):
    """純計算（不打API），可以對同一批 baskets 重複呼叫算不同基準，成本很低。
    benchmark: "index"（加權指數/S&P500）或 "equal"（用全部籃子自己等權組成的合成指數，
    跟同儕比不跟大盤比）。回 (current, history_rows)，格式同舊版 build_market_snapshot。

    2026-08-25 補「等權類股」：老墨控制面板有「加權指數/櫃買指數/等權類股」三選項。
    櫃買指數（TPEx上櫃指數）查過幾種常見 yfinance ticker 猜法都拿不到資料，沒做——
    寧可少一個選項也不要編一個假資料源。

    2026-08-25 補回填：3年歷史資料本來就抓了，同一批資料回頭算過去每週座標
    幾乎不用額外成本，不用等每週排程真的跑過才多一幀動畫。

    2026-08-26：資金規模改成真的隨時間變化，不再是「用現在的值回貼過去」——
    baskets 現在帶的是 size_series（歷史序列，見 `_basket_size_series`），
    每個時間點都用 `_size_at()` 查那個時間點自己的值，回填出來的每一幀
    泡泡大小是當時真實的（近似）資金規模，不是同一個數字複製貼上。
    """
    if not baskets:
        return {}, []
    if benchmark == "equal":
        bench = _basket_index([b[2] for b in baskets])
    else:
        if index_bench is None or index_bench.empty:
            return {}, []
        bench = index_bench

    out, hist_by_date = {}, {}
    for key, name, closes, size_series in baskets:
        rm = rs_ratio_momentum(closes, bench)
        if rm is None:
            continue
        idx = rm[PERIODS[0]]["ratio"].index
        cur = _periods_at(rm, idx[-1])
        if not cur:
            continue
        out[key] = {"name": name, "periods": cur, "size": _size_at(size_series, idx[-1])}
        if backfill_weeks:
            for ts, date_str in _backfill_points(idx, backfill_weeks):
                p = _periods_at(rm, ts)
                if p:
                    hist_by_date.setdefault(date_str, {})[key] = {"name": name, "periods": p,
                                                                    "size": _size_at(size_series, ts)}
    rows = [(d, hist_by_date[d]) for d in sorted(hist_by_date)]
    return out, rows


SECTOR_TW_LABEL = {   # TradingView sector 英文 → 繁中（跟 buffett_html_legacy.SECTOR_TW 同一套語彙，這裡是TV自己的20分類不是GICS，名字對不上不能直接共用那份）
    "Commercial Services": "商業服務", "Communications": "通訊", "Consumer Durables": "耐久消費品",
    "Consumer Non-Durables": "非耐久消費品", "Consumer Services": "消費服務",
    "Distribution Services": "流通服務", "Electronic Technology": "電子科技",
    "Energy Minerals": "能源礦業", "Finance": "金融", "Health Services": "健康服務",
    "Health Technology": "健康科技", "Industrial Services": "工業服務",
    "Miscellaneous": "其他", "Non-Energy Minerals": "非能源礦業",
    "Process Industries": "製程工業", "Producer Manufacturing": "生產製造",
    "Retail Trade": "零售貿易", "Technology Services": "科技服務",
    "Transportation": "運輸", "Utilities": "公用事業",
}


# ── 歷史存檔：給軌跡尾巴用 ────────────────────────────────────────────

def _empty_history():
    return {"us": {"index": [], "equal": []}, "tw": {"index": [], "equal": []}}


def load_history():
    """歷史存檔結構 2026-08-25 改成 hist[market][benchmark] = [rows...]（多了基準這一層，
    才能讓「加權指數」跟「等權類股」兩種基準各自留自己的軌跡歷史）。
    舊檔是 hist[market] = [rows...]（沒有基準這層），讀到舊格式時搬進 "index"
    （原本就是用加權指數/S&P500算的），不丟掉已經回填好的歷史。"""
    if not os.path.exists(HIST_PATH):
        return _empty_history()
    try:
        with open(HIST_PATH, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        return _empty_history()
    out = _empty_history()
    for market in ("us", "tw"):
        v = hist.get(market)
        if isinstance(v, list):            # 舊格式：搬進 index，不丟資料
            out[market]["index"] = v
        elif isinstance(v, dict):
            out[market]["index"] = v.get("index", [])
            out[market]["equal"] = v.get("equal", [])
    return out


def append_history(hist, market, benchmark, snapshot, date_str):
    """把這次快照疊進歷史，並裁掉太舊的（軌跡尾巴不用留太長，留了也看不清）。"""
    hist.setdefault(market, {"index": [], "equal": []})
    hist[market].setdefault(benchmark, [])
    rows = hist[market][benchmark]
    # 同一天重跑會產生重複點——先移除同一天的舊紀錄再疊新的，不是每次都無限累加
    rows = [row for row in rows if row.get("date") != date_str]
    rows.append({"date": date_str, "snapshot": snapshot})
    rows.sort(key=lambda r: r["date"])
    if len(rows) > HIST_KEEP_WEEKS:
        rows = rows[-HIST_KEEP_WEEKS:]
    hist[market][benchmark] = rows
    return hist


def save_history(hist):
    tmp = HIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
    os.replace(tmp, HIST_PATH)


# ── HTML 渲染（跟 ark_report.py 同款：BASE_CSS + header + click-selector）────

def _size_scale(all_sizes, min_r=6, max_r=26):
    """資金規模→泡泡半徑。用 log10 是因為規模橫跨好幾個數量級
    （產業市值合計從幾十億到上兆美元/台幣都有，台美股都是同樣量級差），
    線性映射會讓小的全部擠成一個點。回傳一個 size→radius 的函式，
    lo/hi 用「這個市場所有已知規模（含歷史）」算，不是只看單一快照——
    這樣動畫播放時泡泡大小才不會因為每幀重新正規化而忽大忽小亂跳。"""
    sizes = [s for s in all_sizes if s and s > 0]
    if not sizes:
        return lambda s: (min_r + max_r) / 2
    logs = [np.log10(s) for s in sizes]
    lo, hi = min(logs), max(logs)
    if hi <= lo:
        return lambda s: (min_r + max_r) / 2

    def scale(s):
        if not s or s <= 0:
            return min_r
        frac = (np.log10(s) - lo) / (hi - lo)
        frac = max(0.0, min(1.0, frac))
        return round(min_r + frac * (max_r - min_r), 1)
    return scale


def _bubble_data(snapshot, period, radius_fn):
    pts = []
    for key, d in snapshot.items():
        p = d["periods"].get(period)
        if not p:
            continue
        size = d.get("size", 0.0)
        pts.append({"key": key, "name": d["name"], "ratio": p["ratio"], "momentum": p["momentum"],
                    "quadrant": p["quadrant"], "size": size, "radius": radius_fn(size)})
    return pts


def _frames_data(hist_rows, snapshot, period, radius_fn, max_frames=52):
    """「圈圈會跑」動畫＋軌跡尾巴共用的資料來源：把歷史快照依日期切成一格一格的畫面，
    每格是「當天所有籃子的座標」。前端用 buildTrailDs() 對這份資料動態切片組軌跡線，
    不再另外算一份給尾巴專用的資料（原本 _trail_data 是分開算的，排序/缺值處理
    不保證跟這裡一致，兩套「歷史」各算各的容易對不起來）。
    最後一格永遠是「現在」（用當下 snapshot，不是歷史裡的最後一筆——避免
    歷史還沒來得及 append 這次結果時動畫少一格）。

    2026-08-25 補：原本每幀的籃子清單是「當天有算出來的就收」，不同幀的
    籃子數量/順序可能不一樣——前端要做平滑補間動畫（一週一格跳動太生硬，
    看不出移動方向），補間需要每幀是「同一組籃子、同一個順序」對應著算，
    不然會補間到不同籃子身上變亂跳。改成：用「現在」的籃子清單當基準順序，
    某幀缺該籃子就沿用它上一個已知位置（不是补0、不是跳過），
    這樣每幀陣列長度/順序永遠一致，前端才能安全逐一補間。
    """
    keys_order = list(snapshot.keys())
    last_known = {}
    frames = []
    for row in hist_rows[-max_frames:]:
        d = row.get("snapshot", {})
        pts = []
        for key in keys_order:
            basket = d.get(key)
            p = None
            if basket:
                p = basket.get("periods", {}).get(str(period)) or basket.get("periods", {}).get(period)
            if p:
                size = basket.get("size", 0.0)
                pt = {"key": key, "name": basket.get("name", key), "ratio": p["ratio"],
                      "momentum": p["momentum"], "quadrant": p["quadrant"], "size": size,
                      "radius": radius_fn(size)}
                last_known[key] = pt
            elif key in last_known:
                pt = last_known[key]     # 沿用上一個已知位置，不留空、不讓泡泡消失
            else:
                continue                  # 從頭到尾都沒資料的籃子才真的跳過
            pts.append(pt)
        if pts:
            frames.append({"date": row["date"], "points": pts})

    cur_pts = _bubble_data(snapshot, period, radius_fn)
    for pt in cur_pts:
        last_known[pt["key"]] = pt
    if not frames or frames[-1]["date"] != time.strftime("%Y-%m-%d"):
        # 用同一個 keys_order + last_known 補齊，跟歷史幀維持同一組籃子/順序
        final_pts = [last_known[k] for k in keys_order if k in last_known]
        frames.append({"date": time.strftime("%Y-%m-%d") + "（現在）", "points": final_pts})
    return frames


PERIOD_LABEL = {20: "短線", 60: "波段", 120: "中期", 240: "長期"}
RANGE_WEEKS = [("1m", "1個月", 4), ("3m", "3個月", 13), ("6m", "半年", 26), ("1y", "一年", 52)]


def render_html(snaps, hist, holdings=None):
    """snaps: {"us": {"index": current_snapshot, "equal": current_snapshot}, "tw": {...}}
    hist:  {"us": {"index": [rows...], "equal": [rows...]}, "tw": {...}}"""
    import json as _json
    from board_theme import BASE_CSS, header, NAV, esc

    # 資金大小→泡泡半徑：兩種基準用的是同一批籃子同一個資金規模，只算一次、
    # 兩個基準共用同一把尺（不然切換基準時同一顆泡泡大小會跳動，很奇怪）。
    def _all_sizes(market):
        sizes = [d.get("size", 0.0) for d in snaps[market]["index"].values()]
        for bench_rows in hist.get(market, {}).values():
            for row in bench_rows:
                sizes += [b.get("size", 0.0) for b in row.get("snapshot", {}).values()]
        return sizes

    radius_fn = {m: _size_scale(_all_sizes(m)) for m in ("us", "tw")}

    # 軌跡尾巴改成前端用 frames（逐週快照）動態切片組出來（buildTrailDs），
    # 不再另外算一份 trail_*——原本 _trail_data 產的軌跡跟 frames 是分開算的兩套資料，
    # 排序/缺值處理不保證一致，且前端尾巴長度滑桿需要能動態切不同長度，
    # 讓 frames 當唯一資料來源才不會有兩份「歷史軌跡」各算各的、可能對不起來。
    payload = {}
    for m in ("us", "tw"):
        payload[m] = {}
        payload["frames_" + m] = {}
        for bench in ("index", "equal"):
            snap = snaps[m][bench]
            rows = hist.get(m, {}).get(bench, [])
            payload[m][bench] = {str(n): _bubble_data(snap, n, radius_fn[m]) for n in PERIODS}
            payload["frames_" + m][bench] = {str(n): _frames_data(rows, snap, n, radius_fn[m]) for n in PERIODS}

    snap_tw_index = snaps["tw"]["index"]
    snap_us_index = snaps["us"]["index"]
    date = time.strftime("%Y-%m-%d %H:%M")

    # 2026-08-25：X/Y 軸說明加長（用戶反饋「再多說明一下」）——原本只寫軸名稱，
    # 沒解釋這兩個數字實際在算什麼、100 是什麼意思，看得懂座標但不懂數字從哪來。
    quad_note = (
        '<b>X軸 RS-Ratio 相對強弱</b>：這個產業／類股的價格走勢，跟大盤基準比起來是強還是弱——'
        '100 代表跟基準一樣強，<b>大於100 = 這段時間比大盤強、小於100 = 比大盤弱</b>。<br>'
        '<b>Y軸 RS-Momentum 強弱變化率</b>：RS-Ratio 本身正在變強還是變弱（強弱的「加速度」，'
        '不是強弱本身）——<b>大於100 = 相對強弱正在轉強、小於100 = 正在轉弱</b>，'
        '就算 X 軸還沒轉正，Y 軸轉強也代表風向在變。<br>'
        '四象限順時針輪動：'
        f'<b style="color:{QUADRANT_COLOR["improving"]}">改善</b>（弱但正轉強）→ '
        f'<b style="color:{QUADRANT_COLOR["leading"]}">領先</b>（強且持續轉強）→ '
        f'<b style="color:{QUADRANT_COLOR["weakening"]}">弱化</b>（強但開始轉弱）→ '
        f'<b style="color:{QUADRANT_COLOR["lagging"]}">落後</b>（弱且持續轉弱）→ 回到改善。<br>'
        '<mark class="hl">「改善→領先」的轉折是資金剛轉強的甜蜜點，值得優先注意</mark>。'
    )
    period_btns = "".join(  # 2026-08-26：預設週期改 60 日（Leo 指定），要跟上面 JS 的 curP 初始值同步
        f'<button data-p="{n}" aria-pressed="{"true" if n == 60 else "false"}">{n}日<br><span class="pnote">{PERIOD_LABEL[n]}</span></button>'
        for n in PERIODS)
    bench_btns = "".join(
        f'<button data-b="{k}" aria-pressed="{"true" if k == "index" else "false"}">{v}</button>'
        for k, v in (("index", "加權指數"), ("equal", "等權類股"))
    )
    range_btns = "".join(
        f'<button data-r="{k}" aria-pressed="{"true" if k == "3m" else "false"}">{label}</button>'
        for k, label, _ in RANGE_WEEKS
    )

    head_html = ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 '<meta name="robots" content="noindex"><title>產業輪動雷達</title>'
                 '<style>' + BASE_CSS + CSS_EXTRA + '</style></head><body><div class="wrap">')
    hdr = header("rotation", "產業輪動雷達",
                 f"RRG（Relative Rotation Graph）· 美股{len(snap_us_index)}個 + 台股{len(snap_tw_index)}個"
                 "TradingView產業籃子"
                 f" · 更新 {esc(date)}（每週六隨全市場重掃）", NAV, "rotation")
    # 2026-08-25：說明區塊搬到圖表下面（原本卡在 header 跟控制面板中間，
    # 用戶一打開頁面要先滑過一大段文字才看得到圖，反饋「產業說明可以放下面」）。
    # 2026-08-25：整段重做卡片化——原本是一大坨用 <br> 接起來的灰色小字，
    # 用戶反饋「不明顯」。改成有標題的卡片＋逐條分隔線，主要說明用比較亮的字色，
    # 只有最後一條「已知限制」維持muted（那條本來就是次要但仍要看得到的資訊）。
    note_html = (
        '<div class="rrgnote">'
        '<div class="rrgnotehd">📖 名詞與方法論說明</div>'
        f'<div class="rrgnoteitem">{quad_note}</div>'
        '<div class="rrgnoteitem">資料源：台美股都沒有現成的類股指數可直接抓，'
        f'改成 TradingView 產業分類下市值前 {SECTOR_BASKET_SIZE} 大成分股等權聚合'
        '（2026-08-26起美股也改用這個方法，原本是抓SPDR類股ETF——ETF本身查不到歷史股數，'
        '沒辦法讓資金規模真的隨時間變化，只有個股才有歷史股數可查，是資料源逼的取捨，'
        '不是喜好；代價是跟SPDR官方版脫鉤，變成近似值）。'
        '公式為業界公開重建版（非老墨官方精確值），數字不會跟他的工具逐點對上，方法論一致。</div>'
        '<div class="rrgnoteitem"><b>泡泡大小＝資金規模</b>'
        '（成分股歷史股價×股數加總，台美股都一樣算法）——'
        '兩個市場單位不同、不能互比，只在各自市場內部比大小。</div>'
        '<div class="rrgnoteitem"><b>軌跡看不清楚？</b>'
        '滑鼠移到某顆泡泡、或排行榜某一列，只會留那一條軌跡清楚顯示，其餘自動淡出——'
        '11~17 條軌跡同時全部顯示本來就會互相蓋住，一次看一條方向才看得懂。</div>'
        f'<div class="rrgnoteitem rrgnotedim">軌跡與「▶ 播放資金移動軌跡」已回填近 {BACKFILL_WEEKS} 週歷史'
        '（用既有3年價格資料反推，不是等出來的）；之後每週六會再多疊一幀「現在」。'
        '回填歷史的資金規模是用當時真實股價×股數算的（股數視為這段期間大致不變，'
        '沒有歷史股數資料源可查），不是套用今天的數字；位置(RS-Ratio/Momentum)本身也是當時的真實值。'
        '美股 2026-08-26 換算法那一週，拖尾軌跡會出現一次不連續的跳動——舊資料(SPDR ETF)'
        '跟新資料(TradingView自組籃子)是兩把不同的尺，接不上，是已知且不可逆的代價。<br>'
        '基準只做了「加權指數」與「等權類股」——查過幾種常見 yfinance 代號寫法，'
        '「櫃買指數」都拿不到資料，寧可少一個選項也不編假資料源。</div>'
        '</div>'
    )
    # 2026-08-25：控制面板從「圖表正上方整排」改成「圖表左側直排」（用戶反饋
    # 篩選要放圖的左邊或右邊）——每個 ctrlrow 改直排（標籤在控制項上面），
    # 240px 窄欄放得下。
    ctrl_html = (
        # 2026-08-25：拿掉共用的 "ctrl" class——它是全站另一個用途的 sticky 頂列
        # （z-index/border-bottom/margin-bottom 都是那邊要的，不是這裡要的），
        # 疊在一起會有樣式互相污染的風險，這裡完全自訂樣式，不需要借用它。
        '<div class="rrgctrl">'
        '<div class="ctrlrow">'
        '<span class="ctrllbl">市場</span>'
        '<div class="seg" role="group" aria-label="切換市場" id="mktSeg">'
        '<button data-m="us" aria-pressed="true">美股</button>'
        '<button data-m="tw" aria-pressed="false">台股</button></div>'
        '</div>'
        '<div class="ctrlrow">'
        '<span class="ctrllbl">基準（相對誰比強弱）</span>'
        f'<div class="seg" role="group" aria-label="切換基準" id="benchSeg">{bench_btns}</div>'
        '</div>'
        '<div class="ctrlrow">'
        '<span class="ctrllbl">計算週期</span>'
        f'<div class="seg segwide" role="group" aria-label="切換週期" id="perSeg">{period_btns}</div>'
        '</div>'
        # 2026-08-26：兩個控制項的白話說明直接放在控制項下面（Leo：「可以寫在下面嗎」），
        # 不用另外滑到最下面的說明卡片才看得懂在調什麼——「回放範圍」跟「尾巴長度」
        # 常被搞混，但其實是兩件不同的事：前者是按「播放」時整段動畫要走多久的歷史，
        # 後者是任何時刻（不管有沒有在播放）每顆泡泡身後拖著的殘影要看多久以前的位置。
        '<div class="ctrlrow">'
        '<span class="ctrllbl">回放範圍</span>'
        f'<div class="seg" role="group" aria-label="切換回放範圍" id="rangeSeg">{range_btns}</div>'
        '<div class="ctrlnote">按「▶ 播放」時，動畫從幾個月前一路播到現在</div>'
        '</div>'
        '<div class="ctrlrow">'
        '<span class="ctrllbl">尾巴長度</span>'
        '<input type="range" id="tailSlider" min="0" max="20" value="8" class="tailslider">'
        '<span id="tailVal" class="tailval">8 週</span>'
        '<div class="ctrlnote">每顆泡泡身後拖著幾週前的殘影軌跡（不只播放時，平常靜態畫面也會顯示）</div>'
        '</div>'
        '<div class="ctrlrow">'
        '<button id="playBtn" class="playbtn">▶ 播放資金移動軌跡</button>'
        '<span id="playHint" class="playhint"></span>'
        '</div>'
        '</div>'
    )
    # 排行榜數字欄原本沒有欄名，只有 hover tooltip 看得到「這兩個數字是什麼」——
    # 加一列固定表頭，不用滑鼠也看得懂（用戶反饋「101.1／101.8 是什麼意思」）。
    # 2026-08-26：排行榜面板獨立成整頁滿版寬（原本困在「圖表」那個 1fr 欄裡，
    # 反饋「這個左右大小可以跟市場+圖左右一樣大嗎」）——拆成兩塊：chart_html
    # 只剩圖表本身（留在 rrglayout 的兩欄結構裡），rank_html 變成 rrglayout 外面
    # 一個獨立的滿版寬區塊，寬度＝篩選欄+圖表欄相加的整個版面寬度。
    chart_html = (
        '<div class="rrgwrap"><div class="rrgbox"><canvas id="rrgChart"></canvas>'
        '<div class="rrgframe" id="rrgFrameLabel"></div></div></div>'
    )
    rank_html = (
        '<div class="rrgrankpanel">'
        # 2026-08-26：可以點列表勾選只看某幾個產業（用戶反饋「可以只選下面的產業
        # 只跑那一個或幾個嗎」）——選取狀態＋清除按鈕放在表頭上方，跟表頭本身分開，
        # 不然「未勾選」時這排空空的會很奇怪。
        '<div class="rrgselbar"><span id="selInfo"></span>'
        '<button type="button" id="selClear" style="display:none;">清除選取，顯示全部</button></div>'
        '<div class="rrghint">點列表可複選只看某幾個產業，圖表跟播放都只顯示勾選的幾檔</div>'
        # 2026-08-25：RS-Ratio／RS-Momentum 合併一欄擠成兩行（用戶反饋「標題位置太擠」）
        # ——拆成兩個獨立欄位，各自欄寬夠放一行，不用再靠斜線塞在一起。
        # 「強弱位置」欄加 title 提示（hover 看得到白話說明，用戶反饋「這是什麼意思」）。
        # 2026-08-26：拿掉開頭那個空的 <span></span>（原本對應獨立的「dot」欄）——
        # 展開箭頭跟色點都併進「產業」欄本身了，表頭欄位數要跟著資料列一起變成7欄，
        # 不然表頭跟資料列欄數對不上，兩邊的直欄會全部錯位（這正是這次「名字消失」
        # 的根因：資料列少了一欄，8欄格線硬套在7個元素上，每欄全部往前錯位一格）。
        '<div class="rrgrankhd"><span>產業</span><span>象限</span>'
        '<span>RS-Ratio</span><span>RS-Momentum</span><span>資金規模</span>'
        '<span title="由左至右＝短線(20日)/波段(60日)/中期(120日)/長期(240日)，'
        '顏色是該週期的象限——短中長期顏色一致代表趨勢一致，不一致代表正在轉折">多週期</span>'
        '<span title="RS-Ratio(相對強弱)在座標軸範圍內的位置，越右邊代表比大盤越強">強弱位置</span></div>'
        '<div class="rrgrank" id="rrgRank"></div>'
        '</div>'
    )
    layout_html = '<div class="rrglayout">' + ctrl_html + chart_html + '</div>' + rank_html
    disc_html = (
        '<p class="disc">RRG 是產業/籃子層級的相對強弱統計工具，不是個股買賣訊號，'
        '不構成投資建議。台股籃子由少數大型股等權聚合，會被成分股個別異動放大，'
        '僅供研究參考，正式決策前請自行查核。</p></div>'
    )

    script_html = _rrg_script(payload, holdings or {"us": {}, "tw": {}})
    return head_html + hdr + layout_html + note_html + disc_html + script_html + "</body></html>"


def _axis_bounds(payload, pad=0.6):
    """算兩軸要固定在哪個範圍：掃過 payload 裡全部 ratio/momentum（含所有市場/基準/
    週期/歷史幀），跟著實際資料算，不是憑感覺挑一個數字。

    2026-08-25：改用百分位數，不用絕對 min/max。原本用絕對極值＋pad=2.0，
    52 週歷史裡只要有一兩天出現過極端值，整個範圍就被那一兩天撐開，平常大部分的日子
    資料其實擠在中間一小段——反饋「圖都集中在中間看不清楚」，根因就是這個。
    百分位數會自然忽略最極端的尾巴，讓「平常看到的資料」佔滿大部分繪圖區；
    真正的極端值超出範圍時 Chart.js 會畫在邊界附近（不會憑空消失），
    只是不會為了極端的少數犧牲多數資料的可讀性。

    第一輪用 p2~p98+pad1.0 反饋還是太寬，這輪收緊到 p5~p95+pad0.6——
    再往下收會開始常態性地把普通日子的資料切在邊界外，不只是真正的極端值。"""
    vals = []
    for m in ("us", "tw"):
        for bench in ("index", "equal"):
            for p, pts in payload.get(m, {}).get(bench, {}).items():
                for pt in pts:
                    vals.append(pt["ratio"]); vals.append(pt["momentum"])
            for p, frames in payload.get("frames_" + m, {}).get(bench, {}).items():
                for f in frames:
                    for pt in f["points"]:
                        vals.append(pt["ratio"]); vals.append(pt["momentum"])
    if not vals:
        return 90.0, 110.0
    vals.sort()
    n = len(vals)
    lo = vals[max(0, int(n * 0.05))]
    hi = vals[min(n - 1, int(n * 0.95))]
    # 兩軸用同一個範圍（不要 x/y 各自的範圍不同，那樣象限對角線就不是45度，視覺會扭曲）
    span = max(hi - lo, 1.0)
    center = (hi + lo) / 2
    half = span / 2 + pad
    return round(center - half, 1), round(center + half, 1)


def _rrg_script(payload, holdings):
    import json as _json
    lines = []
    lines.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>')
    lines.append("<script>")
    lines.append("window.RRG_DATA = " + _json.dumps(payload, ensure_ascii=False) + ";")
    # 2026-08-26：展開排行榜某產業看前5大成分股用（台美股都是市值排序的前5大，
    # 見 _sector_members）。靜態資料，不像 RRG_DATA 要按市場/基準/週期分層——
    # 一個籃子的成分股不會因為
    # 你切了計算週期就變了。
    lines.append("window.RRG_HOLDINGS = " + _json.dumps(holdings, ensure_ascii=False) + ";")
    # 2026-08-26：預設週期改 60 日（Leo 指定）；回放範圍3個月／尾巴8週本來就已經是預設值。
    lines.append("var rrgChart = null, curM = 'us', curP = '60', curBench = 'index', curRange = '3m', tailWeeks = 8;")
    lines.append("var hoveredKey = null, _lastFullFrames = [], _lastUptoIdx = -1, _lastAllPts = [];")
    lines.append("var selectedKeys = new Set();")  # 2026-08-26：只看勾選的幾個產業
    lines.append("var expandedKeys = new Set();")  # 2026-08-26：展開看前幾大成分股的籃子
    lines.append(f"var TOP_HOLDINGS_N_JS = {TOP_HOLDINGS_N};")
    lines.append("var QCOLOR = " + _json.dumps(QUADRANT_COLOR, ensure_ascii=False) + ";")
    lines.append("var QLABEL = " + _json.dumps(QUADRANT_LABEL, ensure_ascii=False) + ";")
    lines.append("var RANGE_WEEKS = " + _json.dumps(dict((k, w) for k, _, w in RANGE_WEEKS)) + ";")
    # 2026-08-26：改回固定 94~106（Leo 指定），不再用 _axis_bounds() 百分位數動態算。
    # 前兩輪先收緊到 p2~p98(span7.2)、又收到 p5~p95(span5.7)，範圍越縮，
    # 同樣的真實價格波動在畫面上占的比例越大，播放動畫看起來反而「移動太劇烈」——
    # 固定範圍不會隨資料變（也不會被單一天的極端值撐開或縮小），動畫幅度可預期。
    _axis_lo, _axis_hi = 94.0, 106.0
    lines.append(f"var AXIS_MIN = {_axis_lo}, AXIS_MAX = {_axis_hi};")
    lines.append("""
function quadrantBgPlugin() {
  return {
    id: 'quadrantBg',
    beforeDraw: function(chart) {
      var ctx = chart.ctx, area = chart.chartArea;
      var xScale = chart.scales.x, yScale = chart.scales.y;
      var midX = xScale.getPixelForValue(100), midY = yScale.getPixelForValue(100);
      ctx.save();
      ctx.fillStyle = 'rgba(57,135,229,.05)'; ctx.fillRect(area.left, area.top, midX-area.left, midY-area.top);
      ctx.fillStyle = 'rgba(229,72,77,.06)'; ctx.fillRect(midX, area.top, area.right-midX, midY-area.top);
      ctx.fillStyle = 'rgba(125,133,144,.05)'; ctx.fillRect(area.left, midY, midX-area.left, area.bottom-midY);
      ctx.fillStyle = 'rgba(237,161,0,.06)'; ctx.fillRect(midX, midY, area.right-midX, area.bottom-midY);
      ctx.strokeStyle = '#2a3550'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(midX, area.top); ctx.lineTo(midX, area.bottom);
      ctx.moveTo(area.left, midY); ctx.lineTo(area.right, midY); ctx.stroke();
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#5f80a6';
      ctx.fillText('改善 ▲', area.left+6, area.top+14);
      ctx.fillText('領先 ▲', midX+6, area.top+14);
      ctx.fillText('落後 ▼', area.left+6, area.bottom-6);
      ctx.fillText('弱化 ▼', midX+6, area.bottom-6);
      ctx.restore();
    }
  };
}

// 泡泡本身標上產業名字（原本只有 hover tooltip 跟右側排行清單看得到名字，
// 圖上一堆彩色泡泡卻不知道哪個是哪個，用戶反饋要直接標出來）。
// 用自訂 plugin 畫在 Canvas 上，不引入 chartjs-plugin-datalabels 這種外部套件——
// 跟現有 quadrantBgPlugin 同一種做法，全站不多加 CDN 依賴。
function bubbleLabelPlugin() {
  return {
    id: 'bubbleLabels',
    afterDatasetsDraw: function(chart) {
      var pts = window._rrgCurPts;
      if (!pts || !pts.length) return;
      var meta = chart.getDatasetMeta(0);
      if (!meta || !meta.data) return;
      var ctx = chart.ctx;
      ctx.save();
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      meta.data.forEach(function(el, i) {
        var p = pts[i];
        if (!p || !el) return;
        var x = el.x, y = el.y - (el.options.radius || 8) - 3;
        // 深色描邊再疊亮色字：泡泡顏色深淺不一，純色字在某些泡泡上會糊掉看不清楚
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(4,7,15,.85)';
        ctx.strokeText(p.name, x, y);
        ctx.fillStyle = '#e8f2ff';
        ctx.fillText(p.name, x, y);
      });
      ctx.restore();
    }
  };
}

// 2026-08-26：軌跡起點/中點標記（用戶反饋「可以標出第一個點還有中間跟最後嗎」）。
// window._rrgTrailMarkers 由 buildTrailDs() 在高亮單一籃子時填入（座標是資料值，
// 不是像素——用 chart.scales 換算成當下實際畫面座標，圖表縮放/切換都會自動對）。
function trailMarkerPlugin() {
  return {
    id: 'trailMarkers',
    afterDatasetsDraw: function(chart) {
      var marks = window._rrgTrailMarkers;
      if (!marks || !marks.length) return;
      var ctx = chart.ctx, xs = chart.scales.x, ys = chart.scales.y;
      ctx.save();
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      marks.forEach(function(m) {
        var x = xs.getPixelForValue(m.ratio), y = ys.getPixelForValue(m.momentum);
        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#e8f2ff'; ctx.fill();
        ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(4,7,15,.85)';
        ctx.strokeText(m.label, x, y - 9);
        ctx.fillStyle = '#e8f2ff';
        ctx.fillText(m.label, x, y - 9);
      });
      ctx.restore();
    }
  };
}

var playTimer = null, playRAF = null, playIdx = 0;
// 2026-08-25（第二輪）：改回手動補間，但這次用 requestAnimationFrame 驅動，
// 不是固定 35ms 的 setInterval。
// 第一輪試過交給 Chart.js 自己的 animation 系統補間（update() 不帶'none'）——
// 結果泡泡全部從畫面下方往上長出來，不是照 RS-Ratio/RS-Momentum 真實軌跡移動。
// 追下來是 Chart.js 對「這個索引位置沒有記錄到前一個真實值」的新元素，
// 預設用 y 軸底部當起始點動畫長出來——我們每次 update 都整個換掉 datasets 陣列，
// Chart.js 沒有穩定認得「這是同一顆泡泡的延續」，於是每次都當新泡泡處理。
// 改法：完全不用 Chart.js 的動畫系統（update 永遠帶'none'），
// 兩個真實週之間的 ratio/momentum/radius 由我們自己逐格算好、直接餵座標，
// Chart.js 純粹畫「這一格算好的靜態座標」，绝对照真實軌跡走，不會被它自己的
// 「新元素從哪裡長出來」規則干擾。rAF 而不是 setInterval，是因為 rAF 綁瀏覽器
// 實際繪圖節奏，畫面忙不過來時會自動跳格而不是硬擠，比固定間隔更不容易卡頓。
var ANIM_MS = 300;     // 一個真實週的補間時長（2026-08-26 加快一倍：600→300）
var PAUSE_MS = 60;     // 補間完成後，接下一週之前留一點點停頓感（120→60，同倍率）
function _easeInOutQuad(t) { return t < 0.5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2; }
function _lerp(a, b, t) { return a + (b - a) * t; }

function rrgGet(kind) {
  // kind: 'bubble'(現在座標) | 'trail'（保留給舊資料相容） | 'frames'（動畫用逐週快照）
  var key = (kind === 'bubble') ? curM : (kind + '_' + curM);
  var byBench = window.RRG_DATA[key] || {};
  var byPeriod = byBench[curBench] || {};
  return byPeriod[curP] || [];
}

function stopPlay() {
  if (playTimer) { clearTimeout(playTimer); playTimer = null; }
  if (playRAF) { cancelAnimationFrame(playRAF); playRAF = null; }
  document.getElementById('playBtn').classList.remove('playing');
  document.getElementById('playBtn').textContent = '▶ 播放資金移動軌跡';
  document.getElementById('rrgFrameLabel').style.display = 'none';
}

// 從完整歷史 frames 中，取 uptoIdx（含）往前數 weeks 週的每個籃子座標，接成軌跡線。
// weeks<=0 時不畫尾巴。這是用戶要求加的功能：原本補間動畫只有會動的泡泡、
// 沒有留下走過的路徑，看久了還是看不出「這一路怎麼走過來的」。
// 8 色分類色盤——原本泡泡顏色只有 4 種象限色，同象限裡好幾個產業長得一模一樣、
// 只能靠標籤字認。改成每個籃子固定一個分類色（顏色數 > 籃子數時循環使用，
// 8 色對 11~17 個籃子一定會重複，但比 4 色可辨識度高很多，配合標籤字已經夠用）；
// 象限資訊改用泡泡邊框色表達，不丟掉這個訊號、只是換位置放。
// 2026-08-25 換成 dataviz skill 驗證過的 8 色分類色盤（node validate_palette.js，
// surface #0a1222 dark mode，adjacent-pairs 全過）。17 個籃子仍會循環用色，
// skill 對純色相編碼的建議上限是 3 個可過 all-pairs、更多就該「折進 Other 或分面」，
// 但這張圖的重點就是要同時看到全部產業輪動位置，折疊掉大半籃子等於毀了圖的用途——
// 每顆泡泡已經強制標了產業名字（bubbleLabelPlugin，不是選擇性標籤），色相只是輔助
// 辨識不是唯一辨識依據，這是刻意的取捨，不是沒驗證。
var CAT_PALETTE = ['#3987e5','#d95926','#199e70','#c98500','#d55181','#008300','#9085e9','#e66767'];
var _keyOrderCache = {};
function keyColor(key) {
  var order = _keyOrderCache[curM] || [];
  var idx = order.indexOf(key);
  return CAT_PALETTE[(idx >= 0 ? idx : 0) % CAT_PALETTE.length];
}
function _hexAlpha(hex, a) {
  var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a.toFixed(2) + ')';
}

// 資金規模數字化（原本只有泡泡大小看得出來）。美股成分股市值合計是美元，
// 台股是合格成分股市值合計台幣——量級差很多，各自挑好讀的單位（美股billion／台股兆或億）。
function fmtSize(size) {
  if (!size) return '—';
  if (curM === 'tw') {
    return size >= 1e12 ? (size/1e12).toFixed(2) + '兆' : (size/1e8).toFixed(0) + '億';
  }
  return '$' + (size/1e9).toFixed(1) + 'B';
}

// 多週期象限一覽（2026-08-26 加）：重用 window.RRG_DATA 裡已經算好的 4 個週期資料，
// 不用額外抓——只是換個角度切同一份資料，看短中長期象限是否一致。
var MP_PERIODS = [20, 60, 120, 240];
var MP_LABEL = {20: '短線', 60: '波段', 120: '中期', 240: '長期'};
function mpDots(key) {
  return MP_PERIODS.map(function(n) {
    var byBench = window.RRG_DATA[curM] || {};
    var arr = (byBench[curBench] || {})[String(n)] || [];
    var pt = arr.find(function(p) { return p.key === key; });
    var q = pt && pt.quadrant;
    var col = q ? (QCOLOR[q] || '#5f80a6') : '#2a3550';
    var title = MP_LABEL[n] + '(' + n + '日)：' + (q ? QLABEL[q] : '資料不足');
    return '<span style="background:' + col + '" title="' + title + '"></span>';
  }).join('');
}

// 殘影效果：原本只有一條細線當軌跡，用戶反饋不明顯。改成「越舊越淡、越舊越小」
// 的殘影泡泡疊在細線上——跟真實殘影/彗星尾巴的視覺邏輯一樣，比一條線好辨認方向與新舊。
// 2026-08-25：加 highlightKey——反饋「軌跡很不清楚」，根因是 11~17 條軌跡同時
// 全部顯示，本來就會互相蓋。與其再調透明度（已經調過一輪，治標不治本），
// 改成滑鼠移到某顆泡泡／排行榜某一列時，只留那一條清楚，其餘壓到幾乎看不見——
// 一次只看一條軌跡，方向才看得懂；不 hover 時維持原本全部淡淡顯示的樣子。
// onlyKeys（2026-08-26 加）：有勾選特定產業時，其他籃子的軌跡直接不算——
// 反正對應的泡泡都已經被篩掉了，畫看不到主泡泡的軌跡沒有意義。
function buildTrailDs(fullFrames, uptoIdx, weeks, highlightKey, onlyKeys) {
  if (weeks <= 0 || uptoIdx < 1) return [];
  var start = Math.max(0, uptoIdx - weeks + 1);
  var slice = fullFrames.slice(start, uptoIdx + 1);
  if (slice.length < 2) return [];
  var byKey = {};
  slice.forEach(function(f) {
    f.points.forEach(function(p) {
      // 補上這幀的日期到每個點身上——原本 frame 的點物件沒有帶日期，
      // 只有 frame 本身有；起點/中點標記需要知道「這是哪一天」。
      (byKey[p.key] = byKey[p.key] || []).push(Object.assign({}, p, {date: f.date}));
    });
  });
  window._rrgTrailMarkers = [];   // 2026-08-26：起點/中點標記，只標「當下唯一高亮那條軌跡」
  var lineDs = [], ghostData = [], ghostColors = [];
  Object.keys(byKey).forEach(function(k) {
    if (onlyKeys && onlyKeys.size && !onlyKeys.has(k)) return;
    var pts = byKey[k];
    if (pts.length < 2) return;
    var col = keyColor(k);
    var isHi = highlightKey && k === highlightKey;
    var isDim = highlightKey && !isHi;
    var hist = pts.slice(0, -1);   // 排除最後一個——那是現在的位置，主泡泡已經畫了，不用重疊一個殘影在上面
    // 反饋「可以標出第一個點還有中間跟最後嗎」——「最後」本來就有主泡泡+名字標籤，
    // 這裡補起點跟中點。只在高亮單一籃子時標（不然17條軌跡全部都標，又變回一開始
    // 「配色/軌跡混亂」那個問題，跟 hover-isolate 的初衷矛盾）。
    if (isHi && hist.length >= 1) {
      var first = hist[0], mid = hist[Math.floor((hist.length - 1) / 2)];
      window._rrgTrailMarkers.push({ratio: first.ratio, momentum: first.momentum, label: first.date + ' 起點'});
      if (hist.length >= 3) {
        window._rrgTrailMarkers.push({ratio: mid.ratio, momentum: mid.momentum, label: mid.date});
      }
    }
    hist.forEach(function(p, i) {
      var t = (i + 1) / hist.length;         // 0(最舊)→1(最接近現在)
      var a = isHi ? Math.min(1, 0.35 + t * 0.65) : isDim ? 0.04 : (0.16 + t * 0.55);
      var rMul = isHi ? 1.25 : 1;
      ghostData.push({x: p.ratio, y: p.momentum, r: Math.max(3, (p.radius || 10) * (0.35 + 0.4 * t) * rMul)});
      ghostColors.push(_hexAlpha(col, a));
    });
    var lineA = isHi ? 0.95 : isDim ? 0.05 : 0.4;
    lineDs.push({type: 'line', data: pts.map(function(p){return {x: p.ratio, y: p.momentum};}),
                 borderColor: _hexAlpha(col, lineA), borderWidth: isHi ? 2.5 : 1.5, pointRadius: 0,
                 showLine: true, fill: false, order: isHi ? 5 : 3});
  });
  if (ghostData.length) {
    lineDs.push({data: ghostData, backgroundColor: ghostColors, borderWidth: 0, order: 4});
  }
  return lineDs;
}

function updateChartPoints(pts, trailDs) {
  var bubbleDs = {
    label: '位置',
    data: pts.map(function(p) { return {x: p.ratio, y: p.momentum, r: p.radius || 10}; }),
    // 2026-08-25 拿掉邊框的象限色：泡泡填色(8色分類)＋邊框(4色象限)兩種色相疊在同一
    // 顆泡泡上，兩軸色域互相干擾，是「配色混亂」反饋的主因之一。象限資訊改成只留
    // 背景色塊(quadrantBgPlugin)＋泡泡所在位置本身＋排行榜色點三個管道，不再重複
    // 佔用泡泡邊框這個位置——邊框改中性色，純粹讓泡泡在深色背景上更立體、好辨識輪廓。
    backgroundColor: pts.map(function(p) { return _hexAlpha(keyColor(p.key), 0.85); }),
    borderColor: 'rgba(232,242,255,.5)',
    borderWidth: 1.5, order: 10   // order 要比殘影(3/4)高，確保主泡泡永遠畫在殘影上面
  };
  if (!rrgChart) {
    rrgChart = new Chart(document.getElementById('rrgChart'), {
      type: 'bubble',
      data: {datasets: [bubbleDs].concat(trailDs || [])},
      options: {
        responsive: true, maintainAspectRatio: false,
        // 永遠關掉 Chart.js 自己的動畫——補間完全由我們手動算好座標再餵進來
        // （見上方 playRAF 那段的教訓：讓 Chart.js 自己補間會出現「從底部長出來」的假動畫）。
        animation: false,
        interaction: {mode: 'point', intersect: true},
        // 滑鼠移到某顆泡泡，只讓那條軌跡清楚顯示（見 buildTrailDs 的 highlightKey 說明）。
        onHover: function(evt, elements) {
          var hit = elements.find(function(e) { return e.datasetIndex === 0; });
          var key = hit && window._rrgCurPts && window._rrgCurPts[hit.index] ? window._rrgCurPts[hit.index].key : null;
          if (key !== hoveredKey) setTrailHighlight(key);
        },
        // 2026-08-26：點圖上的泡泡＝勾選/取消勾選那個產業（跟點排行榜某一列同一個
        // toggleSelect，圖表跟排行榜是同一套篩選狀態，兩邊點哪邊都一樣）。
        onClick: function(evt, elements) {
          var hit = elements.find(function(e) { return e.datasetIndex === 0; });
          var key = hit && window._rrgCurPts && window._rrgCurPts[hit.index] ? window._rrgCurPts[hit.index].key : null;
          if (key) toggleSelect(key);
        },
        plugins: {
          legend: {display: false},
          tooltip: {callbacks: {label: function(ctx) {
            var p = window._rrgCurPts && window._rrgCurPts[ctx.dataIndex];
            if (!p) return '';
            return [p.name + '（' + QLABEL[p.quadrant] + '）',
                    'RS-Ratio ' + p.ratio.toFixed(1) + '／RS-Momentum ' + p.momentum.toFixed(1),
                    '資金規模 ' + fmtSize(p.size)];
          }}}
        },
        scales: {
          // 固定死 min/max：原本 Chart.js 每次 update 都照當下資料自動縮放，
          // 切市場/基準/週期或播放動畫時整張圖的座標尺度會跟著跳動，
          // 泡泡明明沒怎麼動、畫面卻感覺在亂飄。實測全部資料落在95.8~104.9，
          // 固定 AXIS_MIN~AXIS_MAX（留一點緩衝）之後，唯一會動的只有泡泡本身。
          x: {min: AXIS_MIN, max: AXIS_MAX, title: {display:true, text:'RS-Ratio 相對強弱', color:'#8fb0d6'}, ticks:{color:'#5f80a6', stepSize: 1}, grid:{color:'#16223A'}},
          y: {min: AXIS_MIN, max: AXIS_MAX, title: {display:true, text:'RS-Momentum 強弱變化率', color:'#8fb0d6'}, ticks:{color:'#5f80a6', stepSize: 1}, grid:{color:'#16223A'}}
        }
      },
      plugins: [quadrantBgPlugin(), bubbleLabelPlugin(), trailMarkerPlugin()]
    });
  } else {
    // 更新既有 chart 的資料集，不整個銷毀重建；'none' 是刻意的，見上面 animation:false 的說明。
    rrgChart.data.datasets = [bubbleDs].concat(trailDs || []);
    rrgChart.update('none');
  }
  window._rrgCurPts = pts;
}

// 播放中不處理 hover（會跟 tweenWeek 每格都在 updateChartPoints 打架），
// 只有靜態畫面時 hover 才會重算一次軌跡（成本很低，只是重畫 trail 那幾個 dataset）。
// 只留勾選的產業（排行榜可複選）。空集合＝沒勾＝顯示全部，不是「選了但沒東西」。
function filteredPts(pts) {
  return selectedKeys.size ? pts.filter(function(p) { return selectedKeys.has(p.key); }) : pts;
}

// 圖表重畫的單一入口：套用目前的勾選篩選＋hover高亮，不重新抓資料
// （資料已經在 _lastAllPts/_lastFullFrames 裡，篩選/hover都只是換一種切法）。
function renderChart() {
  var pts = filteredPts(_lastAllPts);
  var trailDs = buildTrailDs(_lastFullFrames, _lastUptoIdx, tailWeeks, hoveredKey, selectedKeys);
  updateChartPoints(pts, trailDs);
}

function setTrailHighlight(key) {
  if (isPlaying || !_lastFullFrames.length) return;
  hoveredKey = key;
  renderChart();
}

// 排行榜某一列點一下＝勾選/取消勾選；圖表跟著只顯示勾選的幾檔。
function _escHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

// 排行榜整段重畫（篩選/展開狀態變動都走這裡）——17列字串重組成本可忽略，
// 不值得為了省這點效能另外維護局部更新的邏輯。
// 2026-08-25：排行榜寬度改跟圖表一樣寬（原本被限在較窄的右側欄），
// 多出來的空間補幾欄：資金規模（原本只有泡泡大小看得出來，數字化更清楚）、
// 多週期象限一覽、強弱位置迷你條（跟圖表X軸對照著看）。
// 2026-08-26：dot／迷你條標記改用 keyColor(產業分類色)，不再用 QCOLOR(象限色)——
// 反饋「圖的顏色跟下面產業的顏色不一致」，根因是圖表泡泡填色是分類色、
// 排行榜圓點卻是象限色，兩套不同編碼當然對不起來。象限資訊本來就有文字欄
// （「象限」那一欄）顯示，改用分類色不會少掉任何資訊。
function renderRankList() {
  var rank = _lastAllPts.slice().sort(function(a,b){ return (b.ratio+b.momentum)-(a.ratio+a.momentum); });
  document.getElementById('rrgRank').innerHTML = rank.map(function(p) {
    var pct = Math.max(0, Math.min(100, (p.ratio - AXIS_MIN) / (AXIS_MAX - AXIS_MIN) * 100));
    var col = keyColor(p.key);
    var isExp = expandedKeys.has(p.key);
    var row = '<div class="rrgrow' + (selectedKeys.has(p.key) ? ' sel' : '') + '" data-key="'+p.key+'">'+
      '<span class="nm"><button type="button" class="expbtn" data-key="'+p.key+'" '+
        'aria-label="展開看前' + TOP_HOLDINGS_N_JS + '大成分股">'+(isExp?'▾':'▸')+'</button>'+
        '<span class="dot" style="background:'+col+'"></span>'+
        '<span class="nmtext">'+_escHtml(p.name)+'</span></span>'+
      '<span class="qv">'+QLABEL[p.quadrant]+'</span>'+
      '<span class="num ratioval">'+p.ratio.toFixed(1)+'</span>'+
      '<span class="num momval">'+p.momentum.toFixed(1)+'</span>'+
      '<span class="sz">'+fmtSize(p.size)+'</span>'+
      '<span class="mp">'+mpDots(p.key)+'</span>'+
      '<span class="posbar"><span class="posbartrack">'+
        '<span class="posbarmark" style="left:'+pct.toFixed(1)+'%;background:'+col+'"></span>'+
      '</span></span></div>';
    return row + (isExp ? holdingsHTML(p.key) : '');
  }).join('') || '<div class="rrgrow">（本次無資料）</div>';
}

// 展開一個籃子＝看它前幾大成分股（台美股都是市值排序的前幾大——
// 兩者都是靜態資料，見 window.RRG_HOLDINGS）。
function holdingsHTML(key) {
  var list = ((window.RRG_HOLDINGS || {})[curM] || {})[key] || [];
  if (!list.length) {
    return '<div class="rrgexpand"><div class="rrgexpempty">暫無成分股資料</div></div>';
  }
  var rows = list.map(function(h) {
    var w = Math.max(0, Math.min(100, h.weight_pct));
    return '<div class="rrgexprow"><span class="exptk">'+_escHtml(h.ticker)+'</span>'+
      '<span class="expnm">'+_escHtml(h.name)+'</span>'+
      '<span class="expwt">'+h.weight_pct.toFixed(1)+'%</span>'+
      '<span class="expbar"><span class="expbarfill" style="width:'+w.toFixed(0)+'%"></span></span></div>';
  }).join('');
  return '<div class="rrgexpand">'+rows+'</div>';
}

function toggleExpand(key) {
  if (expandedKeys.has(key)) expandedKeys.delete(key); else expandedKeys.add(key);
  renderRankList();
}

function toggleSelect(key) {
  if (selectedKeys.has(key)) selectedKeys.delete(key); else selectedKeys.add(key);
  document.querySelectorAll('.rrgrow[data-key]').forEach(function(r) {
    r.classList.toggle('sel', selectedKeys.has(r.dataset.key));
  });
  var info = document.getElementById('selInfo');
  info.textContent = selectedKeys.size ? ('已選 ' + selectedKeys.size + ' 檔（只顯示在圖表上）') : '';
  document.getElementById('selClear').style.display = selectedKeys.size ? '' : 'none';
  renderChart();
}
function clearSelection() {
  selectedKeys.clear();
  document.querySelectorAll('.rrgrow[data-key]').forEach(function(r) { r.classList.remove('sel'); });
  document.getElementById('selInfo').textContent = '';
  document.getElementById('selClear').style.display = 'none';
  renderChart();
}

function draw() {
  stopPlay();
  var pts = rrgGet('bubble');
  var fullFrames = rrgGet('frames');
  // 每個籃子的分類色要固定不能每次重畫就換——用「現在」這一幀的籃子順序當基準
  // （frames 最後一幀是最完整的籃子清單，見 Python 端 _frames_data 的順序修正）。
  if (fullFrames.length) {
    _keyOrderCache[curM] = fullFrames[fullFrames.length - 1].points.map(function(p){ return p.key; });
  }
  // 靜態（沒在播放）畫面也用尾巴長度滑桿控制要不要畫軌跡——跟播放時同一套邏輯，
  // 不是播放才有軌跡、平常沒有，兩種狀態顯示邏輯要一致。
  hoveredKey = null;   // 換篩選/市場後，之前 hover 選到的籃子多半已經不在新清單裡，重置
  _lastFullFrames = fullFrames; _lastUptoIdx = fullFrames.length - 1;   // 供 hover 高亮/篩選重算軌跡用
  _lastAllPts = pts;   // 未篩選的完整清單——renderChart() 會照 selectedKeys 再篩一次

  if (rrgChart) { rrgChart.destroy(); rrgChart = null; }   // 換市場/基準/週期要強制重建一次（軸範圍等設定要重來）
  renderChart();
  document.getElementById('rrgFrameLabel').style.display = 'none';

  expandedKeys.clear();   // 換篩選/市場後，展開的成分股清單多半也不是同一批籃子了，收合重置
  renderRankList();

  var btn = document.getElementById('playBtn');
  var hint = document.getElementById('playHint');
  if (fullFrames.length < 2) {
    btn.disabled = true;
    hint.textContent = '（資料還在累積，需要至少2週歷史才能播放）';
  } else {
    var rangeW = RANGE_WEEKS[curRange] || fullFrames.length;
    var n = Math.min(rangeW, fullFrames.length);
    btn.disabled = false;
    hint.textContent = '（回放 ' + n + ' 週，共累積 ' + fullFrames.length + ' 週歷史）';
  }
}

var isPlaying = false;

document.getElementById('playBtn').addEventListener('click', function() {
  if (isPlaying) { isPlaying = false; stopPlay(); return; }
  var fullFrames = rrgGet('frames');
  if (fullFrames.length < 2) return;
  var rangeW = RANGE_WEEKS[curRange] || fullFrames.length;
  var startOffset = Math.max(0, fullFrames.length - rangeW);
  var playFrames = fullFrames.slice(startOffset);
  if (playFrames.length < 2) return;
  isPlaying = true;
  playIdx = 0;
  document.getElementById('playBtn').classList.add('playing');
  document.getElementById('playBtn').textContent = '⏸ 播放中…';
  var lbl = document.getElementById('rrgFrameLabel');
  lbl.style.display = 'block';

  // 走「真實一週 → 真實下一週」，中間用 rAF 自己逐格算補間座標餵給 Chart.js
  // （不讓 Chart.js 自己補間，見上面 animation:false 的說明）。
  function tweenWeek(fromPts, toPts, trailDs, onDone) {
    var t0 = performance.now();
    function frame(now) {
      if (!isPlaying) return;                 // 使用者按了停止，中途放棄這段補間
      var t = Math.min(1, (now - t0) / ANIM_MS);
      var e = _easeInOutQuad(t);
      var pts = toPts.map(function(pb, idx) {
        var pa = fromPts[idx] || pb;
        return {key: pb.key, name: pb.name,
                ratio: _lerp(pa.ratio, pb.ratio, e),
                momentum: _lerp(pa.momentum, pb.momentum, e),
                radius: _lerp(pa.radius || 10, pb.radius || 10, e),
                size: _lerp(pa.size || 0, pb.size || 0, e),
                quadrant: e < 0.5 ? pa.quadrant : pb.quadrant};
      });
      updateChartPoints(filteredPts(pts), trailDs);
      if (t < 1) { playRAF = requestAnimationFrame(frame); } else { playRAF = null; onDone(); }
    }
    playRAF = requestAnimationFrame(frame);
  }

  function stepPlay() {
    if (!isPlaying) return;
    if (playIdx >= playFrames.length - 1) { isPlaying = false; stopPlay(); draw(); return; }
    var a = playFrames[playIdx].points, b = playFrames[playIdx + 1].points;
    var realIdx = startOffset + playIdx + 1;
    var trailDs = buildTrailDs(fullFrames, realIdx, tailWeeks, null, selectedKeys);
    lbl.textContent = playFrames[playIdx + 1].date;
    tweenWeek(a, b, trailDs, function() {
      playIdx++;
      playTimer = setTimeout(stepPlay, PAUSE_MS);
    });
  }
  lbl.textContent = playFrames[0].date;
  updateChartPoints(filteredPts(playFrames[0].points), buildTrailDs(fullFrames, startOffset, tailWeeks, null, selectedKeys));
  playTimer = setTimeout(stepPlay, PAUSE_MS);
});

document.getElementById('mktSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#mktSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curM = b.dataset.m;
  selectedKeys.clear();   // 換市場代號完全不同一套（美股ETF代號 vs 台股sector名），選取沒意義了
  draw();
});
document.getElementById('benchSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#benchSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curBench = b.dataset.b; draw();
});
document.getElementById('perSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#perSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curP = b.dataset.p; draw();
});
document.getElementById('rangeSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#rangeSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curRange = b.dataset.r; draw();
});
document.getElementById('tailSlider').addEventListener('input', function(e) {
  tailWeeks = parseInt(e.target.value, 10);
  document.getElementById('tailVal').textContent = tailWeeks + ' 週';
  if (!playTimer) draw();   // 播放中先不重畫，讓下一個真實週的格子自然套用新尾巴長度
});
// 排行榜某一列 hover 也能高亮該籃子的軌跡（跟直接 hover 泡泡同一套邏輯），
// 事件委派在容器上，因為每次 draw() 都會整個重畫 #rrgRank 的 innerHTML。
document.getElementById('rrgRank').addEventListener('mouseover', function(e) {
  var row = e.target.closest('.rrgrow');
  if (row && row.dataset.key) setTrailHighlight(row.dataset.key);
});
document.getElementById('rrgRank').addEventListener('mouseleave', function() {
  setTrailHighlight(null);
});
// 點一列＝勾選/取消勾選（複選）。跟上面 hover 高亮軌跡是兩件事，不衝突——
// hover 只是「看一下這條」，點擊才是「圖表只留這幾檔」。
document.getElementById('rrgRank').addEventListener('click', function(e) {
  var chev = e.target.closest('.expbtn');
  if (chev) { toggleExpand(chev.dataset.key); return; }   // 點展開箭頭：只展開，不連動勾選
  var row = e.target.closest('.rrgrow');
  if (row && row.dataset.key) toggleSelect(row.dataset.key);
});
document.getElementById('selClear').addEventListener('click', clearSelection);
draw();
</script>""")
    return "\n".join(lines)


CSS_EXTRA = """
/* 2026-08-25：篩選面板在圖表左側，寬度加大到 300px（原本 240px 導致4顆一組的按鈕
 [計算週期/回放範圍] 擠成兩排，用戶反饋要維持一列）；小螢幕收成單欄疊回最上面。
 2026-08-26：align-items 改回 start——上一輪改 center 是我猜錯了需求，
 用戶反饋「還是卡在中間」，要的其實是「篩選面板上緣對齊圖表上緣」，不是置中。 */
.rrglayout{display:grid;grid-template-columns:300px 1fr;gap:14px;align-items:start;margin-top:12px}
/* 排行榜搬到圖表下面而不是旁邊（用戶反饋），改直排堆疊。 */
.rrgwrap{display:flex;flex-direction:column;gap:14px}
.rrgbox{height:520px;background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:10px;position:relative}
/* 排行榜寬度改跟圖表一樣寬（原本限制 640px，右側留一大塊空白）。
 多出來的空間補兩欄新資訊：資金規模數字化、RS-Ratio 在座標軸上的相對位置迷你條——
 用戶反饋「太空了，請建議要放什麼」，這兩欄都是現成算好的資料，不用另外抓。 */
.rrgrankpanel{background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:10px;margin-top:14px}
/* 表頭跟資料列共用同一組欄寬(CSS Grid)，這樣兩邊才能真的對齊——
 原本 flex 寫法表頭跟資料列各算各的寬度容易對不準。 */
/* 2026-08-25：RS-Ratio／RS-Momentum 拆成兩欄（原本合併一欄，標題+數字都會被
 擠成兩行，反饋「標題位置太擠」）。
 2026-08-26：加「多週期」欄（20/60/120/240日象限一次看，短中長期是否一致）；
 強弱位置改 1fr 吃掉剩餘寬度——反饋「可以左右填滿嗎」，原本固定100px在寬版面下
 右邊留一大塊空白，改彈性寬度後那條迷你條會跟著排行榜面板寬度一起伸縮。 */
/* 2026-08-26：7欄（拿掉獨立的dot欄——展開箭頭跟色點都併進「產業」欄本身了）。
 表頭跟資料列的欄數／欄寬必須完全一致，這是這次「名字消失、多週期跟強弱位置跑掉」
 的教訓：資料列欄數改了卻沒同步改格線定義，7個元素套進8欄格線，全部欄位錯位一格。 */
/* 2026-08-26（再修）：「產業」欄還是被擠——根因是兩個 1fr 欄（產業／強弱位置）
 平分剩餘空間，強弱位置那條裝飾用的迷你條其實不需要那麼多寬度，卻分走了一半，
 真正需要空間的產業名稱反而不夠。改成只有「產業」是 1fr（吃掉全部剩餘空間），
 強弱位置固定 180px（比原本 100px 寬，仍會隨版面寬度一起變寬，只是不再跟產業搶）。
 2026-08-26（再修二）：中間幾欄（象限/RS-Ratio/RS-Momentum/資金規模/多週期）反饋
 「太擠了」——欄距 gap 從 8px 加大到 18px，加上 RS-Momentum 欄變寬（68→86px，
 原本這個字本身在欄內還是會換行，兩行更擠）、象限欄變寬（40→52px），
 讓中間這一段跟兩側（產業／強弱位置）比起來不會顯得特別擁擠。 */
/* 2026-08-26（手機版）：桌面版7欄固定寬度加總超過600px，手機螢幕(~390px)完全塞不下——
 反饋「產業消失了」「表格內容超出框框」，根因就是這個，不是換算法能修的，是版面
 本身沒做手機版。改用具名 grid-area：桌面版維持一列橫排，<700px 改成「卡片」——
 每個籃子一張卡，欄位改上下堆疊＋文字標籤（用 ::before 加標籤，不用另外寫HTML），
 不用橫向捲動就能看完整資訊。表頭列(.rrgrankhd)手機版直接隱藏——卡片自己帶標籤，
 不需要對齊的表頭了。 */
.rrgrankhd{display:grid;grid-template-columns:1fr 52px 64px 86px 72px 130px 180px;gap:18px;
 grid-template-areas:"name qv ratio mom size mp pos";
 padding:2px 4px 8px;border-bottom:1px solid #2a3550;font-size:10.5px;color:#5f80a6}
.rrgrankhd span:nth-child(2){text-align:center}
.rrgrankhd span:nth-child(3),.rrgrankhd span:nth-child(4){text-align:right}
.rrgrankhd span:nth-child(1){grid-area:name}.rrgrankhd span:nth-child(2){grid-area:qv}
.rrgrankhd span:nth-child(3){grid-area:ratio}.rrgrankhd span:nth-child(4){grid-area:mom}
.rrgrankhd span:nth-child(5){grid-area:size}.rrgrankhd span:nth-child(6){grid-area:mp}
.rrgrankhd span:nth-child(7){grid-area:pos}
.rrgrow{display:grid;grid-template-columns:1fr 52px 64px 86px 72px 130px 180px;gap:18px;align-items:center;
 grid-template-areas:"name qv ratio mom size mp pos";
 padding:7px 4px;border-bottom:1px solid #131c30;font-size:12.5px;cursor:pointer;transition:background .15s}
.rrgrow .nm{grid-area:name}.rrgrow .qv{grid-area:qv}.rrgrow .ratioval{grid-area:ratio}
.rrgrow .momval{grid-area:mom}.rrgrow .sz{grid-area:size}.rrgrow .mp{grid-area:mp}
.rrgrow .posbar{grid-area:pos}
@media (max-width:700px){
  .rrgrankhd{display:none}
  .rrgrow{grid-template-columns:1fr auto;row-gap:7px;column-gap:12px;padding:13px 10px;
   grid-template-areas:"name qv" "ratio mom" "size mp" "pos pos"}
  .rrgrow .qv{grid-area:qv;font-size:12px;font-weight:600;align-self:start}
  .rrgrow .ratioval,.rrgrow .momval,.rrgrow .sz{text-align:left;display:flex;flex-direction:column;gap:2px}
  .rrgrow .ratioval::before{content:"RS-Ratio";font-size:9.5px;color:#5f80a6;font-weight:400}
  .rrgrow .momval::before{content:"RS-Momentum";font-size:9.5px;color:#5f80a6;font-weight:400}
  .rrgrow .sz::before{content:"資金規模";font-size:9.5px;color:#5f80a6;font-weight:400}
  .rrgrow .mp{grid-area:mp;align-self:end;justify-self:end}
  .rrgexprow{grid-template-columns:56px 1fr 40px;column-gap:8px}
  .rrgexprow .expbar{display:none}   /* 手機版寬度不夠放權重條，數字本身已經夠用 */
}
.rrgrow:hover{background:#101b30}
/* 2026-08-26：勾選狀態——左邊一條實色邊線＋淡底色，跟純 hover 的灰底區分開來。 */
.rrgrow.sel{background:#132038;border-left:3px solid #25e6ff;padding-left:1px}
.rrgselbar{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:22px;margin-bottom:4px}
.rrgselbar span{font-size:12px;color:#25e6ff;font-weight:600}
#selClear{background:none;border:1px solid #2a3550;color:#8fb0d6;font-size:11.5px;
 padding:4px 10px;border-radius:6px;cursor:pointer;font-family:inherit}
#selClear:hover{border-color:#25e6ff;color:#25e6ff}
.rrghint{font-size:11px;color:#5f80a6;margin-bottom:8px}
.rrgrow .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.rrgrow .nm{color:#cfe6ff;display:flex;align-items:center;gap:6px;min-width:0}
.rrgrow .nmtext{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.expbtn{background:none;border:0;color:#5f80a6;font-size:11px;cursor:pointer;padding:2px 4px 2px 0;
 flex-shrink:0;font-family:inherit;line-height:1}
.expbtn:hover{color:#25e6ff}
/* 展開的前N大成分股子清單——跨滿整個表格寬度，不受欄寬限制，
 縮排一點跟上層列區分開來。 */
.rrgexpand{padding:8px 4px 10px 34px;background:#080d18;border-bottom:1px solid #131c30}
.rrgexpempty{font-size:11.5px;color:#5f80a6}
.rrgexprow{display:grid;grid-template-columns:70px 1fr 48px 120px;gap:10px;align-items:center;
 padding:4px 0;font-size:11.5px}
.exptk{color:#cfe6ff;font-family:var(--mono,monospace);font-weight:600}
.expnm{color:#8fb0d6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.expwt{color:#5f80a6;text-align:right;font-variant-numeric:tabular-nums}
.expbar{height:4px;background:#16223A;border-radius:2px;overflow:hidden}
.expbarfill{display:block;height:100%;background:#25e6ff;border-radius:2px}
.rrgrow .qv{color:#8fb0d6;font-size:11px;text-align:center}
.rrgrow .sz{color:#8fb0d6;font-size:11.5px;font-variant-numeric:tabular-nums;text-align:right}
.posbar{display:flex;align-items:center}
.posbartrack{position:relative;width:100%;height:4px;background:#16223A;border-radius:2px}
.posbarmark{position:absolute;top:50%;width:8px;height:8px;border-radius:50%;
 transform:translate(-50%,-50%);box-shadow:0 0 0 2px #0a1222}
/* 多週期象限一覽：4 個小圓點對應 20/60/120/240 日，一眼看短中長期象限是否一致
 （用戶反饋「加上其它欄位」，這是重用已經抓好的資料，不用額外打 API）。 */
.mp{display:flex;gap:6px}
.mp span{width:9px;height:9px;border-radius:50%;flex-shrink:0;cursor:help}
.rrgrow .num{color:#5f80a6;font-variant-numeric:tabular-nums;text-align:right}
.playbtn{background:#132038;border:1px solid #2a3550;color:#25e6ff;
 font-size:12.5px;font-weight:600;padding:8px 14px;border-radius:8px;cursor:pointer;font-family:inherit}
.playbtn:hover{border-color:#25e6ff}
.playbtn:disabled{color:#5f80a6;border-color:#16223A;cursor:not-allowed}
.playbtn.playing{color:#ffb020;border-color:#ffb020}
.playhint{font-size:11px;color:#5f80a6;align-self:center}
.rrgframe{position:absolute;top:14px;right:20px;font-size:12px;color:#8fb0d6;
 background:#0a122299;padding:3px 10px;border-radius:6px;pointer-events:none}
/* 2026-08-25：拿掉 position:sticky——用戶反饋「鎖在圖旁邊，不用跟滾輪一起跑」，
 意思是不需要跟隨捲動固定，正常跟著版面流動、待在圖表旁邊的位置就好。 */
/* 2026-08-26：高度固定跟圖表一樣 520px（反饋「市場(篩選)上下跟圖上下一樣大」）——
 原本自然高度比圖表矮一截，兩個並排的框高度對不齊。space-between 把 6 排
 控制項平均撐開分布在整個高度裡，不是全部擠在頂端、底下留一塊空白。 */
.rrgctrl{display:flex;flex-direction:column;justify-content:space-between;height:520px;
 padding:12px 14px;background:#0a1222;border:1px solid #16223A;border-radius:12px}
/* 篩選面板改窄欄直排：標籤疊在控制項上面，不是左右並排——橫排在300px塞不下。
 按鈕本身也縮小一號（padding/字級都比全站預設的 .seg button 小），
 這樣「計算週期」「回放範圍」這兩組4顆一排的才擠得進一列，不會被逼到換行。 */
.rrgctrl .ctrlrow{display:flex;flex-direction:column;align-items:stretch;gap:6px}
.rrgctrl .seg button{padding:6px 9px;min-height:32px;font-size:11.5px}
.ctrllbl{font-size:11.5px;color:#5f80a6}
.ctrlnote{font-size:10px;color:#5f80a6;line-height:1.5;margin-top:-2px}
.segwide button{line-height:1.3;padding:5px 6px}
.pnote{font-size:9px;color:#5f80a6;font-weight:400}
.seg button[aria-pressed=true] .pnote{color:#cfe6ff}
.tailslider{width:100%;accent-color:#25e6ff}
.tailval{font-size:12px;color:#25e6ff;font-variant-numeric:tabular-nums}
/* 2026-08-25：說明區塊卡片化（用戶反饋原本一大坨灰字「不明顯」）。
 主要說明用比 --muted 亮的藍白色，只有最後一條(已知限制)維持muted層級。 */
.rrgnote{background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:16px 18px;margin-top:14px}
.rrgnotehd{font-size:13.5px;font-weight:700;color:#e8f2ff;margin-bottom:10px}
.rrgnoteitem{color:#cfe6ff;font-size:12.5px;line-height:1.75;padding:10px 0;border-top:1px solid #131c30}
.rrgnoteitem:first-of-type{border-top:0;padding-top:0}
.rrgnotedim{color:#8fb0d6;font-size:12px}
/* 「反色」重點提示：背景填色、文字反過來用深色，跟周圍的深底淺字對調，才會跳出來。 */
.hl{background:var(--accent);color:#04070f;padding:1px 7px;border-radius:4px;font-weight:700}
@media (max-width:980px){.rrglayout{grid-template-columns:1fr}.rrgctrl{height:auto}}
@media (max-width:820px){.rrgbox{height:400px}}
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/rotation.html")
    args = ap.parse_args()

    print("抓美股產業籃子（TradingView分類+成分股，需逐檔抓歷史價，較慢；兩種基準共用同一批，只抓一次）…")
    us_baskets, us_index_bench, us_holdings = _fetch_baskets("us")
    print("抓台股產業籃子（需逐檔抓歷史價，較慢；兩種基準共用同一批，只抓一次）…")
    tw_baskets, tw_index_bench, tw_holdings = _fetch_baskets("tw")
    holdings = {"us": us_holdings, "tw": tw_holdings}

    hist = load_history()
    date_str = time.strftime("%Y-%m-%d")
    snaps = {"us": {}, "tw": {}}
    for m, baskets, index_bench in (("us", us_baskets, us_index_bench), ("tw", tw_baskets, tw_index_bench)):
        for bench in ("index", "equal"):
            snap, backfill = compute_snapshot(baskets, index_bench, benchmark=bench, backfill_weeks=BACKFILL_WEEKS)
            print(f"  {m}/{bench}: {len(snap)} 個籃子算出結果，回填 {len(backfill)} 週歷史")
            snaps[m][bench] = snap
            # 2026-08-26：先清掉跟現在籃子完全對不上的舊歷史列（例如美股從 SPDR ETF
            # 換成 TV 產業分類前留下的 XLB/XLC/... 那些列）——這些舊列的日期常常跟
            # 新方法論的回填日期錯開幾天，不會被下面「同一天去重」擋掉，會一直卡在
            # 歷史裡跟新資料交錯，害動畫每兩格有一格是沿用舊值、看起來卡住不動。
            keep = [r for r in hist.get(m, {}).get(bench, [])
                    if set(r.get("snapshot", {}).keys()) & set(snap.keys())]
            dropped = len(hist.get(m, {}).get(bench, [])) - len(keep)
            if dropped:
                print(f"  {m}/{bench}: 清掉 {dropped} 筆對不上現在籃子的舊方法論歷史列")
            hist.setdefault(m, {"index": [], "equal": []})[bench] = keep
            # 先疊回填的歷史（由舊到新），再疊「現在」這一筆——append_history 依日期去重，
            # 重跑也不會累積出重複的同一天。
            for d, s in backfill:
                hist = append_history(hist, m, bench, s, d)
            hist = append_history(hist, m, bench, snap, date_str)
    save_history(hist)

    html = render_html(snaps, hist, holdings)
    # obis 一律嘗試寫，不用額外參數——跟 buffett_html.py/portfolio_html.py 同款寫法
    # （本機成功；GitHub Actions 上這個路徑不存在，try/except 吞掉不影響其他輸出）。
    # 先前這裡要求 --obis 才寫，跟其他頁面不一致、容易忘記加，已改掉。
    OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"
    outs = [args.output, os.path.join(OBIS, "產業輪動雷達.html")]
    for out in outs:
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"已存：{out}")
        except Exception as e:
            print(f"警告 寫入 {out} 失敗（不影響其他輸出）：{e}")


if __name__ == "__main__":
    main()


