"""財報懶人包 Infographic（CLI）→ HTML

用法：
    python earnings_infographic.py TSLA
    python earnings_infographic.py TSLA -o docs/earnings_TSLA.html
    python earnings_infographic.py 2330.TW --no-llm      # 只出數據不跑敘事

設計原則（重要）：
  · **所有財務數字一律來自 yfinance 真實財報**，不讓 LLM 生成任何數字。
    這種「機構級」版面看起來很有說服力，數字錯了會比純文字更誤導。
  · LLM 只負責「敘事層」（亮點/風險/投資邏輯），且 prompt 明確禁止編造數字，
    只能引用下方餵給它的真實數據。
  · **本頁並列兩套獨立策略，互不覆蓋**（用戶明確要求，2026-08-03）：
      ① 洪瑞泰選股法：三大關卡＋俗貴價＋變壞判定，沿用 buffett_screener 既有實作，
         **不自創指標**（曾自創成長性/PEG/Beta 星等，那不是他的東西，已移除）。
         動這塊前先讀 memory/hongruitai_method.md。
      ② 原 prompt 的分析師共識：BUY/SELL 標章＋Forward P/E/PEG/FCF Yield/EV-Sales。
    兩者可能給相反結論，那是預期行為（不同策略），**不要再自作主張讓其中一套覆蓋另一套**。
"""
import os
import io
import re
import sys
import json
import argparse
from datetime import datetime, timedelta, date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yfinance as yf

import chain_positioning as CP  # 2026-08-06：產業鏈定位區塊（BEST MATCH 拆解功能之一）
import fundamentals_reality as FR  # 2026-08-06：財報與營收實況（BEST MATCH 拆解功能之二）
import technical_indicators as TI  # 2026-08-06：技術面四指標（BEST MATCH 拆解功能之四）
import earnings_call as EC  # 2026-08-09：管理層口頭重點（法說會逐字稿，補財報三表沒有的公司自訂KPI）

# 2026-09-05 資料夾整理：路徑一律走 obis_paths，不再各自寫死。
from obis_paths import EARNINGS as OBIS
# 台股中文名的第二來源（board_html_legacy.TW_NAME 只有七鏈守備清單的 62 檔，
# Leo 的持股台泥/正新/台灣大/中華電不在裡面，卡片標題會退成 yfinance 的英文長名）
HOLDINGS_JSON = r"C:\Users\Mophy\AI\assets-dashboard\data\holdings.json"


# ────────────────────────────── 資料層 ──────────────────────────────

def _safe(df, row, col):
    try:
        v = df.loc[row, col]
        return float(v) if v == v else None      # NaN → None
    except Exception:
        return None


