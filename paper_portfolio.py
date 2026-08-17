"""策略賽馬：產業鏈 vs 巴菲特，真實買股模擬（股數×價格），每週調倉、每日記市值。

2 主倉各投 $10,000 美金：
  ① 產業鏈全：7 鏈守備清單全買，等權重
  ② 巴菲特價值：現價≤俗價折價最大前 30，等權重
另含 7 鏈明細倉（各 $10,000）。

真實模擬：起始把 $10,000 等分買進（可買零股），記下每股「股數/進場價」。
台股價格用即時匯率換成美金 → 全部用美金加總。每日更新現價算市值與損益。

調倉頻率：
  · 產業鏈全 / 巴菲特價值 / 7 鏈明細 → 每週日隨守備清單重篩調倉
  · 產業鏈+趨勢 → 每日追 SuperTrend，綠燈名單一有變就換股（翻燈才動，不天天重配）

  · 三指標合流 → 每日檢查SuperTrend+RS30日+EXCEED CHARGE噴出，事件觸發才動（見下方CHAIN_COMBO）

用法:python paper_portfolio.py [init|rebalance|rebalance-trend|rebalance-combo|nav]
"""
import sys
import json
import os
from datetime import datetime
import yfinance as yf

import board_html_legacy as _L
from technical_indicators import squeeze_momentum, mansfield_rs_series, _benchmark

STORE = "portfolios.json"
SCREEN = "screen_result.json"
BUFFETT = "buffett_watch.json"
BASE = 10000.0
BUFFETT_NAME = "巴菲特價值"
CHAIN_ALL = "產業鏈全"          # 七鏈完整守備清單聯集（2026-07-28 由「精選前2」改回全買）
CHAIN_TREND = "產業鏈+趨勢"
BUFFETT_TOPN = 30
TOP_PER_CHAIN = 2              # （保留供他用；產業鏈倉已改用完整守備清單，不再取前 N）
# ── 趨勢倉：改用「週線」SuperTrend（2026-07-28 依回測改）─────────────────
# 公式與參數(ATR10×3)完全不變，只把判斷 K 棒由日改週。實證依據：
#  · 訊號診斷：日線 32 次賣出有 24 次(75%)賣完股價續漲(+8.2%/10日)，買進訊號則正常
#  · 同池同期：日線 65 次訊號 vs 週線 10 次，多出來的全是雜訊
#  · 2026 YTD 回測：週線 +71.1%/回撤-16.1%/換股8次 vs 日線 +17.9%/-28.9%/47次
#  · 5.5 年 QQQ：週線 +73.5%(9次) ≈ 日線 +70.8%(44次)，報酬相當但交易只要 1/5
TREND_WEEKLY = True            # True=週線判斷（False 可切回日線做對照）
TREND_CONFIRM_DAYS = 1         # 週線本身已濾掉日內雜訊，確認天數降回 1（避免雙重延遲）
TREND_MIN_SLOTS    = 8         # 最少切成 N 份；綠燈不足時剩餘留現金（避免集中在 3-4 檔）
# ── Bitcoin→AI 機房限重（2026-07-28）─────────────────────────────────
# 5.5 年回測最大回撤 -94%（2022 年 -87.7%，接近歸零）。這是風險管理事實，
# 不是回測過擬合：等權重讓它一檔就能砸掉整個精選倉。
BTC_CHAIN = "Bitcoin→AI 機房"
BTC_MAX_WEIGHT = 0.10          # 該鏈標的在跨鏈主倉的合計權重上限
# ── 三指標合流倉（2026-08-11 新設，實驗性）───────────────────────────
# 假說：純日線SuperTrend翻燈雜訊多（見上方TREND_WEEKLY註解，75%賣訊是錯的），
# 用RS(30日)+EXCEED CHARGE擠壓噴出當「降噪濾網」是否能改善。
# backtest_combined_signal.py 6個月回測：合流篩選把賣錯率從57%降到38%，
# 方向正確但樣本(10筆)不足以下定論——這個倉就是拿真金白銀(模擬)去累積更長樣本。
# 買：SuperTrend翻多 + RS30日>0 + 擠壓剛噴出(前一根還在擠壓、這一根釋放)
# 賣（2026-08-11改為不對稱兩階段，用戶依自己回測結果指示的「最優進出法」）：
#   ① SuperTrend單獨翻空 → 賣一半（不用等RS/squeeze同時翻）
#   ② RS(60日)線跌破自己的60日均線（rs_60由正轉負）→ 剩餘部位全出
# 詳見 backtest_position_sim.py（完整倉位模擬回測，跟backtest_combined_signal.py
# 的「訊號後N日報酬統計」是互補的兩支，不是同一套評測方法）
CHAIN_COMBO = "三指標合流"
MAIN = [CHAIN_ALL, CHAIN_TREND, BUFFETT_NAME, CHAIN_COMBO]
FX_FALLBACK = 32.0              # USD/TWD 備援匯率


