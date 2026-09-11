# -*- coding: utf-8 -*-
"""每週總體市場報告：美股＋台股（2026-09-11，Leo 指定「結構、推論嚴謹」）。

## 為什麼是自己寫，不是裝套件

2026-09-11 查過一輪外部方案（GitHub 專案＋MCP server），結論是**沒有一個值得裝**：
  · OpenBB 只支援 Python 3.9–3.12，這台是 3.13，直接出局（而且是 AGPL）
  · FinRobot 寫死 OpenAI、要付費 FMP/Finnhub key——等於丟掉本機 claude 的零成本優勢
  · FRED 系的 MCP server 比直接 requests 多一層 Node runtime 跟一個陌生維護者，
    換到的功能是零
  · 有中繼站的（openecon-data／TWSEMCPServer 預設端點）會把查詢送到第三方，
    而且都有付費方案——不符合零成本與資料流向兩條硬規則
**真正缺的不是工具，是推論紀律**，那是 schema 設計問題，裝什麼都不會變嚴謹。

## 嚴謹是怎麼來的（兩個機制，都寫在 SCHEMA 裡強制）

1. **每個陳述要標 kind**：observed（程式算出來的數字）／inference（從數字推的）／
   speculation（猜的）。讀的人一眼看得出哪句話有數字撐、哪句沒有。
2. **每個判斷要帶 falsifier**：「這個看法錯了，如果 X 高於 Y」。沒有失效條件的
   判斷無法被證偽，下週也無從檢討——這跟 `advisor_reports.conditions_for()`
   對券商報告的要求是同一套紀律。

⭐ **數字一律由程式算，AI 只負責解讀**（同 `stock_brief` 的 biz 簡介：
「沒有給它任何數字」）。AI 看得到算好的數字，但不准自己生數字——
記憶 `advisor_reports_pipeline`：「能算的別讓 AI 用講的」。

## 成本

零。資料全部是官方免費端點（FRED 公開 CSV 免 key／證交所 openapi／
主計總處），產出走本機 claude（Max 訂閱額度，不是付費 API）。

用法:
    python macro_weekly.py            # 產出這一週的報告
    python macro_weekly.py --data     # 只印算出來的數字，不叫 AI（除錯用）
"""
import io
import os
import re
import sys
import json
import argparse
import datetime as dt

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op
from llm_board import _claude_bin

SNAP = "state/macro_weekly.json"      # 上週快照，用來算「跟上週差多少」
OUT_NAME = "每週總體報告.html"


# ── 資料層：FRED ────────────────────────────────────────────────────
# 🔴 用**公開 CSV 端點**，不是 api.stlouisfed.org——公開 CSV 免申請 key。
#    2026-09-11 實測這 6 個數列全部抓得到（gdp_fetch.py 抓 GDPC1 走的是同一條路，
#    連 FRED 擋 Python TLS 指紋的 curl 備援都已經寫好了，直接複用不重寫）。
# freq 決定要用「週變化」還是「月變化」——⚠️ 月頻數列給週變化是假訊息：
# UNRATE 一個月才一筆，7 天前跟 30 天前常常是同一筆，算出來永遠是 0.0，
# 看起來像「這週沒變」，實際上是「這週本來就沒有新資料」。兩者意思完全不同。
FRED = {
    "T10Y2Y":       ("殖利率曲線 10Y−2Y", "%",   "level", "d"),
    "DGS10":        ("美國10年期公債殖利率", "%", "level", "d"),
    "DGS2":         ("美國2年期公債殖利率", "%",  "level", "d"),
    "BAMLH0A0HYM2": ("高收益債利差 OAS", "%",     "level", "d"),
    "DTWEXBGS":     ("美元指數（廣義）", "",      "level", "d"),
    "UNRATE":       ("美國失業率", "%",           "level", "m"),
    "CPIAUCSL":     ("美國CPI", "% YoY",          "yoy",   "m"),
}


def fred_rows(sid):
    """回 [(date, float)]，由舊到新。FRED 的缺值是 '.'，直接丟掉。"""
    import gdp_fetch
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    txt = gdp_fetch._get_text_curl_fallback(url)
    out = []
    for ln in txt.strip().splitlines()[1:]:
        parts = ln.split(",")
        if len(parts) < 2:
            continue
        d, v = parts[0].strip(), parts[-1].strip()
        if v in (".", ""):
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    return out


