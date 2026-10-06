# -*- coding: utf-8 -*-
"""美股單季財報 ← SEC 8-K 財報新聞稿（EX-99.1）表格（2026-10-06，Leo：MU 新財報抓不到 →「都做」）。

**為什麼要有這支**：財報卡的美股數字來自 SEC companyfacts（sec_quarterly.py）與 yfinance，兩者都要等
10-K／10-Q 送出後才有新一季。會計年度結束那一季（例：MU FY26 Q4，9/30 公布）10-K 常常要再等 1～4 週，
這段時間卡片一直是上一季。但同樣的數字，8-K 財報新聞稿當天就有完整的損益表（多數公司也附資產負債表、現金流量表）。

**做法（零成本，同 sec_release.py）**：找新聞稿（sec_release.latest_release）→ 本機 claude 擷取下列欄位，
每筆附**原文引句**→ 程式驗證 ①引句真的在新聞稿裡 ②引句裡有數字換算後跟回報值對得上（0.1%）
③期末日的英文寫法真的出現在原文 ④不變式：毛利 ≤ 營收、營業利益 ≤ 毛利，以及營收要跟新聞稿重點段的營收一致
（防止表格同一列的相鄰欄位被對調）。驗不過的欄位丟掉；營收或期末日驗不過就整份不用。
**只取單季數字**：新聞稿只有全年／累計的現金流（例 MU）就留空，不拿全年數字冒充單季。

回傳結構同 sec_quarterly.quarterly_us()，呼叫端可以直接疊用；另帶 "source": "8-K 新聞稿（未經審計）"。
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sec_release as SR                                    # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "sec_press_core")
FIELDS = {
    "revenue": "營收（Revenue／Net sales）",
    "gross": "毛利（Gross margin／Gross profit 的金額，不是百分比）",
    "op_income": "營業利益（Operating income）",
    "net_income": "歸屬母公司淨利（Net income）",
    "eps": "GAAP 稀釋每股盈餘（Diluted earnings per share，美元）",
    "ocf": "營業活動現金流（Net cash provided by operating activities）",
    "capex": "資本支出（Expenditures for property, plant and equipment；回報正值）",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def _date_in_text(iso, text):
    """期末日的英文寫法（September 3, 2026／Sept. 3, 2026／9/3/2026）有沒有出現在原文。"""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    t = SR._norm(text)
    m = MONTHS[d.month - 1]
    cands = [f"{m} {d.day}, {d.year}", f"{m[:3]}. {d.day}, {d.year}", f"{m[:4]}. {d.day}, {d.year}",
             f"{m[:3]} {d.day}, {d.year}", f"{d.month}/{d.day}/{d.year}"]
    return any(SR._norm(c) in t for c in cands)


def _extract(rel):
    schema = {"type": "object", "properties": {
        "period_end": {"type": "string", "description": "本季期末日 YYYY-MM-DD"},
        "prev_year_period_end": {"type": "string", "description": "去年同季期末日 YYYY-MM-DD"},
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "which": {"type": "string", "enum": ["cur", "prev"]},
            "value": {"type": "number"},
            "unit": {"type": "string", "enum": ["USD_million", "USD_per_share"]},
            "quote": {"type": "string"}}, "required": ["key", "which", "value", "unit", "quote"]}}},
        "required": ["period_end", "facts"]}
    keys = "\n".join(f"- {k}：{v}" for k, v in FIELDS.items())
    prompt = f"""你是財報數據擷取員。下面是 {rel['ticker']} 在 {rel['filed']} 公布的財報新聞稿全文（含附表）。
請從**損益表／現金流量表附表**擷取「本季（which=cur）」與「去年同一季（which=prev）」的 GAAP 數字：
{keys}

規則：
1. **只要單季（約 13 週／三個月）的數字**。若某科目在新聞稿裡只有全年或年初至今累計（例如現金流量表只有 year ended），就不要回報該科目。
2. 只用新聞稿明確寫出的數字，禁止自己計算或推測；GAAP 與 non-GAAP 分清楚，只要 GAAP。
3. 每筆附 quote：新聞稿原文一字不差的連續片段（不超過 80 字元，要包含該數字；表格就複製那一列）。
4. 金額一律換算成百萬美元（表格本來就以百萬為單位就直接用，例 54,229 → 54229）；每股為美元。資本支出回報正值。
5. period_end／prev_year_period_end 用附表欄位標題上的期末日（例「September 3, 2026」→ 2026-09-03）。

