# -*- coding: utf-8 -*-
"""美股財報新聞稿 ← SEC EDGAR 8-K（Item 2.02 的 EX-99.1），公布當下就有（2026-10-01）

**為什麼要有這支**：Leo 10/1 拿第三方工具（StockPulse）的美光財報貼文來比，發現他們公布後
幾分鐘就有「營收 vs 預期、各事業部營收、每股股利、指引區間」，我們要等隔天 06:00 而且只有
每股盈餘一項。差在資料源：他們讀 SEC 8-K 新聞稿，我們等 yfinance／XBRL 財務資料庫
（那兩個要隔天到年報／季報送出才跟上，見 sec_quarterly.py 檔頭）。

**做法（零成本）**：SEC 免費；解析用本機 claude -p（Max，不是 API 計費）。
**防亂編**：LLM 只負責「指出哪個數字在哪句話」，每一筆都要附原文引句；程式驗證 ①引句真的
出現在新聞稿裡 ②引句裡有一個數字換算後跟它回報的值對得上（容許四捨五入）。驗不過的整筆丟棄，
寧可少一個欄位也不推錯數字。YoY／QoQ 等衍生數字一律程式算，不給 LLM 算。

用法:
    from sec_release import latest_release, parse_release
    rel = latest_release("MU", since_days=7)     # 沒有新聞稿回 None
    facts = parse_release(rel)                    # {key: {"value", "unit", "quote"}}
"""
import json
import os
import re
import subprocess
import sys
import time
import html as _html
import urllib.request
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sec_edgar as SE

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "sec_releases")

# 允許 LLM 回報的欄位。數值單位固定：金額＝百萬美元、每股＝美元、比率＝百分比。
KEYS = {
    "revenue": "本季營收（百萬美元）",
    "revenue_prev_q": "上一季營收（百萬美元）",
    "revenue_prev_y": "去年同季營收（百萬美元）",
    "eps_gaap": "本季 GAAP 稀釋每股盈餘（美元）",
    "eps_nongaap": "本季非 GAAP 稀釋每股盈餘（美元）",
    "eps_nongaap_prev_y": "去年同季非 GAAP 稀釋每股盈餘（美元）",
    "gross_margin_nongaap_pct": "本季非 GAAP 毛利率（%）",
    "gross_margin_gaap_pct": "本季 GAAP 毛利率（%）",
    "op_cash_flow": "本季營運現金流（百萬美元）",
    "free_cash_flow": "本季自由現金流或調整後自由現金流（百萬美元）",
    "capex": "本季資本支出（百萬美元）",
    "dividend_per_share": "本次宣布的每股股利（美元）",
    "guide_revenue_mid": "下一季營收指引：新聞稿寫「X ± Y」或「約 X」時的 X（百萬美元）",
    "guide_revenue_pm": "下一季營收指引：「X ± Y」的 Y（百萬美元）",
    "guide_revenue_low": "下一季營收指引：新聞稿寫「between A and B」時的 A（百萬美元）",
    "guide_revenue_high": "下一季營收指引：「between A and B」的 B（百萬美元）",
    "guide_eps_mid": "下一季非 GAAP 每股盈餘指引：「X ± Y」或「約 X」的 X（美元）",
    "guide_eps_pm": "下一季非 GAAP 每股盈餘指引：「X ± Y」的 Y（美元）",
    "guide_eps_low": "下一季非 GAAP 每股盈餘指引：「between A and B」的 A（美元）",
    "guide_eps_high": "下一季非 GAAP 每股盈餘指引：「between A and B」的 B（美元）",
    "guide_gross_margin_pct": "下一季非 GAAP 毛利率指引（%）",
}
# 事業部另外處理：key 形如 "seg:事業部名稱"（本季營收）、"segpy:事業部名稱"（去年同季營收），百萬美元


def _get_text(url, timeout=60):
    SE._throttle()
    req = urllib.request.Request(url, headers=SE.UA)
    return urllib.request.urlopen(req, timeout=timeout, context=SE._CTX).read().decode("utf-8", "ignore")