def _pick_back(rows, days):
    """回「約 N 天前」那一筆的值。找不到剛好那天就取最接近且不晚於它的。"""
    if not rows:
        return None
    target = dt.date.fromisoformat(rows[-1][0]) - dt.timedelta(days=days)
    prev = None
    for d, v in rows:
        if dt.date.fromisoformat(d) <= target:
            prev = v
        else:
            break
    return prev


def fred_block():
    """全部 FRED 數列 → {sid: {label, unit, latest, date, wow, mom}}。

    ⚠️ 抓不到的數列**留 None 並記 error**，不要靜默跳過——下游報告要看得出
    「這項沒有資料」跟「這項沒有變化」的差別。
    """
    out = {}
    for sid, (label, unit, kind, freq) in FRED.items():
        try:
            rows = fred_rows(sid)
        except Exception as e:                              # noqa: BLE001
            out[sid] = {"label": label, "unit": unit, "error": str(e)[:80]}
            print(f"  ⚠️ FRED {sid} 抓不到：{str(e)[:60]}")
            continue
        if not rows:
            out[sid] = {"label": label, "unit": unit, "error": "空資料"}
            continue
        date, latest = rows[-1]
        rec = {"label": label, "unit": unit, "date": date,
               "freq": "每日" if freq == "d" else "每月"}
        if kind == "yoy":
            # CPI 是指數不是變動率，要自己換算年增率（跟去年同月比）
            base = _pick_back(rows, 365)
            rec["latest"] = round((latest / base - 1) * 100, 2) if base else None
            prev_m = _pick_back(rows, 31)
            base_pm = _pick_back(rows, 31 + 365)
            if prev_m and base_pm and rec["latest"] is not None:
                rec["delta"] = round(rec["latest"] - (prev_m / base_pm - 1) * 100, 2)
                rec["delta_label"] = "較上月"
        else:
            rec["latest"] = latest
            back = 7 if freq == "d" else 31
            prev = _pick_back(rows, back)
            if prev is not None:
                rec["delta"] = round(latest - prev, 3)
                rec["delta_label"] = "較上週" if freq == "d" else "較上月"
        out[sid] = rec
        print(f"  FRED {sid:14} {rec.get('latest')}")
    return out


