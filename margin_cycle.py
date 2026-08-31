# -*- coding: utf-8 -*-
"""毛利率循環位階（2026-08-31）

**它回答什麼**：base_rate 量的是「市場**期待**的成長率 vs 這檔自己的歷史成長率」，
量不到「這檔**現在的獲利能力**在自己歷史的哪個位置」。少了後者會誤判循環股。

實測案例（就是為什麼做這支）：
    MU 美光  base_rate = ✅ normal（只要求季增 +22%，自己做過 +75%）→ 看起來寬鬆
             但毛利率 84.6% 是 24 季最高，24 季區間是 **-32.7% ~ 84.6%**
             那個「做過 +75%」的基期，本身就是毛利率從中位 37.7% 衝到 84.6% 撐出來的
             → 低期待不是因為市場沒在看，是因為**基期太高**

## 為什麼要「位階」和「擺盪」兩個一起看

把 24 季毛利率想成一座山：位階＝現在站在多高（100%＝山頂），擺盪＝這座山多高。

    MU   位階 100%｜擺盪 117.2pp（-32.7% → 84.6%）  站在雲霄飛車頂端
    AVC  位階 100%｜擺盪  16.8pp（15.7% → 32.6%）  站在樓梯頂端

**兩檔都是「史上最高」，均值回歸風險差一個數量級。** 只看位階會把兩者當成一樣危險；
只看擺盪不知道現在在哪。

## 已知限制（不是 bug，是這個指標的適用範圍）

代工廠的毛利率本來就貼地平走——鴻海 24 季擺盪 1.0pp、廣達 4.0pp。這種公司算出來的
位階（46% / 12%）讀不出任何循環訊息，所以擺盪 < FLAT_SWING 時直接標「無鑑別力」，
**不給結論**。寧可少一個訊號，也不要製造假訊號。

## 資料源
台股 FinMind TaiwanStockFinancialStatements（實測 3037/8046/3017/3324 都有 34 季）
美股 SEC EDGAR companyfacts（走 sec_quarterly，2026-08-31 接的）
兩邊都免費。結果快取在 state/margin_profile.json，毛利率一季才變一次，
預設 30 天才重算——base_rate 每週一跑 186 檔，不重算就不會多花時間。

⚠️ 抓失敗**不寫進快取**（沿用 cache_negative_result_bug 的教訓：一次逾時會被
永久記成「沒資料」）。

用法:
    from margin_cycle import profile
    p = profile("MU")        # 拿不到回 None
    python margin_cycle.py MU NVDA 3037.TW      # 診斷
"""
import os
import re
import sys
import json
from datetime import date, timedelta

QUARTERS = 24           # 取幾季算分布（約 6 年，涵蓋一輪完整記憶體/景氣循環）
MIN_QUARTERS = 8        # 少於此不給結論
FLAT_SWING = 8.0        # 擺盪小於此（百分點）視為「毛利率不擺盪」，此欄無鑑別力
HIGH_PCT = 90           # 位階多高算「頂」
LOW_PCT = 30            # 位階多低算「底」
BIG_SWING = 40.0        # 擺盪多大算「雲霄飛車型」
# 毛利率低於這個絕對值就不給「循環頂」結論——見 _classify() 的 PLUG 案例。
# 10% 這個數字是「還算有毛利的生意」的下限量級，不是投資門檻；
# 代工廠（鴻海 6.1%）本來就會先被 FLAT_SWING 擋掉，不會走到這一關。
MIN_ABS_MARGIN = 10.0
# 中位毛利率低於此就整檔不給結論（回 None，那一行不顯示）。
# 2026-08-31 首跑抓到 MARA：營收 12.8M 對成本 267M → 毛利率 -1992.3%、擺盪 2072pp。
# 查下去不是「生意很差」，是**營收標籤只抓到部分營收、成本標籤是全部**，兩個科目
# 範圍對不上（RevenueFromContractWithCustomer 只涵蓋其中一段）。這種數字顯示出來
# 是雜訊不是資訊。
# 門檻取自實測分布而不是拍腦袋：140 檔的中位毛利率只有 3 檔為負，
# MARA -112.5%、次低 3149.TW -0.9%，中間空了 111.6pp——-50% 落在這個天然斷點上。
USABLE_MIN_MED = -50.0
CACHE = "state/margin_profile.json"
CACHE_DAYS = 30         # 毛利率一季才變一次，30 天內不重算

