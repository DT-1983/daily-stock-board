# -*- coding: utf-8 -*-
"""美股單季財報 ← SEC EDGAR companyfacts（2026-08-31）

**為什麼要有這支**：財報卡片的美股數字原本只有 yfinance 的 quarterly_income_stmt
一個來源，而它在財報剛公布時**慢好幾天**。2026-08-31 實測（Leo 要求「網頁財報分析
2 天內做深入分析」，用 MRVL 當依據）：

    MRVL  8/27 公布 → yfinance 到 8/31（D+4）還停在 2026-04-30 上一季
                    → SEC 10-Q **8/28 就送了**（D+1），數字齊全
    NVDA  8/26 公布 → yfinance D+5 仍是上一季；SEC D+0 當天就有

11 檔美股實測 10-Q 申報時差：9 檔 D+0~D+1、AVGO D+6、GLW 例外（見下）。

**但 EDGAR 不是萬靈丹**，所以這支是「疊在 yfinance 上面」不是「取代」：
- GLW 康寧的 10-Q 2026-07-29 就送進 SEC（申報清單查得到），但 XBRL facts 到
  8/31（33 天）還沒進 companyfacts API；同一天送件的 MSFT 就有。這是 SEC 端的
  個案落差，我們控制不了——而 GLW 的 yfinance 反而是新的。
- 兩個資料源**失敗的公司不一樣**，疊起來覆蓋率比任一邊單獨用都高。
呼叫端（earnings_infographic.fetch）照 `_tw_core` 既有的模式：**只在 EDGAR 真的
比較新的時候才覆蓋**，拿不到就自動落回 yfinance，不會比現況差。

## 三個實測到的坑（不是查文件抄的，是打開 MRVL 資料看到的）

1. **同一期末有兩筆，一筆是 YTD 累計**
   MRVL 期末 2026-08-01：181 天那筆 5157.1M 是半年累計、90 天那筆 2739.3M 才是單季。
   → 用 `frame` 欄位分辨：SEC 自己標了 `CY2026Q2` 的才是它認定的單季值，
     YTD 那筆 `frame` 是空的。再加上 80~100 天的期間長度雙重確認。

2. **現金流量表在 10-Q 裡「只有 YTD」，沒有單季**
   MRVL 的 NetCashProvidedByUsedInOperatingActivities 期末 2026-08-01 只有
   181 天的 1244.3M，沒有 90 天的版本。
   → 必須自己相減：單季 = 本期YTD − 上一季YTD（1244.3 − 638.8 = 605.5M）。
     這是會計期間的定義，不是估算。相減不到（例如 Q1，YTD 本來就等於單季）就直接用。

3. **每家公司的科目標籤不一樣，而且缺項是正常的**
   - GOOG **沒有 GrossProfit**——Alphabet 財報本來就不列毛利，不是資料缺失
   - GLW 的資本支出用 `PaymentsToAcquireProductiveAssets` 不是標準的
     `PaymentsToAcquirePropertyPlantAndEquipment`
   → 每個欄位給一串候選標籤依序試，缺就是 None，不硬湊別的科目替代。

## 符號慣例
資本支出在 EDGAR 是**正值**（現金流出金額），但 yfinance / FinMind 兩邊都用負值。
這裡回傳前轉成負值對齊，否則 FCF = OCF + capex 會算成加法。

用法:
    from sec_quarterly import quarterly_us
    d = quarterly_us("MRVL")     # 拿不到回 None
"""
import sys
import json
import urllib.request
from datetime import date

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")

import sec_edgar as SE

# 每個欄位的候選標籤，依序試。第一個抓得到就用，不做加總或替代。
TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues", "SalesRevenueNet"],
    "gross": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    # AVGO 2024-11 之後改用 ProfitLoss 報淨利，NetIncomeLoss 停在 2024-11-03。
    # 兩者差在有無少數股東權益；_series 會挑資料最新的那個，實測 AVGO 走 ProfitLoss
    # 的 9,310M 跟 yfinance 完全一致，其餘 10 檔仍走 NetIncomeLoss。
    "net_income": ["NetIncomeLoss", "ProfitLoss",
                   "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets",
              "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets"],
}
EPS_FIELDS = {"eps"}
CAPEX_FIELDS = {"capex"}