# ── 資料層：本機既有資料（不重抓，讀每日排程已經算好的）──────────────
def _load(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def tw_block():
    """台股：電金比體溫計＋三大法人＋加權指數。"""
    out = {}
    try:
        import market_thermometer as mt
        st = mt.status()
        if st:
            out["ef_ratio"] = {
                "ratio": st.get("ratio"), "ma100": st.get("ma"),
                "below_ma": st.get("below"), "streak_days": st.get("streak"),
                "elec": st.get("elec"), "fin": st.get("fin"),
                "date": st.get("latest_date"),
            }
    except Exception as e:                                  # noqa: BLE001
        print(f"  ⚠️ 電金比讀不到：{str(e)[:60]}")
    md = _load("market_data.json", {})
    out["inst_flow_yi"] = md.get("inst")            # 三大法人買賣超（億元）
    out["indices"] = md.get("indices") or []
    out["news"] = [h for h in (md.get("news") or [])][:10]
    return out


def gdp_block():
    g = _load("gdp_data.json", {})
    return {k: g.get(k) for k in ("us", "tw", "asof", "updated") if k in g}


def rrg_block():
    """RRG 四象限分布：不是列出每個類股，是算「多少比例在強勢象限」。

    ⚠️ 取 60 日窗口（中期）：20 日太雜訊、240 日對週報來說太鈍。
    """
    h = _load("industry_rotation_history.json", {})
    out = {}
    for mkt in ("us", "tw"):
        series = (h.get(mkt) or {}).get("index") or []
        if not series:
            continue
        snap = series[-1].get("snapshot") or {}
        cnt, lead, lag = {}, [], []
        for key, v in snap.items():
            q = ((v.get("periods") or {}).get("60") or {}).get("quadrant")
            if not q:
                continue
            cnt[q] = cnt.get(q, 0) + 1
            nm = v.get("name") or key
            if q == "leading":
                lead.append(nm)
            elif q == "lagging":
                lag.append(nm)
        out[mkt] = {"date": series[-1].get("date"), "counts": cnt,
                    "n": sum(cnt.values()),
                    "leading": sorted(lead)[:8], "lagging": sorted(lag)[:8]}
    return out


def calendar_block():
    try:
        import macro_calendar as mc
        return {"recent": mc.upcoming_events(days_before=7, days_after=0),
                "ahead": mc.upcoming_events(days_before=0, days_after=10)}
    except Exception as e:                                  # noqa: BLE001
        print(f"  ⚠️ 總經行事曆讀不到：{str(e)[:60]}")
        return {}


def gather():
    print("抓資料…", flush=True)
    facts = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "week_of": dt.date.today().isoformat(),
        "us_macro": fred_block(),
        "tw": tw_block(),
        "gdp": gdp_block(),
        "rrg": rrg_block(),
        "calendar": calendar_block(),
    }
    facts["vs_last_week"] = _diff_last(facts)
    # ⚠️ 同一件事有兩個來源時要明講，否則 AI 會把「資料日不同」當成「數字互相矛盾」。
    # 實測：FRED DGS10（官方，落後1-2天）跟 yfinance ^TNX（即時）同一天可以差 0.1%，
    # 兩個都對，只是量的不是同一天。
    facts["data_notes"] = [
        "美債10年期在這份資料裡出現兩次：FRED 的 DGS10 是官方定盤價、會落後 1-2 個交易日；"
        "indices 裡的 ^TNX 是 yfinance 即時報價。兩者不同不是矛盾，是資料日不同，"
        "引用時要講清楚是哪一個。",
        "每月頻率的數列（失業率、CPI）標的是「較上月」，不是「較上週」——"
        "一個月才一筆，沒有週變化可言。",
    ]
    return facts


def _diff_last(facts):
    """跟上週快照比。第一次跑沒有上週檔案 → 明講「無對照」，不要裝作沒事。"""
    prev = _load(SNAP, None)
    if not prev:
        return {"available": False, "reason": "首次產出，沒有上週快照可比"}
    out = {"available": True, "prev_week": prev.get("week_of"), "moved": {}}
    for sid, cur in (facts.get("us_macro") or {}).items():
        old = (prev.get("us_macro") or {}).get(sid) or {}
        if cur.get("latest") is None or old.get("latest") is None:
            continue
        d = round(cur["latest"] - old["latest"], 3)
        if d:
            out["moved"][sid] = {"label": cur.get("label"),
                                 "from": old["latest"], "to": cur["latest"], "delta": d}
    pe = (prev.get("tw") or {}).get("ef_ratio") or {}
    ce = (facts.get("tw") or {}).get("ef_ratio") or {}
    if pe.get("ratio") and ce.get("ratio"):
        out["ef_ratio"] = {"from": pe["ratio"], "to": ce["ratio"],
                           "delta": round(ce["ratio"] - pe["ratio"], 4)}
    return out


# ── AI 解讀層：schema 強制「標來源」＋「帶失效條件」─────────────────
_CLAIM = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "一句話，繁體中文"},
        "kind": {"type": "string", "enum": ["observed", "inference", "speculation"],
                 "description": "observed=直接引用給你的數字；inference=從數字推出來的；speculation=沒有數字支撐的推測"},
        "basis": {"type": "string", "description": "依據哪個數字或哪項事實；speculation 就寫「無數據支撐」"},
    },
    "required": ["text", "kind", "basis"],
}

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "整份報告的結論，一句話講完，繁體中文"},
        "week_change": {"type": "string", "description": "這週跟上週相比最重要的變化；沒有上週資料就寫「首次產出，無對照」"},
        "sections": {
            "type": "array",
            "description": "依序：政策與利率／通膨與成長／市場定價／台灣專章",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "claims": {"type": "array", "items": _CLAIM, "minItems": 2, "maxItems": 5},
                },
                "required": ["title", "claims"],
            },
            "minItems": 3, "maxItems": 5,
        },
        "views": {
            "type": "array",
            "description": "這週的判斷。每一條都必須帶失效條件——不能被證偽的判斷不要寫",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "判斷本身，繁體中文"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "falsifier": {"type": "string",
                                  "description": "什麼情況代表這個判斷錯了，要具體到數字或事件，例如「10Y-2Y 倒掛回到 -0.2% 以下」"},
                },
                "required": ["claim", "confidence", "falsifier"],
            },
            "minItems": 2, "maxItems": 5,
        },
        "watch_next": {"type": "array", "items": {"type": "string"},
                       "description": "下週要盯的事，對照行事曆", "maxItems": 6},
        "blind_spots": {"type": "array", "items": {"type": "string"},
                        "description": "這份報告看不到的東西（資料缺口），誠實列出", "maxItems": 4},
    },
    "required": ["headline", "week_change", "sections", "views", "watch_next", "blind_spots"],
}