_MEM = None


def _load_cache():
    global _MEM
    if _MEM is None:
        try:
            _MEM = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            _MEM = {}
    return _MEM


def _save_cache():
    if _MEM is None:
        return
    os.makedirs("state", exist_ok=True)
    json.dump(_MEM, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _is_tw(tk):
    return bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(tk)))


def _series_tw(tk):
    """台股毛利率序列（FinMind）。回 [毛利率%] 由舊到新。"""
    code = str(tk).split(".")[0]
    import fundamentals_reality as FR
    d = FR._fm("TaiwanStockFinancialStatements", code, "2016-01-01") or []
    by = {}
    for x in d:
        by.setdefault(x["date"], {})[x["type"]] = x["value"]
    out = []
    for dt in sorted(by):
        r, g = by[dt].get("Revenue"), by[dt].get("GrossProfit")
        if r and g is not None:
            out.append((r, g / r * 100))
    return out[-QUARTERS:]


# 沒有 GrossProfit 時用「營收 − 成本」回推。2026-08-31 實測 186 檔有 63 檔抓不到，
# 拆解後發現一大類是**公司根本不揭露 GrossProfit 這個科目**（AMZN 2009 年後就不報了、
# ACN 只報 CostOfGoodsAndServicesSold），但成本科目都在，減一下就有。
# 實測回推值：AMZN 52.3%、ACN 32.8%，跟公開數字對得上。
COST_TAGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold",
             "CostOfGoodsSold", "CostOfServices"]


def _series_us(tk):
    """美股毛利率序列（SEC EDGAR）。回 [毛利率%] 由舊到新。"""
    from sec_quarterly import _facts, _series, _quarter_value, TAGS
    f = _facts(str(tk).upper())
    if not f:
        return []
    rev, _ = _series(f, TAGS["revenue"])
    if not rev:
        return []
    gr, _ = _series(f, TAGS["gross"])
    cost, _ = _series(f, COST_TAGS)
    if not gr and not cost:
        # 保險/金融業（ACGL、ALL）本來就沒有「毛利」的概念——這不是抓失敗，
        # 是這個指標對它們不適用。回空，呼叫端就不會顯示這一行。
        return []
    out = []
    for e in sorted({k[1] for k in rev})[-QUARTERS:]:
        r, _ = _quarter_value(rev, e)
        if not r:
            continue
        g = None
        if gr:
            g, _ = _quarter_value(gr, e)
        if g is None and cost:
            c, _ = _quarter_value(cost, e)
            if c is not None:
                g = r - c
        if g is not None:
            out.append((r, g / r * 100))
    return out


COLLAPSE_RATIO = 0.2    # 單季營收低於期間中位數的幾成就剔除，見 _drop_collapsed


