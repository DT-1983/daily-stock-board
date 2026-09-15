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


def render(tk, verdict, cond_entry):
    name = tkname(tk)
    held = bool((verdict or {}).get("held") or (cond_entry or {}).get("held"))
    ts = (verdict or {}).get("ts") or (cond_entry or {}).get("source_date") or "?"
    price = (verdict or {}).get("price")
    price_asof = (verdict or {}).get("price_asof")

    out = [f"# {name}", ""]
    out.append(f"軍師資料庫（AI 專用，非給人讀）｜持有：{'是' if held else '否'}"
                f"｜最後更新：{ts}"
                + (f"｜參考價 {price}（{price_asof}）" if price is not None else ""))
    out.append("")
    out.append("## 投資長判斷")
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
    006208.TW 各自生出一份）。用 investment_chief 自己的 norm_ticker() 收斂，
    同一正規化 key 只留一組，優先選有 verdict 的那個原始代號當檔名。"""
    canon = {}          # norm key -> 選定的原始代號
    for tk in set(verdicts) | set(conditions):
        k = norm_ticker(tk)
        if k not in canon or (tk in verdicts and canon[k] not in verdicts):
            canon[k] = tk
    merged_v, merged_c = {}, {}
    for tk in verdicts:
        k = norm_ticker(tk)
        pick = canon[k]
        if pick not in merged_v or verdicts[tk].get("ts", "") >= merged_v[pick].get("ts", ""):
            merged_v[pick] = verdicts[tk]
    for tk in conditions:
        k = norm_ticker(tk)
        merged_c[canon[k]] = conditions[tk]
    return merged_v, merged_c


def main():
    verdicts = _latest_verdicts()
    conditions = json.load(io.open(CONDITIONS_PATH, encoding="utf-8")) \
        if os.path.exists(CONDITIONS_PATH) else {}
    verdicts, conditions = _dedupe(verdicts, conditions)
    tickers = sorted(set(verdicts) | set(conditions))
    print(f"軍師資料庫：{len(tickers)} 檔（verdicts {len(verdicts)} / conditions {len(conditions)}）")

    if not op.available():
        print("obis 不在這台機器上，略過（跟其他 obis 輸出一樣的行為）")
        return

    index = ["# 軍師資料庫索引", "", "AI 專用，非給人讀。逐檔內容見同資料夾其他檔案。", ""]
    for tk in tickers:
        v = verdicts.get(tk)
        c = conditions.get(tk)
        held = bool((v or {}).get("held") or (c or {}).get("held"))
        name = tkname(tk)
        fn = (f"{tk}_{name.split(' ', 1)[1]}.md" if " " in name else f"{tk}.md").replace("/", "_")
        try:
            content = render(tk, v, c)
            io.open(op.advisor_db(fn), "w", encoding="utf-8").write(content)
        except Exception as e:                                  # noqa: BLE001
            print(f"  [WARN] {tk} 產生失敗：{str(e)[:120]}")
            continue
        j = (v or {}).get("trend_angle", {}).get("judgment", "")
        icon = J_ICON.get(j, "⚪")
        index.append(f"- [{name}]({fn})　{'🟢持有' if held else ''}{icon}{j}")

    io.open(op.advisor_db("_索引.md"), "w", encoding="utf-8").write("\n".join(index))
    print(f"已寫入 {len(tickers)} 檔 + 索引 → {op.ADVISOR_DB}")


if __name__ == "__main__":
    main()
