# -*- coding: utf-8 -*-
"""#軍議：仲達（風險官）與陳壽（復盤官）的問答層（2026-09-04，路線圖第 1 項階段 3）。

## 這支解決什麼

仲達的 P1（失效條件日檢＝`thesis_check.py`）與陳壽的 A 型（判斷準確度追蹤＝
`verdict_review.py`）**早就在跑**，但輸出只有兩個地方：日報第③④段、以及
`state/*.json`。想問「我現在最大的風險是什麼」「你的判斷到底準不準」，
只能自己去翻檔案。

這支把材料湊齊 → 丟給**本機 claude**（`llm_board`，Max plan 訂閱額度，
**不是付費 API、不產生帳單**）→ 回一段可以貼進 Discord 的答覆。

## 兩位的分工（不重疊，材料也不同）

| | 仲達（風險官） | 陳壽（復盤官） |
|---|---|---|
| 回答 | **現在**有什麼風險 | **回頭看**判斷準不準、紀律如何 |
| 材料 | 失效條件日檢／燈號／電金比大盤溫度／投顧失效線／券商異動／里程碑 | 投資長判斷歷史＋基準價追蹤／交易紀錄 |
| 時間軸 | 今天 | 過去 |

## 🔴 兩個誠實邊界（寫在 prompt 裡，不是靠自覺）

1. **仲達不下行動指令**。大盤總開關（電金比 vs 100MA）目前**只量測不下指令**——
   老墨的「連 32 日轉弱就清倉」是他自己系統的規則，我們沒有對應回測。
   照「不自行發明投資判定門檻」的鐵則，仲達只能講「現在的狀態是什麼」，
   不能講「所以你應該賣」。
2. **陳壽的 B 型（Leo 自己的交易紀律）樣本嚴重不足**——`trade_journal` 目前只有
   個位數筆。材料裡會標出筆數，prompt 明令「樣本 < 20 筆時不得下任何紀律結論」。

用法:
    python war_room.py 仲達 "我的持股現在最大的風險是什麼"
    python war_room.py 陳壽 "你的判斷準不準"
    python war_room.py 仲達            # 不給問題＝要一份現況摘要
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

MAX_CHARS = 1800          # Discord 單則 2000，留餘裕給標題


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _jsonl(p, limit=None):
    out = []
    if not os.path.exists(p):
        return out
    for ln in io.open(p, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out[-limit:] if limit else out



_HELD_CACHE = None


def _held_set():
    """Leo 實際持有的代號（正規化）。一次執行內快取，材料組裝要用好幾次。"""
    global _HELD_CACHE
    if _HELD_CACHE is None:
        try:
            import investment_chief
            _HELD_CACHE = {investment_chief.norm_ticker(t)
                           for t in investment_chief.held_universe()}
        except Exception:                                   # noqa: BLE001
            _HELD_CACHE = set()
    return _HELD_CACHE


def resolve_in_question(q):
    """從問題裡認出使用者在問哪一檔，並回一段「這檔的實際資料」加進材料。

    🔴 2026-09-04 加，起因是一次**答錯股票**：Leo 問「高力怎麼看？」，
    仲達回答的是 **HIG（The Hartford Insurance Group）**——完全不同的公司。
    高力是 **8996**，而 8996 根本不在材料裡（不是持股、不在燈號母體），
    於是他在材料中找了個看起來最像的代號套上去，還講得頭頭是道。

    ⭐ **這是最危險的一種錯**：格式正確、語氣謹慎、甚至誠實標了「材料沒給的部分」，
    但整段講的是另一家公司。靠 prompt 叫他「不要猜」擋不住——他不覺得自己在猜。

    修法兩層：
      ① 這裡先做**名稱→代號**的硬解析（中文名走 combo_scan._tw_names，
         英文/數字直接當代號），把那一檔的真實資料撈進材料。
      ② 解析不到、或解析到但我們沒有資料時，材料裡**明寫**這件事，
         prompt 再加一條硬規則禁止代換。
    """
    q = (q or "").strip()
    if not q:
        return ""
    import re as _re
    cands = []
    # 中文公司名
    try:
        import combo_scan
        names = combo_scan._tw_names() or {}
        for code, nm in names.items():
            nm = str(nm)
            if len(nm) >= 2 and nm in q:
                cands.append((code, nm))
    except Exception:                                       # noqa: BLE001
        pass
    # 直接寫代號
    # ⚠️ 這個 regex **不要用 詞邊界**：跨工具寫檔時反斜線會被吃掉，變成真的
    # 退格字元 0x08，regex 就成了「找退格字元包住的代號」——永遠匹配不到，
    # 而且 grep/sed 顯示不出來，只有 repr() 看得見（2026-09-04 踩了第四次）。
    # 改用字元類自己界定，不依賴反斜線。
    # ⚠️ 在**原文**找、不要先 .upper()：代號本來就是用大寫寫的（COST、NVDA），
    # 先轉大寫的話「Palo Alto Networks」會被切成 PALO/ALTO 當成代號，
    # 而且因為 cands 有東西了，下面的公司名解析（③）就再也不會執行。
    for tk in _re.findall(r"(?:^|[^0-9A-Za-z])([0-9]{4,6}[A-Z]?|[A-Z]{2,5})"
                          r"(?:[^0-9A-Za-z]|$)", " " + q + " "):
        if tk.isdigit() or (tk.isalpha() and len(tk) >= 2):
            cands.append((tk, ""))
    # ③ 中英文公司名（lookup_page.resolve：中文查本地台股名冊、
    #    英文走 yfinance Search 並濾到 EQUITY/ETF）。
    #    只在①②都沒認出東西時才做——英文名要打網路查詢（約 1-2 秒）。
    if not cands:
        try:
            import lookup_page
            # ⚠️ 不能整句丟進去：lookup_page.resolve 看到**任何**非 ASCII 字元就
            # 判定「這是中文」轉去查台股名冊。「Palo Alto Networks 如何」因為結尾
            # 那兩個中文字，整句被當中文查 → 回空。所以英文部分要另外抽出來再試一次。
            tries = [q]
            eng = "".join(c if ord(c) < 128 else " " for c in q).strip()
            if eng and eng != q and len(eng) >= 3:
                tries.append(eng)
            for t in tries:
                # 只取**第一個**候選。Yahoo 搜尋會回一串海外次級掛牌
                # （5AP.F / COST.TO / NVDC34.SA…），第一個才是主要掛牌；
                # 多取只會白白多跑幾次抓價然後 404。
                for code, nm in (lookup_page.resolve(t) or [])[:1]:
                    cands.append((code, nm))
                if cands:
                    break
        except Exception:                                   # noqa: BLE001
            pass
    if not cands:
        return ""
    seen, out = set(), []
    for code, nm in cands:
        if code in seen:
            continue
        seen.add(code)
        out.append(_one_stock_block(code, nm))
    return "\n".join(x for x in out if x)


def _one_stock_block(code, nm=""):
    """單檔的實際資料。**查不到就明說查不到**，不要回空字串讓人以為沒問過。"""
    import re as _re
    label = f"{nm}（{code}）" if nm else code
    lines = [f"【問題裡提到的個股：{label}】"]
    # 🔴 2026-09-04：**公司在做什麼一定要給**。首次軍議時仲達說「高力是連接器/
    # 線纜廠」——實際是熱交換器廠。他沒有公司資料就用自己的知識補了一個，
    # 跟「問高力答成 HIG」同一類錯：材料缺一塊，他就填一塊，而且填得很自然。
    # 龐統當時答對，只是因為我只給了龐統 profile。
    lines.append("  " + _profile(code).replace("\n", "\n  "))
    held = _re.sub(r"\.(TW|TWO)$", "", str(code).upper()) in _held_set()
    lines.append(f"  是不是持股：{'是' if held else '否'}")
    cr = _load("state/combo_result.json", {}) or {}
    row = next((r for r in (cr.get("rows") or [])
                if _re.sub(r"\.(TW|TWO)$", "", str(r.get("ticker", "")).upper())
                == _re.sub(r"\.(TW|TWO)$", "", str(code).upper())), None)
    if row:
        lines.append(f"  燈號：{row.get('lit')}/4"
                     f"｜SuperTrend {'多方' if row.get('bull') else '空方'}"
                     f"（線 {row.get('st_line')}）｜現價 {row.get('price')}"
                     f"｜風報比 {row.get('rr')}｜目標價 {row.get('target')}"
                     f"｜資料日 {row.get('asof')}")
    else:
        lines.append("  ⚠️ **不在每日燈號掃描母體**——我們沒有這檔的技術面資料。")
    st = _load("state/advisor_reports.json", {}) or {}
    reps = [r for r in st.values()
            if not r.get("_notreport")
            and _re.sub(r"\.(TW|TWO)$", "", str(r.get("ticker", "")).upper())
            == _re.sub(r"\.(TW|TWO)$", "", str(code).upper())]
    if reps:
        for r in sorted(reps, key=lambda x: str(x.get("date")), reverse=True)[:3]:
            lines.append(f"  券商報告：{r.get('date')} {r.get('broker')} "
                         f"{r.get('rating')} 目標價 {r.get('target')}"
                         f"｜依據 {(r.get('valuation_basis') or '')[:60]}")
    else:
        lines.append("  券商研究報告：無")
    reg = _load("state/thesis_conditions.json", {}) or {}
    hit = next((v for k, v in reg.items()
                if _re.sub(r"\.(TW|TWO)$", "", k.upper())
                == _re.sub(r"\.(TW|TWO)$", "", str(code).upper())), None)
    lines.append(f"  失效條件：{len(hit.get('conditions', [])) if hit else 0} 條在監控")
    # 🆕 2026-09-04：系統外的股票**即時算一次**（Leo：「都做」）。
    # 走 lamp_lookup.lookup()——跟 Discord `/查` 與查股頁完全同一支，
    # 所以軍議跟那兩處不可能給出不一樣的燈號。實測約 3-8 秒。
    # ⚠️ 即時算的結果要**明確標示**是「臨時算的、不在每日監控裡」，
    # 否則讀的人會以為這檔跟持股一樣有人在盯。
    if not row:
        try:
            import lamp_lookup
            live = lamp_lookup.lookup(code)
            if live:
                lines.append(
                    f"  🔍 **即時計算**（不在每日掃描母體，為了回答這個問題臨時算的）："
                    f"現價 {live.get('price')}｜燈號 {live.get('lit')}/4"
                    f"｜SuperTrend {'多方' if live.get('bull') else '空方'}"
                    f"（線 {live.get('st_line')}）｜風報比 {live.get('rr')}"
                    f"｜目標價 {live.get('target')}｜RS60 {live.get('rs_short')}"
                    f"｜資料日 {live.get('asof')}")
                row = live
        except Exception as e:                              # noqa: BLE001
            lines.append(f"  （即時計算失敗：{str(e)[:80]}）")
    if not row and not reps and not hit:
        lines.append("  🔴 **這檔完全查不到**——連即時計算都算不出來（可能是新掛牌、"
                     "太冷門、或代號不對）。要回答只能說『查不到這檔』，"
                     "**絕對不可以拿材料裡別的代號來代替**。")
    elif not hit:
        lines.append("  ⚠️ 這檔**沒有失效條件在監控**——沒有人在盯它的判斷基礎，"
                     "上面的數字只是這一刻的快照。")
    return "\n".join(lines)


# ── 仲達：現在有什麼風險 ────────────────────────────────────────
def material_sima():
    m = []

    # ⚠️ thesis_check_today 的結構是 triggered/near/pending_metric 三個**陣列**，
    # 每筆是 [代號, 說明, 是否持股, 角度] 的 list——不是 dict。
    # 2026-09-04 第一版我照 rows/dict 假設寫，材料印出「共檢查 0 檔」，
    # 而那看起來就像「今天真的沒有東西要檢查」（同 silent_failure_pattern）。
    tc = _load("state/thesis_check_today.json", {}) or {}

    def _row(x):
        if isinstance(x, (list, tuple)):
            tk = x[0] if len(x) > 0 else ""
            desc = x[1] if len(x) > 1 else ""
            held = bool(x[2]) if len(x) > 2 else False
            ang = x[3] if len(x) > 3 else ""
            return tk, desc, held, ang
        return (x.get("ticker", ""), x.get("desc", ""),
                bool(x.get("held")), x.get("angle", ""))

    fired = [_row(x) for x in (tc.get("triggered") or [])]
    near = [_row(x) for x in (tc.get("near") or [])]
    pend = tc.get("pending_metric") or []
    # ⚠️ 2026-09-04：分組數字**先算好給他**，不要只給總數讓他自己數——
    # 首測仲達寫「共 7 檔（另 2 檔非持股）」又寫「這 6 檔（…共7檔）」，
    # 同一段裡數字自己打架。算數不是 AI 的強項，能算好的就不要留給他算。
    f_held = [x for x in fired if x[2]]
    f_not = [x for x in fired if not x[2]]
    m.append(f"【失效條件日檢】{tc.get('date','—')}：覆蓋 {tc.get('covered_count','?')} 檔，"
             f"**觸發 {len(fired)} 條（持股 {len(f_held)} 條、非持股 {len(f_not)} 條）**、"
             f"逼近 {len(near)} 條、等財報才驗 {len(pend)} 條"
             + (f"；未覆蓋 {tc['uncovered']}" if tc.get("uncovered") else ""))
    # 「非持股」也要寫出來——留空會讓讀的人不確定是漏標還是真的不是持股
    for tk, desc, held, ang in fired[:10]:
        m.append(f"  🚫 {tk}{'（持股）' if held else '（非持股）'}[{ang}] {desc}")
    for tk, desc, held, ang in near[:6]:
        m.append(f"  ⚠️ {tk}{'（持股）' if held else '（非持股）'}[{ang}] 逼近：{desc}")

    cr = _load("state/combo_result.json", {}) or {}
    crows = cr.get("rows") or cr.get("items") or []
    if crows:
        held = [r for r in crows if "持股" in str(r.get("src") or "")]
        bear = [r for r in held if r.get("bull") is False]
        m.append(f"【燈號】{cr.get('date') or ''} 母體 {len(crows)} 檔；"
                 f"持股 {len(held)} 檔，其中 SuperTrend 空方 {len(bear)} 檔")
        for r in bear[:10]:
            m.append(f"  · {r.get('ticker')} {r.get('name') or ''} "
                     f"現價 {r.get('price')} 站上 {r.get('st_line')} 才翻多")

    ef = _load("state/ef_ratio.json", {}) or {}
    if ef:
        ds = sorted(ef)
        last = ef[ds[-1]]
        vals = [ef[d]["ratio"] for d in ds[-100:] if "ratio" in ef[d]]
        ma = sum(vals) / len(vals) if len(vals) >= 100 else None
        m.append(f"【大盤溫度 電金比】{ds[-1]}：比值 {last.get('ratio'):.4f}"
                 + (f"、100 日均線 {ma:.4f}（{'低於' if last['ratio'] < ma else '高於'}均線）"
                    if ma else "、資料不足 100 日算不出均線"))
        m.append("  ⚠️ 這個指標目前**只量測不下行動指令**——老墨的『連 N 日轉弱就清倉』"
                 "是他自己系統的規則，我們沒有對應回測，不能拿來當出場指令。")

    ar = _load("state/advisor_reports_today.json", {}) or {}
    arows = ar.get("rows") or []
    afired = [r for r in arows if r.get("fired")]
    if arows:
        m.append(f"【投顧報告失效線】{len(arows)} 份在檢查，觸發 {len(afired)} 份")
        for r in afired[:5]:
            m.append(f"  🚫 {r.get('name')}({r.get('ticker')}) {r.get('broker')}："
                     f"{(r['fired'][0] or {}).get('desc','')}")

    # ⚠️ 2026-09-04：每一列都要標「是不是持股」。首測仲達自己點出這個缺口——
    # 「材料未標注 WM 是否為持股，我不確定」「券商異動沒標注是否為你的持股」。
    # 他答得誠實，但那是我沒給資料，不該讓他猜。
    tch = _load("state/target_changes_today.json", {}) or {}
    hits, oth = tch.get("alerts") or [], tch.get("ours_untrusted") or []
    if hits or oth:
        m.append(f"【券商異動】要推播 {len(hits)} 筆；母體內但不推播 {len(oth)} 筆")
        for r in (hits + oth)[:8]:
            d_ = {"up": "▲調升", "down": "▼調降"}.get(r.get("direction"), "－")
            tk = re.sub(r"\.(TW|TWO)$", "", str(r.get("ticker") or "").upper())
            m.append(f"  {d_} {r.get('name')}({r.get('ticker')})"
                     f"{'（持股）' if tk in _held_set() else '（非持股）'} "
                     f"{r.get('broker')} {r.get('rating')}　"
                     f"{r.get('tp_old')}→{r.get('tp_new')}（數字未經覆核）"
                     + (f"　←{r['_why']}" if r.get("_why") else ""))

    rm = _load("state/roadmap_milestones.json", {}) or {}
    today = dt.date.today()
    soon = []
    for x in rm.get("milestones", []):
        if x.get("status") != "pending":
            continue
        try:
            dd = (dt.date.fromisoformat(x["due"]) - today).days
        except Exception:                                   # noqa: BLE001
            continue
        if dd <= 60:
            soon.append((dd, x))
    for dd, x in sorted(soon)[:3]:
        m.append(f"【時程里程碑】{x['due']}（{dd} 天後）{x['chain']}｜{x['claim']}")
        if x.get("note"):
            m.append(f"  已查到：{x['note'][:150]}")
    return "\n".join(m) or "（今天沒有任何風險層的資料）"


# ── 陳壽：回頭看判斷準不準 ──────────────────────────────────────
def material_chen():
    m = []
    vs = _jsonl("state/advisor_verdicts.jsonl")
    m.append(f"【投資長判斷累積】共 {len(vs)} 筆")
    from collections import Counter
    for key, nm in (("trend_angle", "趨勢角度"), ("value_angle", "價值角度")):
        c = Counter((v.get(key) or {}).get("judgment") for v in vs
                    if (v.get(key) or {}).get("judgment"))
        m.append(f"  {nm} 分布：" + "、".join(f"{k} {n}" for k, n in c.most_common()))

    # ⚠️ verdict_review 沒有現成的 report()，要自己跑它的管線：
    # _load() → 每筆判斷 × 兩個角度 evaluate() → summarize()。
    # ⭐ 它數的是「判斷 × 角度」所以筆數比判斷本身多（328 筆判斷 → 517 條可評估），
    #   兩個數字都要講出來，不然會像資料對不上。
    try:
        import verdict_review as vr
        rows = vr._load()
        results = []
        for r in rows:
            for angle in ("trend_angle", "value_angle"):
                e = vr.evaluate(r, angle)
                if e:
                    results.append(e)
        have_price = sum(1 for r in rows if r.get("price") is not None)
        m.append(f"【復盤統計】{len(rows)} 筆判斷 → {len(results)} 條可評估"
                 f"（角度分開算）；有基準價的判斷 {have_price}/{len(rows)}")
        m.append(vr.summarize(results)[:2200])
    except Exception as e:                                  # noqa: BLE001
        m.append(f"（verdict_review 取用失敗：{str(e)[:120]}）")

    tj = _jsonl("state/trade_journal.jsonl")
    filled = [t for t in tj if t.get("status") == "filled"]
    m.append(f"【Leo 的交易紀錄】共 {len(tj)} 筆（已成交 {len(filled)} 筆）")
    m.append(f"  🔴 樣本嚴重不足：**{len(filled)} 筆**。低於 20 筆時**不得下任何"
             f"關於交易紀律的結論**（追高殺低、賺賠比、進出場時機都算）。"
             f"可以描述個別案例，但不能講模式。")
    for t in filled[-6:]:
        s_ = t.get("snapshot") or {}
        m.append(f"  · {t.get('date')} {t.get('broker')} {t.get('action')} "
                 f"{t.get('ticker')} {t.get('qty')}股 @{t.get('price')}"
                 f"｜理由：{'、'.join(t.get('reasons') or []) or '未填'}"
                 f"｜當時燈號 {s_.get('lit')}/4 風報比 {s_.get('rr')}")
    return "\n".join(m)


def _tickers_in_question(q):
    """回 [(代號, 名稱)]。跟 resolve_in_question 用同一套解析邏輯的精簡版。"""
    q = (q or "").strip()
    if not q:
        return []
    out = []
    try:
        import combo_scan
        for code, nm in (combo_scan._tw_names() or {}).items():
            if len(str(nm)) >= 2 and str(nm) in q:
                out.append((code, str(nm)))
    except Exception:                                       # noqa: BLE001
        pass
    for tk in re.findall(r"(?:^|[^0-9A-Za-z])([0-9]{4,6}[A-Z]?|[A-Z]{2,5})"
                         r"(?:[^0-9A-Za-z]|$)", " " + q + " "):
        out.append((tk, ""))
    if not out:
        try:
            import lookup_page
            eng = "".join(c if ord(c) < 128 else " " for c in q).strip()
            tries = [q] + ([eng] if eng and eng != q and len(eng) >= 3 else [])
            for t in tries:
                for code, nm in (lookup_page.resolve(t) or [])[:1]:
                    out.append((code, nm))
                if out:
                    break
        except Exception:                                   # noqa: BLE001
            pass
    seen, uniq = set(), []
    for code, nm in out:
        if code in seen:
            continue
        seen.add(code)
        uniq.append((code, nm))
    return uniq


# ── 孔明：對某一檔給兩個獨立角度的判斷 ──────────────────────────────
def material_kongming(question=""):
    """孔明不是「讀既有資料的人」，是**產生判斷的人**——材料就是
    `investment_chief.gather_material()` 那一整包（AI 綜合訊號／貴俗價／
    預估前提檢查／毛利率位階／券商報告／SuperTrend＋RS／產業輪動／今日研究員筆記）。

    ⚠️ **不重寫一份材料**：直接呼叫 investment_chief，所以 `/孔明` 跟每日排程
    產出的判斷吃的是同一包東西，不可能出現「兩邊講法不一樣」。
    ⚠️ 一定要有標的——沒點名股票時明講「要指定一檔」，不要瞎給大盤評論。
    """
    picks = _tickers_in_question(question)
    if not picks:
        return ("（沒有指定股票）孔明是個股判斷的角色，一次判一檔。"
                "請告訴使用者：要問哪一檔？例如「孔明 2454」「孔明 輝達怎麼看」。"
                "不要自己挑一檔來評論，也不要改成講大盤。")
    code, nm = picks[0]
    try:
        import investment_chief as ic
        mat = ic.gather_material(code, [])
    except Exception as e:                                  # noqa: BLE001
        return f"（investment_chief.gather_material({code}) 失敗：{str(e)[:150]}）"
    if isinstance(mat, (list, tuple)):
        keys = ("AI綜合訊號", "價值角度材料", "趨勢角度材料", "今日研究員筆記")
        mat = "\n\n".join(f"【{k}】\n{v}" for k, v in zip(keys, mat))
    # 公司在做什麼也要給——investment_chief 的材料全是數字，沒有業務描述，
    # 少了它 AI 會自己補（見 _one_stock_block 的註解）。
    return f"【判斷標的：{nm}（{code}）】\n{_profile(code)}\n\n{mat}"


# ── 龐統：查這一檔的新聞 ──────────────────────────────────────────
def material_pangtong(question=""):
    """龐統是**找材料**的角色。重用 `researcher_industry._search_one()`
    ——鉅亨網關鍵字搜尋（公開免 key、零成本），跟每日研究員同一個來源。

    ⚠️ 只給新聞，**不做判斷**——判斷是孔明的事，prompt 也這樣寫。
    """
    picks = _tickers_in_question(question)
    kws = []
    if picks:
        for code, name in picks[:2]:
            kws.append(code)
            if name:
                kws.append(name)
    else:
        kws = [question.strip()[:30]] if question.strip() else []
    if not kws:
        return "（沒有可查的關鍵字）請使用者說要查哪一檔或哪個主題。"
    out = []
    try:
        import researcher_industry as ri
        for kw in kws:
            for it in ri._search_one(kw, n=6):
                out.append(f"  · [{it['kw']}] {it['ts']}　{it['title']}\n"
                           f"    {it['url']}")
    except Exception as e:                                  # noqa: BLE001
        return f"（新聞查詢失敗：{str(e)[:120]}）"
    seen, uniq = set(), []
    for line in out:
        if line in seen:
            continue
        seen.add(line)
        uniq.append(line)
    body = (("【鉅亨網新聞搜尋】關鍵字：" + "、".join(kws) + "\n"
             + "\n".join(uniq[:14])) if uniq else
            f"【鉅亨網新聞搜尋】關鍵字 {kws}：**沒有找到任何新聞**")
    # 🔴 2026-09-04 Leo：「高力在做什麼的」——龐統回答不了，因為材料只有新聞快訊，
    # 沒有公司基本資料。那是**材料缺口不是他的問題**：問「這家在做什麼」是研究員
    # 最基本的職責之一，而我沒給他資料。
    # yfinance 的 longBusinessSummary/sector/industry 免費且台美股都有，補進來。
    prof = "\n".join(_profile(code) for code, _ in picks[:2]) if picks else ""
    return (prof + "\n\n" + body) if prof else body


def _profile(code):
    """公司基本資料（yfinance，免費）。查不到就明說，不要留空。"""
    import re as _re
    try:
        import yfinance as yf
        import tw_symbol
        sym = (tw_symbol.resolve(code)
               if _re.match(r"^[0-9]{4,6}[A-Z]?$", str(code)) else str(code))
        i = yf.Ticker(sym).info or {}
    except Exception as e:                                  # noqa: BLE001
        return f"【{code} 公司資料】查詢失敗：{str(e)[:80]}"
    if not i.get("longName") and not i.get("longBusinessSummary"):
        return f"【{code} 公司資料】查無（yfinance 沒有這檔的基本資料）"
    mc = i.get("marketCap")
    return (f"【{code} 公司資料】{i.get('longName') or ''}"
            f"｜產業：{i.get('sector') or '—'} / {i.get('industry') or '—'}"
            + (f"｜市值 {mc / 1e8:,.0f} 億" if mc else "")
            + f"\n  業務：{(i.get('longBusinessSummary') or '（無簡介）')[:600]}")


ROLES = {
    "仲達": {
        "name": "司馬懿 仲達（風險官）",
        "material": material_sima,
        "persona": (
            "你是隆中對的風險官「仲達」。你的職責是**看見現在的風險**，"
            "不是預測未來、也不是給進出場指令。\n"
            "鐵律：\n"
            "1. **不下行動指令**。你可以說「這檔的失效條件被觸發了、代表當初的判斷基礎"
            "不成立」，但不能說「所以你應該賣」。最終決定是 Leo 的。\n"
            "2. **不自行發明門檻**。材料裡沒有的判定線不要自己訂一個。"
            "電金比那個指標目前只量測不下指令，不要把它講成出場訊號。\n"
            "3. 材料裡標「數字未經覆核」的，引用時要一起講。\n"
            "4. 沒有資料就說沒有，不要用推論填空。"),
    },
    "孔明": {
        "name": "諸葛亮 孔明（投資長）",
        "material": material_kongming,
        "needs_question": True,
        "persona": (
            "你是隆中對的投資長「孔明」。你對**一檔股票**給兩個獨立角度的判斷。\n"
            "鐵律：\n"
            "1. **兩個角度要獨立判斷、不要互相影響**——長期價值角度（洪瑞泰：看估值、"
            "年為單位）不看短線趨勢好壞；中短期趨勢角度（SuperTrend＋RS＋產業輪動）"
            "不因為長期便宜就樂觀。**就算兩邊給出相反的建議也照實寫，"
            "不要為了看起來一致而修改任一邊。**\n"
            "2. 每個角度都要給：判斷（續抱可買／觀望／考慮出場／資料不足）"
            "＋一句話結論＋理由（事實與推論分開標）＋**失效條件**"
            "（什麼情況代表這個角度錯了）。\n"
            "3. **不要替 Leo 執行交易**——你的判斷是建議不是指令。\n"
            "4. 資料不足就填「資料不足」並說缺什麼，不要硬掰。\n"
            "5. 材料裡若有「預估前提檢查」，它量的是**市場對這檔的期待被堆到多高**，"
            "是容錯空間的刻度，不是公司好壞的評價。"),
    },
    "龐統": {
        "name": "龐統（研究員）",
        "material": material_pangtong,
        "needs_question": True,
        "persona": (
            "你是隆中對的研究員「龐統」。你的職責是**把找到的材料整理成可讀的研究筆記**，"
            "不是下投資判斷。\n"
            "鐵律：\n"
            "1. **不給買賣建議、不給目標價、不判斷貴便宜**——那是孔明的事。"
            "你只負責「發生了什麼、跟什麼有關」。\n"
            "2. **只根據下面的新聞材料寫**，不要自己補背景知識當事實。"
            "要補脈絡就標明「這是我的補充，不在材料裡」。\n"
            "3. 新聞有日期，**要講哪一則是什麼時候的**——舊聞當新聞是研究員最嚴重的錯。\n"
            "4. 材料是關鍵字搜尋來的，**可能有不相關的**。判斷不相關就直接說不相關，"
            "不要硬湊進敘事。\n"
            "5. 最後給一句「這對持有這檔的人意味著什麼」——描述性的，不是建議。"),
    },
    "陳壽": {
        "name": "陳壽（復盤官）",
        "material": material_chen,
        "persona": (
            "你是隆中對的復盤官「陳壽」。你回頭檢查**這套系統的判斷準不準**，"
            "以及（樣本夠時）Leo 自己的交易紀律。\n"
            "鐵律：\n"
            "1. **樣本不足就明講不足**。交易紀錄低於 20 筆時，**絕對不能**下任何"
            "關於紀律的結論（追高殺低／賺賠比／時機）——可以描述個別案例，不能講模式。\n"
            "2. 判斷準確度的窗口未滿時，浮動報酬**不是準確度**，要講清楚這一點。\n"
            "3. 事後回填基準價的那批要跟實時記錄分開講。\n"
            "4. 不要為了有話講而把雜訊講成模式。"),
    },
}

PROMPT = """{persona}

