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
    m.append(f"【失效條件日檢】{tc.get('date','—')}：覆蓋 {tc.get('covered_count','?')} 檔，"
             f"**觸發 {len(fired)} 條**、逼近 {len(near)} 條、"
             f"等財報才驗 {len(pend)} 條"
             + (f"；未覆蓋 {tc['uncovered']}" if tc.get("uncovered") else ""))
    for tk, desc, held, ang in fired[:10]:
        m.append(f"  🚫 {tk}{'（持股）' if held else ''}[{ang}] {desc}")
    for tk, desc, held, ang in near[:6]:
        m.append(f"  ⚠️ {tk}{'（持股）' if held else ''}[{ang}] 逼近：{desc}")

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

    tch = _load("state/target_changes_today.json", {}) or {}
    hits, oth = tch.get("alerts") or [], tch.get("ours_untrusted") or []
    if hits or oth:
        m.append(f"【券商異動】可信券商 × 我們母體內 {len(hits)} 筆；"
                 f"母體內但券商不在可信名單 {len(oth)} 筆")
        for r in (hits + oth)[:6]:
            d_ = {"up": "▲調升", "down": "▼調降"}.get(r.get("direction"), "－")
            m.append(f"  {d_} {r.get('name')}({r.get('ticker')}) {r.get('broker')} "
                     f"{r.get('rating')}　{r.get('tp_old')}→{r.get('tp_new')}"
                     f"（數字未經覆核）")

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
- 開頭直接講結論，不要「好的，讓我來分析」這種開場。"""

DEFAULT_Q = {
    "仲達": "今天我該注意什麼風險？照重要性排序，講最關鍵的三件。",
    "陳壽": "現在的復盤結果告訴我們什麼？哪些還不能下結論？",
}


def ask(role, question=None, limit=MAX_CHARS):
    r = ROLES.get(role)
    if not r:
        return f"沒有這位軍師：{role}（可用：{'、'.join(ROLES)}）"
    q = (question or "").strip() or DEFAULT_Q[role]
    mat = r["material"]()
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
    ap.add_argument("role", choices=list(ROLES))
    ap.add_argument("question", nargs="?", default="")
    ap.add_argument("--material-only", action="store_true",
                    help="只印材料不呼叫 AI（除錯用）")
    a = ap.parse_args()
    if a.material_only:
        print(ROLES[a.role]["material"]())
        return 0
    print(f"—— {ROLES[a.role]['name']} ——")
    print(ask(a.role, a.question))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
