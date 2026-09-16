# -*- coding: utf-8 -*-
"""軍師資料庫匯出（2026-09-15，Leo：「讓AGENT有需要可以直接讀（軍議跟燈號討論的功能）」）。

跟老墨自己的做法同一套：把 state/*.jsonl 那些原始資料庫轉成一檔一股的
Markdown，丟進 obis（全域已知路徑），讓任何一個 Claude session都找得到、
讀得懂——不是給 Leo 看的，格式濃度優先，不用排版。

來源只有兩個（都是 investment_chief.py / thesis_check.py 寫的）：
  · state/advisor_verdicts.jsonl —— 投資長逐日判斷（取每檔最新一筆）
  · state/thesis_conditions.json —— 失效線／燈號登錄簿（現在還生不生效）

⚠️ 只新增/覆寫，不刪舊檔——一支股票從追蹤名單移除後，它的檔案會停在
最後一次的內容（舊日期），不會消失也不會被清空。這跟「每日看板」的
「舊日期＝那支壞了」是同一個判準，但這裡的「壞了」可能是「已經不追蹤了」，
不是程式故障。要不要做自動清除，之後有需要再說（見 dev_log 2026-09-15）。

用法: python advisor_db_export.py
"""
import io
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                       # noqa: E402
from daily_warroom import tkname, J_ICON                       # noqa: E402
from investment_chief import norm_ticker                       # noqa: E402

VERDICTS_PATH = "state/advisor_verdicts.jsonl"
CONDITIONS_PATH = "state/thesis_conditions.json"
# 2026-09-16 Leo：「不是只有券商目標價，還要加上相關的資料（不只限於營收）」。
# 這是第一種「查過的事實」資料源，之後同類型的（不管什麼主題）都照這個
# 模式加：獨立存一份 state/*.json，這裡多讀一份、render() 多一段。
MONTHLY_REVENUE_PATH = "state/monthly_revenue.json"
# 2026-09-16：第三種事實來源——industry-note-intake skill 那套一次性產業筆記
# （社群貼文/券商影音整理）查到的個股事實，見 industry_notes.py。

STATUS_ICON = {"triggered": "🔴已觸發", "active": "⏳追蹤中"}


