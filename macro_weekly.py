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
            # ⚠️ 帶一個中文 label：不然 AI 會直接把欄位名 `ef_ratio` 寫進報告正文
            #    （實測發生過）。內部欄位名不該出現在給人看的句子裡。
            out["ef_ratio"] = {
                "指標名稱": "電金比（電子類指數÷金融類指數）",
                "ratio": st.get("ratio"), "ma100": st.get("ma"),
                "below_ma": st.get("below"), "streak_days": st.get("streak"),
                "elec": st.get("elec"), "fin": st.get("fin"),
                "date": st.get("latest_date"),
            }
    except Exception as e:                                  # noqa: BLE001
        print(f"  ⚠️ 電金比讀不到：{str(e)[:60]}")
    md = _load("market_data.json", {})
    out["inst_flow_yi"] = md.get("inst")            # 三大法人買賣超（億元）
    # 🔴 2026-09-11 Leo：「^TNX 那段看不懂」。原本把 yfinance 的 ^TNX（即時 4.94）
    # 跟 FRED DGS10（官方定盤 4.83，晚 1-2 天）**兩個都餵給 AI**，還附註解說明差異，
    # 結果 AI 照實寫了一整句在報告裡解釋兩者為何不同——那是**我的管線問題，
    # 不是讀報告的人該看的東西**。同一個利率只留一個來源（FRED 官方定盤），
    # 在這裡就濾掉，不要讓它有機會變成報告裡的一句話。
    # ⭐ 教訓：資料層自己能解決的歧義，不要丟給 AI「解釋一下」。
    out["indices"] = [i for i in (md.get("indices") or [])
                      if i.get("sym") != "^TNX"]
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
    facts["data_notes"] = [
        "每月頻率的數列（失業率、CPI）標的是「較上月」，不是「較上週」——"
        "一個月才一筆，沒有週變化可言。",
        "這些註記是給你判讀用的前提，**不要寫進報告內容**——讀報告的人不需要知道"
        "資料管線怎麼運作。",
        "⚠️ 引用指標時用**中文名稱**（例如「電金比」），不要把程式的欄位名"
        "（ef_ratio、inst_flow_yi 之類）寫進給人看的句子裡。",
    ]
    return facts


MIN_GAP_DAYS = 4        # 快照要離今天這麼多天，才配稱作「上週」


def _diff_last(facts):
    """跟**上週**的快照比。

    🔴 2026-09-11 修：原本快照是單一檔案、每跑一次就覆蓋，所以同一天跑第二次時
    「上週」其實是「20 分鐘前」，標題卻還寫「跟上週比」——而且那一版 AI 寫
    「首次產出無對照」、程式算出來的表卻有差異數字，**同一頁兩個說法打架**
    （跟 dev_log 記過的「卡片與圖不同天」是同一種錯）。
    改成快照按日期存，比對時只取**至少 4 天前**的那一份；找不到就誠實說沒有。
    """
    hist = _load(SNAP, {}) or {}
    if not isinstance(hist, dict) or "us_macro" in hist:
        hist = {}                       # 舊格式（單筆快照）直接丟掉，不硬轉
    today = dt.date.today()
    cand = [(d, v) for d, v in hist.items()
            if (today - dt.date.fromisoformat(d)).days >= MIN_GAP_DAYS]
    prev = max(cand)[1] if cand else None
    if not prev:
        n = len(hist)
        return {"available": False,
                "reason": (f"還沒有 {MIN_GAP_DAYS} 天以前的快照可比"
                           f"（目前存了 {n} 份，最舊的也太近）") if n else
                          "首次產出，沒有上週快照可比"}
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

# 🔴 2026-09-11 Leo：「看不出市場是積極還是保守」。
# 原本只有一段 headline 把五件事塞進一句話，讀完不知道結論是什麼。
# 改成**強制先表態**：stance 是列舉，AI 只能選一個，躲不掉。
STANCE = ["積極", "偏積極", "中性", "偏保守", "保守"]

