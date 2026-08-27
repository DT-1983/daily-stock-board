# -*- coding: utf-8 -*-
"""P3 預估值 base-rate 檢查（2026-08-27）——「這個預估要求什麼，歷史上發生過嗎」。

原型是老墨戰情室的估值前提檢查（見 memory/mofi_warroom_structure.md）：
    「5234：2026 EPS 9.6元需8-12月月營收平均5.04億，而2010年以來199個月最高只有
      4.53億 → 這估值假設等於要求連續五個月創歷史新高再高11%」

重點不是「股價有沒有跌破某條線」（那是 P1 thesis_check 做的），而是把**分析師的
預估翻譯成一句可證偽的要求**，再拿這家公司自己的歷史去對。兩個獨立檢查：

  A. 隱含要求：本年度營收共識，扣掉已實現的部分，剩下的月/季要跑多快？
     那個**成長率**在這家公司自己的歷史裡是什麼位置？
       台股 → FinMind 月營收（2330 有 260 個月）→ 剩餘月份的同期年增率
       美股 → 沒有月營收 → 剩餘季度的季增率（quarterly_income_stmt 只給 5 季，n 會標出來）
     兩個設計要點，都是實測踩到才發現的：
       ① **先扣掉已實現的部分**，否則會把已發生的事講成未來的要求
          （implied_requirement_us 的 MU 實例：扣不扣差了一個量級的結論）
       ② **比成長率不比絕對金額**，否則會被公司自身的成長帶歪
          （implied_requirement_tw 的 2330 實例：中位數是十幾年前的台積電）
  B. 預估者準頭：`get_earnings_dates` 給 24 季的 EPS 預估 vs 實際（美台都有）。
     系統性低估的公司，一個「很兇」的預估沒那麼可疑；系統性高估的公司則相反。
     B 是 A 的解讀脈絡，不是獨立訊號。

⚠️ **只量測不下行動指令**（同 market_thermometer）：分級只描述「這個要求在歷史上多罕見」，
不說「所以該賣」。要幾個百分位算危險、罕見到什麼程度該減碼，我們沒有回測依據，
等 Leo 拍板（Leo 硬規則：不自行發明投資判定門檻）。

零 AI 呼叫，純算術。跑一次約 1-2 秒/檔（yfinance + FinMind）。

用法:
    python base_rate.py                 # 全持股 + 台股觀察名單
    python base_rate.py --tickers NVDA,2330.TW
"""
import os
import re
import sys
import json
import time
import argparse
import datetime as dt
import warnings

warnings.filterwarnings("ignore")
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_PATH = "state/base_rate.json"
TW_RE = re.compile(r"^(\d{4,6}[A-Z]?)\.(TWO?)$", re.I)

MIN_ANALYSTS = 3        # 少於此不算「共識」，不分級（5287.TWO 只有1位）
TIER = {"unprecedented": "🚫", "rare": "⚠️", "normal": "✅",
        "low_coverage": "⚪", "unknown": "⚪"}
# 分級的「顯著幅度」係數——見 _tier() 說明。這是**版面凸顯用的分界，不是投資判定門檻**
# （要罕見到什麼程度該減碼，我們沒有回測依據）。Leo 想調鬆緊改這個數字即可。
EXCESS_K = 0.5
# 升 🚫 的絕對下限（百分點）。沒有這道下限時，歷史分布很窄的股票會被誤升級：
# 實測 ON 的季增歷史最高 +6.0%、中位 +5.6%（差 0.4pp），K×spread 趨近 0，
# 於是只超出 +1.4pp 就被判 🚫，卻排在超出 +9.8pp 的 CLS 同一級。
# 3pp 這個值的理由是資料雜訊量級（財報重編、四捨五入、會計期間邊界）而非投資判斷。
EXCESS_MIN_PP = 0.03