def tw_yf(code):
    return f"{code}.TW" if str(code).isdigit() else str(code)


def is_tw(tk):
    return tk.endswith(".TW")


def get_fx():
    """USD/TWD（1 美元 = X 台幣），抓不到用備援。"""
    try:
        d = yf.download("TWD=X", period="5d", progress=False, threads=False)
        v = float(d["Close"].dropna().iloc[-1])
        return v if 25 < v < 40 else FX_FALLBACK
    except Exception:
        return FX_FALLBACK


def to_usd(tk, native, fx):
    """台股價(台幣)→美金；美股原樣。"""
    if native is None:
        return None
    return native / fx if is_tw(tk) else native


# 賽馬排除鏈：比賽中途不換賽制。玻璃基板（2026-08-05 新增第 8 鏈）是題材驗證期
# 觀察鏈，只上看板+深度報告，不進任何模擬倉。
# 關鍵金屬/原物料（2026-08-17 新增第 9 鏈）同理：賽馬 6/30 開跑，這時候才加入的鏈
# 會拿著全新的 $10,000 跟已經跑了 48 天的鏈比，數字沒有可比性 → 一併排除。
RACE_EXCLUDE = {"玻璃基板/TGV", "關鍵金屬/原物料"}


def chain_holdings():
    d = json.load(open(SCREEN, encoding="utf-8"))
    out = {}
    for chain in d.get("us", {}):
        if chain in RACE_EXCLUDE:
            continue
        us = [x["code"] for x in d["us"].get(chain, [])]
        tw = [tw_yf(x["code"]) for x in d["tw"].get(chain, [])]
        out[chain] = sorted(set(us + tw))
    return out


def chain_top_picks(n=TOP_PER_CHAIN):
    """每鏈取分數最高前 n（美+台合併按 score 排）。回 {chain: [yf_ticker,...]}。"""
    d = json.load(open(SCREEN, encoding="utf-8"))
    out = {}
    for chain in d.get("us", {}):
        if chain in RACE_EXCLUDE:
            continue
        items = [(x["code"], x.get("score", 0)) for x in d["us"].get(chain, [])]
        items += [(tw_yf(x["code"]), x.get("score", 0)) for x in d["tw"].get(chain, [])]
        items.sort(key=lambda z: -z[1])
        out[chain] = [c for c, _ in items[:n]]
    return out


def chain_select_union():
    """產業鏈全 = 七鏈「完整守備清單」聯集（2026-07-28 改回原設計）。
    原本取各鏈前 2（精選 11-13 檔），但 5.5 年回測顯示過度集中：
    精選倉 MDD -55.9%，比單一鏈（AI 伺服器 -39.4%、機器人 -36.0%）還差。
    改回全買後檔數約 50+，分散度回到七鏈原本的水準。"""
    return sorted({t for v in chain_holdings().values() for t in v})