_ANGLE = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "角度名稱"},
        "verdict": {"type": "string", "enum": STANCE, "description": "這個角度的表態"},
        "reason": {"type": "string", "description": "理由，最多兩句，繁體中文"},
        "falsifier": {"type": "string",
                      "description": "什麼情況代表這個角度錯了，要具體到數字或事件"},
    },
    "required": ["name", "verdict", "reason", "falsifier"],
}

_MARKET = {
    "type": "object",
    "properties": {
        "stance": {"type": "string", "enum": STANCE,
                   "description": "這個市場整體該積極還是保守。只能選一個，不准騎牆"},
        "headline": {"type": "string",
                     "description": "一句話講完結論，40字以內，先講判斷。不要把多件事塞進同一句"},
        "stance_basis": {"type": "string",
                         "description": "這個表態最主要的依據是哪一個數字，一句話"},
        "angles": {
            "type": "array",
            "description": "兩個獨立角度：結構面（政策/通膨/成長，年為單位）與 資金面"
                           "（利差/流向/輪動，週為單位）。⚠️ 兩邊獨立判斷，"
                           "就算結論相反也照實寫，不要為了看起來一致而修改任一邊",
            "items": _ANGLE, "minItems": 2, "maxItems": 2,
        },
        "claims": {"type": "array", "items": _CLAIM, "minItems": 3, "maxItems": 6,
                   "description": "支撐上面判斷的事實與推論"},
    },
    "required": ["stance", "headline", "stance_basis", "angles", "claims"],
}

SCHEMA = {
    "type": "object",
    "properties": {
        "us": _MARKET,
        "tw": _MARKET,
        "linkage": {"type": "string",
                    "description": "美股與台股這週的連動關係，一句話。若兩邊表態不同要說明為什麼"},
        "week_change": {"type": "string",
                        "description": "**只准根據 vs_last_week 這個欄位寫**："
                                       "available=false 就照抄它的 reason，不要自己補充；"
                                       "available=true 就講 moved 裡最重要的那一兩項變化"},
        "watch_next": {"type": "array", "items": {"type": "string"},
                       "description": "下週要盯的事，對照行事曆", "maxItems": 6},
        "blind_spots": {"type": "array", "items": {"type": "string"},
                        "description": "這份報告看不到的東西（資料缺口），誠實列出", "maxItems": 4},
    },
    "required": ["us", "tw", "linkage", "week_change", "watch_next", "blind_spots"],
}

# 🔴 角色直接沿用 war_room 的「孔明」persona，**不另外發明一個分析師**
# （2026-09-11 Leo：「可以讓孔明來判斷嗎？」）。
# ⭐ 為什麼這個角色正好對症：孔明的鐵律本來就是「**先講判斷再講理由**，理由最多兩句」
#    與「最重要的一句話永遠是『什麼情況代表我錯了』」——Leo 抱怨的
#    「看不出積極還是保守」「寫得雜亂」，就是原本那版少了這兩條紀律。
# ⚠️ 他原本的職務是判斷**一檔股票**的兩個角度；這裡把對象換成**一個市場**，
#    但兩個角度必須獨立、相反也照實寫這條規矩原封不動搬過來。
def _kongming_persona():
    """從 war_room 讀孔明的 persona，讀不到就用精簡版——**不維護第二份人設**。"""
    try:
        import war_room
        p = (war_room.ROLES.get("孔明") or {}).get("persona")
        if p:
            return p
    except Exception:                                       # noqa: BLE001
        pass
    return ("你是隆中對的投資長「孔明」。你條理分明、兩面並陳，**先講判斷再講理由**，"
            "理由最多兩句。你最重要的一句話永遠是「什麼情況代表我錯了」。")