def _tier(need, hist, n_analysts):
    """用**這檔自己的歷史分布**分級，不用全市場通用門檻。

    為什麼不用百分位：實測 96 檔時美股每一檔觸發的都是「第100百分位、n=5」——
    單季樣本只有 5 季，「超過最高」就必然是 100%，百分位變成二元值毫無鑑別度。
    而同樣「100百分位」底下，CI 只超出 +1.8%（正常季節性）、SPCX 超出 +105%
    （真的異常），兩者被歸成同一級 → 32% 觸發率，flag 失去意義。

    為什麼不用「超出 X%」的通用門檻：各股波動天差地遠。MU 要求 +22% QoQ 看似很兇，
    但它歷史 QoQ 中位數就有 +48%，對它是常態；TFC 要求 +4.4% 看似溫和，卻已超過
    它歷史最高 +4.0%。同一個 X% 對兩者意義完全不同。

    所以改成：拿「要求值」對照這檔自己的歷史最高與中位數。
        ✅ 沒超過歷史最高           → 過去做得到的事
        ⚠️ 超過歷史最高            → 要創紀錄
        🚫 超過最高再加 K×(最高−中位)，且至少超出 EXCESS_MIN_PP
           → 創紀錄的幅度本身也超出這檔的正常變異
    K 是版面分界不是投資門檻（見 EXCESS_K）。實測 K=0.5 的結果：
      AAOI +81%(自身最高+27%)🚫、NVDA +29%(+22%)🚫、2330 +50%(+44%)⚠️、
      TFC +4.4%(+4.0%)⚠️、MU +22%(最高+75%,中位+48%)✅、CI +2.9%(+4.5%)✅
    """
    if n_analysts < MIN_ANALYSTS:
        return "unknown" if not hist else "low_coverage"
    if not hist or len(hist) < 3:
        return "unknown"
    mx, mn = max(hist), min(hist)
    # 歷史分布完全沒有變異 → 沒有東西可以校準，任何要求都會被判成破紀錄。
    # 實測 AUR：連續四季營收都恰好 $1,000,000（Yahoo 對前營收期公司的四捨五入佔位值），
    # 於是季增歷史全是 0.0%，算出「要求季增 +367%」→ 技術上沒錯但毫無意義。
    # 這種資料要誠實回「算不出來」，不能給一個看起來很篤定的 🚫。
    if mx == mn:
        return "unknown"
    med = sorted(hist)[len(hist) // 2]
    if need <= mx:
        return "normal"
    big = need > mx + EXCESS_K * max(mx - med, 0) and need - mx >= EXCESS_MIN_PP
    return "unprecedented" if big else "rare"


def _tw_id(tk):
    m = TW_RE.match(str(tk) or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- 檢查 B：預估者準頭
def analyst_track_record(tk, quarters=24):
    """分析師對這檔的歷史準頭。回 None 表示沒有可用資料（不是「準」）。"""
    import yfinance as yf
    try:
        e = yf.Ticker(tk).get_earnings_dates(limit=quarters)
    except Exception:
        return None
    if e is None or e.empty or "Surprise(%)" not in e.columns:
        return None
    e = e.dropna(subset=["Reported EPS", "Surprise(%)"])
    s = [float(x) for x in e["Surprise(%)"].tolist()]
    if len(s) < 8:                      # 樣本太少講不出偏誤
        return None
    beats = sum(1 for x in s if x > 0)
    med = sorted(s)[len(s) // 2]
    # 「偏保守/偏樂觀」講的是分析師，不是公司好壞
    if beats >= len(s) * 0.75:
        bias = "共識偏保守"
    elif beats <= len(s) * 0.25:
        bias = "共識偏樂觀"
    else:
        bias = "共識大致中性"
    return {"n": len(s), "beats": beats, "median_surprise": round(med, 1), "bias": bias}


# ---------------------------------------------------------------- 檢查 A：隱含要求
def _fy_revenue_consensus(tk):
    """本年度營收共識（yfinance revenue_estimate 的 0y）。回 (值, 分析師數)。"""
    import yfinance as yf
    try:
        r = yf.Ticker(tk).revenue_estimate
        if r is None or r.empty or "0y" not in r.index:
            return None, 0
        v = float(r.loc["0y", "avg"] or 0)
        n = int(r.loc["0y", "numberOfAnalysts"] or 0)
        return (v, n) if v > 0 and n > 0 else (None, 0)
    except Exception:
        return None, 0


def _pctl(hist, v):
    """v 在 hist 裡的百分位（0~1）。"""
    return sum(1 for x in hist if x <= v) / len(hist) if hist else None


def implied_requirement_tw(tk):
    """老墨原型：本年度營收共識 → 剩餘月份要求的月均營收 vs 月營收歷史分布。"""
    sid = _tw_id(tk)
    if not sid:
        return None
    import requests
    tok = os.environ.get("FINMIND_TOKEN", "")
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanStockMonthRevenue", "data_id": sid,
                                 "start_date": "2005-01-01", "token": tok}, timeout=30)
        rows = r.json().get("data") or []
    except Exception:
        return None
    if len(rows) < 24:
        return None
    fy, n_an = _fy_revenue_consensus(tk)
    if not fy:
        return None

    year = max(int(x["revenue_year"]) for x in rows)
    ytd_rows = [x for x in rows if int(x["revenue_year"]) == year]
    ytd = sum(float(x["revenue"]) for x in ytd_rows)
    done = len(ytd_rows)
    left = 12 - done
    if left <= 0:
        return None
    need_avg = (fy - ytd) / left
    hist = [float(x["revenue"]) for x in rows]
    # 同期月份（控制季節性）——剩下要跑的就是這幾個月，拿往年同月來比才公平
    left_months = set(range(done + 1, 13))
    # 往年「同樣這幾個月」的平均——要求的是一個平均值，拿歷年同期平均來比才是同一種東西
    by_year = {}
    for x in rows:
        y, m = int(x["revenue_year"]), int(x["revenue_month"])
        if y < year and m in left_months:
            by_year.setdefault(y, []).append(float(x["revenue"]))
    same = [sum(v) / len(v) for v in by_year.values() if len(v) == len(left_months)]

    # ⚠️ 比的是**同期年增率**不是絕對金額。拿絕對金額比會被公司自身的成長帶歪：
    # 2330 同期歷年最高 3,425億、中位才 733億——中位數是十幾年前的台積電，
    # 公司規模長了五倍，「超越歷史最佳」對任何成長股都幾乎必然成立，等於沒篩。
    # 改比年增率後，問的才是「這個加速度這家公司做過嗎」（與美股 QoQ 那條同一個邏輯）。
    yrs = sorted(by_year)
    if len(yrs) < 4:
        return None
    avg = {y: sum(by_year[y]) / len(by_year[y]) for y in yrs if len(by_year[y]) == len(left_months)}
    yrs = sorted(avg)
    hist_yoy = [avg[yrs[i]] / avg[yrs[i - 1]] - 1 for i in range(1, len(yrs))
                if avg[yrs[i - 1]]]
    prev = avg.get(year - 1)
    if not prev or len(hist_yoy) < 3:
        return None
    need_yoy = need_avg / prev - 1
    tier = _tier(need_yoy, hist_yoy, n_an)
    return {"kind": "tw_monthly", "tier": tier, "fy": fy, "year": year, "analysts": n_an,
            "ytd": ytd, "months_done": done, "months_left": left, "need_avg": need_avg,
            "hist_n": len(hist), "prev_avg": prev, "need_yoy": need_yoy,
            "yoy_max": max(hist_yoy), "yoy_med": sorted(hist_yoy)[len(hist_yoy) // 2],
            "yoy_n": len(hist_yoy), "excess": need_yoy - max(hist_yoy)}


def implied_requirement_us(tk):
    """美股季度版：本年度營收共識扣掉已公布的季，剩下的季要跑多快 vs 單季歷史。

    ⚠️ 這裡一定要扣掉已實現的部分，否則會把「已經發生的事」講成「未來的要求」。
    實測 MU：FY26 共識 129.7B vs FY25 實際 37.4B ＝ +247%，聽起來像天方夜譚——
    但 FY26 已經公布 3 季（13.6+23.9+41.5＝79.0B），真正還沒發生的只有最後一季
    50.7B，對照上一季 41.5B 是 +22%。**同一組數字，扣不扣已實現差了一個量級的結論。**
    老墨方法的精髓就在這個扣除（他的台股月營收版本也是先扣 YTD）。

    會計年度用 income_stmt 最新一欄的日期界定：日期比它新的季就屬於本年度。
    單季歷史 yfinance 只給 5 季，所以文案講「近 N 季最高」不講「史上最高」。
    """
    import yfinance as yf
    fy, n_an = _fy_revenue_consensus(tk)
    if not fy:
        return None
    try:
        t = yf.Ticker(tk)
        a, q = t.income_stmt, t.quarterly_income_stmt
        if a is None or a.empty or q is None or q.empty:
            return None
        if "Total Revenue" not in a.index or "Total Revenue" not in q.index:
            return None
        fy_end = max(a.columns)                       # 上一個已結束的會計年度結束日
        qs = [(c, float(q.loc["Total Revenue", c])) for c in q.columns
              if q.loc["Total Revenue", c] == q.loc["Total Revenue", c]]
        qs = [(c, v) for c, v in qs if v]
    except Exception:
        return None
    if len(qs) < 3:
        return None
    ytd_q = [(c, v) for c, v in qs if c > fy_end]
    done = len(ytd_q)
    left = 4 - done
    # done==0 是**合法**情況不是異常：會計年度剛結束、新年度還沒公布任何一季
    # （MSFT/COHR/LITE 都是 6/30 結算，實測就落在這裡）。整年都在前面，
    # 需求＝共識÷4，照算。原本把它擋掉會讓三檔大型持股靜默消失。
    if left <= 0:
        return None
    ytd = sum(v for _, v in ytd_q)
    need_avg = (fy - ytd) / left
    hist = [v for _, v in qs]
    last_q = qs[0][1]                                 # 最近一季＝要求成長的起算基準
    # 比的是「要求的季增率」而不是絕對金額——絕對金額對成長股永遠是新高（沒鑑別度），
    # 季增率才問得出「這個加速度這家公司做過嗎」。
    qoq = [hist[i] / hist[i + 1] - 1 for i in range(len(hist) - 1) if hist[i + 1]]
    need_qoq = need_avg / last_q - 1 if last_q else None
    if need_qoq is None or len(qoq) < 3:
        return None
    tier = _tier(need_qoq, qoq, n_an)
    return {"kind": "us_quarterly", "tier": tier, "fy": fy, "analysts": n_an,
            "ytd": ytd, "q_done": done, "q_left": left, "need_avg": need_avg,
            "hist_n": len(hist), "last_q": last_q, "need_qoq": need_qoq,
            "qoq_max": max(qoq), "qoq_med": sorted(qoq)[len(qoq) // 2],
            "qoq_n": len(qoq), "excess": need_qoq - max(qoq)}


def pe_snapshot(tk):
    """本益比快照＋「股價押注了多少還沒發生的獲利成長」。

    押注幅度 = 現在本益比 ÷ 預估本益比 − 1。預估本益比的分母是分析師預估獲利，
    所以這個數字就是「市場把多少未實現的獲利算進股價了」。

    ⚠️ 預估本益比**單獨看會騙人**：獲利在景氣循環高點時最高，於是預估本益比在
    風險最大的時候看起來最便宜——而這份清單上幾乎全是半導體。洪瑞泰的「常利」
    正是為了修這個毛病而存在。所以報告一定要同時列俗貴價（常利基準）：
    兩者的失效方向相反，俗貴價會把獲利跳級的公司一律說成「貴」，
    預估本益比會在循環高點說「便宜」。缺一個都會被騙。
    """
    import yfinance as yf
    try:
        i = yf.Ticker(tk).info
    except Exception:
        return None
    fwd, ttm = i.get("forwardPE"), i.get("trailingPE")
    ps = i.get("priceToSalesTrailing12Months")
    out = {"forward_pe": fwd if (fwd and fwd > 0) else None,
           "trailing_pe": ttm if (ttm and ttm > 0) else None,
           "ps": ps, "price": i.get("currentPrice")}
    if out["forward_pe"] and out["trailing_pe"]:
        out["implied_growth"] = out["trailing_pe"] / out["forward_pe"] - 1
    return out


def check(tk):
    req = implied_requirement_tw(tk) if _tw_id(tk) else implied_requirement_us(tk)
    return {"ticker": tk, "requirement": req, "track_record": analyst_track_record(tk),
            "pe": pe_snapshot(tk)}


# ---------------------------------------------------------------- 輸出
def _fmt_tw(r):
    u = 1e8                                      # 億元
    s = (f"{r['year']} 營收共識 {r['fy']/u:,.0f}億（{r['analysts']}位）"
         f"→ 剩 {r['months_left']} 個月要月均 **{r['need_avg']/u:,.1f}億**"
         f"（去年同期 {r['prev_avg']/u:,.1f}億，年增 **{r['need_yoy']*100:+.0f}%**）")
    s += (f"；這檔同期年增歷史最高 {r['yoy_max']*100:+.0f}%、中位 {r['yoy_med']*100:+.0f}%"
          f"（n={r['yoy_n']}）")
    if r["excess"] > 0:
        s += f" → 要**超越自身最佳 {r['excess']*100:+.1f}個百分點**"
    return s


def _fmt_us(r):
    b = 1e9
    s = (f"本年營收共識 {r['fy']/b:,.1f}B（{r['analysts']}位）"
         f"→ 已公布 {r['q_done']} 季 {r['ytd']/b:,.1f}B，"
         f"剩 {r['q_left']} 季要季均 {r['need_avg']/b:,.1f}B "
         f"＝ 季增 **{r['need_qoq']*100:+.0f}%**")
    s += (f"；這檔歷史季增最高 {r['qoq_max']*100:+.0f}%、中位 {r['qoq_med']*100:+.0f}%"
          f"（n={r['qoq_n']}）")
    if r["excess"] > 0:
        s += f" → 要**超越自身最佳 {r["excess"]*100:+.1f}個百分點**"
    return s


def line(c):
    r = c.get("requirement")
    if not r:
        return None
    body = _fmt_tw(r) if r["kind"] == "tw_monthly" else _fmt_us(r)
    out = f"{TIER[r['tier']]} **{c['ticker']}**｜{body}"
    t = c.get("track_record")
    if t:
        out += (f"\n-# 分析師準頭：{t['n']}季中 {t['beats']}季低估、"
                f"中位數 {t['median_surprise']:+.1f}% → {t['bias']}")
    return out


def _held_set():
    try:
        from trade_plan import load_holdings
        active, _ = load_holdings()
        return {h["ticker"] for h in active if isinstance(h, dict) and h.get("ticker")}
    except Exception:
        return set()


def summary_lines(max_items=8, scope=None, fresh_only=True):
    """給報告用：只列 🚫/⚠️（正常的和低覆蓋的不佔版面）。

    scope=None 全部／"private" 只列持股／"public" 只列非持股——沿用日報的
    公私分流（#每日戰情 是家人看得到的頻道，不透露持股）。
    fresh_only：只在產出當天顯示。這份檢查是週跑的（分析師共識與月營收都是
    月/季頻率），天天貼同一份等於洗版；只在跑的那天出現，一週剛好一次。"""
    d = _load()
    if not d:
        return []
    if fresh_only and d.get("date") != dt.date.today().isoformat():
        return []
    held = _held_set() if scope else set()
    hot = []
    for c in d.get("checks", []):
        if (c.get("requirement") or {}).get("tier") not in ("unprecedented", "rare"):
            continue
        if scope == "private" and c["ticker"] not in held:
            continue
        if scope == "public" and c["ticker"] in held:
            continue
        hot.append(c)
    # 同一級之內按「超越幅度」排——版面有限時先讓最誇張的被看到
    hot.sort(key=lambda c: (0 if c["requirement"]["tier"] == "unprecedented" else 1,
                            -(c["requirement"].get("excess") or 0)))
    out = [x for x in (line(c) for c in hot[:max_items]) if x]
    if len(hot) > max_items:
        out.append(f"-# …還有 {len(hot)-max_items} 檔預估偏高，見完整清單")
    return out


def _load():
    if not os.path.exists(OUT_PATH):
        return None
    try:
        return json.load(open(OUT_PATH, encoding="utf-8"))
    except Exception:
        return None


# ETF／指數型商品沒有「公司營收共識」這回事，跑了只會變成 unknown 雜訊。
SKIP = {"TLT", "XYLG", "ARKG", "ARKK", "ARKQ", "ARKX", "CVSA", "SPCX"}


def default_tickers():
    ts = []
    try:
        from trade_plan import load_holdings
        active, _ = load_holdings()
        ts += [h["ticker"] for h in active if isinstance(h, dict) and h.get("ticker")]
    except Exception:
        pass
    try:
        # 巴菲特清單**全部**納入，不只台股。納入標準是「在評估中的標的」而不是
        # 「補足另一個市場」——清單上的美股是已到俗價的非持股，正是投資長 P0 在看的
        # 進場候選，也最需要知道「分析師的預估是不是已經很兇了」。
        # （原本寫 `if _tw_id(k)`，漏掉 BMY/PGR/ACN/TROW/VZ 五檔。）
        w = json.load(open("buffett_watch.json", encoding="utf-8"))
        ts += list(w)
    except Exception:
        pass
    try:
        # 2026-08-28 Leo：補七鏈守備清單（原本 93 檔漏掉 94 檔，2317/2330/2454 這些
        # 研究員每天在盯的成分股都不在範圍內）。同樣的納入標準：在評估中的標的。
        from paper_portfolio import chain_holdings
        ts += [t for v in chain_holdings().values() for t in v]
    except Exception:
        pass
    return sorted(set(ts) - SKIP)


def run(tickers=None, write=True):
    """write=False：只印不寫檔。

    ⚠️ `--tickers` 的診斷跑**一律不寫檔**。原本會寫，結果 2026-08-27 用
    `--tickers BMY,PGR,...` 查五檔時，把跑了 8 分鐘的 88 檔結果覆寫成 5 檔
    （同一個錯誤模式：前幾天用 `--markets us` 診斷洗掉了 buffett_watch.json）。
    診斷用的子集合永遠不該蓋掉正式產出。"""
    tickers = tickers or default_tickers()
    checks, tiers = [], {}
    for i, tk in enumerate(tickers, 1):
        try:
            c = check(tk)
        except Exception as e:
            print(f"  {tk} 失敗：{str(e)[:60]}")
            continue
        checks.append(c)
        t = (c.get("requirement") or {}).get("tier", "unknown")
        tiers[t] = tiers.get(t, 0) + 1
        if i % 20 == 0:
            print(f"  已檢查 {i}/{len(tickers)}…")
        time.sleep(0.2)
    if write:
        # 記錄「這次跟上次比，燈號有沒有變」——週更只推有變的，不然同一份清單每週貼一次，
        # Leo 第二週就不會看了（2026-08-28 Leo 指定，沿用系統裡既有的「變化才推」模式）。
        prev = _load() or {}
        pt = {c["ticker"]: (c.get("requirement") or {}).get("tier")
              for c in prev.get("checks", [])}
        for c in checks:
            t = (c.get("requirement") or {}).get("tier")
            was = pt.get(c["ticker"])
            c["prev_tier"] = was
            # 第一次看到這檔（was is None 且不在舊清單裡）不算「變化」，否則擴範圍那天
            # 會一次噴出上百檔「新出現」。只有真的從一級跳到另一級才算。
            c["changed"] = bool(was and t and was != t)
        os.makedirs("state", exist_ok=True)
        json.dump({"date": dt.date.today().isoformat(),
                   "prev_date": prev.get("date"), "checks": checks},
                  open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        nch = sum(1 for c in checks if c.get("changed"))
        print(f"　燈號有變動的：{nch} 檔" + (f"（對比 {prev.get('date')}）" if prev.get("date") else ""))
    else:
        print("（診斷模式，未寫入 state/base_rate.json）")
    # 一定要印分布——「全部正常」有可能是資料沒抓到而不是真的正常
    print(f"✅ 檢查 {len(checks)}/{len(tickers)} 檔｜"
          + "、".join(f"{TIER.get(k,k)}{k} {v}" for k, v in sorted(tiers.items())))
    # 算不出來的要列名字——「沒有警訊」和「根本沒算到」看起來一樣，那就是靜默失效
    nores = [c["ticker"] for c in checks if not c.get("requirement")]
    if nores:
        print(f"⚪ 無分析師營收共識或歷史不足（{len(nores)}）：{', '.join(nores)}")
    for l in summary_lines():
        print("\n" + l)
    return checks


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="", help="逗號分隔；預設全持股+台股觀察名單")
    ap.add_argument("--if-stale-days", type=int, default=0,
                    help="既有結果比這個天數新就跳過（給排程自我節流用）")
    ap.add_argument("--weekday", type=int, default=None,
                    help="釘在星期幾跑（0=一…4=五）。超過 if-stale-days 仍會補跑")
    a = ap.parse_args()
    # 自我節流：這份檢查的輸入（分析師共識、台股月營收）都是月頻，天天跑沒有新資訊，
    # 而且 70 檔 × 4 個 yfinance 呼叫會逼近限流。放在平日排程裡但一週只真的跑一次。
    # ⚠️ 為什麼不掛在週六的 buffett_scan_weekly：BuffettScanWeekly 只在週六跑，
    # ResearcherStockSync（daily_warroom 在裡面）只在週一至五跑——掛週六的話
    # summary_lines 的 fresh_only 會讓這一段**永遠不出現在日報**。掛平日＋自我節流
    # 才會真的被看到。（這正是記憶庫裡「上線但從沒執行」那個靜默失效模式。）
    if a.if_stale_days:
        d = _load()
        if d and d.get("date"):
            age = (dt.date.today() - dt.date.fromisoformat(d["date"])).days
            # 釘星期幾：不然「滿7天就跑」會漂移——哪個週一電腦沒開，之後就永遠變成週二。
            # 但超過門檻仍要補跑，否則漏一次就要等下週（漏跑比晚跑嚴重）。
            if a.weekday is not None and dt.date.today().weekday() != a.weekday and age < a.if_stale_days + 3:
                print(f"今天不是排定的星期{'一二三四五六日'[a.weekday]}，跳過（上次 {d['date']}）")
                sys.exit(0)
            if age < a.if_stale_days:
                print(f"上次檢查 {d['date']}（{age} 天前），未達 {a.if_stale_days} 天門檻，跳過")
                sys.exit(0)
    for ln in open(".env", encoding="utf-8") if os.path.exists(".env") else []:
        if ln.startswith("FINMIND_TOKEN"):
            os.environ.setdefault("FINMIND_TOKEN", ln.split("=", 1)[1].strip())
    sel = [t.strip() for t in a.tickers.split(",") if t.strip()]
    run(sel or None, write=not sel)


# ---------------------------------------------------------------- 卡片（2026-08-28）
# 一檔三行：俗貴價（價格）／預估本益比（價格，配分析師預估成長當註腳）／預估門檻（預估）。
#
# ⚠️ **只有「預估門檻」有燈號**，另外兩行只給數字。原因：
#  ① 我一度把「現PE ÷ 預估PE」當成「市場押注」並想給燈號——那是錯的。
#     現PE÷預估PE =(P/現EPS)/(P/預估EPS)= 預估EPS/現EPS，**股價完全被約掉**，
#     實測 NVDA 兩種算法到小數點都一樣(+122.8%)。它只是分析師的 EPS 成長預估，
#     不是市場的判斷，也不構成獨立的第二軸。已改標為「分析師預估獲利成長」。
#  ② 想給股價燈號就得有校準基準。「本益比 vs 自身歷史」做不到——季EPS只有5季，
#     疊TTM只剩2個點，TSM還算出 0.9 倍（ADR 的 EPS 與股價單位對不上）。
#  ③ 剩下的兩個選項都不能用：絕對門檻（「預估PE>30算貴」）是我自己發明的判定門檻；
#     用這 186 檔的相對百分位則**保證永遠有 40% 是紅燈**——組合再便宜也會有人被標紅，
#     燈號會退化成排名而不是警訊，比沒有燈號更糟（它看起來像在示警）。
#
# 「預估門檻」的燈號則站得住：它是拿要求值對照**這檔自己的歷史分布**校準出來的，
# 沒有用到任何我發明的跨股門檻。


def _load_json_safe(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def _val_line(tk):
    """俗貴價。持股讀 valuation_state（每日），非持股讀 buffett_watch（週六）。"""
    v = (_load_json_safe("state/valuation_state.json") or {}).get(tk)
    if v:
        return (f"{v.get('icon','⚪')} 俗貴價（用正常化獲利算）：現價 ${v['price']:,.2f}"
                f"／俗價 ${v['cheap']:,.2f}／貴價 ${v['expensive']:,.2f}")
    w = (_load_json_safe("buffett_watch.json") or {}).get(tk)
    if w and w.get("cheap"):
        return (f"⚪ 俗貴價（用正常化獲利算）：俗價 ${w['cheap']:,.2f}／貴價 ${w['expensive']:,.2f}"
                f"（巴菲特清單，週六更新）")
    return None


def card(c):
    """一檔的卡片。回 list[str]。"""
    tk, r = c["ticker"], c.get("requirement")
    pe, tr = c.get("pe") or {}, c.get("track_record") or {}
    out = [f"**{tk}**"]
    vl = _val_line(tk)
    if vl:
        out.append(vl)

    if pe.get("forward_pe"):
        t = f"　現在本益比 {pe['trailing_pe']:,.0f} 倍" if pe.get("trailing_pe") else ""
        g = (f"　分析師預估獲利成長 {pe['implied_growth']*100:+,.0f}%"
             if pe.get("implied_growth") is not None else "")
        out.append(f"　預估本益比 {pe['forward_pe']:,.0f} 倍{t}{g}")
    elif pe.get("ps"):
        out.append(f"　股價營收比 {pe['ps']:,.1f} 倍（虧損中，沒有本益比）")

    if r:
        need = r.get("need_qoq") if r["kind"] == "us_quarterly" else r.get("need_yoy")
        mx = r.get("qoq_max") if r["kind"] == "us_quarterly" else r.get("yoy_max")
        unit = "季" if r["kind"] == "us_quarterly" else "年"
        if need is not None and mx is not None:
            out.append(f"{TIER[r['tier']]} 預估門檻：分析師要求每{unit}成長 {need*100:+,.0f}%，"
                       f"它史上最好的一{unit}是 {mx*100:+,.0f}%")
    if tr:
        # 措辭要看門檻高不高——✅ 的檔案沒有高門檻，不能寫「這個高門檻是它自己打出來的」
        hot = (r or {}).get("tier") in ("unprecedented", "rare")
        if tr["beats"] >= tr["n"] * 0.75:
            w = "這個高門檻是它自己打出來的" if hot else "分析師對它一向偏保守"
        elif tr["beats"] <= tr["n"] * 0.25:
            w = "**而且分析師對它一向偏樂觀，這個門檻要打折看**" if hot else "分析師對它一向偏樂觀"
        else:
            w = "分析師準頭中性"
        out.append(f"-# 過去 {tr['n']} 季分析師有 {tr['beats']} 季猜太低，{w}")
    return out