def _drop_collapsed(pairs):
    """剔除**分母崩塌**的季度，回 [毛利率%]。

    2026-08-31 首跑抓到：CCL 嘉年華郵輪擺盪 4943pp。查下去是 2020-2021 疫情停航，
    單季營收 31M（正常 8,000M）但固定成本照付 → 毛利率 -4896.8%。算術沒錯，
    但那不是「毛利率很低」，是**分母幾乎歸零**，跟其他季度不可比。

    擋法刻意用「營收 vs 自身中位數」而不是「毛利率超過某個值」——後者會誤殺
    真的長期低毛利的公司（PLUG 有一季 -132% 是真實營運狀態）。實測這條規則：
    CCL 剔 4 季（停航期，擺盪 4943→87.9pp）、PLUG 只剔 1 季（營收是負的）、
    MU 一季都不剔。"""
    if not pairs:
        return []
    revs = sorted(r for r, _ in pairs)
    med = revs[len(revs) // 2]
    if med <= 0:
        return [m for _, m in pairs]
    return [m for r, m in pairs if r >= med * COLLAPSE_RATIO]


def _classify(pct, swing, cur, med):
    """回 (要不要當警訊, 一句話結論)。

    ⚠️ cur/med 這兩個參數是 2026-08-31 首跑後補的。第一版只看位階和擺盪，
    結果 PLUG 被標成「🔴 循環頂」——它位階 92%、擺盪 271.7pp 完全符合條件，
    但**現在的毛利率是 -0.9%、中位數是 -30.7%**。那不是「站在獲利頂點」，
    是「比平常沒那麼虧」。位階是相對自己的排名，在長期虧損的公司身上，
    排名高不代表獲利能力強——要加絕對值的地板才擋得住。"""
    if swing < FLAT_SWING:
        return False, "毛利率幾乎不擺盪，此欄無鑑別力"
    if cur < MIN_ABS_MARGIN:
        # 措辭不能寫死「位階高」——3149.TW 位階只有 38%，訊息卻說「位階高」就自相矛盾。
        # 這一關擋的是「絕對毛利率太低，位階這個相對排名沒有意義」，跟位階高低無關。
        return False, (f"毛利率僅 {cur:.1f}%，絕對值太低，"
                       "位階這個相對排名讀不出獲利強弱")
    if pct >= HIGH_PCT and swing >= BIG_SWING:
        return True, "循環頂＋大擺盪，均值回歸風險高"
    if pct >= HIGH_PCT:
        return False, "位階高但擺盪小，屬結構性墊高"
    if pct <= LOW_PCT:
        return False, "位階偏低，獲利能力尚未回到自身高點"
    return False, "位階中段"


def profile(tk, force=False):
    """{pct, cur, lo, hi, med, swing, n, alert, note} 或 None。"""
    c = _load_cache()
    hit = c.get(str(tk))
    if hit and not force:
        try:
            if date.fromisoformat(hit["asof"]) > date.today() - timedelta(days=CACHE_DAYS):
                return hit["data"]
        except Exception:
            pass
    try:
        pairs = _series_tw(tk) if _is_tw(tk) else _series_us(tk)
    except Exception:
        pairs = []
    v = _drop_collapsed(pairs)
    if len(v) < MIN_QUARTERS:
        # ⚠️ 抓不到**不寫快取**——一次逾時會被記成「這檔永遠沒有毛利率」，
        # 而且 30 天內不會重試（cache_negative_result_bug 的同一個坑）
        return None
    cur, lo, hi = v[-1], min(v), max(v)
    pct = sum(1 for x in v if x <= cur) / len(v) * 100
    swing = hi - lo
    med = sorted(v)[len(v) // 2]
    if med < USABLE_MIN_MED:
        return None       # 科目範圍對不上，不是可比的獲利指標（見 USABLE_MIN_MED）
    alert, note = _classify(pct, swing, cur, med)
    data = {"pct": round(pct, 1), "cur": round(cur, 1), "lo": round(lo, 1),
            "hi": round(hi, 1), "med": round(med, 1),
            "swing": round(swing, 1), "n": len(v), "alert": alert, "note": note}
    c[str(tk)] = {"asof": date.today().isoformat(), "data": data}
    _save_cache()
    return data


def line(tk):
    """給 base_rate 用的一行 Discord 小字（`-#` 開頭）。拿不到回 None。"""
    p = profile(tk)
    if not p:
        return None
    ic = "🔴 " if p["alert"] else ""
    return (f"-# 毛利率位階 {p['pct']:.0f}%（{p['cur']:.1f}%，{p['n']}季區間 "
            f"{p['lo']:.1f}~{p['hi']:.1f}%、中位 {p['med']:.1f}%）"
            f"｜擺盪 {p['swing']:.1f}pp → {ic}{p['note']}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="毛利率循環位階（診斷用）")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--force", action="store_true", help="忽略快取重算")
    a = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    for tk in a.tickers:
        p = profile(tk, force=a.force)
        print(f"\n{tk}: " + ("抓不到（季數不足或無 GrossProfit 揭露）" if not p else ""))
        if p:
            print(f"  {line(tk)}")
