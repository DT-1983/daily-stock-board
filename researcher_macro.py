"""研究員 Agent —— 總體層。每天開盤前跑一次，但不是每天都花錢叫 AI。

2026-08-26 Leo 問「可以降到0嗎」之後重構：拆成兩塊——
1. macro_calendar.py：FOMC/CPI/非農/台灣央行「哪天開會/發布」是官方提前公布的排定行程，
   純查表零成本零AI呼叫。
2. 這裡：只有「今天前後1天內有排定事件」才值得花錢叫 claude -p + WebSearch 去查證
   當天的實際結果/有沒有意外消息（例如已知的行事曆之外的人事變動、法說會意外重點）。
   平常沒事的日子直接用查表結果存一筆零成本筆記，不叫AI。

用 `--json-schema` 強制結構化輸出（見 dev_log 2026-08-26 實測：CLI層級驗證，比
llm_board.ask_json() 的「拜託只回JSON+正則猜測+重試」硬）。

2026-08-26 先落地：只存本機 JSONL，不進 advisor.db（schema 設計好了但還沒建表，
先跑幾天驗證輸出品質/成本穩不穩，見 investment_advisor_architecture.md）。

用法: python researcher_macro.py
"""
import os
import sys
import json
import time
import subprocess

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_board import _claude_bin  # 共用同一套 CLAUDE_BIN 尋找邏輯，不重複寫
from macro_calendar import upcoming_events, needs_verification

NOTES_PATH = "state/research_notes.jsonl"

SCHEMA = {
    "type": "object",
    "properties": {
        "layer": {"type": "string", "enum": ["macro"]},
        "scope": {"type": "string"},
        "source": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "summary": {"type": "string"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "market": {"type": "string", "enum": ["US", "TW", "global"]},
                    "event": {"type": "string"},
                    "date": {"type": "string"},
                    "status": {"type": "string", "enum": ["scheduled", "released"]},
                },
                "required": ["market", "event", "date", "status"],
            },
        },
    },
    "required": ["layer", "scope", "source", "confidence", "summary", "events"],
}

PROMPT = """你是總體經濟研究員，任務是幫投資長整理研究筆記，不是給結論、不是建議買賣。

鐵律（不能違反）：
1. 把事實、推論、假設分開標註——summary 裡用「已公布：」「預期：」這種字眼區分
2. 資料不足就直接說缺少什麼，不要自己補數字
3. 不要建議買賣，只整理事實給投資長參考

今天是 {date}。下面是已經確認的行事曆事件（不用重查，這是已知事實）：
{known_events}

任務：針對上面這些事件，查證：
1. 已經發生的（status=released）：實際公布的數字是多少？跟市場預期比如何？
2. 還沒發生的（status=scheduled）：市場預期是什麼？有沒有行事曆上沒有但相關的意外消息
   （例如人事異動、政策風向轉變）？
不要重新查一次「有哪些事件」，上面已知事件清單就是全部，只需要查「這些事件的細節/結果」。
events 陣列照原樣列出上面每個事件，可以在 event 欄位裡補充查到的細節。
scope 填 "global"；source 填 "websearch"；confidence 依資料確定性填 high/medium/low
（已公布的數字=high，尚未發生但已排定時程=medium，不確定的傳言=low）。"""


def _save(note):
    os.makedirs("state", exist_ok=True)
    with open(NOTES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    cost = note.get("cost_usd")
    print(f"已存：{NOTES_PATH}（cost約${cost:.3f}）" if cost is not None else f"已存：{NOTES_PATH}（零成本，查表）")
    print(json.dumps(note, ensure_ascii=False, indent=2))


def _ask_claude(events, date):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    known = "\n".join(f"- {e['date']} {e['market']} {e['event']}（{e['status']}）" for e in events)
    prompt = PROMPT.format(date=date, known_events=known)
    r = subprocess.run(
        [exe, "-p", "--dangerously-skip-permissions", "--output-format", "json",
         "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude 失敗 (exit {r.returncode}): {(r.stderr or '')[:300]}")
    out = json.loads(r.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude 回錯誤: {out}")
    note = out.get("structured_output")
    if not note:
        raise RuntimeError(f"沒有 structured_output，原始回覆：{r.stdout[:300]}")
    note["ts"] = date
    note["cost_usd"] = out.get("total_cost_usd")
    return note


def run():
    date = time.strftime("%Y-%m-%d")
    near_term = needs_verification(date, window_days=1)   # 今天前後1天內有事才花錢查

    if not near_term:
        note = {
            "layer": "macro", "scope": "global", "source": "calendar",
            "confidence": "high",
            "summary": "近期（前後1天）無排定總經事件，跳過AI查證，零成本。"
                       "近期已知行事曆（未來25天內）：" +
                       ("；".join(f"{e['date']} {e['market']} {e['event']}"
                                  for e in upcoming_events(date, days_before=0, days_after=25)) or "無"),
            "events": upcoming_events(date, days_before=0, days_after=25),
            "ts": date, "cost_usd": 0.0,
        }
        _save(note)
        return note

    note = _ask_claude(near_term, date)
    _save(note)
    return note


if __name__ == "__main__":
    run()
