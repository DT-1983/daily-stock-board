# -*- coding: utf-8 -*-
"""產業輪動雷達 RRG（Relative Rotation Graph）

2026-08-25 建立。緣由：老墨的 XQ 官方工具「PROJECT RX 產業輪動雷達」
（mophyfei/MOFI_XQ repo）示範了這張圖的價值——資金輪動到哪個產業一眼看穿，
比在單一個股上猜方向踏實。他的版本吃 XQ 自己維護的台股族群/細產業指數，
我們沒有那份資料，改用可行的替代籃子：

  美股：11 檔 SPDR 類股 ETF（XLK/XLF/...）——業界標準做法，
        StockCharts 自己的美股 Sector RRG 用的也是這組，免另外聚合。
  台股：沒有現成的類股指數 ticker 可抓（yfinance 查無 ^TW 開頭的官方分類指數），
        改成自己聚合：TradingView sector 分類下，市值前 N 大成分股等權組成籃子指數。

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

# 美股：SPDR 11 大類股 ETF。免聚合、免猜產業分類，直接抓歷史價格。
SPDR_SECTORS = {
    "XLK": "科技", "XLF": "金融", "XLV": "醫療保健", "XLY": "非必需消費",
    "XLP": "必需消費", "XLE": "能源", "XLI": "工業", "XLB": "原物料",
    "XLU": "公用事業", "XLRE": "房地產", "XLC": "通訊服務",
}
US_BENCHMARK = "^GSPC"          # 跟 technical_indicators._benchmark 美股基準一致
TW_BENCHMARK = "^TWII"
TW_BASKET_SIZE = 8              # 每個台股產業取市值前 8 大聚合成籃子（等權）
TW_MIN_MEMBERS = 3              # 成分股不足 3 檔的產業籃子雜訊太大，跳過


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


def _tw_sector_members(min_market_cap=3e9):
    """台股各 sector 市值前 TW_BASKET_SIZE 大成分股。用 TradingView 一次性快照，
    不逐檔查——這一步快（幾秒），真正貴的是後面逐檔抓歷史價格。
    回 {sector: (tickers, 全部合格成分股市值合計)}——市值合計是「資金大小」的代理值，
    2026-08-25 補：原本完全沒算這個，泡泡大小美股全部一樣、台股只是算成分股檔數，
    根本不是「資金大小」。這裡用「合格成分股（市值≥門檻）市值合計」而非只加前8大，
    比較貼近整個產業的資金規模，不會因為只取前8大而低估大產業。"""
    base = Query().set_markets("taiwan")
    q = base.select("name", "sector", "market_cap_basic", "exchange", "close").where(
        col("market_cap_basic") >= min_market_cap,
        col("close") >= 5.0,
        col("exchange").isin(["TWSE", "TPEX"]),
    )
    count, df = q.limit(3000).get_scanner_data()
    if df is None or df.empty:
        return {}
    df["ticker"] = df["name"].astype(str) + df["exchange"].map({"TWSE": ".TW", "TPEX": ".TWO"}).fillna(".TW")
    out = {}
    for sector, grp in df.groupby("sector"):
        if not sector or str(sector).lower() == "nan":
            continue
        top = grp.sort_values("market_cap_basic", ascending=False).head(TW_BASKET_SIZE)
        if len(top) >= TW_MIN_MEMBERS:
            total_cap = float(grp["market_cap_basic"].sum())   # 全部合格成分股，不只前8大
            out[sector] = (top["ticker"].tolist(), total_cap)
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
    if len(series_list) < TW_MIN_MEMBERS:
        return None
    all_idx = sorted(set().union(*[set(s.index) for s in series_list]))
    aligned = [s.reindex(all_idx).ffill() for s in series_list]
    rets = pd.concat([a.pct_change() for a in aligned], axis=1).mean(axis=1, skipna=True)
    idx = (1 + rets.fillna(0)).cumprod() * 100
    idx.iloc[0] = 100.0
    return idx


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
QUADRANT_COLOR = {"leading": "#ff5277", "improving": "#25e6ff", "lagging": "#8fb0d6", "weakening": "#ffb020"}


# ── 快照組裝：算出每個籃子在 4 個週期下的最新座標 ─────────────────────────

def _spdr_aum(ticker):
    """SPDR ETF 的資產規模（美元）——這就是「這個籃子裡有多少資金」的直接數字，
    不用像台股那樣拿市值當代理，ETF 的 AUM 本身就是資金量。抓不到就回 None，
    呼叫端要用「不知道」處理，不能當 0（0 會讓泡泡整個消失或算錯排名）。"""
    try:
        info = yf.Ticker(ticker).info
        aum = info.get("totalAssets") or info.get("netAssets")
        return float(aum) if aum else None
    except Exception:
        return None


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


def _fetch_baskets(market):
    """只做網路抓取（貴的部分），回 (baskets, index_bench)。
    baskets = [(key, name, closes_series, size), ...]。
    跟 benchmark 選擇無關——「等權類股」基準要用到全部籃子的價格序列，
    所以基準運算要等全部籃子都抓完才能算，抓取本身跟基準選哪個無關，
    拆開後同一批抓來的資料可以算多種基準，不用每切一次基準就重抓一次。"""
    if market == "us":
        index_bench = yf.Ticker(US_BENCHMARK).history(period="3y")["Close"]
        baskets = []
        for tk, name in SPDR_SECTORS.items():
            h = yf.Ticker(tk).history(period="3y")
            if h.empty:
                print(f"  [industry_rotation] {tk} 抓取失敗，跳過")
                continue
            aum = _spdr_aum(tk)
            baskets.append((tk, name, h["Close"], aum or 0.0))
        return baskets, index_bench

    if market == "tw":
        index_bench = yf.Ticker(TW_BENCHMARK).history(period="3y")["Close"]
        members = _tw_sector_members()
        baskets = []
        for sector, (tks, total_cap) in members.items():
            closes = []
            for tk in tks:
                h = yf.Ticker(tk).history(period="3y")
                if h.empty:
                    continue
                closes.append(h["Close"])
            b = _basket_index(closes)
            if b is None:
                print(f"  [industry_rotation] {sector} 成分股資料不足（<{TW_MIN_MEMBERS}檔），跳過")
                continue
            baskets.append((sector, SECTOR_TW_LABEL.get(sector, sector), b, total_cap))
        return baskets, index_bench

    raise ValueError(f"未知市場：{market}")


BENCHMARK_LABEL = {"index": "加權指數／S&P500", "equal": "等權類股（全部籃子等權組成）"}


def compute_snapshot(baskets, index_bench, benchmark="index", backfill_weeks=0):
    """純計算（不打API），可以對同一批 baskets 重複呼叫算不同基準，成本很低。
    benchmark: "index"（加權指數/S&P500）或 "equal"（用全部籃子自己等權組成的合成指數，
    跟同儕比不跟大盤比）。回 (current, history_rows)，格式同舊版 build_market_snapshot。

    2026-08-25 補「等權類股」：老墨控制面板有「加權指數/櫃買指數/等權類股」三選項。
    櫃買指數（TPEx上櫃指數）查過幾種常見 yfinance ticker 猜法都拿不到資料，沒做——
    寧可少一個選項也不要編一個假資料源。

    2026-08-25 補回填：3年歷史資料本來就抓了，同一批資料回頭算過去每週座標
    幾乎不用額外成本，不用等每週排程真的跑過才多一幀動畫。
    ⚠️ 已知簡化：回填快照的「資金規模」用現在的 AUM/市值回貼過去（無歷史資料可用），
    RS-Ratio/Momentum 本身是當時真實價格算的，只有泡泡大小是簡化。
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
    for key, name, closes, size in baskets:
        rm = rs_ratio_momentum(closes, bench)
        if rm is None:
            continue
        idx = rm[PERIODS[0]]["ratio"].index
        cur = _periods_at(rm, idx[-1])
        if not cur:
            continue
        out[key] = {"name": name, "periods": cur, "size": size}
        if backfill_weeks:
            for ts, date_str in _backfill_points(idx, backfill_weeks):
                p = _periods_at(rm, ts)
                if p:
                    hist_by_date.setdefault(date_str, {})[key] = {"name": name, "periods": p, "size": size}
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
    （SPDR AUM 從幾十億到上千億美元、台股產業市值合計也是同樣量級差），
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
                      "momentum": p["momentum"], "quadrant": p["quadrant"], "radius": radius_fn(size)}
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