def _supertrend_dir(highs, lows, closes, period=10, mult=3.0):
    """標準 SuperTrend（ATR/Wilder），回最新方向 1多/-1空；資料不足回 1。
    （複製自 board_html.supertrend，避免拉進 markdown/opencc 依賴。）"""
    n = len(closes)
    if n < period + 1 or not highs or not lows:
        return 1
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(n)]
    up = lo = None
    dr = 1
    for i in range(period - 1, n):
        if atr[i] is None:
            continue
        bu, bl = hl2[i] + mult * atr[i], hl2[i] - mult * atr[i]
        if up is None:
            up, lo = bu, bl
            dr = 1 if closes[i] >= hl2[i] else -1
        else:
            nu = bu if (bu < up or closes[i - 1] > up) else up
            nl = bl if (bl > lo or closes[i - 1] < lo) else lo
            if closes[i] > up:
                dr = 1
            elif closes[i] < lo:
                dr = -1
            up, lo = nu, nl
    return dr


def _to_weekly(df):
    """日 K → 週 K（週五收盤）。SuperTrend 公式與參數不變，只換 K 棒週期。"""
    return df.resample("W-FRI").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()


def _dir_of(df, weekly=True):
    """回單一標的最新 SuperTrend 方向（1 多 / -1 空）。weekly=True 用週線判斷。"""
    d = _to_weekly(df) if weekly else df
    if len(d) < 12:                     # 週線需要足夠棒數，不足時視為多頭（不過濾）
        return 1
    return _supertrend_dir(d["High"].tolist(), d["Low"].tolist(), d["Close"].tolist())


def trend_longs(tickers, weekly=None):
    """從候選裡只留 SuperTrend 多頭（綠燈）的；抓不到 OHLC 的保留（不過濾）。
    weekly=None 時採用 TREND_WEEKLY 設定（預設週線）。"""
    if not tickers:
        return []
    weekly = TREND_WEEKLY if weekly is None else weekly
    period = "1y" if weekly else "3mo"   # 週線需要更長歷史才有足夠 K 棒
    data = yf.download(sorted(tickers), period=period, progress=False,
                       threads=False, auto_adjust=True, group_by="ticker")
    longs = []
    for tk in tickers:
        try:
            df = data[tk].dropna()
            if _dir_of(df, weekly) == 1:
                longs.append(tk)
        except Exception:
            longs.append(tk)
    return sorted(longs)


def combo_signal_events(tickers, held_frac):
    """三指標合流：回 (buy_list, half_sell_list, full_exit_list)，只回「今天剛觸發」的事件。
    買：SuperTrend(日線)翻多 + RS(30日)>0 + EXCEED CHARGE擠壓剛噴出（未持有才算買訊）
    賣分兩階段（2026-08-11 用戶指示改為不對稱出場，其回測驗證為最優進出法）：
      ① ST單獨翻空 → 賣一半（不用等RS/squeeze同時翻，全倉時才觸發，已經賣過一半的不重複觸發）
      ② RS(60日)線跌破自己的60日均線（rs_60由正轉負）→ 剩餘部位全出，任何持倉比例都適用
    held_frac：{ticker: 0.5或1.0}，目前持倉比例（0或不在字典裡＝未持有）。
    詳見 CHAIN_COMBO 常數註解、backtest_position_sim.py（完整回測）。"""
    buy, half_sell, full_exit = [], [], []
    for tk in tickers:
        try:
            hist = yf.Ticker(tk).history(period="1y")
            if hist.empty or len(hist) < 210:
                continue
            highs, lows, closes = hist["High"].tolist(), hist["Low"].tolist(), hist["Close"].tolist()
            bench = yf.Ticker(_benchmark(tk)).history(period="1y")
            bench_closes = bench["Close"].tolist() if not bench.empty else []
        except Exception:
            continue
        if not bench_closes:
            continue
        st = _L.supertrend(highs, lows, closes)
        if not st:
            continue
        dr = st["dir"]
        i = len(closes) - 1
        if i < 1 or dr[i] is None or dr[i - 1] is None:
            continue
        frac = held_frac.get(tk, 0.0)
        flip_bull = dr[i] == 1 and dr[i - 1] == -1
        flip_bear = dr[i] == -1 and dr[i - 1] == 1

        # mansfield_rs_series 內部用 min(len(closes),len(bench_closes)) 右對齊，
        # 台美交易日曆天數常不同，陣列長度可能小於closes——只看「今天」故直接用[-1]/[-2]，
        # 不要用絕對索引i去查（那是backtest_position_sim.py踩過的IndexError同一個坑）。
        if frac == 0.0 and flip_bull:
            sq = squeeze_momentum(highs, lows, closes)
            rs_30 = mansfield_rs_series(closes, bench_closes, 30)
            if sq is not None and rs_30 is not None and len(rs_30) and rs_30[-1] is not None \
                    and not (rs_30[-1] != rs_30[-1]):
                fired = bool(sq["squeeze_on"][i - 1]) and not bool(sq["squeeze_on"][i])
                if fired and rs_30[-1] > 0:
                    buy.append(tk)
                    continue

        if frac == 1.0 and flip_bear:
            half_sell.append(tk)
            continue    # 這天已經觸發賣一半，RS60全出訊號留到之後某天再判斷，不同天疊加動作

        if frac > 0.0:
            rs_60 = mansfield_rs_series(closes, bench_closes, 60)
            if rs_60 is not None and len(rs_60) >= 2:
                a, b = rs_60[-2], rs_60[-1]
                if a is not None and b is not None and not (a != a) and not (b != b):
                    if a >= 0 and b < 0:
                        full_exit.append(tk)
    return sorted(buy), sorted(half_sell), sorted(full_exit)