PROMPT = """{persona}

=== 這次的任務跟平常不同 ===
這次判斷的對象**不是一檔股票，是兩個市場**（美股、台股），要產出一份每週總體報告。
你原本對個股的規矩全部照用，只是把「這檔」換成「這個市場」：

1. **先表態再講理由**：每個市場都要先選 stance（積極／偏積極／中性／偏保守／保守），
   只能選一個，**不准騎牆**。headline 40 字以內，一句話講完，不要把五件事塞進同一句。
2. **兩個角度獨立判斷**：結構面（政策／通膨／成長，年為單位）與資金面（利差／
   外資流向／輪動／體溫計，週為單位）。**兩邊相反也照實寫**，不要為了一致而修改任一邊。
3. **每個角度都要有失效條件**，具體到數字或事件。不能被證偽的話不要寫。
4. 美股跟台股**分開判斷**，兩邊 stance 可以不同；不同的話在 linkage 說明為什麼。

=== 數字的規矩 ===
- **不准寫出資料裡沒有的數字**。你的工作是解讀，數字都算好了。
- 每個 claim 標 kind：observed（直接引用給的數字）／inference（從給的數字推的）／
  speculation（沒有數字支撐）。**寧可標 speculation 也不要假裝有依據**。
- 資料缺口誠實寫進 blind_spots。
- ⚠️ **不要在報告裡解釋資料來源之間的技術差異**（哪個 API 比較即時之類）——
  那是管線的事，讀報告的人不需要知道。

全部用繁體中文（台灣用語）。不要用「可能」「或許」灌水。

=== 程式算好的資料 ===
{facts}
"""


def ask(facts):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    import subprocess
    prompt = PROMPT.format(persona=_kongming_persona(),
                           facts=json.dumps(facts, ensure_ascii=False, indent=1))
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
/* 分頁：美股／台股（2026-09-11 Leo：「台股獨立一個分頁」）。
   方框樣式跟資產中控台一致，不另外發明一套。 */