def render_html(snaps, hist):
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
    date = time.strftime("%Y-%m-%d %H:%M")

    quad_note = (
        'X軸 <b>RS-Ratio 相對強弱</b>、Y軸 <b>RS-Momentum 強弱變化率</b>，兩軸中心值皆為 100。'
        '四象限順時針輪動：'
        f'<b style="color:{QUADRANT_COLOR["improving"]}">改善</b> → '
        f'<b style="color:{QUADRANT_COLOR["leading"]}">領先</b> → '
        f'<b style="color:{QUADRANT_COLOR["weakening"]}">弱化</b> → '
        f'<b style="color:{QUADRANT_COLOR["lagging"]}">落後</b> → 回到改善。'
        '<b>「改善→領先」的轉折是資金剛轉強的甜蜜點</b>，值得優先注意。'
    )
    period_btns = "".join(
        f'<button data-p="{n}" aria-pressed="{"true" if n == 20 else "false"}">{n}日<br><span class="pnote">{PERIOD_LABEL[n]}</span></button>'
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
                 f"RRG（Relative Rotation Graph）· 美股11大類股(SPDR ETF) + 台股{len(snap_tw_index)}個TradingView產業籃子"
                 f" · 更新 {esc(date)}（每週六隨全市場重掃）", NAV, "rotation")
    note_html = (
        '<div class="note">' + quad_note + '<br>'
        '資料源：美股用 11 檔 SPDR 類股 ETF（業界標準籃子）；台股沒有官方類股指數可直接抓，'
        f'改成 TradingView 產業分類下市值前 {TW_BASKET_SIZE} 大成分股等權聚合。'
        '公式為業界公開重建版（非老墨官方精確值），數字不會跟他的工具逐點對上，方法論一致。<br>'
        '<b>泡泡大小＝資金規模</b>（美股用 SPDR ETF 資產規模美元、台股用該產業合格成分股市值合計台幣）——'
        '兩個市場單位不同、不能互比，只在各自市場內部比大小。<br>'
        f'<span style="color:var(--muted)">軌跡與「▶ 播放資金移動軌跡」已回填近 {BACKFILL_WEEKS} 週歷史'
        '（用既有3年價格資料反推，不是等出來的）；之後每週六會再多疊一幀「現在」。'
        '回填歷史的泡泡大小是用現在的資金規模回貼過去，位置(RS-Ratio/Momentum)則是當時的真實值。<br>'
        '基準只做了「加權指數」與「等權類股」——查過幾種常見 yfinance 代號寫法，'
        '「櫃買指數」都拿不到資料，寧可少一個選項也不編假資料源。</span>'
        '</div>'
    )
    ctrl_html = (
        '<div class="ctrl rrgctrl">'
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
        '<div class="ctrlrow">'
        '<span class="ctrllbl">回放範圍</span>'
        f'<div class="seg" role="group" aria-label="切換回放範圍" id="rangeSeg">{range_btns}</div>'
        '</div>'
        '<div class="ctrlrow">'
        '<span class="ctrllbl">尾巴長度</span>'
        '<input type="range" id="tailSlider" min="0" max="20" value="8" class="tailslider">'
        '<span id="tailVal" class="tailval">8 週</span>'
        '</div>'
        '<div class="ctrlrow">'
        '<button id="playBtn" class="playbtn">▶ 播放資金移動軌跡</button>'
        '<span id="playHint" class="playhint"></span>'
        '</div>'
        '</div>'
        '<div class="rrgwrap"><div class="rrgbox"><canvas id="rrgChart"></canvas>'
        '<div class="rrgframe" id="rrgFrameLabel"></div></div>'
        '<div class="rrgrank" id="rrgRank"></div></div>'
        '<p class="disc">RRG 是產業/籃子層級的相對強弱統計工具，不是個股買賣訊號，'
        '不構成投資建議。台股籃子由少數大型股等權聚合，會被成分股個別異動放大，'
        '僅供研究參考，正式決策前請自行查核。</p></div>'
    )

    script_html = _rrg_script(payload)
    return head_html + hdr + note_html + ctrl_html + script_html + "</body></html>"