def market_is_green(symbol="QQQ"):
    """大盤總開關：QQQ 週線 SuperTrend 是否為多頭。抓不到資料時回 True（不空手）。
    依據 5.5 年回測：2022 空頭 QQQ 買進持有 -32.6%，週線擇時僅 -11.7%。"""
    try:
        df = yf.download(symbol, period="2y", progress=False, threads=False,
                         auto_adjust=True)
        if isinstance(df.columns, __import__("pandas").MultiIndex):
            df.columns = df.columns.droplevel(1)
        return _dir_of(df.dropna(), weekly=True) == 1
    except Exception as e:
        print(f"[market_is_green] {symbol} 抓取失敗，視為綠燈：{e}")
        return True


def _hong_score(rank, roe, rr):
    """洪瑞泰品質分：龍頭 + 高ROE + 低盈再率（好生意=不用一直砸錢就會賺）。"""
    s = {1: 3, 2: 2, 3: 1}.get(rank, 0)        # 龍頭加權（產業龍頭優先）
    s += min(roe or 0, 0.6) * 3                  # ROE 越高越好
    if rr is not None:
        s += max(0, 0.80 - rr) * 4              # 盈再率越低越好（權重最高）
    return s


def buffett_top30(prices):
    """洪瑞泰選股：好公司（龍頭 + ROE≥15% + 盈再率<80% + 排照妖鏡）在便宜時買。
    現價 ≤ 俗價（EPS×12）才買，取品質分前 30。

    2026-08-17 修 bug：原本讀 d["fair"]（合理價）當第二層放寬條件，但洪瑞泰方法論
    只有俗價/貴價兩條線、沒有合理價，buffett_scan.py 早就改成輸出 cheap/expensive，
    這裡沒跟著改 → `if not (p and cheap and fair)` 因為 fair 永遠是 None 而把每一檔
    都跳過，巴菲特倉持股長期是 0（頁面顯示 0 檔、淨值凍結）。
    合理價那層放寬直接拿掉不補回來：俗價~貴價之間在這套方法裡是「觀望」不是「買進」，
    硬補會讓模擬倉買進方法論明講不該買的區間。目前買進區有 20+ 檔，不需要放寬。"""
    wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
    picks = []
    for tk, d in wl.items():
        p, cheap = prices.get(tk), d.get("cheap")
        roe, rr = d.get("roe") or 0, d.get("reinvest")
        if not (p and cheap):
            continue
        if d.get("trap_flags"):           # 照妖鏡：EPS估降/高負債 → 排除
            continue
        if roe < 0.15:                     # 洪瑞泰第一關：ROE ≥ 15%
            continue
        if rr is not None and rr >= 0.80:  # 第二關：盈再率 < 80%（吃資本的爛生意淘汰）
            continue
        if p <= cheap:                     # 第三關：現價 ≤ 俗價才進場
            picks.append((tk, _hong_score(d.get("rank"), roe, rr)))
    picks.sort(key=lambda x: -x[1])
    return sorted(tk for tk, _ in picks[:BUFFETT_TOPN])