def _tw_core(code, n=8):
    """台股核心 KPI 卡改用 FinMind，只在它比 yfinance 新的時候才覆蓋。

    2026-08-10 教訓：兩個資料源誰新誰舊沒有固定答案——3037/2313/6134/2308
    這批 yfinance 卡在 Q1 2026，FinMind 也卡在 Q1 2026（一樣舊）；但 2330 反而
    yfinance 已經有 Q2 2026、FinMind 還停在 Q1 2026（FinMind 比較舊）。
    不能寫死「TW 一律改用 FinMind」，只能兩邊都查、取真正比較新的那個。
    損益表項目（營收/毛利/營業利益/淨利/EPS）覆蓋用 TaiwanStockFinancialStatements。
    2026-08-12 補：FinMind 另有 TaiwanStockCashFlowsStatement，之前誤以為沒有
    現金流量表所以把 ocf/capex/fcf 清成 None——其實有，補上算 OCF/CapEx/FCF。
    現金流量表跟損益表兩個 dataset 各自查詢，季底日期理論上一致，用損益表選定的
    cur_date/yoy_date 去查現金流量表，查不到就是那個 field 本來沒揭露（None），
    不強行湊別的日期。"""
    try:
        start = (datetime.now() - timedelta(days=95 * (n + 2))).strftime("%Y-%m-%d")
        d = FR._fm("TaiwanStockFinancialStatements", code, start)
        cf = FR._fm("TaiwanStockCashFlowsStatement", code, start)
    except Exception:
        return None
    if not d:
        return None
    dates = sorted(set(x["date"] for x in d))
    by_date = {dt: {x["type"]: x["value"] for x in d if x["date"] == dt} for dt in dates}
    cur_date = dates[-1]
    cd = date.fromisoformat(cur_date)
    yoy_date = next((dt for dt in dates if date.fromisoformat(dt).year == cd.year - 1
                     and date.fromisoformat(dt).month == cd.month), None)

    # 2026-08-31 修（Leo：「為什麼玉山點進去資料會是空的？」）：金控股的 FinMind
    # 科目名稱跟一般股不同，寫死單一名稱會整欄 N/A。實測對照：
    #   一般股（鴻海/新產）：IncomeAfterTaxes、OperatingIncome、GrossProfit
    #   金控（玉山/富邦/國泰）：**IncomeAfterTax**（少一個 s）、無 OperatingIncome、
    #                          無 GrossProfit（銀行本來就沒有毛利概念，N/A 是對的）
    # 所以只有淨利需要補候選名稱；毛利/營業利益維持 N/A，不拿稅前淨利硬湊
    # （那是不同的概念，標成營業利益是騙人）。
    ALIASES = {"IncomeAfterTaxes": ["IncomeAfterTaxes", "IncomeAfterTax"]}

    # YoY 基期健全度：富邦金 2025-06-30 的 Revenue 在 FinMind 是 37.9 億，
    # 其他季都 700~1,400 億——基期本身不可比，照算會得到 +2700.4% 這種數字
    # （8/31 Discord 上真的推出去了）。基期太低就顯示 N/A，不給假的成長率。
    #
    # 門檻取自實測分布不是拍腦袋：掃 17 檔台股共 304 個季度的「單季營收÷該檔中位數」，
    # 最低的 6 個季度**全部是金控/壽險**（富邦金 2022-12-31 甚至是負營收 -36.7%、
    # 2025-06-30 是 4.5%、國泰金 2025-06-30 是 27.8%），而全體第 5 百分位是 70.8%
    # ——40% 落在 37.8% 與 70.8% 中間的空隙裡，抓得到全部異常又不誤傷正常季度。
    # 代價是金控的營收 YoY 會常常顯示 N/A，那是誠實的：壽險單季營收含投資與避險
    # 損益抵銷，本來就不是穩定可比的數列。
    BASE_MIN_RATIO = 0.4

    def _median(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else None

    def pair(field):
        names = ALIASES.get(field, [field])
        name = next((n for n in names if n in by_date[cur_date]), names[0])
        a = by_date[cur_date].get(name)
        b = by_date.get(yoy_date, {}).get(name) if yoy_date else None
        pct = None
        if a is not None and b not in (None, 0):
            med = _median([by_date[dt].get(name) for dt in dates])
            if med and med > 0 and b < med * BASE_MIN_RATIO:
                pct = None          # 基期異常，不給成長率（見 BASE_MIN_RATIO）
            else:
                pct = (a / b - 1) * 100
        return {"cur": a, "prev": b, "yoy": pct}

    cf_by_date = {}
    for x in (cf or []):
        cf_by_date.setdefault(x["date"], {})[x["type"]] = x["value"]

    def cf_pair(field):
        a = cf_by_date.get(cur_date, {}).get(field)
        b = cf_by_date.get(yoy_date, {}).get(field) if yoy_date else None
        pct = ((a / b - 1) * 100) if (a is not None and b not in (None, 0)) else None
        return {"cur": a, "prev": b, "yoy": pct}

    ocf = cf_pair("CashFlowsFromOperatingActivities")
    capex = cf_pair("PropertyAndPlantAndEquipment")  # 已是負值(現金流出)，跟 yfinance 口徑一致
    fcf_cur = (ocf["cur"] + capex["cur"]) if (ocf["cur"] is not None and capex["cur"] is not None) else None
    fcf_prev = (ocf["prev"] + capex["prev"]) if (ocf["prev"] is not None and capex["prev"] is not None) else None
    fcf_pct = ((fcf_cur / fcf_prev - 1) * 100) if (fcf_cur is not None and fcf_prev not in (None, 0)) else None

    return {"cur_date": cur_date, "yoy_date": yoy_date, "partial_yoy": yoy_date is None,
            "revenue": pair("Revenue"), "gross": pair("GrossProfit"),
            "op_income": pair("OperatingIncome"), "net_income": pair("IncomeAfterTaxes"),
            "eps": pair("EPS"), "ocf": ocf, "capex": capex,
            "fcf": {"cur": fcf_cur, "prev": fcf_prev, "yoy": fcf_pct}}


def fetch(ticker: str) -> dict:
    """抓最近一季財報 + 去年同期（YoY）+ 估值。全部真實數據。"""
    t = yf.Ticker(ticker)
    q, cf = t.quarterly_income_stmt, t.quarterly_cashflow
    if q is None or q.empty:
        raise SystemExit(f"❌ {ticker} 沒有季度財報資料")
    cols = list(q.columns)
    cur = cols[0]
    # 去年同期＝往前 4 季；季報不足 5 季就退回最舊那季並標記
    yoy = cols[4] if len(cols) >= 5 else cols[-1]
    partial = len(cols) < 5

    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    def pair(df, row):
        a, b = _safe(df, row, cur), _safe(df, row, yoy)
        pct = ((a / b - 1) * 100) if (a is not None and b not in (None, 0)) else None
        return {"cur": a, "prev": b, "yoy": pct}

    tw_code = re.match(r"^(\d{4,5})(\.TWO?)?$", ticker.upper())
    tw_name = None
    if tw_code:
        try:
            import board_html_legacy as _L
            tw_name = _L.TW_NAME.get(tw_code.group(1))
        except Exception:
            pass
        if not tw_name:
            # TW_NAME 只有七鏈守備清單的 62 檔，Leo 的持股（台泥/正新/台灣大/中華電…）
            # 不在裡面，卡片標題就會退成 yfinance 的英文長名
            # 「Chunghwa Telecom Co., Ltd.」。持股檔本來就有中文名，補這一層。
            # 直接讀 JSON，不 import earnings_watch——那支在 module level 重包
            # stdout，被 import 就會把呼叫端已經包好的那層關掉（實測會讓對方
            # 之後的 print 直接 ValueError: I/O operation on closed file）
            try:
                import json as _json
                hp = HOLDINGS_JSON
                code = tw_code.group(1)
                for row in _json.load(open(hp, encoding="utf-8")):
                    t = str(row.get("ticker", ""))
                    if t.split(".")[0] == code and row.get("name"):
                        tw_name = row["name"]
                        break
            except Exception:
                pass

    d = {
        "ticker": ticker.upper(),
        "name": tw_name or info.get("longName") or info.get("shortName") or ticker.upper(),
        "quarter": f"Q{(cur.month - 1)//3 + 1} {cur.year}",
        "period_end": str(cur.date()),
        "yoy_period": str(yoy.date()),
        "partial_yoy": partial,
        "currency": info.get("financialCurrency", "USD"),
        "revenue":   pair(q, "Total Revenue"),
        "gross":     pair(q, "Gross Profit"),
        "op_income": pair(q, "Operating Income"),
        "net_income": pair(q, "Net Income"),
        "eps":       pair(q, "Diluted EPS"),
        "ocf":       pair(cf, "Operating Cash Flow"),
        "capex":     pair(cf, "Capital Expenditure"),
        "fcf":       pair(cf, "Free Cash Flow"),
        "price": info.get("currentPrice"),
        "market_cap": info.get("marketCap"),
        "fwd_pe": info.get("forwardPE"),
        "trail_pe": info.get("trailingPE"),
        "peg": info.get("pegRatio"),
        "ev_rev": info.get("enterpriseToRevenue"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "pb": info.get("priceToBook"),
        "target": info.get("targetMeanPrice"),
        "reco": info.get("recommendationKey"),
        "n_analysts": info.get("numberOfAnalystOpinions"),
        "cash": info.get("totalCash"),
        "debt": info.get("totalDebt"),
        "margin": info.get("profitMargins"),
        "beta": info.get("beta"),
        "wk_high": info.get("fiftyTwoWeekHigh"),
        "wk_low": info.get("fiftyTwoWeekLow"),
        "sector": info.get("sector", ""),
    }
    # 台股核心卡改用 FinMind——只在它真的比 yfinance 新的時候才覆蓋（2026-08-10，
    # 見 _tw_core() 說明：兩邊誰新誰舊視個股而定，不能寫死一律換源）
    if tw_code:
        tw_core = _tw_core(tw_code.group(1))
        if tw_core and tw_core["cur_date"] > d["period_end"]:
            cd = date.fromisoformat(tw_core["cur_date"])
            d["quarter"] = f"Q{(cd.month - 1)//3 + 1} {cd.year}"
            d["period_end"] = tw_core["cur_date"]
            d["yoy_period"] = tw_core["yoy_date"] or d["yoy_period"]
            d["partial_yoy"] = tw_core["partial_yoy"]
            d["revenue"] = tw_core["revenue"]
            d["gross"] = tw_core["gross"]
            d["op_income"] = tw_core["op_income"]
            d["net_income"] = tw_core["net_income"]
            d["eps"] = tw_core["eps"]
            d["ocf"] = tw_core["ocf"]
            d["capex"] = tw_core["capex"]
            d["fcf"] = tw_core["fcf"]

    # 美股核心卡疊 SEC EDGAR（2026-08-31，Leo：「網頁財報分析 2 天內做深入分析」）。
    # 跟上面台股走 FinMind 完全同一個模式：**只在 EDGAR 真的比較新的時候才覆蓋**，
    # 拿不到或不夠新就維持 yfinance，所以不會比改之前差。
    # 為什麼需要：yfinance 的 quarterly_income_stmt 在財報剛公布時慢好幾天——
    # 實測 MRVL 8/27 公布、D+4 還是上一季；NVDA 8/26 公布、D+5 還是上一季。
    # SEC 10-Q 則是 9/11 檔 D+0~D+1 就有。細節與三個坑見 sec_quarterly.py。
    # 反例保留：GLW 的 10-Q 7/29 就送了但 XBRL 33 天沒進 companyfacts，
    # 那種情況這裡條件不成立、自動用 yfinance——兩邊失敗的公司不一樣，疊起來才完整。
    if not tw_code:
        try:
            from sec_quarterly import quarterly_us
            us_core = quarterly_us(ticker.upper())
        except Exception as e:
            print(f"（EDGAR 取用失敗，改用 yfinance：{e}）")
            us_core = None
        if us_core and us_core["cur_date"] > d["period_end"]:
            cd2 = date.fromisoformat(us_core["cur_date"])
            d["quarter"] = f"Q{(cd2.month - 1)//3 + 1} {cd2.year}"
            d["period_end"] = us_core["cur_date"]
            d["yoy_period"] = us_core["yoy_date"] or d["yoy_period"]
            d["partial_yoy"] = us_core["partial_yoy"]
            for fld in ("revenue", "gross", "op_income", "net_income",
                        "eps", "ocf", "capex", "fcf"):
                # 該科目 EDGAR 沒有就保留 yfinance 的（例如 GOOG 沒有 GrossProfit），
                # 不要用 None 把原本有的數字蓋掉
                if us_core[fld]["cur"] is not None:
                    d[fld] = us_core[fld]
            d["source_note"] = f"SEC EDGAR 10-Q（{us_core['cur_date']}）"


    # 毛利率 / 營益率（自己算，不靠 info 的口徑）
    rev = d["revenue"]["cur"]
    if rev:
        d["gross_margin"] = (d["gross"]["cur"] / rev * 100) if d["gross"]["cur"] else None
        d["op_margin"] = (d["op_income"]["cur"] / rev * 100) if d["op_income"]["cur"] else None
        prev_rev = d["revenue"]["prev"]
        d["op_margin_prev"] = (d["op_income"]["prev"] / prev_rev * 100) \
            if (d["op_income"]["prev"] and prev_rev) else None
    return d


# ────────────────────────── 星級評分（由數據算） ──────────────────────────

def score(d: dict) -> dict:
    """洪瑞泰三大關卡 + 俗貴價 + 變壞判定。

    ⚠️ 2026-08-03 重寫：先前這裡是我自創的評分（營收成長/淨現金FCF/PEG/Beta），
    那**不是洪瑞泰的東西** —— 他明說「不聽未來轉機鬼故事」（不看成長性）、
    估值只有俗價貴價兩條線（不用 PEG）、風險看的是盈再率不是 Beta。
    現在改為直接沿用 buffett_screener 的既有實作，不另立標準。
    依據：memory/hongruitai_method.md（該檔開頭即註明「動巴菲特相關前先讀」）。
    """
    from buffett_screener import (fetch_fundamentals, evaluate, ROE_MIN, ROE_YEARS,
                                  REINVEST_IDEAL, REINVEST_MAX, PAYOUT_MIN)
    f = fetch_fundamentals(d["ticker"]) or {}

    roe = f.get("roe_current")
    roe_hist = f.get("roe_history") or []
    roe_pass_years = sum(1 for r in roe_hist if r and r >= ROE_MIN)
    rr = f.get("reinvest_ratio")
    payout = f.get("payout_ratio")
    eps_ttm = f.get("eps_ttm")
    price = f.get("price") or d.get("price")

    # ── 關卡①高 ROE ≥15%：看「連續穩定」，不是單季好看 ──
    gate_roe = {"pass": bool(roe and roe >= ROE_MIN and roe_pass_years >= ROE_YEARS),
                "value": f"{roe*100:.1f}%" if roe else "N/A",
                "detail": f"近 4 年 {roe_pass_years}/4 年達標（需 ≥{ROE_YEARS}）",
                "label": f"① 高 ROE ≥ {ROE_MIN*100:.0f}%"}

    # ── 關卡②盈再率 <80%（理想<40%，>200% 是掏空地雷）──
    if rr is None:
        gate_rr = {"pass": None, "value": "N/A", "label": "② 盈再率 < 80%",
                   "detail": "資料不足（財報項目缺漏），不評判"}
    else:
        lvl = ("🏆 印鈔機（<40%）" if rr < REINVEST_IDEAL else
               "✅ 過關" if rr < REINVEST_MAX else
               "☠️ 地雷（>200%，掏空徵兆）" if rr > 2.0 else "❌ 吃資本的爛生意")
        gate_rr = {"pass": rr < REINVEST_MAX, "value": f"{rr*100:.1f}%",
                   "detail": lvl, "label": "② 盈再率 < 80%"}

    # ── 關卡③配息率 ≥40%：配得出現金才是真賺錢（作假帳配不出現金）──
    if payout is None:
        gate_po = {"pass": None, "value": "N/A", "label": "③ 配息率 ≥ 40%",
                   "detail": "無配息資料"}
    else:
        gate_po = {"pass": payout >= PAYOUT_MIN, "value": f"{payout*100:.1f}%",
                   "detail": "配得出現金＝真賺錢" if payout >= PAYOUT_MIN
                             else "配息偏低，留意盈餘品質",
                   "label": "③ 配息率 ≥ 40%"}

    # ── 俗價／貴價（只有兩條線，沒有合理價）──
    # 2026-08-28 修：這裡原本自己算 eps_ttm*PE_CHEAP(EPS×12，已棄用的舊公式)，跟
    # buffett_screener.evaluate() 8/27 改版後的常利+CHEAP_DISCOUNT(÷1.15^8≈EPS×9.81)
    # 完全脫鉤——同一檔股票，這張卡片跟 buffett.html/investment_chief/base_rate
    # 顯示的俗貴價會對不上（Leo 8/28 發現「財報分析資料好像倒退了」就是這個）。
    # 改叫 evaluate(f) 用同一套邏輯，全站數字一致。
    ev = evaluate(f)
    cheap, expensive = ev.get("cheap_price"), ev.get("exp_price")
    if not (price and cheap):
        pos, pos_txt = None, "EPS 為負或缺值，俗貴價不適用"
    elif price <= cheap:
        pos, pos_txt = "buy", "🟢 現價 ≤ 俗價 → 買進區"
    elif expensive and price <= expensive:
        pos, pos_txt = "watch", "🟡 俗價~貴價之間 → 觀望"
    else:
        pos, pos_txt = "sell", "🔴 現價 > 貴價 → 太貴，考慮賣出"

    # ── 變壞判定（洪瑞泰：公司變壞就該賣）──
    eps = d["eps"]
    reasons, bad = [], 0
    if eps["yoy"] is not None and eps["yoy"] < 0:
        reasons.append(f'EPS YoY {eps["yoy"]:+.0f}%')
        bad += 1
    eps_hist = f.get("eps_history") or []
    if len(eps_hist) >= 2 and eps_hist[-1] is not None and eps_hist[-2] is not None \
            and eps_hist[-1] < eps_hist[-2]:
        reasons.append("年度 EPS 較前一年衰退")
        bad += 1
    te, fe = f.get("eps_ttm"), f.get("eps_forward")
    if te and fe and te > 0 and (fe / te) < 0.90:
        reasons.append(f"照妖鏡：預估 EPS 降 {(1-fe/te)*100:.0f}%")
        bad += 1
    de = f.get("debt_to_equity")
    if de and de > 250:
        reasons.append(f"照妖鏡：高負債 {de:.0f}%")
        bad += 1
    verdict = "bad" if bad >= 2 else ("watch" if bad == 1 else "ok")

    gates = [gate_roe, gate_rr, gate_po]
    passed = sum(1 for g in gates if g["pass"] is True)
    return {"gates": gates, "passed": passed, "n_gates": len(gates),
            "cheap": cheap, "expensive": expensive, "eps_ttm": eps_ttm, "price": price,
            "pos": pos, "pos_txt": pos_txt,
            "verdict": verdict, "reasons": reasons,
            "roe": roe, "reinvest": rr, "payout": payout,
            "net_cash": (d["cash"] - d["debt"])
                        if (d["cash"] is not None and d["debt"] is not None) else None}


# ────────────────────────────── 敘事層（LLM） ──────────────────────────────

def narrative(d: dict, sc: dict, extra_facts: str = "") -> dict:
    from llm_board import ask_json

    def f(x, unit="B"):
        if x is None:
            return "N/A"
        return f"{x/1e9:.2f}B" if abs(x) > 1e6 else f"{x:.2f}"

    def yoy(x):
        return f"{x:+.1f}%" if x is not None else "N/A"

    facts = f"""公司：{d['name']}（{d['ticker']}）　產業：{d['sector']}
本季：{d['quarter']}（截至 {d['period_end']}），YoY 比較基準 {d['yoy_period']}

損益（{d['currency']}）
  營收       {f(d['revenue']['cur'])}   YoY {yoy(d['revenue']['yoy'])}
  毛利       {f(d['gross']['cur'])}   YoY {yoy(d['gross']['yoy'])}　毛利率 {d.get('gross_margin') or 0:.1f}%
  營業利益   {f(d['op_income']['cur'])}   YoY {yoy(d['op_income']['yoy'])}　營益率 {d.get('op_margin') or 0:.1f}%（去年同期 {d.get('op_margin_prev') or 0:.1f}%）
  淨利       {f(d['net_income']['cur'])}   YoY {yoy(d['net_income']['yoy'])}
  EPS        {f(d['eps']['cur'])}   YoY {yoy(d['eps']['yoy'])}

現金流
  營運現金流 {f(d['ocf']['cur'])}   YoY {yoy(d['ocf']['yoy'])}
  資本支出   {f(d['capex']['cur'])}   YoY {yoy(d['capex']['yoy'])}
  自由現金流 {f(d['fcf']['cur'])}   YoY {yoy(d['fcf']['yoy'])}

洪瑞泰三大關卡（品質第一，估值第二）
  ① 高 ROE：{sc['gates'][0]['value']}　{sc['gates'][0]['detail']}　→ {'過' if sc['gates'][0]['pass'] else '不過' if sc['gates'][0]['pass'] is False else '資料不足'}
  ② 盈再率：{sc['gates'][1]['value']}　{sc['gates'][1]['detail']}
  ③ 配息率：{sc['gates'][2]['value']}　{sc['gates'][2]['detail']}

俗貴價（洪瑞泰只有這兩條線，沒有合理價）
  近四季 EPS {sc['eps_ttm']}
  俗價（買，貴價÷1.15^8）= {sc['cheap']}　貴價（賣，常利EPS×30）= {sc['expensive']}
  現價 {sc['price']} → {sc['pos_txt']}

變壞判定：{sc['verdict']}　理由：{'、'.join(sc['reasons']) or '無'}
  股價 {d['price']}　市值 {f(d['market_cap'])}　52週 {d['wk_low']}~{d['wk_high']}
  總現金 {f(d['cash'])}　總負債 {f(d['debt'])}　淨現金 {f(sc['net_cash'])}
  分析師共識 {d['reco']}（{d['n_analysts']} 位）　平均目標價 {d['target']}
"""
    if extra_facts:
        facts += f"\n【補充查核資料（財報趨勢／技術面／同鏈定位）】\n{extra_facts}\n"

    prompt = f"""你是財報分析師，為這季財報寫一份懶人包。這份懶人包用**兩套獨立視角**，
不要讓其中一套覆蓋另一套：

【視角①：洪瑞泰（Mike桑）巴菲特選股法 —— 只管 thesis／sentiment／entry 這幾個欄位】
· **核心順序：先挑「好公司」（不會變的公司），再等「便宜」才買。品質第一、估值第二。**
· 三大量化關卡：① ROE≥15% 且要連續穩定 ② 盈再率<80%（理想<40%，>200% 是掏空地雷）
  ③ 配息率≥40%（配得出現金才是真賺錢，作假帳的公司配不出現金）
· 估值**只有兩條線**：俗價（常利EPS×30÷1.15^8，買）、貴價（常利EPS×30，賣）。**沒有合理價，不要用 PEG／EV倍數／目標價來論估值。**
· **「不聽未來轉機、爆發力的鬼故事」** —— 不要用「未來成長想像」當利多，要看已實現的獲利穩定度。
· **公司變壞就該賣**：EPS 衰退、預估 EPS 下修、高負債都是變壞訊號。
· 這套框架**只回答「這是不是洪瑞泰會買的股票」**，不代表這是公司唯一值得看的角度。

【視角②：verdict 欄位 —— 獨立的資料查核總結，不受洪瑞泰框架限制】
verdict 是這份懶人包的「我們幫你查了什麼」總結，**視野要比洪瑞泰框架寬**：
· 財報趨勢裡如果有連續多季的變化模式（例如業外損益連續上升、毛利率連續改善／惡化），
  這個「模式本身」就是值得單獨點出的觀察，**不要把它壓縮成洪瑞泰三關卡的附註**。
  三關卡是財務體質的健檢，不是唯一觀點——業外收入的成長軌跡是另一件事，兩者平行呈現。
· 技術面與同鏈定位如果有明確訊號，也是獨立輸入，不用先問「洪瑞泰框架同不同意」才寫。
· verdict 的寫法：先講資料查得到什麼（給查核者的信任基礎），再依重要性列出 2-4 個
  獨立觀察（不用湊成同一個結論，財務體質差跟業外趨勢異常是兩件事可以並列），
  最後給下一個驗證點。

【鐵則】
1. **只能引用下方提供的真實數據，絕對不可以編造任何數字、日期、產品名稱、管理層發言或新聞事件。**
   你沒有這家公司的財報電話會議內容，也沒有新聞，只有下面這些數字。
2. 需要提到具體數字時，直接引用下方數據。不確定的事情就不要寫。
3. **全部用繁體中文（台灣用語）**：營收/毛利率/營益率/資本支出/自由現金流/部位/盈再率。
   ⚠️ 一個簡體字都不能出現。查到的簡中資料要先翻成繁體再寫（营→營、产→產、亿→億、
   现→現、业→業、发→發、达→達、优→優、势→勢、单→單、价→價、涨→漲、观→觀）。
4. 要點出「數字背後的矛盾」——例如營收成長但獲利衰退、現金流轉負等，這才是懶人包的價值。
5. 若補充查核資料出現「連續上升趨勢」這類標記（例如業外損益），verdict 一定要點出這是趨勢
   而非單點異常，這通常比「哪個數字比較大」更重要。
6. 若補充查核資料有技術面/同鏈定位，verdict 可以引用，但不要過度解讀技術指標（僅供參考，不是預測）。

{facts}

請只回 JSON，不要任何說明文字：
{{
  "highlights": [
    {{"icon":"適合的單個emoji","title":"亮點標題(10字內)","desc":"說明(45字內，要引用具體數字)"}}
  ],
  "capital": [
    {{"icon":"單個emoji","title":"資本/產能面標題(10字內)","desc":"說明(45字內，聚焦資本支出與現金流)"}}
  ],
  "positives": ["利多條列(30字內)"],
  "risks": ["風險條列(30字內)"],
  "thesis": "用洪瑞泰框架看這家公司是不是「好公司」(60字內，扣三大關卡與獲利穩定度，不要講成長想像)",
  "investor": "適合什麼樣的投資人(30字內)",
  "sentiment": "市場情緒評級，只能從這五選一：VERY BEARISH / BEARISH / NEUTRAL / BULLISH / VERY BULLISH",
  "sentiment_reason": "情緒評級理由(30字內)",
  "entry": "最佳進場策略 Best Entry Strategy(40字內，可參考 52 週區間與目標價)",
  "bottom_line": "一句話總結(50字內)：綜合這季獲利/現金流/估值給整體評語，用一般投資人看得懂的語言即可，"
    "不要點名任何特定選股方法論或人名(例如不要寫「洪瑞泰」)，也不用複述俗價/貴價的具體數字(那些在別的欄位已呈現)",
  "verdict": "獨立資料查核總結(120字內，見上方視角②)：先講查得到什麼，再列2-4個獨立觀察(財務趨勢/技術面/同鏈定位平行呈現，不用套進洪瑞泰框架)，最後給下一個驗證點。財報趨勢裡若有連續多季的變化模式(如業外損益連續成長)要單獨點出，不要只跟本業比大小。不是重複 bottom_line。"
}}
highlights 與 capital 各給 3-4 項，positives 與 risks 各給 4-5 項。"""
    # 2026-08-31：MRVL 卡片整張簡體（营收/现金流/净利/业外损益），連 verdict 都是。
    # 鐵則 3 本來就寫了「用繁體中文台灣用語」——**寫在 prompt 裡不等於做到**，
    # 餵進去的查核資料是簡中新聞時模型會跟著漂過去。改成事後驗收＋改稿重試。
    # 失敗就回 None 讓卡片這次不產出，落回既有的 infographic_pending 隔天重試，
    # 不要為了「有東西可推」而把簡體字送上網站（Leo 硬規則）。
    from llm_board import ask_json_traditional
    return ask_json_traditional(prompt)


# ────────────────────────────── 版面 ──────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0A1628;color:#E8EEF7;
 font-family:"Microsoft JhengHei","PingFang TC",-apple-system,"Segoe UI",sans-serif;
 padding:22px;line-height:1.5}
.wrap{max-width:1280px;margin:0 auto}
.card{background:#132A47;border:1px solid #1E3A5F;border-radius:14px;padding:16px}
.hd{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
 border-bottom:3px solid #F5B841;padding-bottom:14px;margin-bottom:18px;flex-wrap:wrap}
.hd h1{font-size:27px;font-weight:800;letter-spacing:.5px}
.hd .sub{color:#8FA8C8;font-size:13px;margin-top:3px}
.tk{font-size:34px;font-weight:800;color:#F5B841;line-height:1}
.tk-sub{color:#8FA8C8;font-size:12px;text-align:right;margin-top:4px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:16px}
.kpi{background:#132A47;border:1px solid #1E3A5F;border-radius:14px;padding:14px 12px;
 border-top:3px solid #2E4A6F}
.kpi .lb{color:#8FA8C8;font-size:11.5px;letter-spacing:.4px;text-transform:uppercase}
.kpi .vl{font-size:26px;font-weight:800;margin:5px 0 3px;letter-spacing:-.5px}
.kpi .yo{font-size:13px;font-weight:700}
.up{color:#22C55E}.dn{color:#EF4444}.neu{color:#8FA8C8}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px}
h2{font-size:14px;font-weight:800;color:#F5B841;letter-spacing:.6px;margin-bottom:11px;
 text-transform:uppercase}
.item{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #1E3A5F}
.item:last-child{border-bottom:0}
.ic{font-size:19px;line-height:1.2;flex-shrink:0;width:24px;text-align:center}
.it-t{font-weight:700;font-size:13.5px;margin-bottom:2px}
.it-d{color:#A9C0DC;font-size:12.5px;line-height:1.55}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:#8FA8C8;font-weight:600;text-align:right;padding:6px 4px;
 border-bottom:1px solid #1E3A5F;font-size:11.5px}
th:first-child{text-align:left}
td{padding:6px 4px;text-align:right;border-bottom:1px solid #16304F}
td:first-child{text-align:left;color:#C7D8EC}
.gauge{text-align:center;margin-top:12px}
.gauge .lbl{font-size:15px;font-weight:800;margin-top:-8px}
.gauge .rsn{color:#8FA8C8;font-size:11.5px;margin-top:5px;line-height:1.45}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.pos{background:#0E2E1E;border:1px solid #1B5E3A}
.neg{background:#2E1418;border:1px solid #5E1B24}
.pos h2{color:#22C55E}.neg h2{color:#EF4444}
.li{display:flex;gap:9px;padding:7px 0;font-size:12.8px;line-height:1.5;align-items:flex-start}
.li .m{flex-shrink:0;font-weight:800}
.pos .m{color:#22C55E}.neg .m{color:#EF4444}
.dec{display:grid;grid-template-columns:1.15fr 1fr;gap:12px;margin-bottom:16px}
.rate{display:flex;justify-content:space-between;align-items:center;padding:8px 0;
 border-bottom:1px solid #1E3A5F;font-size:13px}
.rate:last-of-type{border-bottom:0}
.st{color:#F5B841;letter-spacing:2.5px;font-size:14.5px}
.st .off{color:#33507A}
.na{color:#8FA8C8;font-size:11.5px;letter-spacing:0}
.badge{text-align:center;padding:14px;border-radius:12px;margin-bottom:12px}
.badge .bg{font-size:31px;font-weight:800;letter-spacing:2px;line-height:1}
.badge .bs{font-size:11.5px;margin-top:5px;opacity:.92}
.note{color:#8FA8C8;font-size:11.5px;margin-top:9px;line-height:1.5}
.bl{background:linear-gradient(90deg,#14304F,#1B3E63);border:1px solid #2A4E78;
 border-radius:14px;padding:16px 20px;display:flex;align-items:center;gap:15px}
.bl .e{font-size:29px;flex-shrink:0}
.bl .t{font-size:11.5px;color:#F5B841;font-weight:800;letter-spacing:1.2px;margin-bottom:3px}
.bl .c{font-size:14.5px;line-height:1.6}
.verdict{margin-top:14px;padding:14px 16px;background:#161a20;border:1px solid #2a2e35;
 border-left:3px solid #F5B841;border-radius:10px}
.verdict .vt{font-size:11.5px;font-weight:700;color:#F5B841;letter-spacing:.5px;margin-bottom:6px}
.verdict .vc{font-size:13.5px;line-height:1.7;color:#C7D8EC}
.ftr{color:#6B84A6;font-size:11px;margin-top:16px;line-height:1.7;
 border-top:1px solid #1E3A5F;padding-top:12px}
.warn{background:#3A2A0E;border:1px solid #7A5A1E;color:#F5C96B;border-radius:9px;
 padding:9px 13px;font-size:12px;margin-bottom:14px}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(2,1fr)}
 .grid3,.two,.dec{grid-template-columns:1fr}}
"""


def _fmt(v, cur="USD"):
    if v is None:
        return "N/A"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a/1e9:.2f}B" if cur == "USD" else f"{sign}{a/1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a/1e6:.0f}M" if cur == "USD" else f"{sign}{a/1e6:.0f}M"
    return f"{sign}${a:.2f}" if cur == "USD" else f"{sign}{a:.2f}"


def _yoy(p, invert=False):
    """invert=True 用於 CapEx 這種「增加不一定是好事」的指標 → 只顯示不上色。"""
    if p is None:
        return '<span class="yo neu">— YoY 無可比基期</span>'
    if invert:
        return f'<span class="yo neu">{p:+.1f}% YoY</span>'
    cls, arw = ("up", "▲") if p >= 0 else ("dn", "▼")
    return f'<span class="yo {cls}">{arw} {p:+.1f}% YoY</span>'


def _stars_html(n):
    if n is None:
        return '<span class="na">資料不足，不評分</span>'
    return ('<span class="st">' + "★" * n
            + f'<span class="off">{"★" * (5 - n)}</span></span>')


GAUGE = ["VERY BEARISH", "BEARISH", "NEUTRAL", "BULLISH", "VERY BULLISH"]


def _gauge_svg(label):
    idx = GAUGE.index(label) if label in GAUGE else 2
    import math
    ang = math.pi - (idx / 4) * math.pi              # 180°(左/看空) → 0°(右/看多)
    cx, cy, r = 110, 100, 76
    x, y = cx + r * 0.82 * math.cos(ang), cy - r * 0.82 * math.sin(ang)
    segs, colors = 5, ["#EF4444", "#F97316", "#8FA8C8", "#4ADE80", "#22C55E"]
    arcs = []
    for i in range(segs):
        a0, a1 = math.pi - i * math.pi / segs, math.pi - (i + 1) * math.pi / segs
        x0, y0 = cx + r * math.cos(a0), cy - r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy - r * math.sin(a1)
        arcs.append(f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}" '
                    f'stroke="{colors[i]}" stroke-width="15" fill="none" stroke-linecap="butt"/>')
    color = colors[idx]
    return (f'<svg viewBox="0 0 220 118" style="width:100%;max-width:220px">'
            + "".join(arcs)
            + f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#E8EEF7" '
              f'stroke-width="3.5" stroke-linecap="round"/>'
              f'<circle cx="{cx}" cy="{cy}" r="7" fill="#E8EEF7"/></svg>'
              f'<div class="lbl" style="color:{color}">{label}</div>')


# 原 prompt 的「BUY Callout」標章＝分析師共識評級。
# 這是**獨立於洪瑞泰的另一套策略**（市場派/賣方觀點），兩者並存不互相覆蓋。
BADGE_STYLE = {
    "strong_buy":   ("#0E3A22", "#22C55E", "STRONG BUY"),
    "buy":          ("#0E3A22", "#22C55E", "BUY"),
    "hold":         ("#3A3212", "#F5B841", "HOLD"),
    "underperform": ("#3A1A18", "#EF4444", "UNDERPERFORM"),
    "sell":         ("#3A1418", "#EF4444", "SELL"),
}


def render(d, sc, n, extra_html=None):
    extra_html = extra_html or {}
    cur = d["currency"]
    up = d["target"] and d["price"] and (d["target"] / d["price"] - 1) * 100
    bg, fg, txt = BADGE_STYLE.get(d["reco"], ("#22374F", "#8FA8C8", (d["reco"] or "N/A").upper()))

    kpis = [
        ("營收 Revenue", _fmt(d["revenue"]["cur"], cur), d["revenue"]["yoy"], False),
        ("毛利 Gross Profit", _fmt(d["gross"]["cur"], cur), d["gross"]["yoy"], False),
        ("營業利益 Op. Income", _fmt(d["op_income"]["cur"], cur), d["op_income"]["yoy"], False),
        ("淨利 Net Income", _fmt(d["net_income"]["cur"], cur), d["net_income"]["yoy"], False),
        ("資本支出 CapEx", _fmt(abs(d["capex"]["cur"]) if d["capex"]["cur"] else None, cur),
         d["capex"]["yoy"], True),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="lb">{lb}</div><div class="vl">{v}</div>{_yoy(p, inv)}</div>'
        for lb, v, p, inv in kpis)

    def items(rows):
        return "".join(
            f'<div class="item"><div class="ic">{r.get("icon","•")}</div><div>'
            f'<div class="it-t">{r.get("title","")}</div>'
            f'<div class="it-d">{r.get("desc","")}</div></div></div>' for r in rows)

    fin_rows = [("營收", d["revenue"]), ("毛利", d["gross"]), ("營業利益", d["op_income"]),
                ("淨利", d["net_income"]), ("營運現金流", d["ocf"]), ("自由現金流", d["fcf"])]
    fin_html = "".join(
        f'<tr><td>{lb}</td><td>{_fmt(p["cur"], cur)}</td>'
        f'<td class="{"up" if (p["yoy"] or 0) >= 0 else "dn"}">'
        f'{f"{p['yoy']:+.1f}%" if p["yoy"] is not None else "—"}</td></tr>'
        for lb, p in fin_rows)

    # 原 prompt 指定的估值簡表：Forward P/E, PEG Ratio, FCF Yield, EV/Sales
    def _p(v, suf=""):
        return f"{v:.2f}{suf}" if isinstance(v, (int, float)) else "N/A"
    fcf_yield = ((d["fcf"]["cur"] / d["market_cap"] * 100)
                 if (d["fcf"]["cur"] and d["market_cap"]) else None)
    val_rows = [("Forward P/E", _p(d["fwd_pe"]), "低於 20 偏便宜"),
                ("PEG Ratio", _p(d["peg"]), "小於 1＝成長性被低估"),
                ("FCF Yield", _p(fcf_yield, "%"), "自由現金流／市值，越高越好"),
                ("EV / Sales", _p(d["ev_rev"]), "越低越好"),
                ("Trailing P/E", _p(d["trail_pe"]), "看過去 12 個月"),
                ("P / B", _p(d["pb"]), "資產面估值")]
    val_html = "".join(
        f'<tr><td>{lb}</td><td>{v}</td>'
        f'<td style="color:#6B84A6;font-size:11px;text-align:right">{h}</td></tr>'
        for lb, v, h in val_rows)

    # 洪瑞泰三大關卡（不是星等，是過/不過。他的方法是門檻制不是評分制）
    def _mark(p):
        return ('<span style="color:#22C55E;font-weight:800">✅ 過</span>' if p is True
                else '<span style="color:#EF4444;font-weight:800">❌ 不過</span>' if p is False
                else '<span class="na">資料不足</span>')
    rate_html = "".join(
        f'<div class="rate"><div>{g["label"]}'
        f'<div style="color:#6B84A6;font-size:10.5px;font-weight:400;margin-top:1px">'
        f'{g["detail"]}</div></div>'
        f'<div style="text-align:right"><div style="font-weight:700">{g["value"]}</div>'
        f'{_mark(g["pass"])}</div></div>' for g in sc["gates"])

    vd = {"ok": ("#22C55E", "✅ 沒有變壞跡象"),
          "watch": ("#F5B841", "🟠 出現 1 個警訊，觀察"),
          "bad": ("#EF4444", "🔴 變壞 — 洪瑞泰：公司變壞就該賣")}[sc["verdict"]]
    # 俗貴價（洪瑞泰的買賣線，跟右側分析師共識是兩套獨立策略）
    _pf = lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "N/A"
    rate_html += (
        f'<div style="margin-top:12px;padding-top:11px;border-top:1px solid #1E3A5F">'
        f'<div style="color:#F5B841;font-size:11.5px;font-weight:700;margin-bottom:5px">'
        f'俗貴價（常利EPS基準，買=÷1.15^8／賣=×30）</div>'
        f'<div style="font-size:12.5px;color:#C7D8EC;line-height:1.7">'
        f'近四季 EPS {_pf(sc["eps_ttm"])}　'
        f'<span style="color:#22C55E">俗價 {_pf(sc["cheap"])}</span>　'
        f'<span style="color:#EF4444">貴價 {_pf(sc["expensive"])}</span><br>'
        f'現價 {_pf(sc["price"])} → <b>{sc["pos_txt"]}</b></div></div>')
    rate_html += (
        f'<div style="margin-top:12px;padding-top:11px;border-top:1px solid #1E3A5F">'
        f'<div style="color:#F5B841;font-size:11.5px;font-weight:700;margin-bottom:5px">'
        f'變壞判定（EPS 衰退／照妖鏡）</div>'
        f'<div style="color:{vd[0]};font-weight:700;font-size:13.5px">{vd[1]}</div>'
        + ("".join(f'<div style="color:#A9C0DC;font-size:12px;margin-top:3px">· {r}</div>'
                   for r in sc["reasons"]) or
           '<div style="color:#6B84A6;font-size:12px;margin-top:3px">· 無</div>')
        + '</div>')

    warn = ('<div class="warn">⚠️ 這檔季報資料不足 5 季，YoY 比較基期不是去年同期，'
            '成長率僅供參考。</div>') if d["partial_yoy"] else ""

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{d['ticker']} {d['quarter']} 財報懶人包</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script><script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js"></script><script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script><script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js"></script>
<style>{CSS}{CP.CSS}{FR.CSS}{TI.CSS}{EC.CSS}</style></head><body><div class="wrap">

<div class="hd">
  <div><h1>{d['name']}</h1>
    <div class="sub">{d['quarter']} 財報懶人包　·　會計期間截至 {d['period_end']}　·　YoY 基準 {d['yoy_period']}</div></div>
  <div><div class="tk">{d['ticker']}</div>
    <div class="tk-sub">股價 {d['price']} {cur}　·　產生於 {datetime.now():%Y-%m-%d %H:%M}</div></div>
</div>
{warn}
<div class="kpis">{kpi_html}</div>

<div class="grid3">
  <div class="card"><h2>營運亮點 Highlights</h2>{items(n.get('highlights', []))}</div>
  <div class="card"><h2>財務數據 Financial Results</h2>
    <table><tr><th>項目</th><th>本季</th><th>YoY</th></tr>{fin_html}</table>
    <div class="gauge"><h2 style="margin-top:16px">市場情緒 Sentiment</h2>
      {_gauge_svg(n.get('sentiment', 'NEUTRAL'))}
      <div class="rsn">{n.get('sentiment_reason', '')}</div></div>
  </div>
  <div class="card"><h2>資本與產能動態 Capital &amp; Capacity</h2>{items(n.get('capital', []))}</div>
</div>

<div class="two">
  <div class="card pos"><h2>✓ 利多 Key Positives</h2>
    {"".join(f'<div class="li"><span class="m">✓</span><span>{x}</span></div>' for x in n.get('positives', []))}</div>
  <div class="card neg"><h2>✕ 風險 Key Risks &amp; Concerns</h2>
    {"".join(f'<div class="li"><span class="m">✕</span><span>{x}</span></div>' for x in n.get('risks', []))}</div>
</div>

<div class="dec">
  <div class="card"><h2>洪瑞泰選股法 Decision Framework</h2>{rate_html}
    <div style="margin-top:13px;padding-top:12px;border-top:1px solid #1E3A5F">
      <div style="color:#F5B841;font-size:11.5px;font-weight:700;margin-bottom:4px">長線投資邏輯</div>
      <div style="font-size:12.8px;line-height:1.6;color:#C7D8EC">{n.get('thesis', '')}</div>
      <div style="color:#F5B841;font-size:11.5px;font-weight:700;margin:11px 0 4px">適合的投資人</div>
      <div style="font-size:12.8px;color:#C7D8EC">{n.get('investor', '')}</div>
    </div>
  </div>
  <div class="card"><h2>分析師共識與估值 Consensus</h2>
    <div class="badge" style="background:{bg};border:1px solid {fg}">
      <div class="bg" style="color:{fg}">{txt}</div>
      <div class="bs" style="color:{fg}">{d['n_analysts'] or '?'} 位分析師共識　·　平均目標價 {d['target'] or 'N/A'}
        {f'（潛在空間 {up:+.1f}%）' if up is not None else ''}</div>
    </div>
    <table>{val_html}</table>
    <div style="margin-top:11px;padding-top:10px;border-top:1px solid #1E3A5F">
      <div style="color:#F5B841;font-size:11.5px;font-weight:700;margin-bottom:4px">進場策略</div>
      <div style="font-size:12.8px;line-height:1.6;color:#C7D8EC">{n.get('entry', '')}</div>
      <div class="note">52 週區間 {d['wk_low']} ~ {d['wk_high']}　·　市值 {_fmt(d['market_cap'], cur)}
        　·　淨現金 {_fmt(sc['net_cash'], cur)}</div>
    </div>
  </div>
</div>

<div class="bl"><div class="e">💡</div>
  <div><div class="t">BOTTOM LINE</div><div class="c">{n.get('bottom_line', '')}</div></div>
  <div class="e">📈</div></div>

{f'<div class="verdict"><div class="vt">🔎 綜合判斷</div><div class="vc">{n["verdict"]}</div></div>' if n.get('verdict') else ''}
{extra_html.get('reality', '')}
{extra_html.get('technical', '')}
{extra_html.get('positioning', '')}
{extra_html.get('call', '')}

<div class="ftr">
  <b>資料來源</b>：所有財務數字與估值指標皆取自 yfinance 之公司申報財報，未經 AI 生成或修改。
  星級評分中的成長性/財務體質/估值/風險由公式計算，「競爭護城河」與文字敘述由 AI 依上述數據撰寫。<br>
  <b>本頁並列兩套獨立策略，互不覆蓋，可能給出相反結論——那是正常的，不是 bug</b>：<br>
  　<b>① 洪瑞泰（Mike桑）選股法</b>（左下卡）：三大關卡（ROE≥15% 且連續穩定／盈再率&lt;80%／
  配息率≥40%）＋ 俗價（常利EPS÷1.15^8）買、貴價（常利EPS×30）賣 ＋ 變壞判定。長線、重品質、不看成長故事。<br>
  　<b>② 分析師共識與估值</b>（右下卡）：BUY/HOLD/SELL 標章為 yfinance 彙整的<b>賣方分析師共識</b>，
  搭配 Forward P/E、PEG、FCF Yield、EV/Sales。市場派觀點，含成長性預期。<br>
  兩者衝突時（例：分析師喊 BUY 但洪瑞泰三關全不過）＝ 該檔是「市場看好但體質不合格」，
  請自行判斷要跟哪一套。本頁為研究參考，不構成投資建議。<br>
  <b>已知限制</b>：無法取得法說會內容、管理層展望與新聞，因此「下季展望」類資訊不予呈現，避免編造。<br>
  <b>資料源落差</b>：上方核心卡片（洪瑞泰／分析師共識）用 yfinance，「財報與營收實況」用 FinMind（台股）——
  兩者更新頻率不同，若季度標籤看起來不一致，是資料源落後、不是抓錯。以「財報與營收實況」區塊數字為準。
</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="財報懶人包 Infographic 產生器")
    ap.add_argument("ticker")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--no-llm", action="store_true", help="跳過 AI 敘事層，只出數據")
    ap.add_argument("--obis", action="store_true", help="同時存一份到 obis")
    args = ap.parse_args()

    print(f"抓 {args.ticker} 財報 …", end=" ", flush=True)
    d = fetch(args.ticker)
    print(f"{d['quarter']}（截至 {d['period_end']}）")
    sc = score(d)

    print("財報趨勢／技術面／產業鏈定位 …", end=" ", flush=True)
    reality_html, reality_sum = FR.build(d["ticker"])
    technical_html, technical_sum = TI.build(d["ticker"])
    positioning_html = CP.build_html(d["ticker"])
    positioning_sum = CP.summary_text(d["ticker"])
    print("完成")
    print("法說會逐字稿摘要（本機 claude 上網搜尋，較慢）…", end=" ", flush=True)
    try:
        call_html, call_sum = EC.build(d["ticker"], d.get("name", ""), d["quarter"])
    except Exception as e:
        print(f"失敗：{e}", end=" ")
        call_html, call_sum = "", ""
    print("完成" if call_html else "（無資料，跳過）")
    extra_facts = "\n".join(x for x in [
        f"財報趨勢：{reality_sum}" if reality_sum else "",
        f"技術面：{technical_sum}" if technical_sum else "",
        f"產業鏈定位：{positioning_sum}" if positioning_sum else "",
        call_sum if call_sum else "",
    ] if x)

    n = {}
    if not args.no_llm:
        print("AI 撰寫敘事層 …", end=" ", flush=True)
        try:
            n = narrative(d, sc, extra_facts)
            print("完成")
        except Exception as e:
            print(f"失敗：{e}\n  → 改出純數據版")
    if not n:
        n = {"sentiment": "NEUTRAL", "highlights": [], "capital": [],
             "positives": [], "risks": [],
             "bottom_line": "（未產生 AI 敘事層，本頁僅呈現真實財報數據）"}

    out = args.output or f"docs/earnings_{d['ticker'].replace('.', '_')}.html"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    html = render(d, sc, n, extra_html={
        "reality": reality_html, "technical": technical_html, "positioning": positioning_html,
        "call": call_html})
    targets = [out] + ([os.path.join(OBIS, f"{d['ticker']}_{d['quarter']}_財報懶人包.html")]
                       if args.obis else [])
    for p in targets:
        try:
            open(p, "w", encoding="utf-8").write(html)
            print(f"✅ {p}")
        except Exception as e:
            print(f"⚠️ 寫入 {p} 失敗：{e}")


if __name__ == "__main__":
    main()