def _load_jsonl(p):
    if not os.path.exists(p):
        return []
    out = []
    for ln in io.open(p, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:                                      # noqa: BLE001
            pass
    return out


def _latest_verdicts():
    """每檔只留最新一筆（用 ts 比較）。"""
    latest = {}
    for d in _load_jsonl(VERDICTS_PATH):
        tk = d.get("ticker")
        if not tk:
            continue
        if tk not in latest or d.get("ts", "") >= latest[tk].get("ts", ""):
            latest[tk] = d
    return latest


def _safe(s, n=None):
    s = "" if s is None else str(s)
    return s[:n] if n else s


def _angle_block(title, a):
    """trend_angle 或 value_angle 一段。"""
    if not a:
        return f"### {title}\n（無資料）\n"
    j = a.get("judgment", "")
    icon = J_ICON.get(j, "")
    out = [f"### {title}：{icon}{j}"]
    if a.get("brief"):
        out.append(f"**結論**：{_safe(a['brief'])}")
    if a.get("reasoning"):
        out.append(f"**理由**：{_safe(a['reasoning'])}")
    if a.get("invalidation_price") or a.get("invalidation_level") is not None:
        lvl = a.get("invalidation_level")
        out.append(f"**翻多/翻空點**：{_safe(a.get('invalidation_price'))}"
                    + (f"（價位 {lvl}）" if lvl is not None else ""))
    if a.get("support_resistance"):
        out.append(f"**支撐壓力**：{_safe(a['support_resistance'])}")
    if a.get("bull_bear_debate"):
        out.append(f"**多空辯論**：{_safe(a['bull_bear_debate'])}")
    if a.get("event_risk"):
        out.append(f"**事件風險**：{_safe(a['event_risk'])}")
    return "\n\n".join(out) + "\n"


def _conditions_block(conds, angle_filter=None):
    rows = [c for c in (conds or []) if not angle_filter or c.get("angle") == angle_filter]
    if not rows:
        return "（無登記條件）\n"
    lines = []
    for c in rows:
        icon = STATUS_ICON.get(c.get("status"), "⏳追蹤中")
        v = c.get("value")
        vs = f"（門檻 {v}）" if v is not None else ""
        trig = f"　觸發於 {c['triggered_date']}" if c.get("triggered_date") else ""
        lines.append(f"- {icon} {_safe(c.get('desc'))}{vs}{trig}")
    return "\n".join(lines) + "\n"


def _reports_block(reports):
    """券商目標價——直接讀 advisor_reports.json，零 AI 成本，**不等投資長判斷完**。

    2026-09-16 Leo：「新增目標價自動變觸發事件」之後才發現，投資長從觸發到
    真的判斷完要跑好一陣子（每檔 1.6~2.8 分鐘），中間這段空窗期軍師資料庫
    完全沒有這幾檔的檔案——但目標價這種事實其實早就有、不用等 AI。
    這段直接秀原始登錄簿內容，跟下面「投資長判斷」段落分開放、清楚標明
    誰是事實（這段）誰是判斷（下段，可能還沒有）。"""
    if not reports:
        return "（無券商報告登記）\n"
    lines = []
    for r in sorted(reports, key=lambda x: x.get("date") or "", reverse=True):
        lines.append(f"- **{r.get('broker','')}**　{r.get('date','?')}"
                     f"｜評等：{r.get('rating') or '—'}"
                     f"｜目標價：{r.get('target') or '—'}"
                     + (f"　⚠️ {r['_note'][:60]}" if r.get("_manual_entry") and r.get("_note")
                        else ""))
    return "\n".join(lines) + "\n"


def _revenue_block(rev):
    """月營收事實（2026-09-16，跟券商目標價同一層級：查過的事實，不用等 AI）。"""
    if not rev:
        return None
    hi = "　★歷史單月新高" if rev.get("record_high") else ""

    def _pct(v):
        return "—" if v is None else f"{v:+.1f}%"
    out = [f"- {rev.get('period','?')} 營收 {rev.get('revenue',0)/1e8:,.1f} 億"
          f"｜YoY {_pct(rev.get('yoy'))}｜MoM {_pct(rev.get('mom'))}{hi}"]
    if rev.get("comment"):
        out.append(f"- 備註：{_safe(rev['comment'])}"
                   f"（來源：{_safe(rev.get('comment_source',''))}）")
    out.append(f"- 資料源：{_safe(rev.get('data_source',''))}，查證日 {rev.get('fetched','?')}")
    return "\n".join(out) + "\n"


def _industry_notes_block(notes):
    """一次性產業筆記查到的個股事實（2026-09-16，見檔頭）。可以有多筆——
    同一檔股票在不同主題的筆記各出現一次都留著，不像月營收只留最新快照。"""
    if not notes:
        return None
    out = []
    for n in sorted(notes, key=lambda x: x.get("date") or "", reverse=True):
        out.append(f"- **{_safe(n.get('topic'))}**　{n.get('date','?')}")
        out.append(f"  {_safe(n.get('summary'))}")
        out.append(f"  （來源：{_safe(n.get('source'))}；完整報告：{_safe(n.get('report_path'))}）")
    return "\n".join(out) + "\n"


def render(tk, verdict, cond_entry, reports=None, revenue=None, notes=None):
    name = tkname(tk)
    held = bool((verdict or {}).get("held") or (cond_entry or {}).get("held")
                or any(r.get("_manual_held") for r in (reports or [])))
    ts = (verdict or {}).get("ts") or (cond_entry or {}).get("source_date") or "?"
    price = (verdict or {}).get("price")
    price_asof = (verdict or {}).get("price_asof")

    out = [f"# {name}", ""]
    out.append(f"軍師資料庫（AI 專用，非給人讀）｜持有：{'是' if held else '否'}"
                f"｜最後更新：{ts}"
                + (f"｜參考價 {price}（{price_asof}）" if price is not None else ""))
    out.append("")
    out.append("## 券商目標價（事實，來自登錄簿，不用等投資長判斷）")
    out.append("")
    out.append(_reports_block(reports))
    rb = _revenue_block(revenue)
    if rb:
        out.append("## 月營收（事實，FinMind 官方申報數字）")
        out.append("")
        out.append(rb)
    nb = _industry_notes_block(notes)
    if nb:
        out.append("## 相關產業筆記（事實，社群貼文/券商影音整理，FinMind核對過）")
        out.append("")
        out.append(nb)
    out.append("## 投資長判斷（AI，可能還沒輪到這檔——見上面「最後更新」）")
    out.append("")
    va = (verdict or {}).get("trend_angle")
    ha = (verdict or {}).get("value_angle")
    out.append(_angle_block("趨勢角度（技術面）", va))
    out.append(_angle_block("價值角度（估值面）", ha))
    out.append("## 失效線（燈號條件）")
    out.append("")
    conds = (cond_entry or {}).get("conditions")
    out.append("**趨勢角度：**")
    out.append(_conditions_block(conds, "trend"))
    out.append("**價值角度：**")
    out.append(_conditions_block(conds, "value"))
    return "\n".join(out)


def _dedupe(verdicts, conditions):
    """2303 / 2303.TW 這類同一檔的不同寫法，兩份來源不見得用同一種——
    直接 union 會產生兩個檔案講同一檔股票（2026-09-15 實測抓到：006208 /
    006208.TW 各自生出一份）。

    2026-09-16 重寫：原本挑一個「代表用」的原始代號當 key，同一檔股票兩次
    執行剛好遇到不同寫法（一次只有 "2606"、一次多了 "2606.TW"）就會挑到不同
    代表，寫出兩個檔案講同一檔股票（實測抓到：裕民同時有 2606_裕民.md 跟
    2606.TW_裕民.md）。改成直接用**正規化後的代號當 key**，不挑代表——
    不管來源當下用哪種寫法，同一檔股票永遠落在同一把 key，檔名/查找都穩定。"""
    merged_v, merged_c = {}, {}
    for tk, v in verdicts.items():
        k = norm_ticker(tk)
        if k not in merged_v or v.get("ts", "") >= merged_v[k].get("ts", ""):
            merged_v[k] = v
    for tk, c in conditions.items():
        merged_c[norm_ticker(tk)] = c
    return merged_v, merged_c


def _reports_by_ticker():
    """券商目標價登錄簿，依 norm_ticker() 收斂成 {正規化代號: [report,...]}——
    跟 _dedupe() 同一個理由，同一檔股票的不同代號寫法不能拆成兩份檔案。"""
    import advisor_reports as ar
    store = ar.active()
    out = {}
    for r in store.values():
        tk = r.get("ticker")
        if not tk:
            continue
        out.setdefault(norm_ticker(tk), []).append(r)
    return out


def _revenue_by_ticker():
    """月營收事實（見檔頭 2026-09-16），一樣要正規化代號才能跟其他來源比對。"""
    if not os.path.exists(MONTHLY_REVENUE_PATH):
        return {}
    d = json.load(io.open(MONTHLY_REVENUE_PATH, encoding="utf-8"))
    return {norm_ticker(tk): r for tk, r in d.items()}


def main():
    verdicts = _latest_verdicts()
    conditions = json.load(io.open(CONDITIONS_PATH, encoding="utf-8")) \
        if os.path.exists(CONDITIONS_PATH) else {}
    verdicts, conditions = _dedupe(verdicts, conditions)
    reports = _reports_by_ticker()
    revenues = _revenue_by_ticker()
    import industry_notes
    notes = industry_notes.by_ticker()
    # 2026-09-16：verdicts/conditions/reports/revenues/notes 現在全部都是用
    # norm_ticker() 正規化後的代號當 key（_dedupe 那邊已經統一），直接取聯集，
    # **不用再挑一個「顯示用原始代號」**——那正是昨天分裂成兩個檔案的根因
    # （挑代表這件事本身就會因為兩次執行資料不同而選到不同結果）。
    # 正規化後的代號本身就拿來當檔名/查表用，穩定、不會因為執行順序改變。
    tickers = sorted(set(verdicts) | set(conditions) | set(reports)
                     | set(revenues) | set(notes))
    print(f"軍師資料庫：{len(tickers)} 檔（verdicts {len(verdicts)} / conditions {len(conditions)} "
         f"/ 券商目標價 {len(reports)} / 月營收 {len(revenues)} / 產業筆記 {len(notes)}）")

    if not op.available():
        print("obis 不在這台機器上，略過（跟其他 obis 輸出一樣的行為）")
        return

    index = ["# 軍師資料庫索引", "", "AI 專用，非給人讀。逐檔內容見同資料夾其他檔案。", ""]
    for tk in tickers:                                       # tk 現在就是正規化代號
        v = verdicts.get(tk)
        c = conditions.get(tk)
        rs = reports.get(tk)
        rv = revenues.get(tk)
        nt = notes.get(tk)
        held = bool((v or {}).get("held") or (c or {}).get("held"))
        name = tkname(tk)
        fn = (f"{tk}_{name.split(' ', 1)[1]}.md" if " " in name else f"{tk}.md").replace("/", "_")
        try:
            content = render(tk, v, c, rs, rv, nt)
            io.open(op.advisor_db(fn), "w", encoding="utf-8").write(content)
        except Exception as e:                                  # noqa: BLE001
            print(f"  [WARN] {tk} 產生失敗：{str(e)[:120]}")
            continue
        j = (v or {}).get("trend_angle", {}).get("judgment", "")
        icon = J_ICON.get(j, "⚪") if v else "📄"
        tag = j if v else "（只有事實資料，投資長還沒判斷）"
        index.append(f"- [{name}]({fn})　{'🟢持有' if held else ''}{icon}{tag}")

    io.open(op.advisor_db("_索引.md"), "w", encoding="utf-8").write("\n".join(index))
    print(f"已寫入 {len(tickers)} 檔 + 索引 → {op.ADVISOR_DB}")


if __name__ == "__main__":
    main()
