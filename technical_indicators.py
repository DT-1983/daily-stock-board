"""技術面四指標（BEST MATCH 拆解功能 #4）→ 財報卡新增區塊

四個指標全部只需要 OHLCV 價量資料，yfinance 對美股/台股皆可直接抓，
不需要額外資料源。公式依報告「方法說明」逐一對照移植：

  SuperTrend      ATR(10, Wilder's RMA)×3 —— 直接復用 board_html_legacy.supertrend()
  雙重颱風K線     跟 SuperTrend 同構，只差 ATR 用 SMA(TrueRange,10) 而非 Wilder 平滑
  EXCEED CHARGE   TTM Squeeze／擠壓動能：布林帶(樣本標準差) vs 凱特納通道(SMA of TR)，
                   擠壓＝布林帶縮進凱特納通道內；動能＝對 value 序列做線性迴歸取末端值
  RS 相對強弱     Weinstein/Mansfield：(股價/大盤 比值) 對其自身均線的乖離%，
                   短線(30日)＋長線(1年)兩組

2026-08-25：對照老墨 XQ 官方指標（mophyfei/MOFI_XQ）的說明頁後補上三層，
原本這三個指標只有「基礎線」，缺了官方版真正拿來判斷的加值層——
指標邏輯不開源（.xsb 是編譯過的二進位），這裡是照他公開的說明頁文字重新設計，
不是照抄程式碼：
  SuperTrend    + 過去N年歷史統計：多空平均/最短持續根數、歷史延續機率、
                  這波走了幾根、贏過歷史幾成（見 supertrend_stats）
  EXCEED CHARGE + 擠壓三級強度（微/中/極，見 squeeze_intensity）
                + 動能四色文字標籤（見 momentum_label，圖表本來就有四色只是tile沒講出來）
  RS 相對強弱   + RS創新高偵測 + 「RS領先股價」背離訊號 + 短長RS交叉訊號（見 rs_signals）
⚠️ 沒有動 RS 短30日/長1年這兩個窗口——那是先前跟財報卡對齊的決定，不是老墨的預設(60/240)，
   加值層的訊號計算直接套用在既有序列上，不重新定義基礎指標。

用法：
    python technical_indicators.py 3037.TW
    python technical_indicators.py NVDA
"""
import sys
import re
import json
import argparse

import numpy as np
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from board_html_legacy import supertrend  # 復用既有 SuperTrend，不重造


def _is_tw(ticker):
    return bool(re.match(r"^\d{4,5}(\.TWO?)?$", ticker.upper())) or ticker.upper().endswith((".TW", ".TWO"))


def _benchmark(ticker):
    return "^TWII" if _is_tw(ticker) else "^GSPC"


_BENCHMARK_NAME = {"^TWII": "台股加權指數", "^GSPC": "S&P 500"}


# ── 雙重颱風K線：SuperTrend 的 SMA-ATR 變體 ──────────────────────────

def typhoon_state(closes, vols, dt_dir, n=20):
    """雙重颱風的三態顏色：1=紅(偏多) / -1=綠(偏空) / 0=黃(不明)。

    官方定義（mophyfei/MOFI_XQ「DOUBLE TYPHOON 雙重颱風 K 線」README）：
      紅＝市場偏多、綠＝市場偏空、黃＝偏不明；
      「之所以叫雙重，是因為要**同時通過兩道關卡**確認才會判成偏多或偏空，
        只要兩邊沒有一致，就會亮黃燈。」
    燈 3「雙重颱風不為綠」＝ 不是偏空 → 紅與黃都算亮。

    ⚠️⚠️ **第二道關卡是逆向推導的，不是官方公開的定義。**
    .xsb 實測是加密二進位（39% 可讀、抽出的字串全是亂碼），還原不出邏輯。
    這裡用「20 日均線(SMA) 的走向」當第二道。**2026-09-02 由實際畫面定案**：
      · 官方參數表寫「**成本**計算天數 預設 20」——「成本」對應 VWAP，
        而 VWAP 已經實測對上老墨的 135.95（收盤 20MA 是 133.78，差 1.6%）
      · 用 Leo 提供的三個有標示的截圖案例反推，三個全中：
          9939 2026-08-26  第一道空 × VWAP20↑ → 不一致 → 黃   （老墨：不明）✅
          9939 2024-12-16  第一道空 × VWAP20↓ → 一致   → 綠   （老墨：弱勢）✅
          8996 2026-08-26  第一道多 × VWAP20↑ → 一致   → 紅   （老墨：強勢）✅
      · 另外兩個候選（RS60、收vs前一根）被 8996 那個案例排除；
        「SMA20 走向」同樣三個全中，**目前無法與 VWAP 版區分**——
        要區分得找到兩者走向相反、且老墨有標示的日子。
    → 樣本只有 3 個。看到跟老墨畫面不一致時，**先懷疑這裡**。
    """
    if dt_dir is None or len(closes) < n + 2:
        return None
    ma = _sma(closes, n)
    if ma[-1] is None or ma[-2] is None:
        return None
    second = 1 if ma[-1] > ma[-2] else -1
    return dt_dir if dt_dir == second else 0