def _batch(tickers):
    out = {}
    if not tickers:
        return out
    data = yf.download(tickers, period="5d", progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    for tk in tickers:
        try:
            out[tk] = float(data[tk]["Close"].dropna().iloc[-1])
        except Exception:
            pass
    return out


def fetch_prices(tickers):
    """回原幣別現價（美股美元、台股台幣）。台股 .TW 抓不到退 .TWO。"""
    tickers = sorted(set(tickers))
    out = _batch(tickers)
    miss = {tk: tk.replace(".TW", ".TWO") for tk in tickers
            if tk.endswith(".TW") and tk not in out}
    if miss:
        two = _batch(list(miss.values()))
        for orig, tc in miss.items():
            if tc in two:
                out[orig] = two[tc]
    return out


def build_holdings_map(prices):
    """3 主倉 + 7 鏈明細。
    產業鏈全=七鏈完整守備清單聯集；產業鏈+趨勢=同一批股再用 SuperTrend(週線)過濾；
    巴菲特=折價前30。"""
    select = chain_select_union()
    m = {CHAIN_ALL: select,
         CHAIN_TREND: trend_longs(select),
         BUFFETT_NAME: buffett_top30(prices)}
    m.update(chain_holdings())   # 7 鏈明細（各鏈完整守備清單）
    return m


def load():
    return json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else None


def save(state):
    json.dump(state, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _confirmed_longs(state, longs_today, date):
    """遲滯（hysteresis）過濾：翻燈要連續 TREND_CONFIRM_DAYS 天成立才生效。
    已持有的不因單日轉紅就賣、未持有的不因單日轉綠就買 → 直接消滅一日抖動。
    狀態存 state['trend_streak'] = {ticker: [dir, days]}，dir: 1=綠 -1=紅。"""
    pf = state["portfolios"].get(CHAIN_TREND) or {}
    held = set(pf.get("holdings", {}))
    green = set(longs_today)
    streak = state.setdefault("trend_streak", {})
    universe = green | held
    out = []
    for tk in sorted(universe):
        d = 1 if tk in green else -1
        prev = streak.get(tk)
        if prev and prev[0] == d:
            prev[1] += 1
        else:
            streak[tk] = [d, 1]
        days = streak[tk][1]
        if tk in held:
            # 持有中：轉紅要連續 N 天才賣，否則續抱
            if d == -1 and days >= TREND_CONFIRM_DAYS:
                continue
            out.append(tk)
        else:
            # 未持有：轉綠連續 N 天才買
            if d == 1 and days >= TREND_CONFIRM_DAYS:
                out.append(tk)
    # 清掉已不在池子的殘留狀態
    for tk in [t for t in streak if t not in universe]:
        streak.pop(tk, None)
    return sorted(out)


def _capped_weights(valid, min_slots=0, caps=None):
    """等權重為基礎，對 caps 內的標的設權重上限，超出部分按比例分給其他標的。
    回 {tk: weight}（總和 ≤ 1；min_slots 造成的差額留現金）。"""
    n = max(len(valid), min_slots)
    w = {t: 1.0 / n for t in valid}
    if not caps:
        return w
    capped = {t: c for t, c in caps.items() if t in w and w[t] > c}
    if not capped:
        return w
    freed = sum(w[t] - c for t, c in capped.items())
    for t, c in capped.items():
        w[t] = c
    others = [t for t in valid if t not in capped]
    if others and freed > 0:
        base = sum(w[t] for t in others)
        for t in others:                       # 依原權重比例分配釋出的額度
            w[t] += freed * (w[t] / base) if base else freed / len(others)
    return w


def _alloc_shares(tickers, capital, prices, fx, min_slots=0, caps=None):
    """把 capital 依權重買進 tickers，回 {tk: {sh,eu,en}}（eu=進場美金價,en=進場原幣價）。
    min_slots>0 時最少切成 min_slots 份，標的不足則剩餘留現金（由呼叫端記到 pf['cash']）。
    caps={tk: 權重上限} 用於單一鏈限重（如 Bitcoin→AI 機房）。"""
    valid = [t for t in tickers if prices.get(t)]
    if not valid:
        return {}
    w = _capped_weights(valid, min_slots, caps)
    h = {}
    for t in valid:
        pu = to_usd(t, prices[t], fx)
        if pu and pu > 0:
            h[t] = {"sh": round(capital * w[t] / pu, 4), "eu": round(pu, 4),
                    "en": round(prices[t], 2)}
    return h


def combo_apply(state, pf, combo_frac, buy, half_sell, full_exit, prices, fx, date):
    """三指標合流倉的實際下單：直接動股數，不走 _alloc_shares/rebalance() 的整籃子等權重重配
    ——「賣一半A」不該連動改變B的股數，這是跟其他倉本質不同的地方（單一部位獨立管理）。
    combo_frac：state裡的{ticker: 0.5或1.0}持倉比例追蹤，跟pf["holdings"]分開存。"""
    for tk in full_exit:
        h = pf["holdings"].pop(tk, None)
        combo_frac.pop(tk, None)
        if h and prices.get(tk):
            pf["cash"] = pf.get("cash", 0.0) + h["sh"] * to_usd(tk, prices[tk], fx)

    for tk in half_sell:
        h = pf["holdings"].get(tk)
        if not h or not prices.get(tk):
            continue
        pu = to_usd(tk, prices[tk], fx)
        sold_sh = h["sh"] * 0.5
        h["sh"] = round(h["sh"] - sold_sh, 4)
        pf["cash"] = pf.get("cash", 0.0) + sold_sh * pu
        combo_frac[tk] = 0.5

    if buy:
        v = _value(pf, prices, fx)
        slot = v / TREND_MIN_SLOTS   # 跟趨勢倉同一套「最少切N份」精神，避免單檔all-in
        for tk in buy:
            if not prices.get(tk):
                continue
            size = min(pf.get("cash", 0.0), slot)
            if size <= 0:
                continue
            pu = to_usd(tk, prices[tk], fx)
            if not pu or pu <= 0:
                continue
            pf["holdings"][tk] = {"sh": round(size / pu, 4), "eu": round(pu, 4),
                                  "en": round(prices[tk], 2)}
            pf["cash"] -= size
            combo_frac[tk] = 1.0

    _refresh_current(pf, prices, fx)
    v = _value(pf, prices, fx)
    pf["value"] = round(v, 2)
    pf["pnl"] = round(v - BASE, 2)
    pf["ret"] = round((v / BASE - 1) * 100, 2)
    pf["rebalanced"] = date
    if not pf["history"] or pf["history"][-1][0] != date:
        pf["history"].append([date, round(v, 2)])
    state["combo_frac"] = combo_frac


def _btc_caps():
    """Bitcoin→AI 機房「整條鏈」標的的個別權重上限（該鏈合計不超過 BTC_MAX_WEIGHT）。"""
    try:
        members = chain_holdings().get(BTC_CHAIN, [])
    except Exception:
        return {}
    if not members:
        return {}
    per = BTC_MAX_WEIGHT / len(members)
    return {t: per for t in members}


def _value(pf, prices, fx):
    """市值（美金）= Σ 股數 × 現價(美金) + 現金；無現價的用進場價（視為持平）。"""
    v = float(pf.get("cash") or 0.0)          # 綠燈不足時保留的現金部位
    for tk, h in pf["holdings"].items():
        pu = to_usd(tk, prices.get(tk), fx) or h["eu"]
        v += h["sh"] * pu
    return round(v, 2)


def _refresh_current(pf, prices, fx):
    """把每股現價(原幣)寫回 holdings，html 直接讀。"""
    for tk, h in pf["holdings"].items():
        if prices.get(tk):
            h["cur"] = round(prices[tk], 2)
            h["cu"] = round(to_usd(tk, prices[tk], fx), 4)


def _all_tickers(state):
    s = set()
    for pf in state["portfolios"].values():
        s.update(pf["holdings"].keys())
    return s


def update_nav(state, prices, fx, date):
    for pf in state["portfolios"].values():
        _refresh_current(pf, prices, fx)
        v = _value(pf, prices, fx)
        pf["value"] = v
        pf["pnl"] = round(v - BASE, 2)
        pf["ret"] = round((v / BASE - 1) * 100, 2)
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, v])
        else:
            pf["history"][-1][1] = v
    state["updated"] = date
    state["fx"] = round(fx, 3)