def _axis_bounds(payload, pad=2.0):
    """算兩軸要固定在哪個範圍：掃過 payload 裡全部 ratio/momentum（含所有市場/基準/
    週期/歷史幀），取最極端值再加緩衝。不是憑感覺挑一個數字——不同天重跑資料範圍
    可能略有出入，讓它跟著實際資料算，比寫死一個猜的範圍可靠。"""
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
    lo, hi = min(vals), max(vals)
    # 兩軸用同一個範圍（不要 x/y 各自的範圍不同，那樣象限對角線就不是45度，視覺會扭曲）
    span = max(hi - lo, 1.0)
    center = (hi + lo) / 2
    half = span / 2 + pad
    return round(center - half, 1), round(center + half, 1)


def _rrg_script(payload):
    import json as _json
    lines = []
    lines.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>')
    lines.append("<script>")
    lines.append("window.RRG_DATA = " + _json.dumps(payload, ensure_ascii=False) + ";")
    lines.append("var rrgChart = null, curM = 'us', curP = '20', curBench = 'index', curRange = '3m', tailWeeks = 8;")
    lines.append("var QCOLOR = " + _json.dumps(QUADRANT_COLOR, ensure_ascii=False) + ";")
    lines.append("var QLABEL = " + _json.dumps(QUADRANT_LABEL, ensure_ascii=False) + ";")
    lines.append("var RANGE_WEEKS = " + _json.dumps(dict((k, w) for k, _, w in RANGE_WEEKS)) + ";")
    _axis_lo, _axis_hi = _axis_bounds(payload)
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
      ctx.fillStyle = 'rgba(37,230,255,.05)'; ctx.fillRect(area.left, area.top, midX-area.left, midY-area.top);
      ctx.fillStyle = 'rgba(255,82,119,.06)'; ctx.fillRect(midX, area.top, area.right-midX, midY-area.top);
      ctx.fillStyle = 'rgba(143,176,214,.05)'; ctx.fillRect(area.left, midY, midX-area.left, area.bottom-midY);
      ctx.fillStyle = 'rgba(255,176,32,.06)'; ctx.fillRect(midX, midY, area.right-midX, area.bottom-midY);
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

