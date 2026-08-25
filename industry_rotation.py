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
HIST_KEEP_WEEKS = 26          # 軌跡尾巴最多留半年份，太長圖會糊成一團

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


BACKFILL_WEEKS = 26   # 動畫回填幾週歷史。3年資料本來就抓了，回填不用多打任何API

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


def build_market_snapshot(market, backfill_weeks=0):
    """market: "us" 或 "tw"。回 (current, history_rows)：
      current       = {sector_key: {"name":.., "periods": {...}, "size": 資金規模}}（現在這一刻）
      history_rows  = [(date_str, snapshot_dict), ...] 由舊到新，backfill_weeks>0 時才有內容

    2026-08-25 補回填：本來就已經抓 3 年歷史價格來算「現在」這個點，
    同一批資料回頭算過去每週的座標幾乎不用額外成本（沒有新的 API 呼叫，
    純粹是在已經抓好的 pandas Series 上多取幾個歷史時間點）。
    不用像原本設計那樣「每週排程跑一次才多一幀動畫」，第一次跑就有完整歷史可以播放。

    ⚠️ 已知簡化：回填的歷史快照，「資金規模」(size) 用的是**現在**的 AUM/市值，
    不是那個歷史時間點當時的規模（我們沒有歷史 AUM/市值資料）。RS-Ratio/Momentum
    本身是用當時真實價格算的，只有泡泡大小這個視覺參考值是用現在的規模回貼過去，
    可接受的簡化（規模不會一週內劇烈變化，且這只影響泡泡大小不影響位置判斷）。
    """
    if market == "us":
        bench_h = yf.Ticker(US_BENCHMARK).history(period="3y")
        if bench_h.empty:
            print("  [industry_rotation] 美股基準抓取失敗，跳過整個美股快照")
            return {}, []
        bench = bench_h["Close"]
        out, hist_by_date = {}, {}
        for tk, name in SPDR_SECTORS.items():
            h = yf.Ticker(tk).history(period="3y")
            if h.empty:
                print(f"  [industry_rotation] {tk} 抓取失敗，跳過")
                continue
            rm = rs_ratio_momentum(h["Close"], bench)
            if rm is None:
                continue
            idx = rm[PERIODS[0]]["ratio"].index
            cur = _periods_at(rm, idx[-1])
            if not cur:
                continue
            aum = _spdr_aum(tk)
            out[tk] = {"name": name, "periods": cur, "size": aum or 0.0}
            if backfill_weeks:
                for ts, date_str in _backfill_points(idx, backfill_weeks):
                    p = _periods_at(rm, ts)
                    if p:
                        hist_by_date.setdefault(date_str, {})[tk] = {"name": name, "periods": p, "size": aum or 0.0}
        rows = [(d, hist_by_date[d]) for d in sorted(hist_by_date)]
        return out, rows

    if market == "tw":
        bench_h = yf.Ticker(TW_BENCHMARK).history(period="3y")
        if bench_h.empty:
            print("  [industry_rotation] 台股基準抓取失敗，跳過整個台股快照")
            return {}, []
        bench = bench_h["Close"]
        members = _tw_sector_members()
        out, hist_by_date = {}, {}
        for sector, (tks, total_cap) in members.items():
            closes = []
            for tk in tks:
                h = yf.Ticker(tk).history(period="3y")
                if h.empty:
                    continue
                closes.append(h["Close"])
            basket = _basket_index(closes)
            if basket is None:
                print(f"  [industry_rotation] {sector} 成分股資料不足（<{TW_MIN_MEMBERS}檔），跳過")
                continue
            rm = rs_ratio_momentum(basket, bench)
            if rm is None:
                continue
            idx = rm[PERIODS[0]]["ratio"].index
            name = SECTOR_TW_LABEL.get(sector, sector)
            cur = _periods_at(rm, idx[-1])
            if not cur:
                continue
            out[sector] = {"name": name, "periods": cur, "size": total_cap}
            if backfill_weeks:
                for ts, date_str in _backfill_points(idx, backfill_weeks):
                    p = _periods_at(rm, ts)
                    if p:
                        hist_by_date.setdefault(date_str, {})[sector] = {"name": name, "periods": p, "size": total_cap}
        rows = [(d, hist_by_date[d]) for d in sorted(hist_by_date)]
        return out, rows

    raise ValueError(f"未知市場：{market}")


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