QUARTER_MIN, QUARTER_MAX = 80, 100     # 一季的合理天數
_FACTS = {}


def _facts(ticker):
    """companyfacts 原始 JSON（一次執行內同一檔只抓一次）。"""
    if ticker in _FACTS:
        return _FACTS[ticker]
    cik = SE._load_cik_map().get(ticker.upper())
    out = None
    if cik:
        hdr = SE.UA if isinstance(SE.UA, dict) else {"User-Agent": SE.UA}
        try:
            req = urllib.request.Request(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=hdr)
            out = json.loads(urllib.request.urlopen(req, timeout=90).read())
        except Exception:
            out = None
    _FACTS[ticker] = out
    return out


def _series(facts, tags, unit_kind="USD"):
    """回 ({(start, end): val}, 用了哪個標籤)，只取 10-Q/10-K，同期間留最後申報的那筆。

    同一個期間會在多次申報裡重複出現（例如 Q1 的數字在 Q2 的 10-Q 裡當比較基期
    又報一次）。用 filed 取最新，因為後報的版本可能已經重編過。

    ⚠️ 2026-08-31 交叉驗證抓到的 bug：原本「照 TAGS 順序，第一個有資料的就用」，
    結果 NVDA 停在 2022-01-30、GLW 停在 2018-09-30、GOOG 停在 2025-03-31——
    因為這些公司**中途換過科目標籤**，舊標籤還留著歷史資料，新資料在別的標籤裡。
    改成：所有候選標籤都算一次，**挑資料最新的那個**（同樣新才照 TAGS 順序）。
    這個錯誤自洽測試看不出來（數字都算得出來、也對得起來），是跟 yfinance
    比對同一季才現形的。"""
    us = (facts or {}).get("facts", {}).get("us-gaap", {})
    best_tag, best_ser, best_end = None, None, ""
    for i, tag in enumerate(tags):
        if tag not in us:
            continue
        units = us[tag]["units"]
        key = next((k for k in units if k.startswith(unit_kind)), None)
        if not key:
            continue
        rows = {}
        for r in units[key]:
            if not str(r.get("form", "")).startswith(("10-Q", "10-K")):
                continue
            s_, e_ = r.get("start"), r.get("end")
            if not s_ or not e_:
                continue          # 資產負債表科目（只有 end）不是本支要的
            k = (s_, e_)
            if k not in rows or r.get("filed", "") >= rows[k].get("filed", ""):
                rows[k] = r
        if not rows:
            continue
        mx = max(k[1] for k in rows)
        if mx > best_end:         # 嚴格大於 → 同樣新時保留先列出的標籤
            best_tag, best_ser, best_end = tag, {k: v["val"] for k, v in rows.items()}, mx
    return (best_ser or {}), best_tag


def _dur(k):
    return (date.fromisoformat(k[1]) - date.fromisoformat(k[0])).days


def _quarter_value(series, end):
    """期末為 end 的**單季**值。找不到直接的單季筆數就用 YTD 相減推。

    回 (值, 來源)；來源 'direct'＝報表本來就有單季、'derived'＝YTD 相減。
    """
    ends = [k for k in series if k[1] == end]
    direct = [k for k in ends if QUARTER_MIN <= _dur(k) <= QUARTER_MAX]
    if direct:
        return series[max(direct, key=_dur)], "direct"
    # YTD 相減：本期 YTD 減掉「同一個會計年度起點、但期末更早」的那筆
    ytd = sorted(ends, key=_dur)
    if not ytd:
        return None, None
    cur = ytd[-1]
    prev = [k for k in series
            if k[0] == cur[0] and k[1] < cur[1]
            and _dur(cur) - _dur(k) <= QUARTER_MAX + 10]
    if not prev:
        return None, None
    p = max(prev, key=_dur)
    return series[cur] - series[p], "derived"


