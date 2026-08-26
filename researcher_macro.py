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
from macro_calendar import (upcoming_events, needs_verification, macro_headlines,
                            market_anomaly, keyword_hits)

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

任務：
1. 行事曆事件——已經發生的（released）查實際公布數字跟市場預期差多少；
   還沒發生的（scheduled）查市場預期，以及有沒有行事曆上沒有但相關的意外消息。
   不要重新查一次「有哪些事件」，上面清單就是全部。
2. 如果下面有附「市場異常波動」或「警示關鍵字新聞」——那代表發生了行事曆上沒有的事，
   要查清楚：發生了什麼、影響範圍多大、是短期噪音還是結構性變化。
   這類事件本來就不在行事曆上（關稅戰、戰爭、制裁、信用事件），是這次要觀測的重點。
   **市場異常但查不出原因時要直接說「查不到對應事件」**，不要硬找一個新聞來配。

events 陣列列出所有事件（行事曆的照原樣列、意外事件也新增進去，用當天日期）。
scope 填 "global"；source 填 "websearch"；confidence 依資料確定性填 high/medium/low
（已公布的數字=high，尚未發生但已排定時程=medium，不確定的傳言=low）。"""


def _save(note):
    os.makedirs("state", exist_ok=True)
    with open(NOTES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    cost = note.get("cost_usd")
    print(f"已存：{NOTES_PATH}（cost約${cost:.3f}）" if cost is not None else f"已存：{NOTES_PATH}（零成本，查表）")
    print(json.dumps(note, ensure_ascii=False, indent=2))


def _ask_claude(events, date, anomalies=None, kw_hits=None, headlines=None):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    known = "\n".join(f"- {e['date']} {e['market']} {e['event']}（{e['status']}）"
                      for e in events) or "（無排定事件）"
    extra = ""
    if anomalies:
        extra += "\n\n市場異常波動（已偵測到，這是事實不用查證）：\n" + \
                 "\n".join(f"- {a}" for a in anomalies)
    if kw_hits:
        extra += "\n\n今日新聞命中警示關鍵字（已附上，不用再查）：\n" + \
                 "\n".join(f"- [{k}] {t}" for k, t in kw_hits[:8])
    if headlines and not kw_hits:
        extra += "\n\n今日總經新聞標題（已附上，不用再查）：\n" + \
                 "\n".join(f"- {h['ts']} {h['title']}" for h in headlines[:8])
    prompt = PROMPT.format(date=date, known_events=known) + extra
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
    near_term = needs_verification(date, window_days=1)   # 今天前後1天內有排定事件
    headlines = macro_headlines(5)   # 免費、非LLM，鉅亨網總經新聞，所有分支都附
    # 2026-08-26 加：沒排定的重大事件觸發器（關稅戰/戰爭/制裁這種不會出現在行事曆上，
    # 但一樣撼動大盤）。兩個都零成本：市場異常讀既有 market_data.json，關鍵字純字串比對。
    anomalies = market_anomaly()
    kw_hits = keyword_hits(headlines)

    if not (near_term or anomalies or kw_hits):
        note = {
            "layer": "macro", "scope": "global", "source": "calendar+headlines",
            "confidence": "high",
            "summary": "近期（前後1天）無排定總經事件、市場無異常波動、新聞無警示關鍵字命中，"
                       "跳過AI查證，零成本。近期已知行事曆（未來25天內）：" +
                       ("；".join(f"{e['date']} {e['market']} {e['event']}"
                                  for e in upcoming_events(date, days_before=0, days_after=25)) or "無"),
            "events": upcoming_events(date, days_before=0, days_after=25),
            "headlines": headlines,
            "ts": date, "cost_usd": 0.0,
        }
        _save(note)
        return note

    why = []
    if near_term:
        why.append(f"行事曆有排定事件（{len(near_term)}項）")
    if anomalies:
        why.append("市場異常波動：" + "；".join(anomalies))
    if kw_hits:
        why.append("新聞命中警示關鍵字：" + "；".join(f"[{k}]{t[:30]}" for k, t in kw_hits[:5]))
    print("觸發AI查證，原因：" + " ｜ ".join(why))

    note = _ask_claude(near_term, date, anomalies, kw_hits, headlines)
    note["headlines"] = headlines
    note["trigger"] = why
    _save(note)
    return note


if __name__ == "__main__":
    run()