def load_history():
    if not os.path.exists(HIST_PATH):
        return {"us": [], "tw": []}
    try:
        with open(HIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"us": [], "tw": []}


def append_history(hist, market, snapshot, date_str):
    """把這次快照疊進歷史，並裁掉太舊的（軌跡尾巴不用留太長，留了也看不清）。"""
    hist.setdefault(market, [])
    # 同一天重跑會產生重複點——先移除同一天的舊紀錄再疊新的，不是每次都無限累加
    hist[market] = [row for row in hist[market] if row.get("date") != date_str]
    hist[market].append({"date": date_str, "snapshot": snapshot})
    hist[market].sort(key=lambda r: r["date"])
    if len(hist[market]) > HIST_KEEP_WEEKS:
        hist[market] = hist[market][-HIST_KEEP_WEEKS:]
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


def _trail_data(hist_rows, market_key, period, max_points=8):
    """某一籃子過去幾週的座標序列，給軌跡尾巴用。歷史累積不足時就是短尾巴或沒有，
    不是 bug——這功能本來就要跑幾週才有東西可畫。"""
    out = []
    for row in hist_rows[-max_points:]:
        d = row.get("snapshot", {}).get(market_key)
        if not d:
            continue
        p = d.get("periods", {}).get(str(period)) or d.get("periods", {}).get(period)
        if p:
            out.append({"date": row["date"], "ratio": p["ratio"], "momentum": p["momentum"]})
    return out


