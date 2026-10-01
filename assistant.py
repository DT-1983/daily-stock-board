# -*- coding: utf-8 -*-
"""投資助理模式（2026-10-02，Leo：「基本上就像投資助理一樣，任何問題都可以問阿福，他會找資料庫，估算股票價值等等」）

老墨的阿福會在回答前「翻投顧報告」「算風報比」——它能跨檔、能找資料庫。我們戰情室的孔明原本只能對**一檔**
給兩個角度的判斷，沒指定股票就拒答。這支讓孔明變成投資助理：

    問題 ──→ ① 規劃：AI 從一份固定的工具清單裡挑 1～4 個要查的資料（不能自己上網、不能自己編數字）
         ──→ ② 執行：程式查資料庫、算數字（唯讀）
         ──→ ③ 回答：孔明拿到「程式查好算好」的材料，照角色規則回答

🔴 邊界（跟 war_room 的 9/7 定案一致）：判斷角色**只能用我們自己的管線**，每個數字回得了頭。
   所以工具全部是「讀我們的資料庫／跑我們已有的計算」，沒有 WebSearch。
🔴 數字一律程式算好，AI 只負責挑要查什麼、以及用算好的東西回答。規劃那一步的輸出會被程式驗證
   （工具名、參數都在白名單內），不合格就丟掉，退回關鍵字規則。
🔴 估值只給「多個角度的參考」，**不給單一合理價、不自己訂倍數門檻**（見記憶 feedback_no_self_change_criteria）。

工具（唯讀）：
    reports    券商報告查詢（跨檔）：某券商／某段時間／某評等 → 一張表＋價格、距目標、估值拆解、燈號、矛盾旗標
    lamps      燈號篩選：幾燈以上、多空、產業、是否持股
    stock      單檔的完整現況（公司、持股與否、程式算好的技術狀態、報告摘要）
    valuation  估值的幾個角度：洪瑞泰貴俗價、券商目標價分布、市場共識、自己歷史本益比的位置
    decompose  把這檔的券商目標價拆成「倍數 × EPS／淨值」，多家券商拆「倍數差／EPS 差」
    peers      同產業的其他股票燈號
"""
import datetime as dt
import io
import json
import os
import re
import statistics as st
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOOLS = {}
_NO_SUFFIX = re.compile(r"\.(TW|TWO)$")


def _k(tk):
    return _NO_SUFFIX.sub("", str(tk or "").upper())


def tool(name, desc, args):
    def deco(fn):
        TOOLS[name] = {"desc": desc, "args": args, "fn": fn}
        return fn
    return deco


# ───────────────────────────── 共用 ─────────────────────────────