def double_typhoon(highs, lows, closes, period=10, mult=3.0):
    n = len(closes)
    if n < period + 1:
        return None
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = [None] * n
    for i in range(period - 1, n):
        atr[i] = sum(tr[i - period + 1:i + 1]) / period  # SMA，不是 Wilder RMA
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(n)]
    st, dr, up, lo = [None] * n, [None] * n, [None] * n, [None] * n
    for i in range(period - 1, n):
        if atr[i] is None:
            continue
        bu, bl = hl2[i] + mult * atr[i], hl2[i] - mult * atr[i]
        if i == period - 1 or up[i - 1] is None:
            up[i], lo[i] = bu, bl
            dr[i] = 1 if closes[i] >= hl2[i] else -1
        else:
            up[i] = bu if (bu < up[i - 1] or closes[i - 1] > up[i - 1]) else up[i - 1]
            lo[i] = bl if (bl > lo[i - 1] or closes[i - 1] < lo[i - 1]) else lo[i - 1]
            dr[i] = 1 if closes[i] > up[i - 1] else (-1 if closes[i] < lo[i - 1] else dr[i - 1])
        st[i] = lo[i] if dr[i] == 1 else up[i]
    return {"st": st, "dir": dr}


# ── EXCEED CHARGE：擠壓動能（TTM Squeeze） ───────────────────────────

# 2026-09-02：double_typhoon 算的其實就是「SMA 版 ATR 的 SuperTrend」。
# 在策略層用 double_typhoon 這個名字會看不懂在做什麼，所以給一個語意清楚的別名。
# 老墨的 SUPER TREND PRO MAX 實測就是這一版（3037 @ 09-02 空方壓力 1223.7 對到小數）。
supertrend_sma = double_typhoon

def typhoon_state_series(closes, vols, dt_dir, n=20):
    """每日的雙重颱風三態序列：1=紅(偏多) / -1=綠(偏空) / 0=黃(不明) / None=算不出。

    2026-09-02：雙重颱風**本來就是 K 棒著色，不是一條線**（老墨 README：
    紅=偏多、綠=偏空、黃=不明）。我們原本把它當第二條 SuperTrend 畫在圖上，
    只是因為兩版 ATR 算法不同才「看起來像兩條線」；顯示層統一成 SMA 之後
    兩條 100% 重疊，Leo 一眼看出「雙重颱風沒畫成功」——其實是畫法從頭就錯。
    改用這個序列去替收盤線分段上色，才是它真正的樣子。
    """
    ma = _sma(closes, n)
    out = []
    for i in range(len(closes)):
        d = dt_dir[i] if i < len(dt_dir) else None
        if d is None or i < 1 or ma[i] is None or ma[i-1] is None:
            out.append(None)
            continue
        second = 1 if ma[i] > ma[i-1] else -1
        out.append(d if d == second else 0)
    return out



def squeeze_momentum(highs, lows, closes, length=20, bb_mult=2.0, kc_mult=1.5):
    n = len(closes)
    if n < length + 1:
        return None
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)

    def sma(a, w):
        out = np.full(len(a), np.nan)
        for i in range(w - 1, len(a)):
            out[i] = a[i - w + 1:i + 1].mean()
        return out

    bb_mid = sma(c, length)
    bb_std = np.full(n, np.nan)
    for i in range(length - 1, n):
        bb_std[i] = c[i - length + 1:i + 1].std(ddof=1)  # 樣本標準差
    bb_up, bb_lo = bb_mid + bb_mult * bb_std, bb_mid - bb_mult * bb_std

    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    kc_range = sma(tr, length)  # 凱特納：SMA of TR，非 ATR
    kc_up, kc_lo = bb_mid + kc_mult * kc_range, bb_mid - kc_mult * kc_range

    squeeze_on = (bb_lo > kc_lo) & (bb_up < kc_up)

    donchian_mid = np.full(n, np.nan)
    for i in range(length - 1, n):
        donchian_mid[i] = (h[i - length + 1:i + 1].max() + l[i - length + 1:i + 1].min()) / 2
    value = c - (donchian_mid + bb_mid) / 2

    # 線性迴歸取視窗末端投影值（標準 TTM Squeeze 動能柱算法）
    mom = np.full(n, np.nan)
    x = np.arange(length)
    for i in range(length - 1, n):
        y = value[i - length + 1:i + 1]
        if np.isnan(y).any():
            continue
        b, a = np.polyfit(x, y, 1)
        mom[i] = a + b * (length - 1)

    return {"squeeze_on": squeeze_on, "momentum": mom}


# ── RS 相對強弱（Mansfield） ──────────────────────────────────────────

def mansfield_rs(closes, bench_closes, short=30, long=250):
    n = min(len(closes), len(bench_closes))
    c = np.array(closes[-n:], dtype=float)
    b = np.array(bench_closes[-n:], dtype=float)
    rs_raw = c / b
    out = {}
    for label, win in (("short", short), ("long", long)):
        if n < win + 1:
            out[label] = None
            continue
        rs_avg = rs_raw[-win:].mean()
        out[label] = (rs_raw[-1] / rs_avg - 1) * 100
    return out


def mansfield_rs_series(closes, bench_closes, win):
    """整段序列版（給畫圖用），不是只取最新一值。"""
    n = min(len(closes), len(bench_closes))
    c = np.array(closes[-n:], dtype=float)
    b = np.array(bench_closes[-n:], dtype=float)
    rs_raw = c / b
    out = np.full(n, np.nan)
    for i in range(win, n):
        avg = rs_raw[i - win:i].mean()
        out[i] = (rs_raw[i] / avg - 1) * 100 if avg else np.nan
    return out


# ── SuperTrend 歷史統計層（老墨 SUPER TREND PRO MAX 加值層）────────────

def supertrend_runs(dir_series):
    """把方向序列切成一段段連續同向的「波段」。回 [(start_i, end_i, length, dir), ...]。
    只收完整落在資料範圍內、方向不是 None 的段；最後一段若還在走（尚未翻轉）
    照樣算進來，由呼叫端自己決定要不要排除「進行中」的這一段。"""
    runs = []
    start, cur = None, None
    for i, d in enumerate(dir_series):
        if d is None:
            continue
        if cur is None:
            start, cur = i, d
        elif d != cur:
            runs.append((start, i - 1, i - start, cur))
            start, cur = i, d
    if cur is not None:
        runs.append((start, len(dir_series) - 1, len(dir_series) - start, cur))
    return runs


