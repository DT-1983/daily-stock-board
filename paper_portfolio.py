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

  · 進出燈號 → 每日讀 combo_scan 四燈結果：打點(≥3燈+風報比≥1)進、ST翻空賣半、RS跌破60MA全出（見下方CHAIN_COMBO）

用法:python paper_portfolio.py [init|rebalance|rebalance-trend|rebalance-combo|nav]
"""
import sys
import json
import os
from datetime import datetime
import yfinance as yf

import board_html_legacy as _L
from technical_indicators import squeeze_momentum, mansfield_rs_series, _benchmark

STORE = os.environ.get("PORTFOLIO_STATE", "portfolios.json")   # 測試時指到別的檔
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
TREND_ATR = "wilder"           # 趨勢倉 SuperTrend 的 ATR：wilder（5.7 年回測基準）/ sma（老墨版，顯示層與進出燈號用）
TREND_CONFIRM_DAYS = 1         # 週線本身已濾掉日內雜訊，確認天數降回 1（避免雙重延遲）
TREND_MIN_SLOTS    = 8         # 最少切成 N 份；綠燈不足時剩餘留現金（避免集中在 3-4 檔）
# ── Bitcoin→AI 機房限重（2026-07-28）─────────────────────────────────
# 5.5 年回測最大回撤 -94%（2022 年 -87.7%，接近歸零）。這是風險管理事實，
# 不是回測過擬合：等權重讓它一檔就能砸掉整個精選倉。
BTC_CHAIN = "Bitcoin→AI 機房"
BTC_MAX_WEIGHT = 0.10          # 該鏈標的在跨鏈主倉的合計權重上限
# ── 進出燈號倉（2026-09-02 由「三指標合流」換成，實驗性）──────────────────
# 三指標合流（ST翻多+RS30>0+擠壓剛噴出「同一天」）是事件同步條件，8/18 開倉到 9/2
# 一次都沒觸發、10000 現金全趴著——不是訊號不好，是三件事同天發生的機率太低。
# 改成老墨的 COMBO 四燈「狀態」判斷，跟 docs/combo.html 進出燈號頁同一份資料
# （直接讀 combo_scan.py 產出的 state/combo_result.json，頁面看到什麼、倉就照什麼進出，
# 兩邊不會漂移；本機 07:00 掃描→push，Actions 09:00 讀）。
# 進場（打點）：≥3 燈成立 且 風報比 ≥ 1（分子=市場目標價共識−現價、分母=現價−ST線）
#   四燈 = L1 SuperTrend(日線,SMA版ATR)多方 / L2 動能>0 / L3 雙重颱風不為綠 / L4 RS60日乖離>+3%
#   排序：亮燈數多者先、同燈數風報比高者先；每檔 1/TREND_MIN_SLOTS 倉，現金用完為止
# 出場（跟原本三指標一樣，老墨的不對稱兩階段）：
#   ① ST 翻空（bull=False）→ 賣一半（狀態判斷；賣過一半的不重複）
#   ② RS60 跌破自己的 60MA（rs_short<0）→ 剩餘全出，全出後 LAMP_COOLDOWN_DAYS 內不再進
# 沒有歷史回測：目標價沒有歷史資料，風報比回不了頭——這個倉本身就是累積樣本的器材。
CHAIN_COMBO = "進出燈號"
CHAIN_COMBO_OLD = "三指標合流"   # portfolios.json 舊倉名，load() 時自動改名（歷史淨值沿用，都是 10000）
LAMP_RESULT = "state/combo_result.json"
LAMP_MAX_AGE_DAYS = 4            # 掃描結果超過這麼多天沒更新就不動作（別拿舊燈號下單）
LAMP_COOLDOWN_DAYS = 7           # 全出後幾個日曆天內不重新進場（避免出了隔天又買回）
MAIN = [CHAIN_ALL, CHAIN_TREND, BUFFETT_NAME, CHAIN_COMBO]
FX_FALLBACK = 32.0              # USD/TWD 備援匯率


def tw_yf(code):
    return f"{code}.TW" if str(code).isdigit() else str(code)


def is_tw(tk):
    # 2026-09-02：上櫃股是 .TWO（combo_result 的 symbol 走 tw_symbol.resolve），
    # 原本只認 .TW 會把台幣價當美金加總
    return tk.endswith(".TW") or tk.endswith(".TWO")


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


# 賽馬排除鏈。2026-08-18 用戶指示把玻璃基板/TGV 放進賽馬（原本 08-05 上線時列為
# 題材驗證期觀察鏈、只上看板不進模擬倉）。
# 關鍵金屬/原物料（2026-08-17 新增第 9 鏈）維持排除。
# ⚠️ 中途加入的鏈是從加入當天以 $10,000 起跑，跟 6/30 就開跑的鏈比「報酬率」時
# 期間不同、不可直接比大小——賽馬頁會標示起跑日，看的時候要注意。
RACE_EXCLUDE = {"關鍵金屬/原物料"}


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
    # 2026-09-02：一度改成 SMA（跟顯示層/進出燈號統一），同日用 backtest_trend_2026.py
    # 重跑 5.7 年（QQQ + 守備清單 × 日/週線）：週線趨勢倉 Wilder 報酬略優、SMA 沒有優勢，
    # 依「只改有結構性證據的」原則改回 Wilder；用 TREND_ATR 切換，兩版都能重跑對照。
    # 這支刻意不 import technical_indicators（會拉進 numpy/markdown 依賴鏈），所以就地算。
    if TREND_ATR == "sma":
        for i in range(period - 1, n):
            atr[i] = sum(tr[i - period + 1:i + 1]) / period
    else:
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


def load_lamp_result(today):
    """讀 combo_scan.py 的結果；缺檔或太舊回 None（寧可不動，不拿舊燈號下單）。"""
    if not os.path.exists(LAMP_RESULT):
        print(f"⚠️ 找不到 {LAMP_RESULT}，進出燈號倉不動作")
        return None
    res = json.load(open(LAMP_RESULT, encoding="utf-8"))
    from datetime import date as _d
    age = (_d.fromisoformat(today) - _d.fromisoformat(res["date"])).days
    if age > LAMP_MAX_AGE_DAYS:
        print(f"⚠️ {LAMP_RESULT} 是 {res['date']} 的（{age} 天前），太舊不動作")
        return None
    return res


def lamp_signal_events(rows, held_frac, exits, today):
    """進出燈號倉：狀態判斷，回 (buy, half_sell, full_exit)。
    rows 是 combo_result 的列（已依 亮燈數↓/風報比↓ 排好，買單照這個順序吃現金）。
    買：未持有 + combo(≥3燈) + rr≥1 + 不在全出冷卻期
    賣①：全倉 + ST 翻空(bull=False) → 賣一半      賣②：持有 + rs_short<0 → 全出
    exits：{symbol: 全出日期}，冷卻用。"""
    from datetime import date as _d
    buy, half_sell, full_exit = [], [], []
    for r in rows:
        tk = r.get("symbol") or r.get("ticker")
        frac = held_frac.get(tk, 0.0)
        if frac == 0.0:
            rr = r.get("rr")
            if r.get("combo") and rr is not None and rr >= 1:
                ex = exits.get(tk)
                if ex and (_d.fromisoformat(today) - _d.fromisoformat(ex)).days < LAMP_COOLDOWN_DAYS:
                    continue
                buy.append(tk)
            continue
        rs = r.get("rs_short")
        if rs is not None and rs < 0:
            full_exit.append(tk)
            continue
        if frac == 1.0 and not r.get("bull", True):
            half_sell.append(tk)
    return buy, sorted(half_sell), sorted(full_exit)


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
        # 2026-09-02：三指標合流倉用 SMA 版 ATR——跟進出燈號/顯示層同一套（對齊老墨的燈號定義）；
        # 週線趨勢倉另走 _supertrend_dir(TREND_ATR="wilder")，兩層刻意不同，見 supertrend_backtest_findings 證據五
        from technical_indicators import supertrend_sma as _st_sma
        st = _st_sma(highs, lows, closes)
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
        # 第二關：盈再率。2026-08-25 改用分級，原本是 `rr is not None and rr >= 0.80`，
        # 有兩個漏洞：
        #   ① 抓不到資料（rr is None）直接放行——「一無所知」比「知道有問題」還容易過關。
        #      當初這樣寫是因為涵蓋率只有 6 成，硬擋會殺掉太多；今天接完 SEC EDGAR
        #      並修好 FinMind 快取後涵蓋率 97.6%（41 檔只剩 1 檔抓不到），代價已經很小。
        #   ② 只比大小，沒看方向。盈再率 −43% 是公司在**縮表**（處分廠房、收掉事業），
        #      不是「資本效率好」，但 −43 < 0.80 會被當成優等生買進。
        grade = d.get("reinvest_grade")
        if grade is None:
            # 舊版 buffett_watch.json 沒有這欄。**不要直接當不合格**——
            # 2026-08-17 就是因為讀一個永遠不存在的欄位（"fair"），
            # 讓巴菲特倉持股長期是 0、淨值凍結而且完全沒有報錯。
            grade = "ideal" if (rr is not None and 0 <= rr < 0.80) else "unknown"
        if grade not in ("ideal", "acceptable"):   # unknown / shrinking / warn 都不買
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
    if not os.path.exists(STORE):
        return None
    state = json.load(open(STORE, encoding="utf-8"))
    # 2026-09-02 倉名「三指標合流」→「進出燈號」：同一個 $10,000、同一條歷史線
    pfs = state.get("portfolios", {})
    if CHAIN_COMBO_OLD in pfs and CHAIN_COMBO not in pfs:
        pfs[CHAIN_COMBO] = pfs.pop(CHAIN_COMBO_OLD)
        state["main"] = [CHAIN_COMBO if n == CHAIN_COMBO_OLD else n for n in state.get("main", [])]
        print(f"（倉名 {CHAIN_COMBO_OLD} → {CHAIN_COMBO}）")
    return state


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


def _check_basis(pf, name, fx):
    """檢查進場成本的幣別跟現價一致——**只警告不自動改**，改要人看過。

    🔴 2026-09-03 踩過：9/2 修 `is_tw()` 讓 `.TWO` 被認出來後，**現價**開始正確
    換成美元，但**儲存的進場價 `eu` 還是舊制的台幣數字**（8/18 建倉時寫的）。
    於是 1580.TWO / 5520.TWO 的市值一夜之間變成原本的 1/32，巴菲特倉顯示
    -37.36%（真實是 +0.30%），而且**沒有任何地方報錯**——數字看起來就只是「跌很多」。

    ⭐ 通則：改了「怎麼算」的規則，要一併檢查**已經用舊規則存起來的資料**。
    只改計算不遷移資料＝改了一半，而且壞掉的樣子會偽裝成正常的市場波動。
    （同 [[otc_suffix_coverage_gap]]、[[derived_files_stale_after_correction]]）
    """
    for tk, h in pf["holdings"].items():
        en, eu = h.get("en"), h.get("eu")
        if not (is_tw(tk) and en and eu and fx):
            continue
        expect = en / fx
        if abs(eu - expect) / max(expect, 1e-9) > 0.2:
            print(f"  🔴 {name} / {tk} 進場成本幣別不一致："
                  f"eu={eu}（台幣 {en} ÷ {fx} 應為 {expect:.4f}，差 {eu/expect:.0f} 倍）"
                  f"——這檔的損益是假的，要先修 portfolios.json 再看數字")


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
    for name, pf in state["portfolios"].items():
        _check_basis(pf, name, fx)          # 幣別一致性，只警告不自動改
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

    # 進出燈號倉（原三指標合流，2026-08-11新設）延遲建倉：跟其他倉不同，一開始不buy整個宇宙，
    # 空手等第一個打點才進場——所以只需要在state裡補一個空倉位當起點。
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
        # 一定要把「所有鏈的守備清單」也算進抓價範圍：新鏈第一次進賽馬時還不在
        # state["portfolios"] 裡，只靠 _all_tickers(state) 會漏掉它的個股 →
        # 配股時查不到價格、建了倉卻是 0 檔（2026-08-18 玻璃基板進賽馬時踩到）。
        allt = (_all_tickers(state)
                | set(json.load(open(BUFFETT, encoding="utf-8")).keys())
                | {t for v in chain_holdings().values() for t in v})
        prices = fetch_prices(allt)
        hmap = build_holdings_map(prices)
        # 新鏈上線（或從 RACE_EXCLUDE 移出）時補建倉：rebalance() 只走
        # state["portfolios"] 既有的倉，不會自己長出新鏈，沒這段新鏈永遠不會進賽馬。
        # 記自己的 inception，之後頁面才能標示「中途加入、起跑日不同」。
        for name in hmap:
            if name not in state["portfolios"]:
                state["portfolios"][name] = {
                    "holdings": {}, "cash": BASE, "value": BASE, "pnl": 0.0, "ret": 0.0,
                    "inception": date, "rebalanced": date, "history": [[date, BASE]]}
                print(f"✅ 新增「{name}」倉，起始 ${BASE:,.0f}（起跑日 {date}）")
        rebalance(state, hmap, prices, fx, date)
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
        # 進出燈號倉（2026-09-02 換自三指標合流）：讀 combo_scan 結果做狀態判斷，
        # 部位獨立管理（combo_apply 直接動股數，不整籃重配）。
        pf = state["portfolios"][CHAIN_COMBO]
        combo_frac = state.setdefault("combo_frac", {})
        for tk in pf["holdings"]:
            combo_frac.setdefault(tk, 1.0)
        res = load_lamp_result(date)
        if res is not None:
            exits = state.setdefault("lamp_exits", {})
            buy, half_sell, full_exit = lamp_signal_events(res["rows"], combo_frac, exits, date)
            # 2026-09-03：動作寫成檔給 Discord 日報第②段讀（daily_warroom.sec2_signals）。
            # 無動作也寫（空清單）——「今天沒交易」跟「Actions 沒跑」在檔案上才分得出來。
            def _dump_trades(bought, hs, fe):
                json.dump({"date": date, "lamp_date": res["date"], "buy": bought,
                           "half_sell": hs, "full_exit": fe,
                           "held": len(pf["holdings"]), "cash": round(pf.get("cash", 0.0), 2)},
                          open("state/lamp_trades_today.json", "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
            if not buy and not half_sell and not full_exit:
                print(f"進出燈號倉無動作（燈號日期 {res['date']}，現持 {len(pf['holdings'])} 檔）")
                _dump_trades([], [], [])
            else:
                allt = _all_tickers(state) | set(buy) | set(half_sell) | set(full_exit)
                prices = fetch_prices(allt)
                before = set(pf["holdings"])
                combo_apply(state, pf, combo_frac, buy, half_sell, full_exit, prices, fx, date)
                bought = sorted(set(pf["holdings"]) - before)
                for tk in full_exit:
                    exits[tk] = date
                save(state)
                _dump_trades(bought, half_sell, full_exit)
                print(f"✅ 進出燈號倉 {date}（燈號 {res['date']}，匯率 {fx:.2f}）：買進+{bought or '無'}"
                      f"（打點候選 {len(buy)} 檔，現金吃完為止） / 賣一半{half_sell or '無'} / "
                      f"全出{full_exit or '無'} → 現持 {len(pf['holdings'])} 檔，現金 ${pf['cash']:,.0f}")
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