def _combo_rows():
    try:
        cr = json.load(io.open("state/combo_result.json", encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}, ""
    rows = {_k(r.get("ticker")): r for r in (cr.get("rows") or []) if r.get("ticker")}
    asof = max((str(r.get("asof") or "") for r in rows.values()), default="")
    return rows, asof


def _resolve(t):
    """名稱或代號 → (代號, 名稱)。解析不到回 (None, None)——不猜。"""
    import war_room
    hits = war_room._tickers_in_question(str(t or ""))
    if not hits:
        return None, None
    code, nm = hits[0]
    if not nm:                                               # 只打代號時，名稱從燈號掃描母體補
        nm = str((_combo_rows()[0].get(_k(code)) or {}).get("name") or "")
    return code, nm


def _held():
    try:
        import war_room
        return set(war_room._held_set())
    except Exception:                                        # noqa: BLE001
        return set()


BROKER_ALIAS = {"統一": "統一投顧", "中信": "中信投顧", "元大": "元大投顧", "群益": "群益投顧", "宏遠": "宏遠投顧",
                "康和": "康和投顧", "第一金": "第一金投顧", "元富": "元富投顧", "瑞銀": "瑞銀", "高盛": "高盛",
                "goldman": "高盛", "ubs": "瑞銀"}
_RATING = {"買進": ("買進", "buy", "增加持股", "overweight", "outperform"),
           "賣出": ("賣出", "sell", "減碼", "underweight", "underperform"),
           "中立": ("中立", "neutral", "持有", "hold", "持平")}


def _rating_side(r):
    s = str(r or "").lower()
    for side, keys in _RATING.items():
        if any(k in s for k in keys):
            return side
    return None


# ───────────────────────────── 工具 ─────────────────────────────

@tool("reports", "券商報告查詢（可跨檔）：依券商、近幾天、評等、股票篩選，回一張表（報告日、評等、目標價、現價、距目標、估值拆解、燈號、矛盾旗標）",
      {"broker": "券商名，如 高盛／統一／中信（可省略）", "days": "近幾天內的報告（整數，可省略）",
       "ticker": "股票代號或名稱（可省略）", "rating": "買進／中立／賣出（可省略）", "limit": "最多幾份，預設 12"})
def t_reports(broker=None, days=None, ticker=None, rating=None, limit=12):
    import advisor_reports as AR
    import report_review as RR
    import lamp_lookup as L
    reps = AR._live_reports()
    total = len(reps)
    bkey = None
    if broker:
        b = str(broker).strip()
        bkey = BROKER_ALIAS.get(b.lower(), BROKER_ALIAS.get(b, b))
        reps = [r for r in reps if bkey and bkey in str(r.get("broker") or "")]
    cond = []
    if bkey:
        cond.append(f"券商含「{bkey}」")
    code = None
    if ticker:
        code, nm = _resolve(ticker)
        if not code:
            return f"（查不到「{ticker}」是哪一檔，沒有篩選）", None
        reps = [r for r in reps if _k(r.get("ticker")) == _k(code)]
        cond.append(f"股票 {nm or ''}({code})")
    if rating:
        side = _rating_side(rating)
        reps = [r for r in reps if _rating_side(r.get("rating")) == side]
        cond.append(f"評等偏{side}")
    window_note = ""
    if days:
        since = (dt.date.today() - dt.timedelta(days=int(days))).isoformat()
        inwin = [r for r in reps if str(r.get("date") or "") >= since]
        cond.append(f"近 {int(days)} 天")
        if not inwin and reps:
            window_note = (f"⚠️ 登錄簿裡這個條件近 {int(days)} 天**沒有**報告；"
                           f"以下改列這個條件下最近的幾份（日期都比區間舊，不要當成近期報告）。")
            reps = sorted(reps, key=lambda r: str(r.get("date")), reverse=True)[:5]
        else:
            reps = inwin
    reps = sorted(reps, key=lambda r: str(r.get("date")), reverse=True)[: int(limit or 12)]
    head = (f"報告庫共 {total} 份有效報告｜條件：{'；'.join(cond) or '全部'}｜"
            + (f"改列最近 {len(reps)} 份" if window_note else f"符合 {len(reps)} 份"))
    if not reps:
        return (head + "\n⚠️ 登錄簿裡沒有符合的報告。**不要憑印象補報告**；若 Leo 手上有（例如截圖或 PDF），"
                "要先用 Discord /上傳報告 收進來。"), None
    rows, _asof = _combo_rows()
    budget = 5                                              # 母體外要即時查，最多 5 檔（每檔 3～8 秒）
    lines, table = [], []
    for r in reps:
        c = _k(r.get("ticker"))
        lk = None
        row = rows.get(c)
        if row:
            lk = row
        elif budget > 0:
            budget -= 1
            try:
                lk = L.lookup(c, live=True)
            except Exception:                                # noqa: BLE001
                lk = None
        rep = {"ticker": c, "name": r.get("name"), "broker": r.get("broker"), "date": r.get("date"),
               "rating": r.get("rating"), "target": r.get("target") or 0}
        f = RR.facts(rep, lk) if (lk and r.get("target")) else {"flags": []}
        px = f.get("price")
        s = (f"・{c} {r.get('name') or ''}｜{r.get('broker')} {str(r.get('date'))[5:]}｜{r.get('rating') or '—'}"
             f"｜{AR._target_text(r).split('｜')[0]}")
        if px:
            s += f"｜現價 {px:,.2f}（{str((lk or {}).get('asof') or '')[5:]}）｜距目標 {f['upside']:+.0%}"
        if r.get("valuation_multiple") and (r.get("valuation_eps") or r.get("bps")):
            b = r.get("valuation_eps") or r.get("bps")
            s += f"｜{r.get('valuation_kind') or 'PE'} {r['valuation_multiple']:g}×{b:,.2f}（{r.get('valuation_eps_label') or '基準'}）"
        if lk and lk.get("lit") is not None:
            s += f"｜{lk['lit']}/4燈{'多' if lk.get('bull') else '空'}"
        for fl in f.get("flags", [])[:2]:
            s += f"\n    {fl}"
        lines.append(s)
        table.append(s)
    txt = head + "\n" + "\n".join(lines)
    if window_note:
        txt = window_note + "\n" + txt
    return txt, "\n".join(table)


@tool("lamps", "燈號篩選：從每日掃描母體（約 238 檔）依燈數、多空、產業、是否持股篩選",
      {"min_lit": "至少幾燈（0–4）", "max_lit": "至多幾燈", "bull": "true＝只要 SuperTrend 多方",
       "sector": "產業關鍵字（中文，如 半導體、電子科技）", "held": "true＝只看持股", "limit": "最多幾檔，預設 15"})
def t_lamps(min_lit=None, max_lit=None, bull=None, sector=None, held=None, limit=15):
    rows, asof = _combo_rows()
    if not rows:
        return "（燈號掃描結果讀不到）", None
    hs = _held() if held else set()
    out = []
    for c, r in rows.items():
        lit = r.get("lit")
        if lit is None:
            continue
        if min_lit is not None and lit < int(min_lit):
            continue
        if max_lit is not None and lit > int(max_lit):
            continue
        if bull is not None and bool(r.get("bull")) != bool(bull):
            continue
        if sector and sector not in (str(r.get("sector_zh") or "") + str(r.get("industry") or "") + str(r.get("sector") or "")):
            continue
        if held and c not in hs:
            continue
        out.append(r)
    out.sort(key=lambda r: (-(r.get("lit") or 0), -(r.get("rs_short") or -999)))
    held_set = _held()
    lines = [f"・{r['ticker']} {r.get('name') or ''}｜{r['lit']}/4{'多' if r.get('bull') else '空'}"
             f"｜距SuperTrend線 {r.get('gap_pct')}%｜RS60 {r.get('rs_short')}%｜{r.get('sector_zh') or r.get('sector') or ''}"
             f"{'｜持股' if _k(r['ticker']) in held_set else ''}" for r in out[: int(limit or 15)]]
    head = (f"燈號掃描母體 {len(rows)} 檔｜資料日 {asof}（每日 07:00 掃描，等於前一個交易日收盤）｜"
            f"符合 {len(out)} 檔" + (f"，只列前 {int(limit or 15)}" if len(out) > int(limit or 15) else ""))
    return head + "\n" + ("\n".join(lines) if lines else "（沒有符合的）"), None


@tool("stock", "單檔完整現況：公司業務、是否持股、程式算好的技術狀態（SuperTrend／RS60／四燈／風報比）、券商報告摘要",
      {"ticker": "股票代號或名稱"})
def t_stock(ticker=None):
    import war_room
    code, nm = _resolve(ticker)
    if not code:
        return f"（查不到「{ticker}」是哪一檔）", None
    return war_room._one_stock_block(code, nm or ""), None


@tool("valuation", "估值的幾個角度（參考，不是單一合理價）：洪瑞泰貴俗價、券商目標價分布、市場共識目標價、這檔自己歷史本益比的位置",
      {"ticker": "股票代號或名稱"})
def t_valuation(ticker=None):
    import advisor_reports as AR
    code, nm = _resolve(ticker)
    if not code:
        return f"（查不到「{ticker}」是哪一檔）", None
    out = [f"{nm or ''}({code}) 估值角度（各角度獨立並列，不合成單一合理價）"]
    # ① 洪瑞泰：直接用 investment_chief 那包價值材料（跟孔明每日判斷同一份）
    try:
        import investment_chief as ic
        mat = ic.gather_material(code, [])
        val = mat[2] if isinstance(mat, (list, tuple)) and len(mat) >= 3 else ""
        out.append("① 洪瑞泰（常利 EPS×30＝貴價；品質關／盈再率／配息率）：\n" + str(val)[:900])
    except Exception as e:                                   # noqa: BLE001
        out.append(f"① 洪瑞泰：讀取失敗（{str(e)[:60]}）")
    # ② 券商目標價
    reps = [r for r in AR._live_reports() if _k(r.get("ticker")) == _k(code) and r.get("target")]
    if reps:
        ts = sorted(float(r["target"]) for r in reps)
        out.append(f"② 券商目標價（我們報告庫 {len(reps)} 份）：低 {ts[0]:,.1f}／中位 {st.median(ts):,.1f}／高 {ts[-1]:,.1f}；"
                   + "；".join(f"{r.get('broker')} {str(r.get('date'))[5:]} {r.get('target')}" for r in
                               sorted(reps, key=lambda x: str(x.get("date")), reverse=True)[:5]))
    else:
        out.append("② 券商目標價：報告庫沒有這檔的報告（不要憑印象補）")
    # ③ 市場共識與現價
    rows, _ = _combo_rows()
    lk = rows.get(_k(code))
    if not lk:
        try:
            import lamp_lookup as L
            lk = L.lookup(code, live=True)
        except Exception:                                    # noqa: BLE001
            lk = None
    if lk and lk.get("price"):
        s = f"③ 現價 {lk['price']:,.2f}（{lk.get('asof')}）"
        if lk.get("target"):
            s += (f"｜市場共識目標價 {lk['target']:,.2f}"
                  + (f"（{lk['target_n']} 位分析師）" if lk.get("target_n") else "（分析師人數未知）"))
        out.append(s)
    # ④ 自己歷史本益比的位置（台股，證交所 PER 同口徑）
    if str(code).isdigit():
        try:
            import target_decompose as TD
            md = TD.market_data(str(code))
            h, now = md.get("per_hist"), md.get("per_now")
            if h and now:
                pc = TD.pctile(h, now)
                out.append(f"④ 本益比位置（證交所落後 PER，近 {len(h)} 個交易日）：現在 {now:.1f} 倍，落在自己分布第 {pc * 100:.0f} 百分位"
                           f"（中位 {st.median(h):.1f}、最低 {min(h):.1f}、最高 {max(h):.1f}）"
                           + (f"；近四季 EPS 約 {md['ttm_eps']:.2f}" if md.get("ttm_eps") else ""))
                if len(h) < 500:
                    out.append(f"   ⚠️ 歷史只有 {len(h)} 天（不到兩年），分布代表性有限")
        except Exception as e:                               # noqa: BLE001
            out.append(f"④ 本益比位置：讀取失敗（{str(e)[:60]}）")
    return "\n".join(out), None


@tool("decompose", "把這檔的券商目標價拆成「倍數×EPS（或淨值）」，算市場現在給幾倍、EPS 要年化成長多少；多家券商時拆成倍數差與 EPS 差",
      {"ticker": "股票代號或名稱"})
def t_decompose(ticker=None):
    import target_decompose as TD
    code, nm = _resolve(ticker)
    if not code:
        return f"（查不到「{ticker}」是哪一檔）", None
    reps = TD.load_reports(code)
    if not reps:
        return f"{nm or ''}({code})：報告庫沒有可拆解的報告（要有目標價＋倍數＋EPS／淨值）。", None
    ds = [TD.decompose(r) for r in reps]
    out = [f"{nm or ''}({code}) 目標價拆解（{len(ds)} 份）"] + ["・" + TD.line(d) for d in ds]
    for d in ds:
        out += ["  " + f for f in d["flags"]]
    mb = TD.multi_broker(ds)
    if mb:
        ref = mb[0]["vs"]
        out.append(f"多家差異（以最低目標價 {ref['broker']} {ref['target']:,.0f} 為基準）：")
        for x in mb:
            d = x["d"]
            sm = x["mult_share"] / x["tot_log"] if x["tot_log"] else 0
            out.append(f"  {d['broker']} {d['target']:,.0f}（高 {x['total']:+.0%}）＝倍數 {d['mult']:g} vs {ref['mult']:g}（{sm:.0%}）"
                       f"＋基準 {d['base']:,.1f}({d.get('base_label') or ''}) vs {ref['base']:,.1f}({ref.get('base_label') or ''})（{1 - sm:.0%}）")
    return "\n".join(out), None


@tool("peers", "同產業（燈號掃描母體內）的其他股票，依燈數排序",
      {"ticker": "股票代號或名稱", "limit": "最多幾檔，預設 8"})
def t_peers(ticker=None, limit=8):
    code, nm = _resolve(ticker)
    rows, asof = _combo_rows()
    r0 = rows.get(_k(code)) if code else None
    if not r0:
        return f"（{nm or ticker} 不在燈號掃描母體，沒有同業比較）", None
    sec = r0.get("sector_zh") or r0.get("sector")
    peers = [r for c, r in rows.items() if c != _k(code) and (r.get("sector_zh") or r.get("sector")) == sec]
    peers.sort(key=lambda r: (-(r.get("lit") or 0), -(r.get("rs_short") or -999)))
    lines = [f"・{r['ticker']} {r.get('name') or ''}｜{r['lit']}/4{'多' if r.get('bull') else '空'}｜RS60 {r.get('rs_short')}%"
             for r in peers[: int(limit or 8)]]
    return (f"{nm}({code}) 屬「{sec}」：本檔 {r0['lit']}/4｜同產業母體內 {len(peers)} 檔（資料日 {asof}）\n" + "\n".join(lines)), None


# ───────────────────────────── 規劃 ─────────────────────────────

KEYWORDS = re.compile(r"報告|目標價|評等|投顧|券商|估值|估算|合理價|值多少|貴不貴|便宜|比較|哪些|哪一|篩選|排行|最高|最低|"
                      r"拆解|前提|幾燈|[四4]燈|燈號|同業|產業鏈|高盛|統一|中信|元大|群益|宏遠|康和|瑞銀")


def wants_assistant(question):
    """要不要走助理模式：問題帶資料庫／估值／篩選類的字眼。單純「這檔怎麼看」維持原本孔明（快、固定格式）。"""
    return bool(KEYWORDS.search(question or ""))


def _plan_ai(question, named):
    import sec_release as S
    menu = "\n".join(f"- {n}：{t['desc']}　參數 {json.dumps(t['args'], ensure_ascii=False)}" for n, t in TOOLS.items())
    prompt = f"""你是投資助理的「查資料規劃員」。只負責決定要查哪些資料，不回答問題、不給意見。
今天 {dt.date.today().isoformat()}。可用工具（全部是讀我們自己的資料庫，沒有別的）：
{menu}

Leo 的問題：「{question}」
問題裡認出的股票：{named or '（沒有）'}

規則：
1. 挑 1～4 個工具，每個給參數（沒用到的參數不要寫）。同一個工具可以用不同參數呼叫多次。
2. 問題問「某券商／某段時間的報告」→ reports（可跨檔，不需要股票）；問「估值／值多少／貴不貴」→ valuation（要股票）；
   問「目標價怎麼來／差在哪」→ decompose；問「哪些股票幾燈」→ lamps；問同業 → peers。
3. 「過去兩週／近兩週」＝ days 14；「最近」＝ days 7；「這個月」＝ days 30。
4. 沒有明確股票就不要編股票。只回 JSON。"""
    schema = {"type": "object", "properties": {"calls": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}},
        "required": ["tool", "args"]}}}, "required": ["calls"]}
    out = S._claude_json(prompt, schema, timeout=150)
    return (out or {}).get("calls") or []