var playTimer = null, playIdx = 0;
var SUBSTEPS = 12;     // 兩個真實週資料點之間補幾格——數字越大動畫越滑順但播放總長越久
var TICK_MS = 35;      // 每格間隔

function rrgGet(kind) {
  // kind: 'bubble'(現在座標) | 'trail'（保留給舊資料相容） | 'frames'（動畫用逐週快照）
  var key = (kind === 'bubble') ? curM : (kind + '_' + curM);
  var byBench = window.RRG_DATA[key] || {};
  var byPeriod = byBench[curBench] || {};
  return byPeriod[curP] || [];
}

function stopPlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  document.getElementById('playBtn').classList.remove('playing');
  document.getElementById('playBtn').textContent = '▶ 播放資金移動軌跡';
  document.getElementById('rrgFrameLabel').style.display = 'none';
}

// 每個真實週之間線性補 SUBSTEPS 個中間點（ratio/momentum/radius 都補），
// 原本一週一格會跳得很生硬看不出方向；帶著補間點快速播放，肉眼看起來就是連續移動。
// 這只是視覺補間，不是真的推算出中間某天的數值——兩個端點才是真實資料。
// startOffset：這批 frames 在「完整歷史 frames」裡的起始位置，用來對回尾巴軌跡
// （回放範圍可能只挑最近幾週，但尾巴軌跡要能往更早之前接，兩者是分開的概念）。
function _buildPlaySequence(frames, startOffset) {
  var seq = [];
  for (var i = 0; i < frames.length - 1; i++) {
    var a = frames[i].points, b = frames[i + 1].points;
    for (var s = 0; s < SUBSTEPS; s++) {
      var t = s / SUBSTEPS;
      var pts = a.map(function(pa, idx) {
        var pb = b[idx] || pa;
        return {
          key: pa.key, name: pa.name,
          ratio: pa.ratio + (pb.ratio - pa.ratio) * t,
          momentum: pa.momentum + (pb.momentum - pa.momentum) * t,
          radius: (pa.radius || 10) + ((pb.radius || 10) - (pa.radius || 10)) * t,
          quadrant: t < 0.5 ? pa.quadrant : pb.quadrant,
        };
      });
      seq.push({points: pts, label: frames[i].date + ' → ' + frames[i + 1].date,
                isReal: s === 0, realIdx: startOffset + i});
    }
  }
  var last = frames[frames.length - 1];
  seq.push({points: last.points, label: last.date, isReal: true, realIdx: startOffset + frames.length - 1});
  return seq;
}