今天是 {date}。以下是系統幫你備好的材料——**只根據這些材料回答，不要自己去查別的**。

===== 材料開始 =====
{material}
===== 材料結束 =====

Leo 的問題：{question}

回答要求：
- **繁體中文（台灣用語）**，一個簡體字都不能出現。
- 會貼在 Discord，**{limit} 字以內**，用短段落或條列，不要長篇。
- 把**事實**（材料裡寫的）跟**推論**（你的判讀）分開標示。
- 材料裡沒有的就說沒有，不要補。
- 開頭直接講結論，不要「好的，讓我來分析」這種開場。

🔴 **精簡規則（2026-09-04 Leo：「有一段囉嗦不太像軍師，可以簡單一點，
多給一些有用的資訊」）**：
1. **第一句就回答他問的那件事**。問「在做什麼的」就先講這家公司做什麼，
   不要先花一段講「這檔不是持股、數字是臨時算的」——那種話放最後一行，一句話帶過。
2. **同類的雜訊合併成一句，不要逐條加註**。三則大盤新聞就寫
   「另有 3 則是大盤新聞，跟這檔本身無關」，不要每一則後面都掛一個
   「（這是大盤新聞，非個股專屬）」。
3. **不要固定段落**。「沒有的部分」「這對持有的人意味著什麼」這種欄位，
   **有話講才寫**；沒有實質內容就整段不要出現。