def _plan_rules(question, named):
    """AI 規劃失敗時的退路（純關鍵字）。"""
    q = question or ""
    calls = []
    days = 14 if re.search(r"兩週|2週|二週", q) else 7 if re.search(r"最近|本週|這週|一週", q) else 30 if "這個月" in q else None
    brk = next((b for b in BROKER_ALIAS if b in q), None)
    if re.search(r"報告|評等|目標價|投顧|券商", q) or brk:
        a = {"days": days} if days else {}
        if brk:
            a["broker"] = brk
        if named:
            a["ticker"] = named[0]
        calls.append({"tool": "reports", "args": a})
    if named and re.search(r"估值|合理價|值多少|貴不貴|便宜", q):
        calls.append({"tool": "valuation", "args": {"ticker": named[0]}})
    if named and re.search(r"拆解|怎麼算|前提|差在", q):
        calls.append({"tool": "decompose", "args": {"ticker": named[0]}})
    m = re.search(r"([1-4一二三四])\s*燈", q)
    if m or re.search(r"幾燈|燈號", q) and not named:
        n = {"一": 1, "二": 2, "三": 3, "四": 4}.get(m.group(1), None) if m else None
        calls.append({"tool": "lamps", "args": {"min_lit": int(n or (m.group(1) if m else 4))}})
    return calls