// 從完整歷史 frames 中，取 uptoIdx（含）往前數 weeks 週的每個籃子座標，接成軌跡線。
// weeks<=0 時不畫尾巴。這是用戶要求加的功能：原本補間動畫只有會動的泡泡、
// 沒有留下走過的路徑，看久了還是看不出「這一路怎麼走過來的」。
// 8 色分類色盤——原本泡泡顏色只有 4 種象限色，同象限裡好幾個產業長得一模一樣、
// 只能靠標籤字認。改成每個籃子固定一個分類色（顏色數 > 籃子數時循環使用，
// 8 色對 11~17 個籃子一定會重複，但比 4 色可辨識度高很多，配合標籤字已經夠用）；
// 象限資訊改用泡泡邊框色表達，不丟掉這個訊號、只是換位置放。
var CAT_PALETTE = ['#ff5277','#25e6ff','#ffb020','#9b7bff','#4ade80','#facc15','#f472b6','#60a5fa'];
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

// 殘影效果：原本只有一條細線當軌跡，用戶反饋不明顯。改成「越舊越淡、越舊越小」
// 的殘影泡泡疊在細線上——跟真實殘影/彗星尾巴的視覺邏輯一樣，比一條線好辨認方向與新舊。
function buildTrailDs(fullFrames, uptoIdx, weeks) {
  if (weeks <= 0 || uptoIdx < 1) return [];
  var start = Math.max(0, uptoIdx - weeks + 1);
  var slice = fullFrames.slice(start, uptoIdx + 1);
  if (slice.length < 2) return [];
  var byKey = {};
  slice.forEach(function(f) {
    f.points.forEach(function(p) {
      (byKey[p.key] = byKey[p.key] || []).push(p);
    });
  });
  var lineDs = [], ghostData = [], ghostColors = [];
  Object.keys(byKey).forEach(function(k) {
    var pts = byKey[k];
    if (pts.length < 2) return;
    var col = keyColor(k);
    var hist = pts.slice(0, -1);   // 排除最後一個——那是現在的位置，主泡泡已經畫了，不用重疊一個殘影在上面
    hist.forEach(function(p, i) {
      var t = (i + 1) / hist.length;         // 0(最舊)→1(最接近現在)
      ghostData.push({x: p.ratio, y: p.momentum, r: Math.max(3, (p.radius || 10) * (0.35 + 0.4 * t))});
      ghostColors.push(_hexAlpha(col, 0.05 + t * 0.32));   // 越舊越透明
    });
    lineDs.push({type: 'line', data: pts.map(function(p){return {x: p.ratio, y: p.momentum};}),
                 borderColor: _hexAlpha(col, 0.22), borderWidth: 1, pointRadius: 0,
                 showLine: true, fill: false, order: 3});
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
    // 填色＝產業分類色（8色循環）、邊框＝象限色——原本兩者疊在一起用同一種色
    // （象限色當填色），同象限的產業全部撞色。拆開後兩個訊號都留著。
    backgroundColor: pts.map(function(p) { return _hexAlpha(keyColor(p.key), 0.85); }),
    borderColor: pts.map(function(p) { return QCOLOR[p.quadrant] || '#8fb0d6'; }),
    borderWidth: 2, order: 10   // order 要比殘影(3/4)高，確保主泡泡永遠畫在殘影上面
  };
  if (!rrgChart) {
    rrgChart = new Chart(document.getElementById('rrgChart'), {
      type: 'bubble',
      data: {datasets: [bubbleDs].concat(trailDs || [])},
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
          legend: {display: false},
          tooltip: {callbacks: {label: function(ctx) {
            var p = window._rrgCurPts && window._rrgCurPts[ctx.dataIndex];
            return p ? (p.name + '：RS-Ratio ' + p.ratio.toFixed(1) +
              '／RS-Momentum ' + p.momentum.toFixed(1) + '（' + QLABEL[p.quadrant] + '）') : '';
          }}}
        },
        scales: {
          // 固定死 min/max：原本 Chart.js 每次 update 都照當下資料自動縮放，
          // 切市場/基準/週期或播放動畫時整張圖的座標尺度會跟著跳動，
          // 泡泡明明沒怎麼動、畫面卻感覺在亂飄。實測全部資料落在95.8~104.9，
          // 固定 AXIS_MIN~AXIS_MAX（留一點緩衝）之後，唯一會動的只有泡泡本身。
          x: {min: AXIS_MIN, max: AXIS_MAX, title: {display:true, text:'RS-Ratio 相對強弱', color:'#8fb0d6'}, ticks:{color:'#5f80a6'}, grid:{color:'#16223A'}},
          y: {min: AXIS_MIN, max: AXIS_MAX, title: {display:true, text:'RS-Momentum 強弱變化率', color:'#8fb0d6'}, ticks:{color:'#5f80a6'}, grid:{color:'#16223A'}}
        }
      },
      plugins: [quadrantBgPlugin(), bubbleLabelPlugin()]
    });
  } else {
    // 更新既有 chart 的資料集，不整個銷毀重建——搭配補間點快速更新，肉眼看起來平滑移動。
    rrgChart.data.datasets = [bubbleDs].concat(trailDs || []);
    rrgChart.update('none');   // 'none' 關掉 Chart.js 自己的動畫，避免跟我們手動補間互相打架、變卡頓
  }
  window._rrgCurPts = pts;
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
  var trailDs = buildTrailDs(fullFrames, fullFrames.length - 1, tailWeeks);

  if (rrgChart) { rrgChart.destroy(); rrgChart = null; }   // 換市場/基準/週期要強制重建一次（軸範圍等設定要重來）
  updateChartPoints(pts, trailDs);
  document.getElementById('rrgFrameLabel').style.display = 'none';

  var rank = pts.slice().sort(function(a,b){ return (b.ratio+b.momentum)-(a.ratio+a.momentum); });
  document.getElementById('rrgRank').innerHTML = rank.map(function(p) {
    return '<div class="rrgrow"><span class="dot" style="background:'+(QCOLOR[p.quadrant]||'#8fb0d6')+'"></span>'+
      '<span class="nm">'+p.name+'</span>'+
      '<span class="qv">'+QLABEL[p.quadrant]+'</span>'+
      '<span class="num">'+p.ratio.toFixed(1)+' / '+p.momentum.toFixed(1)+'</span></div>';
  }).join('') || '<div class="rrgrow">（本次無資料）</div>';

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