PROMPT = """你是一位總體經濟策略分析師，要寫一份給專業投資人看的**每週美股＋台股總體報告**。

下面是程式算好的數字。**你的工作是解讀，不是產生數字**：
- 不准寫出下面資料裡沒有的任何數字。要引用就引用給你的。
- 每個陳述都要標 kind：observed（直接引用給的數字）／inference（從給的數字推的）／
  speculation（沒有數字支撐）。**寧可標 speculation 也不要假裝有依據**。
- 每個判斷（views）都必須帶失效條件，而且要具體到數字或事件。
  不能被證偽的話不要寫進 views。
- 資料缺口要誠實寫進 blind_spots。例如沒有部位資料、沒有盈餘修正資料就講出來。

寫作風格參考 IMF WEO 第一章與 BIS 季報：先講基準情境，再講驅動力，再講雙向風險。
不要用「可能」「或許」灌水，要嘛有依據要嘛標 speculation。全部用繁體中文（台灣用語）。

=== 程式算好的資料 ===
{facts}
"""


def ask(facts):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    import subprocess
    prompt = PROMPT.format(facts=json.dumps(facts, ensure_ascii=False, indent=1))
    r = subprocess.run(
        [exe, "-p", "--dangerously-skip-permissions", "--output-format", "json",
         "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"claude 失敗 (exit {r.returncode}): {(r.stderr or '')[:300]}")
    out = json.loads(r.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude 回錯誤：{str(out)[:300]}")
    note = out.get("structured_output")
    if not note:
        raise RuntimeError(f"沒有 structured_output：{r.stdout[:300]}")
    return note


# ── 渲染：走 board_theme，不自己發明樣式 ─────────────────────────────
KIND = {
    "observed":    ("有數據", "ok"),
    "inference":   ("推論", "inf"),
    "speculation": ("推測·無數據", "spec"),
}

CSS = """
.mw{background:var(--card,#0C1524);border:1px solid var(--line,#16304A);border-radius:10px;
 padding:14px 16px;margin:12px 0}
.mw h2{color:var(--warn,#FFB627);font-size:15px;margin:0 0 8px}
.lead{border-left:3px solid var(--accent,#22D3EE)}
.lead .big{font-size:16px;line-height:1.7;color:var(--ink,#DCE7F5);font-weight:600}
.cl{margin:9px 0;line-height:1.8;display:flex;gap:8px;align-items:flex-start}
.tag{flex:0 0 auto;font-size:10px;padding:2px 7px;border-radius:4px;margin-top:3px;
 font-family:'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.04em;white-space:nowrap}
.tag.ok{background:#0E2417;color:#86EFAC;border:1px solid #166534}
.tag.inf{background:#0E1B2B;color:#9DB0C8;border:1px solid var(--line,#16304A)}
.tag.spec{background:#2E1418;color:#FCA5A5;border:1px solid #7F1D1D}
.cl .bs{color:var(--dim,#5B6E8A);font-size:11.5px}
.vw{border:1px solid var(--line,#16304A);border-radius:8px;padding:10px 12px;margin:9px 0;
 background:var(--line2,#0E1B2B)}
.vw .c{font-weight:600;color:var(--ink,#DCE7F5);line-height:1.7}
.vw .f{margin-top:6px;font-size:12px;color:#FCA5A5;line-height:1.6}
.vw .conf{font-size:10px;color:var(--dim,#5B6E8A);font-family:'IBM Plex Mono',ui-monospace,monospace}
table.mt{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
table.mt th{text-align:left;color:var(--dim,#5B6E8A);font-weight:600;font-size:11px;
 padding:5px 8px;border-bottom:1px solid var(--line,#16304A)}
table.mt td{padding:5px 8px;border-bottom:1px solid var(--line2,#0E1B2B)}
table.mt td.v{text-align:right;font-family:'IBM Plex Mono',ui-monospace,monospace;
 font-variant-numeric:tabular-nums}
.up{color:var(--up,#22C55E)}.dn{color:var(--down,#EF4444)}
.li{margin:6px 0;line-height:1.7}
.gap{color:var(--muted,#9DB0C8);font-size:12.5px}
"""


def _sign(v, unit=""):
    if v is None:
        return "—"
    cls = "up" if v > 0 else ("dn" if v < 0 else "")
    return f'<span class="{cls}">{v:+g}{unit}</span>'


def render(facts, note):
    from board_theme import BASE_CSS, esc, header

    um = facts.get("us_macro") or {}
    rows = []
    for sid, r in um.items():
        if r.get("error"):
            rows.append(f'<tr><td>{esc(r["label"])}</td><td class="v">—</td>'
                        f'<td class="v">—</td><td class="gap">抓不到：{esc(r["error"])}</td></tr>')
            continue
        unit = r.get("unit") or ""
        lat = r.get("latest")
        rows.append(
            f'<tr><td>{esc(r["label"])}</td>'
            f'<td class="v">{"—" if lat is None else f"{lat:g}"}{esc(unit if unit != "% YoY" else "%")}</td>'
            f'<td class="v">{_sign(r.get("delta"))}</td>'
            f'<td class="gap">{esc(r.get("delta_label") or "")}　{esc(r.get("date") or "")}</td></tr>')
    us_tbl = ('<table class="mt"><tr><th>指標</th><th style="text-align:right">最新</th>'
              '<th style="text-align:right">變化</th><th>比較基準／資料日</th></tr>'
              + "".join(rows) + "</table>")

    ef = (facts.get("tw") or {}).get("ef_ratio") or {}
    inst = (facts.get("tw") or {}).get("inst_flow_yi") or {}
    tw_bits = []
    if ef:
        tw_bits.append(
            f'電金比 <b>{ef.get("ratio")}</b>／100日均線 {ef.get("ma100")}'
            f'（{"低於" if ef.get("below_ma") else "高於"}均線連 {ef.get("streak_days")} 日）')
    if inst:
        tw_bits.append(
            f'三大法人 {inst.get("total_yi")} 億（外資 {inst.get("foreign_yi")} 億／'
            f'投信 {inst.get("trust_yi")} 億，{esc(str(inst.get("date") or ""))}）')
    rrg = facts.get("rrg") or {}
    for mkt, lab in (("us", "美股"), ("tw", "台股")):
        r = rrg.get(mkt)
        if r:
            c = r.get("counts") or {}
            tw_bits.append(f'{lab} RRG(60日)：領先 {c.get("leading",0)}／改善 {c.get("improving",0)}'
                           f'／弱化 {c.get("weakening",0)}／落後 {c.get("lagging",0)}　共 {r.get("n")} 類')

    secs = []
    for s in (note.get("sections") or []):
        cls = []
        for c in (s.get("claims") or []):
            lab, k = KIND.get(c.get("kind"), ("?", "inf"))
            cls.append(f'<div class="cl"><span class="tag {k}">{lab}</span>'
                       f'<span>{esc(c.get("text",""))}'
                       f'<br><span class="bs">依據：{esc(c.get("basis",""))}</span></span></div>')
        secs.append(f'<div class="mw"><h2>{esc(s.get("title",""))}</h2>{"".join(cls)}</div>')

    vws = "".join(
        f'<div class="vw"><div class="c">{esc(v.get("claim",""))}</div>'
        f'<div class="conf">信心 {esc(v.get("confidence",""))}</div>'
        f'<div class="f">✕ 失效條件：{esc(v.get("falsifier",""))}</div></div>'
        for v in (note.get("views") or []))

    watch = "".join(f'<div class="li">· {esc(x)}</div>' for x in (note.get("watch_next") or []))
    blind = "".join(f'<div class="li gap">· {esc(x)}</div>' for x in (note.get("blind_spots") or []))

    cal = (facts.get("calendar") or {}).get("ahead") or []
    cal_html = "".join(
        f'<div class="li">{esc(e.get("date",""))}　<b>{esc(e.get("market",""))}</b>　{esc(e.get("event",""))}</div>'
        for e in cal[:8]) or '<div class="gap">未來 10 天沒有排定的重大事件</div>'

    vs = facts.get("vs_last_week") or {}
    vs_html = ""
    if not vs.get("available"):
        vs_html = f'<div class="gap">{esc(vs.get("reason",""))}</div>'
    else:
        mv = vs.get("moved") or {}
        vs_html = "".join(
            f'<div class="li">{esc(m["label"])}：{m["from"]:g} → {m["to"]:g}　{_sign(m["delta"])}</div>'
            for m in mv.values()) or '<div class="gap">主要指標與上週持平</div>'

    sub = (f'{esc(facts.get("week_of",""))} 週　美股＋台股　'
           f'<br>數字全部由程式從官方來源算出，AI 只做解讀且每句標示依據強度')
    body = (
        f'<div class="mw lead"><h2>結論</h2><div class="big">{esc(note.get("headline",""))}</div>'
        f'<div class="cl" style="margin-top:10px"><span class="tag inf">跟上週比</span>'
        f'<span>{esc(note.get("week_change",""))}</span></div></div>'
        + f'<div class="mw"><h2>本週指標變化</h2>{vs_html}</div>'
        + "".join(secs)
        + f'<div class="mw"><h2>這週的判斷（每條都帶失效條件）</h2>{vws}</div>'
        + f'<div class="mw"><h2>美國總經數字</h2>{us_tbl}</div>'
        + f'<div class="mw"><h2>台股與資金結構</h2>'
        + "".join(f'<div class="li">{b}</div>' for b in tw_bits) + '</div>'
        + f'<div class="mw"><h2>下週行事曆</h2>{cal_html}</div>'
        + f'<div class="mw"><h2>下週要盯</h2>{watch}</div>'
        + f'<div class="mw"><h2>這份報告看不到的東西</h2>{blind}</div>')

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>每週總體報告</title><style>' + BASE_CSS + CSS
            + '</style></head><body><div class="wrap">'
            + header("gdp", "每週總體報告", sub, [], eyebrow="MACRO WEEKLY")
            + body + "</div></body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="store_true", help="只印算出來的數字，不叫 AI")
    ap.add_argument("--weekly", action="store_true",
                    help="排程用：只有週六才真的跑，其餘日子直接結束（exit 0）")
    ap.add_argument("-o", "--output", default="")
    a = ap.parse_args()

    # ⚠️ 星期幾的判斷放在 Python 不放 .cmd：cmd 的 %DATE% 格式跟系統地區設定綁定，
    #    在不同語系機器上剖析方式不一樣，是典型會靜默壞掉的東西。
    # 週六跑的理由：美股週五收盤已經入帳，整週資料完整，而且 Leo 週末讀得到、
    #    趕得上下週一開盤。
    if a.weekly and dt.date.today().weekday() != 5:       # 0=一 … 5=六
        print(f"今天是週{'一二三四五六日'[dt.date.today().weekday()]}，"
              f"每週總體報告只在週六產出，跳過。")
        return 0

    facts = gather()
    if a.data:
        print(json.dumps(facts, ensure_ascii=False, indent=1))
        return 0

    print("叫本機 claude 解讀（Max 訂閱額度，不是付費 API）…", flush=True)
    note = ask(facts)
    html = render(facts, note)
    out = a.output or op.daily(OUT_NAME)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)

    # 存這週快照，下週才算得出「跟上週差多少」
    os.makedirs(os.path.dirname(SNAP) or ".", exist_ok=True)
    json.dump(facts, io.open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"✅ 已存 {out}（{len(html):,} bytes）")
    print(f"   結論：{note.get('headline','')[:70]}")
    print(f"   判斷 {len(note.get('views') or [])} 條（都帶失效條件）｜"
          f"資料缺口 {len(note.get('blind_spots') or [])} 項")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