4. **同一件事只講一次**。前面說過的限制，後面不要再覆述一遍。
5. 寧可**少講幾句廢話、多給一個具體數字**。

🔴 **代號鐵律（違反這條比答不出來嚴重得多）**：
Leo 問哪一檔，就只能回答那一檔。**絕對不可以**因為材料裡沒有它，
就拿一個「看起來像」或「名字接近」的代號來代替。
2026-09-04 實際發生過：問「高力（8996）」，回答的是「HIG（The Hartford
Insurance Group）」——完全不同的公司，而且整段講得很有條理。
材料開頭若有「問題裡提到的個股」區塊，**以那個區塊為準**；
它若寫著「這檔完全查不到」，唯一正確的回答就是**照講**，不要用別的標的填空。
它若標「🔍 即時計算」，那是為了回答這個問題臨時算的——**要講明這檔不在每日監控裡**，
數字只是這一刻的快照，不像持股那樣有人在盯。"""

DEFAULT_Q = {
    "仲達": "今天我該注意什麼風險？照重要性排序，講最關鍵的三件。",
    "陳壽": "現在的復盤結果告訴我們什麼？哪些還不能下結論？",
    "孔明": "這檔現在怎麼看？兩個角度各給判斷與失效條件。",
    "龐統": "這檔最近有什麼消息？",
}


def council_roles(question=""):
    """一次問四位時，決定叫誰。**規則判斷，不用 AI 分派。**

    🔴 2026-09-04 Leo 問「不能四位一起回答嗎？由孔明統一分派？還是加一位角色？」
    三個都不做，理由：

    · **不用孔明分派**——分派是規則問題（有沒有指定個股），不是判斷問題；
      而且他的職責是「對一檔給兩個獨立角度」，兼任調度會混淆角色。
    · **不加第五位**——四位已涵蓋「找材料／下判斷／看風險／看紀錄」。
      第五位只會是「轉述前四位講的話」的人，那正是 Leo 剛嫌過的囉嗦。
    · **不用 AI 分派**——多一層 AI 就多一次會錯的機會（同日才踩過答錯股票）；
      而且分派者要猜使用者想問什麼，猜錯的成本比省下的時間高。

    規則很簡單，因為問題本來就只有兩種：
      有指定個股 → 龐統（發生什麼事）→ 孔明（怎麼看）→ 仲達（有沒有在監控/風險）
      沒指定個股 → 龐統（主題新聞）→ 仲達（今天的風險）→ 陳壽（我們的紀錄）
    ⚠️ 陳壽的材料是**全局**的（判斷準確度、交易紀錄），不是個股層，
      所以問個股時不叫他——叫了也只會重複講全局統計。
    """
    return (["龐統", "孔明", "仲達"] if _tickers_in_question(question)
            else ["龐統", "仲達", "陳壽"])


def ask(role, question=None, limit=MAX_CHARS):
    r = ROLES.get(role)
    if not r:
        return f"沒有這位軍師：{role}（可用：{'、'.join(ROLES)}）"
    q = (question or "").strip() or DEFAULT_Q[role]
    # 孔明/龐統要看問題才知道查哪一檔；仲達/陳壽的材料跟問題無關（是當日全貌）
    mat = (r["material"](question) if r.get("needs_question")
           else r["material"]())
    # 問題裡點名的個股，把它的**真實資料**加在材料最前面（見 resolve_in_question
    # 的註解：2026-09-04 答錯股票那次）。放最前面是因為材料會被截斷。
    named = resolve_in_question(question)
    if named:
        mat = named + "\n\n" + mat
    import llm_board
    base = PROMPT.format(persona=r["persona"],
                         date=dt.date.today().isoformat(),
                         material=mat[:9000], question=q, limit=limit)
    # 繁體字是 Leo 的硬規則。**prompt 寫「用繁體」不等於做到**
    # （simplified_chinese_guard 記過：鐵則本來就有，MRVL 那張照樣整張簡體）。
    # 首測仲達就吐出一個「还」。所以偵測到就帶著「你用了哪幾個」重寫，最多 3 次；
    # 還是有就照實標出來，不要靜靜送出去。
    txt, fix, bad = "", "", []
    for _ in range(3):
        out = llm_board.ask(base + fix)
        if not out:
            return f"⚠️ {r['name']} 這次沒有產出（本機 claude 沒回應），請再試一次。"
        txt = out.strip()
        try:
            bad = sorted(llm_board.simplified_chars(txt))
        except Exception:                                   # noqa: BLE001
            bad = []
        if not bad:
            return txt[:limit]
        fix = ("\n\n⚠️ 你上一次的回答用了簡體字（" + "".join(bad[:10])
               + "）。整份重寫，全部用繁體中文（台灣用語），一個簡體字都不能有。")
    return (txt + "\n\n⚠️ 重寫 3 次後仍偵測到簡體字："
            + "".join(bad[:8]))[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("role", choices=list(ROLES) + ["軍議"])
    ap.add_argument("question", nargs="?", default="")
    ap.add_argument("--material-only", action="store_true",
                    help="只印材料不呼叫 AI（除錯用）")
    a = ap.parse_args()
    if a.role == "軍議":
        roles = council_roles(a.question)
        print(f"—— 軍議：{'、'.join(roles)} ——")
        for r in roles:
            print(f"{os.linesep}—— {ROLES[r]['name']} ——")
            print(ask(r, a.question))
        return 0
    if a.material_only:
        m = ROLES[a.role]
        print(m["material"](a.question) if m.get("needs_question")
              else m["material"]())
        return 0
    print(f"—— {ROLES[a.role]['name']} ——")
    print(ask(a.role, a.question))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