def _validate(calls):
    ok = []
    for c in calls[:4]:
        n = (c or {}).get("tool")
        if n not in TOOLS:
            continue
        allowed = set(TOOLS[n]["args"])
        a = {k: v for k, v in ((c.get("args") or {}).items()) if k in allowed and v not in (None, "", [])}
        if (n, json.dumps(a, sort_keys=True, ensure_ascii=False)) in [(x[0], json.dumps(x[1], sort_keys=True, ensure_ascii=False)) for x in ok]:
            continue
        ok.append((n, a))
    return ok


def run(question, named=None, on_stage=None):
    """回 {"material": 給孔明的材料, "table": 要放在回答最前面的程式表格（可為 ""）, "calls": [...]}。"""
    def st_(m):
        if on_stage:
            try:
                on_stage(m)
            except Exception:                                # noqa: BLE001
                pass
    if named is None:
        import war_room
        named = [c for c, _ in war_room._tickers_in_question(question)]
    st_("助理正在決定要查哪些資料")
    try:
        calls = _validate(_plan_ai(question, named))
    except Exception as e:                                   # noqa: BLE001
        print(f"  [assistant] 規劃失敗，退回關鍵字規則：{str(e)[:80]}")
        calls = []
    plan_src = "AI 規劃"
    if not calls:
        calls, plan_src = _validate(_plan_rules(question, named)), "關鍵字規則"
    LABEL = {"reports": "正在翻投顧報告", "lamps": "正在篩燈號", "stock": "正在讀這檔現況", "valuation": "正在整理估值角度",
             "decompose": "正在拆目標價", "peers": "正在看同業"}
    parts, tables = [], []
    for n, a in calls:
        st_(LABEL.get(n, f"正在用 {n}") + (f"（{a.get('broker') or a.get('ticker') or ''}）" if a else ""))
        try:
            txt, tbl = TOOLS[n]["fn"](**a)
        except Exception as e:                               # noqa: BLE001
            txt, tbl = f"（{n} 執行失敗：{str(e)[:100]}）", None
        parts.append(f"▍{n}　{json.dumps(a, ensure_ascii=False)}\n{txt}")
        if tbl:
            tables.append(tbl)
    if not parts:
        parts.append("（助理沒有挑到適合的工具：這個問題資料庫查不到。請 Leo 換個問法，例如指定股票、券商或時間。）")
    material = ("【助理查詢結果——以下由程式查我們的資料庫與計算（規劃方式：" + plan_src + "），數字直接引用，不要自己重算或補充】\n"
                + "\n\n".join(parts))
    return {"material": material, "table": ("\n".join(tables)).strip(), "calls": calls}


# 孔明 ask_meta 與材料函式之間的傳遞（同一個執行緒內）：進度回報 callback、要放在回答最前面的表格
_tl = threading.local()