def _frames_data(hist_rows, snapshot, period, radius_fn, max_frames=26):
    """「圈圈會跑」動畫用：把歷史快照依日期切成一格一格的畫面，
    每格是「當天所有籃子的座標」，不是單一籃子的軌跡（那是 _trail_data 的事）。
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


def render_html(snap_us, snap_tw, hist):
    import json as _json
    from board_theme import BASE_CSS, header, NAV, esc

    # 資金大小→泡泡半徑：用「這個市場所有已知規模（含歷史）」一起算 lo/hi，
    # 動畫播放時泡泡大小才不會因為每幀重新正規化而忽大忽小亂跳。
    def _all_sizes(market, snapshot):
        sizes = [d.get("size", 0.0) for d in snapshot.values()]
        for row in hist.get(market, []):
            sizes += [b.get("size", 0.0) for b in row.get("snapshot", {}).values()]
        return sizes

    us_radius = _size_scale(_all_sizes("us", snap_us))
    tw_radius = _size_scale(_all_sizes("tw", snap_tw))

    payload = {
        "us": {str(n): _bubble_data(snap_us, n, us_radius) for n in PERIODS},
        "tw": {str(n): _bubble_data(snap_tw, n, tw_radius) for n in PERIODS},
        "trail_us": {str(n): {k: _trail_data(hist.get("us", []), k, n) for k in snap_us} for n in PERIODS},
        "trail_tw": {str(n): {k: _trail_data(hist.get("tw", []), k, n) for k in snap_tw} for n in PERIODS},
        "frames_us": {str(n): _frames_data(hist.get("us", []), snap_us, n, us_radius) for n in PERIODS},
        "frames_tw": {str(n): _frames_data(hist.get("tw", []), snap_tw, n, tw_radius) for n in PERIODS},
    }
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
        f'<button data-p="{n}" aria-pressed="{"true" if n == 20 else "false"}">{n}日</button>'
        for n in PERIODS)

    head_html = ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 '<meta name="robots" content="noindex"><title>產業輪動雷達</title>'
                 '<style>' + BASE_CSS + CSS_EXTRA + '</style></head><body><div class="wrap">')
    hdr = header("rotation", "產業輪動雷達",
                 f"RRG（Relative Rotation Graph）· 美股11大類股(SPDR ETF) + 台股{len(snap_tw)}個TradingView產業籃子"
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
        '回填歷史的泡泡大小是用現在的資金規模回貼過去，位置(RS-Ratio/Momentum)則是當時的真實值。</span>'
        '</div>'
    )
    ctrl_html = (
        '<div class="ctrl">'
        '<div class="seg" role="group" aria-label="切換市場" id="mktSeg">'
        '<button data-m="us" aria-pressed="true">美股</button>'
        '<button data-m="tw" aria-pressed="false">台股</button></div>'
        f'<div class="seg" role="group" aria-label="切換週期" id="perSeg">{period_btns}</div>'
        '<button id="playBtn" class="playbtn">▶ 播放資金移動軌跡</button>'
        '<span id="playHint" class="playhint"></span>'
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


def _rrg_script(payload):
    import json as _json
    lines = []
    lines.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>')
    lines.append("<script>")
    lines.append("window.RRG_DATA = " + _json.dumps(payload, ensure_ascii=False) + ";")
    lines.append("var rrgChart = null, curM = 'us', curP = '20';")
    lines.append("var QCOLOR = " + _json.dumps(QUADRANT_COLOR, ensure_ascii=False) + ";")
    lines.append("var QLABEL = " + _json.dumps(QUADRANT_LABEL, ensure_ascii=False) + ";")
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

var playTimer = null, playIdx = 0;
var SUBSTEPS = 12;     // 兩個真實週資料點之間補幾格——數字越大動畫越滑順但播放總長越久
var TICK_MS = 35;      // 每格間隔；12補間×26週約等於 312 格 × 35ms ≈ 11 秒播完全程

function stopPlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  document.getElementById('playBtn').classList.remove('playing');
  document.getElementById('playBtn').textContent = '▶ 播放資金移動軌跡';
  document.getElementById('rrgFrameLabel').style.display = 'none';
}

// 每個真實週之間線性補 SUBSTEPS 個中間點（ratio/momentum/radius 都補），
// 原本一週一格會跳得很生硬看不出方向；帶著補間點快速播放，肉眼看起來就是連續移動。
// 這只是視覺補間，不是真的推算出中間某天的數值——兩個端點才是真實資料。
function _buildPlaySequence(frames) {
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
                isReal: s === 0, realDate: frames[i].date});
    }
  }
  var last = frames[frames.length - 1];
  seq.push({points: last.points, label: last.date, isReal: true, realDate: last.date});
  return seq;
}

function updateChartPoints(pts, trailDs) {
  var bubbleDs = {
    label: '位置',
    data: pts.map(function(p) { return {x: p.ratio, y: p.momentum, r: p.radius || 10}; }),
    backgroundColor: pts.map(function(p) { return (QCOLOR[p.quadrant] || '#8fb0d6') + 'cc'; }),
    borderColor: '#0a1222', borderWidth: 1.5
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
          x: {title: {display:true, text:'RS-Ratio 相對強弱', color:'#8fb0d6'}, ticks:{color:'#5f80a6'}, grid:{color:'#16223A'}},
          y: {title: {display:true, text:'RS-Momentum 強弱變化率', color:'#8fb0d6'}, ticks:{color:'#5f80a6'}, grid:{color:'#16223A'}}
        }
      },
      plugins: [quadrantBgPlugin()]
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
  var pts = (window.RRG_DATA[curM] || {})[curP] || [];
  var trailKey = 'trail_' + curM;
  var trails = (window.RRG_DATA[trailKey] || {})[curP] || {};
  var trailDs = Object.keys(trails).map(function(k) {
    var seq = trails[k];
    if (!seq || seq.length < 2) return null;
    var cur = pts.find(function(p){ return p.key === k; });
    var line = seq.map(function(s) { return {x: s.ratio, y: s.momentum}; });
    if (cur) line.push({x: cur.ratio, y: cur.momentum});
    return {
      type: 'line', data: line,
      borderColor: 'rgba(139,160,200,.35)', borderWidth: 1.2, pointRadius: 1.5,
      pointBackgroundColor: 'rgba(139,160,200,.5)', showLine: true, fill: false, order: 5
    };
  }).filter(Boolean);

  if (rrgChart) { rrgChart.destroy(); rrgChart = null; }   // 換市場/週期時強制重建一次（軸範圍等設定要重來）
  updateChartPoints(pts, trailDs);
  document.getElementById('rrgFrameLabel').style.display = 'none';

  var rank = pts.slice().sort(function(a,b){ return (b.ratio+b.momentum)-(a.ratio+a.momentum); });
  document.getElementById('rrgRank').innerHTML = rank.map(function(p) {
    return '<div class="rrgrow"><span class="dot" style="background:'+(QCOLOR[p.quadrant]||'#8fb0d6')+'"></span>'+
      '<span class="nm">'+p.name+'</span>'+
      '<span class="qv">'+QLABEL[p.quadrant]+'</span>'+
      '<span class="num">'+p.ratio.toFixed(1)+' / '+p.momentum.toFixed(1)+'</span></div>';
  }).join('') || '<div class="rrgrow">（本次無資料）</div>';

  var frames = ((window.RRG_DATA['frames_' + curM] || {})[curP]) || [];
  var btn = document.getElementById('playBtn');
  var hint = document.getElementById('playHint');
  if (frames.length < 2) {
    btn.disabled = true;
    hint.textContent = '（資料還在累積，需要至少2週歷史才能播放）';
  } else {
    btn.disabled = false;
    hint.textContent = '（共 ' + frames.length + ' 週，補間播放較滑順）';
  }
}

document.getElementById('playBtn').addEventListener('click', function() {
  if (playTimer) { stopPlay(); return; }
  var frames = ((window.RRG_DATA['frames_' + curM] || {})[curP]) || [];
  if (frames.length < 2) return;
  var seq = _buildPlaySequence(frames);
  playIdx = 0;
  document.getElementById('playBtn').classList.add('playing');
  document.getElementById('playBtn').textContent = '⏸ 播放中…';
  var lbl = document.getElementById('rrgFrameLabel');
  lbl.style.display = 'block';
  playTimer = setInterval(function() {
    var f = seq[playIdx];
    updateChartPoints(f.points, []);
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
document.getElementById('perSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#perSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curP = b.dataset.p; draw();
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
.playbtn{margin-left:10px;background:#132038;border:1px solid #2a3550;color:#25e6ff;
 font-size:12.5px;font-weight:600;padding:8px 14px;border-radius:8px;cursor:pointer;font-family:inherit;
 vertical-align:middle}
.playbtn:hover{border-color:#25e6ff}
.playbtn:disabled{color:#5f80a6;border-color:#16223A;cursor:not-allowed}
.playbtn.playing{color:#ffb020;border-color:#ffb020}
.playhint{font-size:11px;color:#5f80a6;margin-left:8px;align-self:center}
.rrgframe{position:absolute;top:14px;right:20px;font-size:12px;color:#8fb0d6;
 background:#0a122299;padding:3px 10px;border-radius:6px;pointer-events:none}
@media (max-width:820px){.rrgwrap{grid-template-columns:1fr}.rrgbox{height:400px}.ctrl{flex-wrap:wrap}.playbtn{margin-left:0}}
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/rotation.html")
    args = ap.parse_args()

    print("算美股 SPDR 11 大類股（含回填近", BACKFILL_WEEKS, "週歷史）…")
    snap_us, backfill_us = build_market_snapshot("us", backfill_weeks=BACKFILL_WEEKS)
    print(f"  {len(snap_us)}/11 檔算出結果，回填 {len(backfill_us)} 週歷史")
    print("算台股產業籃子（需逐檔抓歷史價，較慢）…")
    snap_tw, backfill_tw = build_market_snapshot("tw", backfill_weeks=BACKFILL_WEEKS)
    print(f"  {len(snap_tw)} 個籃子算出結果，回填 {len(backfill_tw)} 週歷史")

    hist = load_history()
    date_str = time.strftime("%Y-%m-%d")
    # 先疊回填的歷史（由舊到新），再疊「現在」這一筆——append_history 依日期去重，
    # 重跑也不會累積出重複的同一天。
    for d, snap in backfill_us:
        hist = append_history(hist, "us", snap, d)
    for d, snap in backfill_tw:
        hist = append_history(hist, "tw", snap, d)
    hist = append_history(hist, "us", snap_us, date_str)
    hist = append_history(hist, "tw", snap_tw, date_str)
    save_history(hist)

    html = render_html(snap_us, snap_tw, hist)
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