document.getElementById('playBtn').addEventListener('click', function() {
  if (playTimer) { stopPlay(); return; }
  var fullFrames = rrgGet('frames');
  if (fullFrames.length < 2) return;
  var rangeW = RANGE_WEEKS[curRange] || fullFrames.length;
  var startOffset = Math.max(0, fullFrames.length - rangeW);
  var playFrames = fullFrames.slice(startOffset);
  if (playFrames.length < 2) return;
  var seq = _buildPlaySequence(playFrames, startOffset);
  playIdx = 0;
  document.getElementById('playBtn').classList.add('playing');
  document.getElementById('playBtn').textContent = '⏸ 播放中…';
  var lbl = document.getElementById('rrgFrameLabel');
  lbl.style.display = 'block';
  playTimer = setInterval(function() {
    var f = seq[playIdx];
    // 軌跡尾巴只在真實週的那一格重算（不必每個補間格都重算，太頻繁沒意義又耗效能），
    // 補間格之間沿用同一份尾巴，肉眼看不出差異。
    var trailDs = f.isReal ? buildTrailDs(fullFrames, f.realIdx, tailWeeks) : window._rrgLastTrail || [];
    window._rrgLastTrail = trailDs;
    updateChartPoints(f.points, trailDs);
    lbl.textContent = f.label;
    playIdx++;
    if (playIdx >= seq.length) { stopPlay(); draw(); }
  }, TICK_MS);
});