def _html_to_text(raw):
    t = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def latest_release(ticker, since_days=7):
    """最近 since_days 天內、Item 2.02 的 8-K 財報新聞稿。回 {ticker, filed, accession, url, text}，沒有回 None。"""
    cik = SE._load_cik_map().get(ticker.upper())
    if not cik:
        return None
    try:
        subs = SE._get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    except Exception:                                    # noqa: BLE001
        return None
    rec = subs.get("filings", {}).get("recent", {})
    cut = (date.today() - timedelta(days=since_days)).isoformat()
    for i, form in enumerate(rec.get("form", [])):
        if form != "8-K" or rec["filingDate"][i] < cut:
            continue
        if "2.02" not in (rec.get("items", [""] * (i + 1))[i] or ""):
            continue
        acc = rec["accessionNumber"][i]
        folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
        doc = None
        try:
            # 申報頁面明列每個附件的類型；新聞稿一定是 EX-99.1（檔名各家不同，不能靠檔名猜：
            # NVDA q2fy27pr.htm、TSLA exhibit991.htm、MU a2026q4ex991-pressrelease.htm）
            idx_html = _get_text(f"{folder}/{acc}-index.htm")
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", idx_html, re.S):
                if re.search(r">\s*EX-99\.1\s*<", row):
                    m = re.search(r'href="[^"]*/([^"/]+\.htm[l]?)"', row)
                    if m:
                        doc = m.group(1)
                        break
        except Exception:                                # noqa: BLE001
            doc = None
        if not doc:
            continue                                     # 沒有 EX-99.1 就不是財報新聞稿（可能只是封面頁）
        try:
            text = _html_to_text(_get_text(f"{folder}/{doc}"))
        except Exception:                                # noqa: BLE001
            continue
        return {"ticker": ticker.upper(), "filed": rec["filingDate"][i], "accession": acc,
                "url": f"{folder}/{doc}", "text": text}
    return None


# ───────────────────────────── 解析＋驗證 ─────────────────────────────

def _nums_in(quote):
    out = []
    for m in re.finditer(r"\(?\$?\s*(\d[\d,]*\.?\d*)\s*(billion|million|%)?", quote, re.I):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append((v, (m.group(2) or "").lower()))
    return out


def _quote_supports(value, unit, quote):
    """引句裡是否有一個數字，換算成同單位後跟 value 在 0.1% 內（容許四捨五入、billion↔million；太鬆會讓同一列的相鄰欄位對調也通過）。"""
    for v, suf in _nums_in(quote):
        cands = [v]
        if suf == "billion":
            cands.append(v * 1000)
        elif suf == "million":
            cands.append(v)
        else:
            cands += [v / 1000, v * 1000, v / 1e6]          # 表格「54,229」＝百萬、或原值為元
        for c in cands:
            if value == 0 and c == 0:
                return True
            if value and abs(c - value) / abs(value) <= 0.001:
                return True
    return False


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def verify(facts, text):
    """丟掉引句不在原文、或引句裡找不到對應數字的欄位。回 (通過, 被丟掉的清單)。"""
    t = _norm(text)
    ok, bad = {}, []
    for f in facts:
        k, v, q = f.get("key"), f.get("value"), _norm(f.get("quote") or "")
        if not k or v is None or not q:
            bad.append((k, "缺值或缺引句"))
            continue
        if not (k in KEYS or k.startswith(("seg:", "segpy:"))):
            bad.append((k, "不在允許欄位"))
            continue
        if q not in t:
            bad.append((k, "引句不在原文"))
            continue
        if not _quote_supports(float(v), f.get("unit"), q):
            bad.append((k, f"引句裡找不到對應 {v}"))
            continue
        ok[k] = {"value": float(v), "quote": q}
    return ok, bad