def rebalance(state, hmap, prices, fx, date, only=None):
    """only=None 全倉調；only={名稱,...} 只調指定倉（其餘不動）。"""
    for name, pf in state["portfolios"].items():
        if only and name not in only:
            continue
        v = _value(pf, prices, fx) if (pf["holdings"] or pf.get("cash")) else BASE
        # 趨勢倉/合流倉：訊號檔數常常很少，留現金避免硬集中在1-2檔（合流倉事件觸發更稀疏，同理套用）
        slots = TREND_MIN_SLOTS if name in (CHAIN_TREND, CHAIN_COMBO) else 0
        # Bitcoin 鏈限重：套用在所有「跨鏈」主倉（單一鏈明細倉不套，那本來就是純曝險）
        caps = _btc_caps() if name in (CHAIN_ALL, CHAIN_TREND, CHAIN_COMBO) else None
        pf["holdings"] = _alloc_shares(hmap.get(name, list(pf["holdings"])), v, prices, fx,
                                       slots, caps)
        invested = sum(h["sh"] * h["eu"] for h in pf["holdings"].values())
        pf["cash"] = round(max(0.0, v - invested), 2)
        _refresh_current(pf, prices, fx)
        pf["value"] = round(v, 2)
        pf["pnl"] = round(v - BASE, 2)
        pf["ret"] = round((v / BASE - 1) * 100, 2)
        pf["rebalanced"] = date
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, round(v, 2)])
    state["updated"] = date
    state["fx"] = round(fx, 3)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "nav"
    date = datetime.now().strftime("%Y-%m-%d")

    if cmd == "init":
        if load():
            print("portfolios.json 已存在")
            return
        chains = chain_holdings()
        wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
        allt = set(wl.keys())
        for v in chains.values():
            allt.update(v)
        fx = get_fx()
        prices = fetch_prices(allt)
        hmap = build_holdings_map(prices)
        state = {"inception": date, "updated": date, "base": BASE, "fx": round(fx, 3),
                 "main": MAIN, "portfolios": {}}
        for name, hold in hmap.items():
            h = _alloc_shares(hold, BASE, prices, fx)
            pf = {"holdings": h, "value": BASE, "pnl": 0.0, "ret": 0.0,
                  "rebalanced": date, "history": [[date, BASE]]}
            _refresh_current(pf, prices, fx)
            state["portfolios"][name] = pf
        save(state)
        print(f"✅ init：{len(state['portfolios'])} 倉，各 ${BASE:,.0f}，匯率 {fx:.2f}，起始 {date}")
        for n, pf in state["portfolios"].items():
            print(f"  [{'主' if n in MAIN else '鏈'}] {n}: {len(pf['holdings'])} 檔")
        return

    state = load()
    if not state:
        print("無 portfolios.json，先 init")
        return
    fx = get_fx()

    # 三指標合流倉延遲建倉（2026-08-11新設）：跟其他倉不同，一開始不buy整個宇宙，
    # 空手等第一個事件觸發訊號才進場——所以只需要在state裡補一個空倉位當起點。
    # 同時補state["main"]（portfolio_html.py讀這個決定「主策略」分組，不是讀MAIN常數）。
    dirty = False
    if CHAIN_COMBO not in state["portfolios"]:
        state["portfolios"][CHAIN_COMBO] = {
            "holdings": {}, "cash": BASE, "value": BASE, "pnl": 0.0, "ret": 0.0,
            "rebalanced": date, "history": [[date, BASE]]}
        print(f"✅ 已建立「{CHAIN_COMBO}」倉，起始 ${BASE:,.0f}現金，等待第一個訊號")
        dirty = True
    if CHAIN_COMBO not in state.get("main", []):
        state["main"] = MAIN
        dirty = True
    if dirty:
        save(state)

    if cmd == "rebalance":
        allt = _all_tickers(state) | set(json.load(open(BUFFETT, encoding="utf-8")).keys())
        prices = fetch_prices(allt)
        rebalance(state, build_holdings_map(prices), prices, fx, date)
        save(state)
        print(f"✅ rebalance {date}（匯率 {fx:.2f}）")
        for n, pf in state["portfolios"].items():
            print(f"  {n}: {len(pf['holdings'])} 檔 ${pf['value']:,.0f} ({pf['ret']:+.2f}%)")
    elif cmd == "rebalance-trend":
        # 趨勢倉：池子(守備清單)週日重篩，綠燈名單「有變」才換股。
        # 2026-07-27 加兩道抗 whipsaw 護欄（實證：4 週換 12 次，比買進持有多虧 7.8pp，
        # 且把唯一賺錢的 2359.TW 砍掉；2345.TW 賣掉隔天又買回）：
        #   ① 翻燈需連續 CONFIRM_DAYS 天成立才動作 → 過濾臨界值抖動
        #   ② 綠燈不足 MIN_HOLDINGS 檔時，剩餘資金留現金，不硬集中在少數幾檔
        select = chain_select_union()
        longs_today = trend_longs(select)
        longs = _confirmed_longs(state, longs_today, date)
        pf = state["portfolios"].get(CHAIN_TREND)
        cur = set(pf["holdings"].keys()) if pf else set()
        if set(longs) == cur:
            print(f"趨勢倉綠燈清單無變化（{len(longs)} 檔），不調倉")
        else:
            allt = _all_tickers(state) | set(longs)
            prices = fetch_prices(allt)
            rebalance(state, {CHAIN_TREND: longs}, prices, fx, date, only={CHAIN_TREND})
            save(state)
            add = sorted(set(longs) - cur)
            rm = sorted(cur - set(longs))
            print(f"✅ 趨勢倉調倉 {date}（匯率 {fx:.2f}）：+{add or '無'} / -{rm or '無'} → {len(longs)} 檔")
    elif cmd == "rebalance-combo":
        # 三指標合流倉：事件觸發才動，跟趨勢倉的「狀態維持」不同（見combo_signal_events）。
        # 2026-08-11 改不對稱出場：ST單獨翻空賣一半、RS(60日)跌破自己60MA才全出。
        select = chain_select_union()
        pf = state["portfolios"][CHAIN_COMBO]
        combo_frac = state.setdefault("combo_frac", {})
        # 持股裡沒有紀錄比例的（例如舊資料或手動調整過）預設當作全倉
        for tk in pf["holdings"]:
            combo_frac.setdefault(tk, 1.0)
        buy, half_sell, full_exit = combo_signal_events(select, combo_frac)
        if not buy and not half_sell and not full_exit:
            print("三指標合流倉無新訊號，不調倉")
        else:
            allt = _all_tickers(state) | set(buy) | set(half_sell) | set(full_exit)
            prices = fetch_prices(allt)
            combo_apply(state, pf, combo_frac, buy, half_sell, full_exit, prices, fx, date)
            save(state)
            print(f"✅ 三指標合流倉 {date}（匯率 {fx:.2f}）：買進+{buy or '無'} / "
                 f"賣一半{half_sell or '無'} / 全出{full_exit or '無'} → 現持 {len(pf['holdings'])} 檔")
    elif cmd == "nav":
        prices = fetch_prices(_all_tickers(state))
        update_nav(state, prices, fx, date)
        save(state)
        rank = sorted(state["portfolios"].items(), key=lambda kv: -kv[1]["ret"])
        print(f"✅ nav {date}（匯率 {fx:.2f}）:")
        for n, pf in rank:
            print(f"  {pf['ret']:+6.2f}%  ${pf['value']:>9,.0f}  損益 {pf['pnl']:+,.0f}  {n}")


if __name__ == "__main__":
    main()