.tabs{display:flex;gap:8px;margin:14px 0 4px;flex-wrap:wrap}
.tabs button{background:none;border:1px solid var(--line,#16304A);border-radius:9px;
 color:var(--muted,#9DB0C8);font-size:13px;font-weight:600;padding:8px 18px;cursor:pointer;
 font-family:inherit}
.tabs button[aria-selected=true]{background:#152238;border-color:var(--accent,#22D3EE);color:#fff}
.pane[hidden]{display:none}
/* 表態燈：一眼看出積極還是保守 */
.stance{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.sv{font-size:21px;font-weight:800;letter-spacing:.04em;padding:4px 16px;border-radius:8px}
.s-積極{background:#0E2417;color:#4ADE80;border:1px solid #166534}
.s-偏積極{background:#0E2417;color:#86EFAC;border:1px solid #166534}
.s-中性{background:#0E1B2B;color:#9DB0C8;border:1px solid var(--line,#16304A)}
.s-偏保守{background:#2E1418;color:#FCA5A5;border:1px solid #7F1D1D}
.s-保守{background:#2E1418;color:#F87171;border:1px solid #7F1D1D}
.ang{border:1px solid var(--line,#16304A);border-radius:8px;padding:11px 13px;margin:9px 0;
 background:var(--line2,#0E1B2B)}
.ang .h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:5px}
.ang .nm{font-weight:700;color:var(--ink,#DCE7F5);font-size:13.5px}
.ang .vd{font-size:11.5px;font-weight:700;padding:2px 10px;border-radius:5px}
.ang .rs{line-height:1.75;color:var(--ink,#DCE7F5);font-size:13px}
.ang .f{margin-top:7px;font-size:12px;color:#FCA5A5;line-height:1.6}
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

    def _claims(lst):
        out = []
        for c in (lst or []):
            lab, k = KIND.get(c.get("kind"), ("?", "inf"))
            out.append(f'<div class="cl"><span class="tag {k}">{lab}</span>'
                       f'<span>{esc(c.get("text",""))}'
                       f'<br><span class="bs">依據：{esc(c.get("basis",""))}</span></span></div>')
        return "".join(out)

    def _market(m, extra=""):
        """一個市場的分頁內容：表態 → 兩個獨立角度 → 支撐的事實。"""
        st = m.get("stance") or "中性"
        angs = "".join(
            f'<div class="ang"><div class="h"><span class="nm">{esc(a.get("name",""))}</span>'
            f'<span class="vd s-{esc(a.get("verdict","中性"))}">{esc(a.get("verdict",""))}</span></div>'
            f'<div class="rs">{esc(a.get("reason",""))}</div>'
            f'<div class="f">✕ 這個角度錯了，如果：{esc(a.get("falsifier",""))}</div></div>'
            for a in (m.get("angles") or []))
        return (f'<div class="mw lead">'
                f'<div class="stance"><span class="sv s-{esc(st)}">{esc(st)}</span>'
                f'<span class="big">{esc(m.get("headline",""))}</span></div>'
                f'<div class="bs">表態依據：{esc(m.get("stance_basis",""))}</div></div>'
                f'<div class="mw"><h2>兩個獨立角度（相反也照實寫）</h2>{angs}</div>'
                f'<div class="mw"><h2>支撐的事實與推論</h2>{_claims(m.get("claims"))}</div>'
                + extra)

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

    sub = (f'{esc(facts.get("week_of",""))} 週　投資長 孔明 判讀　'
           f'<br>數字全部由程式從官方來源算出，孔明只做判斷；每句標示依據強度，每個角度都帶失效條件')

    us_pane = _market(note.get("us") or {},
                      f'<div class="mw"><h2>美國總經數字</h2>{us_tbl}</div>')
    tw_pane = _market(note.get("tw") or {},
                      '<div class="mw"><h2>台股資金結構</h2>'
                      + "".join(f'<div class="li">{b}</div>' for b in tw_bits) + '</div>')

    body = (
        f'<div class="mw"><h2>跟上週比</h2><div class="li">{esc(note.get("week_change",""))}</div>'
        f'{vs_html}</div>'
        f'<div class="mw"><h2>美股 ↔ 台股</h2><div class="li">{esc(note.get("linkage",""))}</div></div>'
        '<div class="tabs" role="tablist">'
        '<button role="tab" aria-selected="true" data-p="us">美股</button>'
        '<button role="tab" aria-selected="false" data-p="tw">台股</button></div>'
        f'<div class="pane" id="p-us">{us_pane}</div>'
        f'<div class="pane" id="p-tw" hidden>{tw_pane}</div>'
        f'<div class="mw"><h2>下週行事曆</h2>{cal_html}</div>'
        f'<div class="mw"><h2>下週要盯</h2>{watch}</div>'
        f'<div class="mw"><h2>這份報告看不到的東西</h2>{blind}</div>')

    js = """<script>
document.querySelectorAll('.tabs button').forEach(function(b){
  b.addEventListener('click', function(){
    document.querySelectorAll('.tabs button').forEach(function(x){
      x.setAttribute('aria-selected', x === b ? 'true' : 'false');});
    ['us','tw'].forEach(function(k){
      document.getElementById('p-' + k).hidden = (k !== b.dataset.p);});
  });
});
</script>"""

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>每週總體報告</title><style>' + BASE_CSS + CSS
            + '</style></head><body><div class="wrap">'
            + header("gdp", "每週總體報告", sub, [], eyebrow="MACRO WEEKLY")
            + body + "</div>" + js + "</body></html>")


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

    # 存這週快照（按日期存，不覆蓋），下週才算得出「跟上週差多少」。
    # 只留最近 8 份：夠回看兩個月，又不會讓檔案無限長大。
    os.makedirs(os.path.dirname(SNAP) or ".", exist_ok=True)
    hist = _load(SNAP, {}) or {}
    if not isinstance(hist, dict) or "us_macro" in hist:
        hist = {}
    keep = {k: v for k, v in hist.items() if k != facts["week_of"]}
    keep[facts["week_of"]] = {k: facts[k] for k in ("week_of", "us_macro", "tw", "rrg")}
    for old in sorted(keep)[:-8]:
        del keep[old]
    json.dump(keep, io.open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"✅ 已存 {out}（{len(html):,} bytes）")
    for k, lab in (("us", "美股"), ("tw", "台股")):
        m = note.get(k) or {}
        print(f"   {lab}：【{m.get('stance','?')}】{m.get('headline','')[:46]}")
        for a in (m.get("angles") or []):
            print(f"      · {a.get('name','')}：{a.get('verdict','')}")
    print(f"   資料缺口 {len(note.get('blind_spots') or [])} 項")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