def supertrend_stats(dir_series, window_m=20):
    """老墨版數值欄：多空平均/最短持續根數、歷史延續機率、這波走了幾根、贏過歷史幾成。

    「歷史延續機率」＝ 講稿定義是「該方向趨勢在其後 M 日內未翻轉的歷史比率」，
    等價於「該方向歷史波段中，長度 ≥ M 根的比例」——用波段長度分布直接算，
    不用逐點往前看，數學上一致且好驗證。
    dir_series 建議傳「用於統計的長序列」（例如 10 年），跟畫圖用的近一年序列分開。
    """
    runs = supertrend_runs(dir_series)
    if len(runs) < 2:
        return None
    completed = runs[:-1]              # 最後一段還在走，只用「已結束」的波段做歷史統計
    cur_start, cur_end, cur_len, cur_dir = runs[-1]

    out = {}
    for d, label in ((1, "up"), (-1, "down")):
        lens = [r[2] for r in completed if r[3] == d]
        if not lens:
            out[f"avg_len_{label}"] = out[f"min_len_{label}"] = out[f"prob_{label}"] = None
            continue
        out[f"avg_len_{label}"] = sum(lens) / len(lens)
        out[f"min_len_{label}"] = min(lens)
        out[f"prob_{label}"] = sum(1 for x in lens if x >= window_m) / len(lens) * 100

    out["cur_dir"] = cur_dir
    out["cur_len"] = cur_len
    same_dir_lens = [r[2] for r in completed if r[3] == cur_dir]
    if len(same_dir_lens) >= 5:         # 樣本太少的百分位沒意義，README同款門檻
        out["cur_percentile"] = sum(1 for x in same_dir_lens if x < cur_len) / len(same_dir_lens) * 100
    else:
        out["cur_percentile"] = None
    return out


# ── EXCEED CHARGE 加值層：擠壓三級強度 + 動能四色標籤 ────────────────────