def quarterly_us(ticker):
    """美股最新一季 + 去年同期。抓不到回 None。

    回傳結構跟 earnings_infographic._tw_core() 一致，呼叫端可以直接替換：
    {cur_date, yoy_date, partial_yoy, revenue/gross/op_income/net_income/eps/ocf/capex/fcf}
    每個科目是 {"cur":, "prev":, "yoy":}。
    """
    facts = _facts(ticker)
    if not facts:
        return None

    data, srcs = {}, {}
    for field, tags in TAGS.items():
        unit = "USD/shares" if field in EPS_FIELDS else "USD"
        data[field], srcs[field] = _series(facts, tags, unit)

    if not data.get("revenue"):
        return None
    # 最新一季期末＝營收裡最大的 end（營收每家一定有，最適合當基準）
    cur_end = max(k[1] for k in data["revenue"])
    cd = date.fromisoformat(cur_end)
    # 去年同期：期末差 355~375 天的那個 end（會計年度長度會差幾天，不能寫死 365）
    cand = {k[1] for k in data["revenue"]}
    yoy_end = None
    for e in cand:
        gap = (cd - date.fromisoformat(e)).days
        if 355 <= gap <= 375:
            yoy_end = e
            break

    def pair(field):
        s = data.get(field) or {}
        a, _ = _quarter_value(s, cur_end) if s else (None, None)
        b, _ = (_quarter_value(s, yoy_end) if (s and yoy_end) else (None, None))
        if field in CAPEX_FIELDS:      # EDGAR 是正值（流出金額），對齊 yfinance 轉負
            a = -a if a is not None else None
            b = -b if b is not None else None
        pct = ((a / b - 1) * 100) if (a is not None and b not in (None, 0)) else None
        return {"cur": a, "prev": b, "yoy": pct}

    out = {f: pair(f) for f in TAGS}
    ocf, capex = out["ocf"], out["capex"]
    fcf_cur = (ocf["cur"] + capex["cur"]) if (ocf["cur"] is not None and capex["cur"] is not None) else None
    fcf_prev = (ocf["prev"] + capex["prev"]) if (ocf["prev"] is not None and capex["prev"] is not None) else None
    out["fcf"] = {"cur": fcf_cur, "prev": fcf_prev,
                  "yoy": ((fcf_cur / fcf_prev - 1) * 100)
                         if (fcf_cur is not None and fcf_prev not in (None, 0)) else None}
    out["cur_date"] = cur_end
    out["yoy_date"] = yoy_end
    out["partial_yoy"] = yoy_end is None
    out["_tags"] = {k: v for k, v in srcs.items() if v}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="SEC EDGAR 美股單季財報（診斷用）")
    ap.add_argument("tickers", nargs="+")
    a = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    for tk in a.tickers:
        d = quarterly_us(tk)
        if not d:
            print(f"{tk}: ❌ 抓不到")
            continue
        print(f"\n=== {tk}　期末 {d['cur_date']}　去年同期 {d['yoy_date']} ===")
        for f in ("revenue", "gross", "op_income", "net_income", "eps", "ocf", "capex", "fcf"):
            v = d[f]
            fmt = (lambda x: f"{x:,.2f}") if f == "eps" else (lambda x: f"{x/1e6:,.1f}M")
            cur = fmt(v["cur"]) if v["cur"] is not None else "—"
            prev = fmt(v["prev"]) if v["prev"] is not None else "—"
            yoy = f"{v['yoy']:+.1f}%" if v["yoy"] is not None else "—"
            print(f"  {f:11s} 本季 {cur:>14s}　去年 {prev:>14s}　YoY {yoy}")