新聞稿全文：
{rel['text'][:90000]}"""
    return SR._claude_json(prompt, schema)


def _verify(out, rel, headline):
    text = rel["text"]
    t = SR._norm(text)
    vals, dropped = {"cur": {}, "prev": {}}, []
    for f in out.get("facts", []):
        k, w, v, q = f.get("key"), f.get("which"), f.get("value"), SR._norm(f.get("quote") or "")
        if k not in FIELDS or w not in ("cur", "prev") or v is None or not q:
            dropped.append((k, w, "欄位不合"))
            continue
        if q not in t:
            dropped.append((k, w, "引句不在原文"))
            continue
        if not SR._quote_supports(float(v), f.get("unit"), q):
            dropped.append((k, w, f"引句裡找不到 {v}"))
            continue
        vals[w][k] = float(v)
    for w in ("cur", "prev"):                               # 不變式：防止同列相鄰欄位對調
        x = vals[w]
        if "gross" in x and "revenue" in x and x["gross"] > x["revenue"] * 1.0001:
            dropped.append(("gross", w, "毛利大於營收")); x.pop("gross")
        if "op_income" in x and "gross" in x and x["op_income"] > x["gross"] * 1.0001:
            dropped.append(("op_income", w, "營業利益大於毛利")); x.pop("op_income")
    # 營收跟新聞稿重點段（sec_release 已驗證）一致才採用整份
    for w, hk in (("cur", "revenue"), ("prev", "revenue_prev_y")):
        hv = ((headline or {}).get(hk) or {}).get("value")
        rv = vals[w].get("revenue")
        if hv and rv and abs(rv - hv) / hv > 0.002:
            dropped.append(("revenue", w, f"跟重點段營收 {hv:g} 不一致"))
            vals[w].pop("revenue", None)
    return vals, dropped


def quarterly_from_release(ticker, since_days=45, use_cache=True):
    """回同 sec_quarterly.quarterly_us() 的結構；找不到新聞稿或驗不過回 None。"""
    rel = SR.latest_release(ticker, since_days=since_days)
    if not rel:
        return None
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = os.path.join(CACHE_DIR, f"{rel['ticker']}_{rel['filed']}.json")
    if use_cache and os.path.exists(cp):
        res = json.load(open(cp, encoding="utf-8"))
        return res if res.get("cur_date") else None
    headline = (SR.parse_release(rel) or {}).get("facts", {})
    out = _extract(rel) or {}
    vals, dropped = _verify(out, rel, headline)
    pe, ppe = out.get("period_end"), out.get("prev_year_period_end")
    res = {"_dropped": dropped, "url": rel["url"], "filed": rel["filed"]}
    if not (pe and _date_in_text(pe, rel["text"]) and vals["cur"].get("revenue")):
        res["_why"] = "期末日或本季營收驗不過，整份不用"
        json.dump(res, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return None
    if not (ppe and _date_in_text(ppe, rel["text"])
            and 355 <= (date.fromisoformat(pe) - date.fromisoformat(ppe)).days <= 375):
        ppe = None
    M = 1e6

    def pair(k):
        a, b = vals["cur"].get(k), vals["prev"].get(k) if ppe else None
        if k != "eps":
            a = a * M if a is not None else None
            b = b * M if b is not None else None
        if k == "capex":                                     # 對齊 yfinance／sec_quarterly：資本支出為負值
            a = -abs(a) if a is not None else None
            b = -abs(b) if b is not None else None
        return {"cur": a, "prev": b, "yoy": ((a / b - 1) * 100) if (a is not None and b not in (None, 0)) else None}

    res.update({k: pair(k) for k in FIELDS})
    o, c = res["ocf"], res["capex"]
    fc = (o["cur"] + c["cur"]) if (o["cur"] is not None and c["cur"] is not None) else None
    fp = (o["prev"] + c["prev"]) if (o["prev"] is not None and c["prev"] is not None) else None
    res["fcf"] = {"cur": fc, "prev": fp, "yoy": ((fc / fp - 1) * 100) if (fc is not None and fp not in (None, 0)) else None}
    res.update({"cur_date": pe, "yoy_date": ppe, "partial_yoy": ppe is None,
                "source": "SEC 8-K 財報新聞稿（未經審計）"})
    json.dump(res, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    tk = sys.argv[1] if len(sys.argv) > 1 else "MU"
    r = quarterly_from_release(tk, use_cache="--fresh" not in sys.argv)
    if not r:
        print(f"{tk}: 沒有可用的新聞稿數字")
        sys.exit(0)
    print(f"{tk} 期末 {r['cur_date']}　去年同期 {r['yoy_date']}　來源 {r['url']}")
    for f in ("revenue", "gross", "op_income", "net_income", "eps", "ocf", "capex", "fcf"):
        v = r[f]
        fmt = (lambda x: f"{x:,.2f}") if f == "eps" else (lambda x: f"{x / 1e6:,.1f}M")
        print(f"  {f:10s} {fmt(v['cur']) if v['cur'] is not None else '—':>14} "
              f"{fmt(v['prev']) if v['prev'] is not None else '—':>14} "
              f"{(str(round(v['yoy'], 1)) + '%') if v['yoy'] is not None else '—':>8}")
    for d in r.get("_dropped", []):
        print("  ✖ 丟棄", d)