def _claude_json(prompt, schema, timeout=300):
    from llm_board import _claude_bin
    exe = _claude_bin()
    if not exe:
        return None
    r = subprocess.run([exe, "-p", "--dangerously-skip-permissions", "--output-format", "json",
                        "--json-schema", json.dumps(schema, ensure_ascii=False)],
                       input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if r.returncode != 0:
        return None
    return (json.loads(r.stdout) or {}).get("structured_output")


def parse_release(rel, use_cache=True):
    """財報新聞稿 → 驗證過的 {key: {value, quote}}。同一份只叫一次 claude（結果快取在 state/sec_releases）。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = os.path.join(CACHE_DIR, f"{rel['ticker']}_{rel['filed']}.json")
    if use_cache and os.path.exists(cp):
        return json.load(open(cp, encoding="utf-8"))
    schema = {"type": "object", "properties": {
        "period": {"type": "string", "description": "這份新聞稿的財報期間，例如 fiscal Q4 2026"},
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "value": {"type": "number"},
            "unit": {"type": "string", "enum": ["USD_million", "USD_per_share", "percent"]},
            "quote": {"type": "string"}}, "required": ["key", "value", "unit", "quote"]}}},
        "required": ["facts"]}
    keys_txt = "\n".join(f"- {k}：{v}" for k, v in KEYS.items())
    prompt = f"""你是財報數據擷取員。下面是 {rel['ticker']} 在 {rel['filed']} 公布的財報新聞稿全文。
請只擷取下列欄位，**只用新聞稿裡明確寫出的數字，沒寫就不要回報該欄位，禁止自己計算或推測**：
{keys_txt}
- seg:事業部名稱（每個事業部一筆，本季營收，百萬美元）、segpy:事業部名稱（同事業部去年同季營收）。事業部名稱照新聞稿原文。

每一筆都要附 quote：**新聞稿原文裡一字不差的連續片段**（不超過 80 字元，要包含該數字，
表格就複製那一列的文字，不要改寫、不要換行補字）。數字單位換算成：金額＝百萬美元（54.23 billion → 54230）、
每股＝美元、比率＝百分比。若新聞稿金額本來就以百萬為單位的表格（如 54,229）就直接用 54229。
GAAP／非 GAAP 要分清楚。指引寫「$61.5 billion ± $1.5 billion」→ mid=61500、pm=1500；寫「between $2.160 – $2.164 billion」→ low=2160、high=2164（**不要自己算中值**）。

新聞稿全文：
{rel['text'][:90000]}"""
    out = _claude_json(prompt, schema)
    if not out:
        return None
    ok, bad = verify(out.get("facts", []), rel["text"])
    res = {"period": out.get("period", ""), "facts": ok, "dropped": bad,
           "filed": rel["filed"], "url": rel["url"], "accession": rel["accession"]}
    json.dump(res, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    tk = sys.argv[1] if len(sys.argv) > 1 else "MU"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    rel = latest_release(tk, days)
    if not rel:
        print(f"{tk} 近 {days} 天沒有 Item 2.02 財報新聞稿")
        sys.exit(0)
    print(f"{tk} 新聞稿 {rel['filed']} {rel['url']}（{len(rel['text'])} 字）")
    r = parse_release(rel, use_cache=False)
    if not r:
        print("解析失敗")
        sys.exit(1)
    print("期間:", r["period"])
    for k, v in r["facts"].items():
        print(f"  ✅ {k}: {v['value']:g}   「{v['quote'][:70]}」")
    for k, why in r["dropped"]:
        print(f"  ✖ 丟棄 {k}：{why}")


# ───────────────────────────── 快訊格式 ─────────────────────────────

def _yi(m, nd=1):
    """百萬美元 → 億美元字串。"""
    return f"{m / 100:,.{nd}f} 億美元"


def _chg(a, b):
    if a is None or not b:
        return None
    return a / b - 1


def _pct(x, nd=0):
    return f"{x:+,.{nd}%}" if x is not None else ""


def _val(facts, k):
    f = facts.get(k)
    return f["value"] if f else None


def _segments(facts):
    """回 [(名稱, 本季, 去年同季)]；各事業部加總跟總營收差超過 5% 就整組不用（多半是漏抓或抓錯欄）。"""
    segs = []
    for k, f in facts.items():
        if k.startswith("seg:"):
            nm = k[4:]
            segs.append((nm, f["value"], _val(facts, "segpy:" + nm)))
    rev = _val(facts, "revenue")
    if not segs or not rev:
        return []
    tot = sum(s[1] for s in segs)
    if tot < rev * 0.95 or tot > rev * 1.05:
        return []
    return sorted(segs, key=lambda s: -s[1])


def _rng(facts, pre, unit_fmt):
    """指引文字＋中值（給跟共識比用）。pre＝'revenue' 或 'eps'。"""
    mid, pm = _val(facts, f"guide_{pre}_mid"), _val(facts, f"guide_{pre}_pm")
    lo, hi = _val(facts, f"guide_{pre}_low"), _val(facts, f"guide_{pre}_high")
    if mid is not None and pm:
        return f"{unit_fmt(mid)}±{unit_fmt(pm)}", mid
    if lo is not None and hi is not None:
        return f"{unit_fmt(lo)}～{unit_fmt(hi)}", (lo + hi) / 2
    if mid is not None:
        return f"約 {unit_fmt(mid)}", mid
    return None, None


def format_facts(parsed, eps_cons=None, rev_cons=None, next_eps_pre=None):
    """驗證過的新聞稿欄位 → 快訊文字行（純函式，不連網）。
    eps_cons／rev_cons：**這次公布的那一季**公布前的共識（用來比本季實際）。
    next_eps_pre：**下一季**在公布前的 EPS 共識（用來比下季指引）。
    三個都是「沒有就不比」，不拿公布後已上修的數字充數；兩種共識是不同季度，不能混用。"""
    F = parsed["facts"]
    out = []
    rev, rq, ry = _val(F, "revenue"), _val(F, "revenue_prev_q"), _val(F, "revenue_prev_y")
    if rev is not None:
        s = f"　① 營收 {_yi(rev)}"
        yoy, qoq = _chg(rev, ry), _chg(rev, rq)
        if yoy is not None:
            s += f"｜年增 {_pct(yoy)}"
        if qoq is not None:
            s += f"｜季增 {_pct(qoq)}"
        if rev_cons:
            s += f"｜公布前共識 {_yi(rev_cons / 1e6)}（{_pct(rev / (rev_cons / 1e6) - 1, 1)}）"
        out.append(s)
    eps = _val(F, "eps_nongaap")
    gm = _val(F, "gross_margin_nongaap_pct")
    s2 = []
    if eps is not None:
        t = f"每股盈餘（非GAAP）{eps:.2f}"
        if _val(F, "eps_nongaap_prev_y"):
            t += f"，年增 {_pct(_chg(eps, _val(F, 'eps_nongaap_prev_y')))}"
        if eps_cons:
            t += f"｜公布前共識 {eps_cons:.2f}（{_pct(eps / eps_cons - 1, 1)}）"
        s2.append(t)
    if _val(F, "eps_gaap") is not None and eps is None:
        s2.append(f"每股盈餘（GAAP）{_val(F, 'eps_gaap'):.2f}")
    if gm is None and _val(F, "gross_margin_gaap_pct") is not None:
        s2.append(f"毛利率（GAAP）{_val(F, 'gross_margin_gaap_pct'):.1f}%")
    if gm is not None:
        t = f"毛利率（非GAAP）{gm:.1f}%"
        if _val(F, "gross_margin_gaap_pct") is not None and abs(_val(F, "gross_margin_gaap_pct") - gm) > 0.05:
            t += f"（GAAP {_val(F, 'gross_margin_gaap_pct'):.1f}%）"
        s2.append(t)
    if s2:
        out.append("　② " + "｜".join(s2))
    segs = _segments(F)
    if segs:
        parts = []
        for nm, v, py in segs:
            nm = re.sub(r"\s*Business Unit$", "", nm)
            g = _chg(v, py)
            parts.append(f"{nm} {v / 100:,.1f}" + (f"（{_pct(g)}）" if g is not None else ""))
        out.append("　③ 事業部營收（億美元，年增）：" + "｜".join(parts))
    cf = []
    if _val(F, "op_cash_flow") is not None:
        cf.append(f"營運現金流 {_yi(_val(F, 'op_cash_flow'))}")
    if _val(F, "free_cash_flow") is not None:
        cf.append(f"自由現金流 {_yi(_val(F, 'free_cash_flow'))}")
    if _val(F, "capex") is not None:
        cf.append(f"資本支出 {_yi(abs(_val(F, 'capex')))}")
    if _val(F, "dividend_per_share") is not None:
        cf.append(f"每股股利 {_val(F, 'dividend_per_share'):.2f} 美元")
    if cf:
        out.append("　④ " + "｜".join(cf))
    g = []
    rt, rmid = _rng(F, "revenue", lambda v: f"{v / 100:,.1f} 億")
    if rt:
        g.append(f"營收 {rt}")
    et, emid = _rng(F, "eps", lambda v: f"{v:.2f}")
    if et:
        t = f"每股盈餘 {et}"
        if emid and next_eps_pre:
            t += f"（比下季公布前共識 {next_eps_pre:.2f} {_pct(emid / next_eps_pre - 1, 1)}）"
        g.append(t)
    gg = _val(F, "guide_gross_margin_pct")
    if gg is not None:
        g.append(f"毛利率約 {gg:g}%" + (f"（本季 {gm:.1f}%）" if gm is not None else ""))
    if g:
        out.append("　⑤ 下季指引：" + "｜".join(g))
    return out