document.getElementById('mktSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#mktSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curM = b.dataset.m; draw();
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
draw();
</script>""")
    return "\n".join(lines)


CSS_EXTRA = """
.rrgwrap{display:grid;grid-template-columns:1.6fr 1fr;gap:14px;margin-top:12px}
.rrgbox{height:520px;background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:10px;position:relative}
.rrgrank{background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:10px;
 max-height:520px;overflow-y:auto}
.rrgrow{display:flex;align-items:center;gap:8px;padding:7px 4px;border-bottom:1px solid #131c30;font-size:12.5px}
.rrgrow .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.rrgrow .nm{flex:1;color:#cfe6ff}
.rrgrow .qv{color:#8fb0d6;font-size:11px;width:36px;text-align:center}
.rrgrow .num{color:#5f80a6;font-variant-numeric:tabular-nums;width:90px;text-align:right}
.playbtn{background:#132038;border:1px solid #2a3550;color:#25e6ff;
 font-size:12.5px;font-weight:600;padding:8px 14px;border-radius:8px;cursor:pointer;font-family:inherit}
.playbtn:hover{border-color:#25e6ff}
.playbtn:disabled{color:#5f80a6;border-color:#16223A;cursor:not-allowed}
.playbtn.playing{color:#ffb020;border-color:#ffb020}
.playhint{font-size:11px;color:#5f80a6;align-self:center}
.rrgframe{position:absolute;top:14px;right:20px;font-size:12px;color:#8fb0d6;
 background:#0a122299;padding:3px 10px;border-radius:6px;pointer-events:none}
.rrgctrl{position:static;display:flex;flex-direction:column;gap:9px;padding:12px 14px;
 background:#0a1222;border:1px solid #16223A;border-radius:12px;margin-bottom:14px}
.ctrlrow{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.ctrllbl{font-size:11.5px;color:#5f80a6;min-width:112px;flex-shrink:0}
.segwide button{line-height:1.35;padding:6px 14px}
.pnote{font-size:9.5px;color:#5f80a6;font-weight:400}
.seg button[aria-pressed=true] .pnote{color:#cfe6ff}
.tailslider{flex:1;max-width:220px;accent-color:#25e6ff}
.tailval{font-size:12px;color:#25e6ff;font-variant-numeric:tabular-nums;min-width:40px}
@media (max-width:820px){.rrgwrap{grid-template-columns:1fr}.rrgbox{height:400px}
 .ctrllbl{min-width:100%}}
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/rotation.html")
    args = ap.parse_args()

    print("抓美股 SPDR 11 大類股歷史價格（兩種基準共用同一批，只抓一次）…")
    us_baskets, us_index_bench = _fetch_baskets("us")
    print("抓台股產業籃子（需逐檔抓歷史價，較慢；兩種基準共用同一批，只抓一次）…")
    tw_baskets, tw_index_bench = _fetch_baskets("tw")

    hist = load_history()
    date_str = time.strftime("%Y-%m-%d")
    snaps = {"us": {}, "tw": {}}
    for m, baskets, index_bench in (("us", us_baskets, us_index_bench), ("tw", tw_baskets, tw_index_bench)):
        for bench in ("index", "equal"):
            snap, backfill = compute_snapshot(baskets, index_bench, benchmark=bench, backfill_weeks=BACKFILL_WEEKS)
            print(f"  {m}/{bench}: {len(snap)} 個籃子算出結果，回填 {len(backfill)} 週歷史")
            snaps[m][bench] = snap
            # 先疊回填的歷史（由舊到新），再疊「現在」這一筆——append_history 依日期去重，
            # 重跑也不會累積出重複的同一天。
            for d, s in backfill:
                hist = append_history(hist, m, bench, s, d)
            hist = append_history(hist, m, bench, snap, date_str)
    save_history(hist)

    html = render_html(snaps, hist)
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