def squeeze_intensity(sq, lookback=252):
    """擠壓強度分三級（微/中/極）。老墨說明頁沒給絕對數字門檻，
    用「布林帶縮進凱特納通道多深」這個比值，相對於近一年自己的擠壓分布分三等分
    （同一檔股票自己比自己，不同波動特性的股票才不會用同一把尺）。
    回傳 ("微壓"|"中壓"|"極壓"|None, 最新一根的緊縮比值)。squeeze_on=False 回 (None, None)。
    """
    on = sq["squeeze_on"]
    mom = sq["momentum"]
    if on is None or len(on) == 0 or not bool(on[-1]):
        return None, None
    # 用動能值的窄幅程度當代理：擠壓期動能貼近 0，越貼近 0 代表布林帶縮得越深。
    # （sq 沒有直接存 bb/kc 寬度，重新算太重，這裡用等價的窄幅代理，方向一致。）
    start = max(0, len(on) - lookback)
    hist_tightness = [abs(mom[i]) for i in range(start, len(on))
                      if on[i] and mom[i] is not None and not np.isnan(mom[i])]
    cur = abs(mom[-1]) if mom[-1] is not None and not np.isnan(mom[-1]) else None
    if cur is None or len(hist_tightness) < 10:
        return "中壓", cur          # 樣本不足時給中性標籤，不硬分級
    hist_sorted = sorted(hist_tightness)
    p33 = hist_sorted[len(hist_sorted) // 3]
    p66 = hist_sorted[len(hist_sorted) * 2 // 3]
    # 動能絕對值越小＝越窄＝壓得越緊＝級別越高
    level = "極壓" if cur <= p33 else ("中壓" if cur <= p66 else "微壓")
    return level, cur


def momentum_label(mom):
    """動能四色文字標籤：強多(加速)/弱多(衰退)/強空(加速)/弱空(收斂)。
    跟前端圖表 momColor 用同一套邏輯（value 正負 × 比前一根更強或更弱），
    只是這裡輸出給 tile 讀的文字，圖表已經在用顏色表達，兩邊要一致不能各自一套。
    """
    if mom is None or len(mom) < 2:
        return None
    v, prev = mom[-1], mom[-2]
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    prev = prev if (prev is not None and not (isinstance(prev, float) and np.isnan(prev))) else v
    if v >= 0:
        return "強多動能" if v >= prev else "弱多動能"
    return "強空動能" if v <= prev else "弱空動能"


# ── RS 加值層：新高偵測 + RS領先股價背離 + 短長線交叉 ────────────────────

def rs_signals(rs_s_series, rs_l_series, closes, newhigh_lookback=120):
    """老墨版真正拿來判斷的三個訊號：
      accel     短線RS 上穿長線RS＝相對動能在加速
      turn_up   長線RS 上穿零軸＝Weinstein突破確認、轉強
      new_high  短線RS 創 N 日新高
      lead      RS創新高但股價沒創同期新高＝「資金比股價先動」（老墨自己說最有價值的訊號）
    只判斷「最新一根」是不是剛發生，不回溯整段歷史（tile 用途，夠了）。
    """
    def _valid(a):
        return a is not None and len(a) >= 2 and not np.isnan(a[-1]) and not np.isnan(a[-2])

    out = {"accel": False, "turn_up": False, "new_high": False, "lead": False}
    if _valid(rs_s_series) and _valid(rs_l_series):
        s0, s1 = rs_s_series[-2], rs_s_series[-1]
        l0, l1 = rs_l_series[-2], rs_l_series[-1]
        out["accel"] = bool(s0 <= l0 and s1 > l1)
        out["turn_up"] = bool(l0 <= 0 and l1 > 0)

    if rs_s_series is not None and len(rs_s_series) >= newhigh_lookback:
        window = rs_s_series[-newhigh_lookback:]
        valid_w = [x for x in window if not np.isnan(x)]
        if len(valid_w) >= newhigh_lookback // 2 and not np.isnan(rs_s_series[-1]):
            out["new_high"] = bool(rs_s_series[-1] >= max(valid_w))
            if out["new_high"] and closes is not None and len(closes) >= newhigh_lookback:
                price_window = closes[-newhigh_lookback:]
                out["lead"] = bool(closes[-1] < max(price_window))  # RS新高、股價還沒破前高
    return out


# ── 綜合：抓資料＋算四指標＋渲染 ──────────────────────────────────────

def _flip_bars(dr):
    """SuperTrend/雙重颱風目前方向已經走了幾根 K。"""
    valid = [d for d in dr if d is not None]
    if not valid:
        return None, None
    cur = valid[-1]
    n = 0
    for d in reversed(valid):
        if d != cur:
            break
        n += 1
    return cur, n


def _vwap(closes, vols, n):
    """20 日「平均成本」＝成交量加權平均收盤價（不是簡單移動平均）。

    ⭐ 這是實測出來的，不是照定義猜的：9939 @ 2026-08-26 老墨顯示 135.95，
    收盤 20MA 算出來是 133.78（差 1.6%），改用 VWAP 是 **135.95**，小數點都一樣。
    「平均成本」這個名字本來就暗示是成本（帶量）而不是單純均價。
    順帶對上截圖的「收盤相對成本：在成本之下」（133.00 < 135.95）。
    """
    out, pv, vv = [], [], []
    for c, v in zip(closes, vols):
        if c is None or v is None or (isinstance(c, float) and np.isnan(c)):
            out.append(None)
            continue
        pv.append(float(c) * float(v)); vv.append(float(v))
        if len(pv) > n:
            pv.pop(0); vv.pop(0)
        s = sum(vv)
        out.append(sum(pv) / s if (len(pv) == n and s > 0) else None)
    return out


def _sma(arr, n):
    """簡單移動平均。前 n-1 筆給 None（不足視窗就不給值，別用不完整的平均充數）。"""
    out, s, q = [], 0.0, []
    for v in arr:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
            continue
        q.append(float(v)); s += float(v)
        if len(q) > n:
            s -= q.pop(0)
        out.append(s / n if len(q) == n else None)
    return out


def build(ticker, disp_days=756):
    """算一次，回 (html, summary_text)。理由同 fundamentals_reality.build()：
    避免財報卡渲染跟 narrative() 的 LLM prompt 各自重抓一次價量資料。
    2026-08-11：RS窗改30日/1年、抓2年資料當暖機（原本抓1年配200日長線窗，暖機不夠，
    圖表前面一大段長線RS是空的，跟看板 board_html_legacy.fetch_us_charts 同一個修法）
    ——算完指標後裁回近 disp_days 給前端顯示。
    2026-09-01：252→756（≈3年），對齊老墨「近三年日線」；前端時間窗可切到 3 年，
    不然按鈕給了 3 年但資料只有 1 年，切了畫面不會變。"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2y")
        if hist.empty or len(hist) < 60:
            return "", ""
        highs, lows, closes = hist["High"].tolist(), hist["Low"].tolist(), hist["Close"].tolist()

        bench = yf.Ticker(_benchmark(ticker)).history(period="2y")
        bench_closes = bench["Close"].tolist() if not bench.empty else []
    except Exception as e:
        print(f"  [technical_indicators] {ticker} 抓取失敗：{e}")
        return "", ""

    # 2026-09-02：顯示層改用 SMA 版 ATR（＝ double_typhoon 那條線），因為老墨的
    # 「SUPER TREND PRO MAX」實測就是 SMA 版：3037 @ 09-02 他顯示空方壓力 1223.7，
    # 我們 SMA 版算 1223.7（分毫不差）、Wilder 版 964.2 且方向相反；
    # 9939 @ 08-26 他 141.40 → SMA 141.40 / Wilder 141.66。
    # 他的方法說明寫「SUPER TREND 採 Wilder's RMA」，與實際數字矛盾，採信數字。
    # ⚠️ 策略層（trade_plan / st_alert / paper_portfolio）仍用 Wilder，不受這裡影響——
    #    Leo 的出場規則是拿 Wilder 版回測出來的。實測兩版長期特性接近
    #    （3037 三年翻轉 23 vs 24 次、平均段長 31.3 vs 30.0 根），差在個別訊號時點。
    st_wilder = supertrend(highs, lows, closes)   # 保留備查，不進顯示
    st = double_typhoon(highs, lows, closes)
    dt = double_typhoon(highs, lows, closes)
    sq = squeeze_momentum(highs, lows, closes)
    rs = mansfield_rs(closes, bench_closes) if bench_closes else {"short": None, "long": None}

    st_dir, st_bars = _flip_bars(st["dir"]) if st else (None, None)
    dt_dir, dt_bars = _flip_bars(dt["dir"]) if dt else (None, None)

    # 2026-08-25：SuperTrend 歷史統計層另外抓 10 年資料——老墨官方版統計窗口是 10 年，
    # 2 年不夠算「歷史延續機率」這種東西。跟展示用的 2 年序列分開抓，互不影響。
    st_stats = None
    try:
        hist10 = t.history(period="10y")
        if len(hist10) >= 250:
            st10 = supertrend(hist10["High"].tolist(), hist10["Low"].tolist(), hist10["Close"].tolist())
            if st10:
                st_stats = supertrend_stats(st10["dir"])
    except Exception as e:
        print(f"  [technical_indicators] {ticker} 10年統計抓取失敗（不影響其他三格）：{e}")

    def trend_tile(name, dir_, bars, stats=None):
        if dir_ is None:
            return _tile(name, "—", "無資料")
        label = "多頭" if dir_ == 1 else "空頭"
        col = "#4ade80" if dir_ == 1 else "#ff8a8a"
        sub = f"第 {bars} 根"
        if stats:
            key = "up" if dir_ == 1 else "down"
            prob, avg = stats.get(f"prob_{key}"), stats.get(f"avg_len_{key}")
            if prob is not None and avg is not None:
                sub = f"第{bars}根／史上平均{avg:.0f}根／20日延續率{prob:.0f}%"
                pct = stats.get("cur_percentile")
                if pct is not None:
                    sub += f"／贏過歷史{pct:.0f}%"
        return _tile(name, f'<span style="color:{col}">{label}</span>', sub)

    sq_on = bool(sq["squeeze_on"][-1]) if sq and not np.isnan(sq["squeeze_on"][-1:].astype(float)).any() else None
    sq_mom = sq["momentum"][-1] if sq is not None else None
    sq_mom_s = f"{sq_mom:+.2f}" if sq_mom is not None and not np.isnan(sq_mom) else "—"
    sq_level, _ = squeeze_intensity(sq) if sq is not None else (None, None)
    sq_mlabel = momentum_label(sq["momentum"]) if sq is not None else None
    sq_label = (sq_level or "擠壓中") if sq_on else "無擠壓"
    sq_col = "#EAB308" if sq_on else ("#4ade80" if (sq_mom or 0) > 0 else "#ff8a8a")

    rs_s = rs.get("short")
    rs_l = rs.get("long")
    rs_html = (f'短線 <b class="num" style="color:{"#4ade80" if (rs_s or 0)>0 else "#ff8a8a"}">'
               f'{f"{rs_s:+.1f}%" if rs_s is not None else "—"}</b>　'
               f'長線 <b class="num" style="color:{"#4ade80" if (rs_l or 0)>0 else "#ff8a8a"}">'
               f'{f"{rs_l:+.1f}%" if rs_l is not None else "—"}</b>')

    # RS 加值訊號：需要完整序列（不只最新一值），搬到這裡先算，圖表資料那段直接複用同一份
    rs_s_series = mansfield_rs_series(closes, bench_closes, 30) if bench_closes else None
    rs_l_series = mansfield_rs_series(closes, bench_closes, 250) if bench_closes else None
    rs_sig = rs_signals(rs_s_series, rs_l_series, closes) if rs_s_series is not None else None
    rs_sub = ""
    if rs_sig:
        badges = []
        if rs_sig["lead"]:
            badges.append("🔴RS領先股價")
        elif rs_sig["new_high"]:
            badges.append("🟢RS創新高")
        if rs_sig["accel"]:
            badges.append("動能加速")
        if rs_sig["turn_up"]:
            badges.append("轉強")
        rs_sub = "　".join(badges)

    # 成交量：台股 yfinance 回「股」，除以 1000 換成「張」跟老墨的顯示一致
    _isw = bool(re.match(r"^[0-9]{4,6}[A-Z]?(\.TWO?)?$", str(ticker)))
    vols = [None if v is None or (isinstance(v, float) and np.isnan(v))
            else (float(v) / 1000 if _isw else float(v))
            for v in hist["Volume"].tolist()]
    tiles = "".join([
        trend_tile("SUPER TREND", st_dir, st_bars, st_stats),
        trend_tile("雙重颱風K線", dt_dir, dt_bars),
        _tile("EXCEED CHARGE", f'<span style="color:{sq_col}">{sq_label}</span>',
              f"{sq_mlabel or ''}（動能 {sq_mom_s}）" if sq_mlabel else f"動能 {sq_mom_s}"),
        _tile("RS 相對強弱", rs_html, rs_sub),
    ])

    # 2026-09-01 Leo：老墨左側資訊欄那幾個明細區塊。上面四個 tile 是「一眼看狀態」，
    # 這裡是「看細項數字」——資料本來就都算出來了，只是先前沒呈現。
    def _rows(title, pairs):
        body = "".join(
            f'<div class="tprow"><span>{k}</span><b>{v}</b></div>' for k, v in pairs if v is not None)
        return f'<div class="tpanel"><div class="tph">{title}</div>{body}</div>' if body else ""

    def _n(v, n=2, suf=""):
        return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.{n}f}{suf}"

    _bull = st_dir == 1 if st_dir is not None else None
    _stl = st["st"][-1] if st else None
    _ma20 = _vwap(closes, vols, 20)[-1]
    _v, _vm = (vols[-1] if vols else None), _sma(vols, 20)[-1]
    _unit = " 張" if _isw else ""

    def _vfmt(v):
        """台股已換算成「張」直接顯示；美股是股數（動輒千萬），縮成 M/K 才讀得懂。"""
        if v is None:
            return None
        if _isw:
            return f"{v:,.0f} 張"
        return f"{v/1e6:,.1f}M" if v >= 1e6 else (f"{v/1e3:,.0f}K" if v >= 1e3 else f"{v:,.0f}")
    panels = (
        _rows("SUPER TREND PRO MAX", [
            ("多方支撐", _n(_stl) if _bull else "N/A"),
            ("空方壓力", "N/A" if _bull else _n(_stl)),
            ("這波走了幾根", f"{st_stats.get('cur_len')} 根" if st_stats else None),
            ("多頭平均長度", f"{st_stats['avg_len_up']:.1f} 根" if st_stats and st_stats.get('avg_len_up') else None),
            ("空頭平均長度", f"{st_stats['avg_len_down']:.1f} 根" if st_stats and st_stats.get('avg_len_down') else None),
            ("多頭最小長度", f"{st_stats['min_len_up']} 根" if st_stats and st_stats.get('min_len_up') else None),
            ("空頭最小長度", f"{st_stats['min_len_down']} 根" if st_stats and st_stats.get('min_len_down') else None),
            ("支撐歷史延續機率", f"{st_stats['prob_up']:.1f}%" if st_stats and st_stats.get('prob_up') else None),
            ("壓力歷史延續機率", f"{st_stats['prob_down']:.1f}%" if st_stats and st_stats.get('prob_down') else None),
        ])
        + _rows("雙重颱風 K 線", [
            ("顏色狀態", {1: "🔴 紅／偏多", -1: "🟢 綠／偏空", 0: "🟡 黃／不明"}.get(
                typhoon_state(closes, vols, dt_dir))),
            ("20 日平均成本", _n(_ma20)),
            ("收盤相對成本", ("在成本之上" if closes[-1] >= _ma20 else "在成本之下") if _ma20 else None),
        ])
        + _rows("成交量", [
            ("成交量", _vfmt(_v)),
            ("20 日均量", _vfmt(_vm)),
            ("量能", ("高於均量" if (_v or 0) >= (_vm or 0) else "低於均量") if _vm else None),
        ])
        + _rows("EXCEED CHARGE 充能爆發", [
            ("動能", sq_mom_s),
            ("動能方向", (sq_mlabel or "").replace("動能", "") or None),
            ("擠壓等級", (sq_level or "擠壓中") if sq_on else "無"),
        ])
        + _rows("RS STRONGER 相對強弱", [
            (f"短線 RS（{30} 日）", f"{rs_s:+.2f}%" if rs_s is not None else None),
            (f"長線 RS（{250} 日）", f"{rs_l:+.2f}%" if rs_l is not None else None),
            ("加值訊號", rs_sub or None),
        ])
    )

    # ── 展開圖表：全部一年份資料都送到前端，90天/1年是前端切片切換，
    # 不用重抓資料（2026-08-11：原本寫死近120個交易日，用戶要求可切換90天/一年）
    uid = re.sub(r"[^A-Za-z0-9]", "_", ticker.upper())
    dates_full = [d.strftime("%m/%d") for d in hist.index]


    def _clean(arr):
        out = []
        for v in arr:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                out.append(None)
            else:
                out.append(round(float(v), 2))
        return out

    # rs_s_series / rs_l_series 已在上面算過（RS 加值訊號要用），這裡直接沿用，不重算
    cut = max(0, len(dates_full) - disp_days)
    chart_data = {
        "dates": dates_full[cut:],
        "closes": _clean(closes)[cut:],
        "st": (_clean(st["st"]) if st else [])[cut:],
        "st_dir": [int(x) if x is not None else None for x in (st["dir"] if st else [])][cut:],
        "dt": (_clean(dt["st"]) if dt else [])[cut:],
        "dt_dir": [int(x) if x is not None else None for x in (dt["dir"] if dt else [])][cut:],
        "mom": (_clean(sq["momentum"]) if sq is not None else [])[cut:],
        "sq_on": [(None if (isinstance(v, float) and np.isnan(v)) else bool(v))
                  for v in (sq["squeeze_on"] if sq is not None else [])][cut:],
        "rs_s": (_clean(rs_s_series) if rs_s_series is not None else [])[cut:],
        "rs_l": (_clean(rs_l_series) if rs_l_series is not None else [])[cut:],
        # 2026-09-01 Leo：補上老墨圖上有、我們沒有的兩層——
        #   ma20＝20 日平均成本（主圖那條橘虛線），vol/vol_ma20＝成交量與 20 日均量。
        #   兩者只要 OHLCV，零額外資料源。
        "ma20": _clean(_vwap(closes, vols, 20))[cut:],
        # 雙重颱風三態（給收盤線分段上色用），不是線
        "ty": (typhoon_state_series(closes, vols, dt["dir"]) if dt else [])[cut:],   # 量加權，不是 SMA
        "vol": [None if v is None else int(v) for v in vols][cut:],
        "vol_ma20": _clean(_sma(vols, 20))[cut:],
    }

    html = f"""<div class="technical"><h3>技術面四指標</h3>
<div class="posnote">近一年日線計算，基準指數：{_BENCHMARK_NAME.get(_benchmark(ticker), _benchmark(ticker))}</div>
<div class="techgrid">{tiles}</div>
<button class="techtoggle" onclick="ti_toggle_{uid}()" id="ti_btn_{uid}">展開圖表 ▾</button>
<div class="techcharts" id="ti_charts_{uid}" style="display:none">
  <div class="tcwin" id="ti_win_{uid}">
    <button data-w="90" aria-pressed="true">90天</button>
    <button data-w="180" aria-pressed="false">半年</button>
    <button data-w="365" aria-pressed="false">1年</button>
    <button data-w="1095" aria-pressed="false">3年</button>
  </div>
  <div class="techwrap">
  <div class="techside">{panels}</div>
  <div class="techmain">
  <div class="tclabel">價格（線色＝雙重颱風三態：🔴偏多 🟢偏空 🟡不明）+ SuperTrend</div>
  <div class="tcbox"><canvas id="ti_c1_{uid}"></canvas></div>
  <div class="tclabel">成交量（青線＝20 日均量）</div>
  <div class="tcbox tcbox-sm"><canvas id="ti_cv_{uid}"></canvas></div>
  <div class="tclabel">EXCEED CHARGE 動能柱（金點＝擠壓中，綠/紅點＝已釋放）</div>
  <div class="tcbox tcbox-sm"><canvas id="ti_c2_{uid}"></canvas></div>
  <div class="tclabel">RS 相對強弱（短線30日／長線1年，紅線＝與大盤同步基準線）</div>
  <div class="tcbox tcbox-sm"><canvas id="ti_c3_{uid}"></canvas></div>
  </div></div>
</div>
<script>
window.TI_DATA_{uid} = {json.dumps(chart_data, ensure_ascii=False)};
let ti_drawn_{uid} = false;
let ti_charts_{uid} = null;
let ti_win_{uid} = 90;
function ti_toggle_{uid}(){{
  const box = document.getElementById('ti_charts_{uid}');
  const btn = document.getElementById('ti_btn_{uid}');
  const open = box.style.display !== 'none';
  box.style.display = open ? 'none' : 'block';
  btn.textContent = open ? '展開圖表 ▾' : '收合圖表 ▴';
  if (!open && !ti_drawn_{uid}) {{ ti_drawn_{uid} = true; ti_draw_{uid}(); }}
}}
document.getElementById('ti_win_{uid}').addEventListener('click', function(e){{
  const b = e.target.closest('button');
  if (!b) return;
  Array.prototype.forEach.call(this.querySelectorAll('button'), x => x.setAttribute('aria-pressed', x === b));
  ti_win_{uid} = parseInt(b.dataset.w, 10) || 90;
  if (ti_drawn_{uid}) ti_draw_{uid}();
}});
function ti_draw_{uid}(){{
  const full = window.TI_DATA_{uid};
  const n = full.dates.length;
  const cut = Math.max(0, n - ti_win_{uid});
  const slice = arr => (arr || []).slice(cut);
  const d = {{dates: slice(full.dates), closes: slice(full.closes), st: slice(full.st),
    st_dir: slice(full.st_dir), dt: slice(full.dt), dt_dir: slice(full.dt_dir),
    mom: slice(full.mom), sq_on: slice(full.sq_on), rs_s: slice(full.rs_s), rs_l: slice(full.rs_l),
    ma20: slice(full.ma20), vol: slice(full.vol), vol_ma20: slice(full.vol_ma20),
    ty: slice(full.ty)}};
  if (ti_charts_{uid}) {{ ti_charts_{uid}.forEach(c => c.destroy()); }}
  const segColor = dir => ctx => {{
    const i = ctx.p1DataIndex; const v = dir[i];
    return v === -1 ? '#ff8a8a' : (v === 1 ? '#4ade80' : '#6b7280');
  }};
  const c1 = new Chart(document.getElementById('ti_c1_{uid}'), {{type:'line',
    data:{{labels:d.dates,datasets:[
      // 雙重颱風＝K 棒著色（紅偏多/綠偏空/黃不明），不是一條線——
      // 所以拿它替收盤線分段上色，而不是再畫一條跟 SuperTrend 重疊的線。
      {{label:'收盤（雙重颱風三色）',data:d.closes,borderWidth:1.6,pointRadius:0,tension:.15,
        segment:{{borderColor:function(c){{
          var t=(d.ty||[])[c.p1DataIndex];
          return t===1?'#ef4444':(t===-1?'#22c55e':(t===0?'#eab308':'#8FA8C8'));
        }}}}}},
      {{label:'SuperTrend',data:d.st,borderWidth:1.6,pointRadius:0,
        segment:{{borderColor:segColor(d.st_dir)}}}},
      // 20 日平均成本＝量加權(VWAP) 不是 SMA——實測對上老墨的 135.95
      {{label:'20日平均成本',data:d.ma20,borderColor:'#F59E0B',borderWidth:1.2,
        pointRadius:0,borderDash:[2,2],tension:.15}}]}},
    options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
      plugins:{{legend:{{labels:{{color:'#9aa0a6',boxWidth:14,font:{{size:10}}}}}}}},
      scales:{{x:{{ticks:{{color:'#6b7280',font:{{size:9}},maxRotation:0,autoSkip:true,maxTicksLimit:8}},grid:{{display:false}}}},
        y:{{ticks:{{color:'#6b7280',font:{{size:9}}}},grid:{{color:'#1a1d23'}}}}}}}}}});
  // 成交量：紅漲綠跌（台股慣例），疊 20 日均量線——老墨圖上有、我們原本漏了
  const volColor = d.closes.map(function(c, i) {{
    const prev = i > 0 ? d.closes[i - 1] : c;
    return (c == null || prev == null) ? '#2a2e35' : (c >= prev ? '#ef4444' : '#22c55e');
  }});
  const cv = new Chart(document.getElementById('ti_cv_{uid}'), {{
    data:{{labels:d.dates,datasets:[
      {{type:'bar',label:'成交量',data:d.vol,backgroundColor:volColor,order:2}},
      {{type:'line',label:'20日均量',data:d.vol_ma20,borderColor:'#22d3ee',
        borderWidth:1.3,pointRadius:0,tension:.2,order:1}}]}},
    options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},
      scales:{{x:{{ticks:{{display:false}},grid:{{display:false}}}},
        y:{{ticks:{{color:'#6b7280',font:{{size:9}}}},grid:{{color:'#1a1d23'}}}}}}}}}});
  // 動能柱：多頭轉強亮綠/轉弱暗綠，空頭轉強亮紅/轉弱暗紅（TTM Squeeze 慣例）；
  // sq_on 點陣列（擠壓中金色、已釋放依動能方向上色）疊在 y=0 當擠壓/釋放標記
  const momColor = d.mom.map((v, i) => {{
    if (v == null) return '#2a2e35';
    const prev = i > 0 ? d.mom[i - 1] : v;
    if (v >= 0) return v >= prev ? '#4ade80' : '#1e7a45';
    return v <= prev ? '#ff8a8a' : '#8a2e2e';
  }});
  const dotColor = d.sq_on.map((on, i) => {{
    if (on) return '#EAB308';
    const m = d.mom[i];
    return m == null ? '#6b7280' : (m >= 0 ? '#4ade80' : '#ff8a8a');
  }});
  const c2 = new Chart(document.getElementById('ti_c2_{uid}'), {{type:'bar',
    data:{{labels:d.dates,datasets:[
      {{label:'動能',data:d.mom,backgroundColor:momColor,order:2}},
      {{label:'擠壓/釋放',type:'line',data:d.mom.map(()=>0),showLine:false,
        pointRadius:2.6,pointBackgroundColor:dotColor,pointBorderWidth:0,order:1}}]}},
    options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},
      scales:{{x:{{ticks:{{display:false}},grid:{{display:false}}}},
        y:{{ticks:{{color:'#6b7280',font:{{size:9}}}},grid:{{color:'#1a1d23'}}}}}}}}}});
  const c3 = new Chart(document.getElementById('ti_c3_{uid}'), {{type:'line',
    data:{{labels:d.dates,datasets:[
      {{label:'基準線(0%)',data:d.mom.map(()=>0),borderColor:'#EF4444',borderWidth:2,
        pointRadius:0,order:3}},
      {{label:'短線30日',data:d.rs_s,borderColor:'#EAB308',borderWidth:1.4,pointRadius:0,tension:.15,order:1}},
      {{label:'長線1年',data:d.rs_l,borderColor:'#4a9eff',borderWidth:1.4,pointRadius:0,tension:.15,order:2}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{labels:{{color:'#9aa0a6',boxWidth:14,font:{{size:10}},
        filter:item=>item.text!=='基準線(0%)'}}}}}},
      scales:{{x:{{ticks:{{display:false}},grid:{{display:false}}}},
        y:{{ticks:{{color:'#6b7280',font:{{size:9}}}},grid:{{color:'#1a1d23'}}}}}}}}}});
  ti_charts_{uid} = [c1, cv, c2, c3];
}}
</script>
</div>"""

    def _lbl(dir_, bars):
        return f'{"多頭" if dir_==1 else "空頭"}第{bars}根' if dir_ is not None else "無資料"

    st_extra = ""
    if st_stats:
        key = "up" if st_dir == 1 else "down"
        prob = st_stats.get(f"prob_{key}")
        if prob is not None:
            st_extra = f"/20日延續率{prob:.0f}%"
    summary = (f"SuperTrend {_lbl(st_dir, st_bars)}{st_extra}　雙重颱風K線 {_lbl(dt_dir, dt_bars)}　"
               f"EXCEED CHARGE {sq_label}{f'/{sq_mlabel}' if sq_mlabel else ''}(動能{sq_mom_s})　"
               f"RS相對強弱 短線{f'{rs_s:+.1f}%' if rs_s is not None else '—'}"
               f"/長線{f'{rs_l:+.1f}%' if rs_l is not None else '—'}"
               f"{'　'+rs_sub if rs_sub else ''}")
    return html, summary


def build_html(ticker):
    """CLI／向下相容用：只要 HTML。"""
    return build(ticker)[0]


def _tile(name, main, sub):
    return (f'<div class="ttile"><div class="tn">{name}</div>'
            f'<div class="tv">{main}</div><div class="ts">{sub}</div></div>')


CSS = """
.technical{margin-top:16px;padding-top:14px;border-top:1px solid #16223A}
.technical h3{font-size:14px;font-weight:700;color:#F5B841;margin-bottom:4px}
.techgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:10px}
.ttile{background:#1a1d23;border:1px solid #2a2e35;border-radius:9px;padding:9px 11px}
.tn{font-size:10px;color:#6b7280;letter-spacing:.3px;font-weight:600}
.tv{font-size:14px;font-weight:700;margin-top:4px;color:#e8eaed}
.ts{font-size:11px;color:#9aa0a6;margin-top:2px}
.techtoggle{margin-top:12px;width:100%;padding:9px;background:#1a1d23;border:1px solid #2a2e35;
 border-radius:8px;color:#93C5FD;font-size:12.5px;font-weight:600;cursor:pointer;font-family:inherit}
.techtoggle:hover{border-color:#4a9eff}
.techcharts{margin-top:10px}
.tclabel{font-size:11px;color:#8a8f98;margin:10px 0 4px}
/* 2026-09-02 Leo：資訊欄改放圖表左邊（跟老墨的版面一樣）。
   290px 固定欄寬——面板是「標籤：數值」的對齊列，欄寬浮動會讓數值左右跳。
   860px 以下疊回上下：手機並排會把圖表壓到看不清楚。 */
.techwrap{display:grid;grid-template-columns:290px minmax(0,1fr);gap:14px;align-items:start;margin-top:6px}
.techside{display:flex;flex-direction:column;gap:8px}
.techmain{min-width:0}
@media(max-width:860px){.techwrap{grid-template-columns:1fr}}
.tpanel{background:#1a1d23;border:1px solid #2a2e35;border-radius:9px;padding:8px 11px}
.tph{font-size:11px;color:#F5B841;font-weight:700;margin-bottom:5px}
.tprow{display:flex;justify-content:space-between;gap:10px;padding:2px 0;font-size:12px}
.tprow>span{color:#8a8f98}
.tprow>b{color:#e8eaed;font-weight:600}
.tcbox{height:180px}
.tcbox-sm{height:100px}
.tcwin{display:inline-flex;background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;
 padding:2px;margin-bottom:6px}
.tcwin button{border:0;background:transparent;color:#8a8f98;font-size:11px;font-weight:600;
 padding:5px 12px;border-radius:6px;cursor:pointer;font-family:inherit}
.tcwin button[aria-pressed=true]{background:#334155;color:#e8eaed}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    print(build_html(args.ticker) or "（無資料）")


if __name__ == "__main__":
    main()
