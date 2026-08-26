"""研究員 Agent —— 個股層。不重新設計訊號偵測，只把「今天已經翻面的股票」轉存成
跟總體層（researcher_macro.py）同一種 research_notes.jsonl 格式，供之後投資長統一讀取。

2026-08-26 涵蓋範圍：
1. 貴俗價翻黃（valuation_alert.py 寫的 state/valuation_flips_today.json，同一批本機
   07:00排程、同一次執行，資料是「今天」的）。
2. SuperTrend/AI訊號翻面（alert_telegram.py 寫的 state/st_flips_today.json，這支跑在
   GitHub Actions台灣09:00，比本機07:00晚2小時——本機讀到的會是「昨天09:00那次」的
   結果，落後一天，是已知限制，不是bug，見 alert_telegram.py 裡的說明）。

零成本優先（比照全域規則）：翻面本身是既有決定論訊號，不用AI。額外查
yfinance upgrades_downgrades（免費，非LLM）看有沒有相關分析師評等異動，
一起存進同一則筆記當佐證——查證過這個資料源有已知漏抓風險（見dev_log/
investment_advisor_architecture.md），confidence 固定標 medium，不能單獨支撐判斷。

用法: python researcher_stock.py
"""
import os
import sys
import json
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

NOTES_PATH = "state/research_notes.jsonl"


def _load(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _analyst_note(ticker):
    """免費、非LLM：查最近14天有沒有分析師評等異動。查不到/沒有都回None，
    呼叫端要處理，不當例外——查證過台股(.TW)這個API本來就常是空的。"""
    try:
        import yfinance as yf
        import pandas as pd
        df = yf.Ticker(ticker).upgrades_downgrades
        if df is None or df.empty:
            return None
        recent = df[df.index >= (pd.Timestamp.now(tz=df.index.tz) - pd.Timedelta(days=14))]
        if recent.empty:
            return None
        rows = [f"{d.strftime('%Y-%m-%d')} {r.Firm} {r.FromGrade}→{r.ToGrade}({r.Action})"
                for d, r in recent.iterrows()]
        return "；".join(rows[:5])
    except Exception as e:
        return f"查詢失敗：{e}"


def _note(ticker, name, source, event, extra_confidence="high"):
    analyst = _analyst_note(ticker)
    summary = f"已觸發：{event}（來源：{source}，決定論訊號，不是AI判斷）。"
    if analyst:
        summary += f" 補充（yfinance分析師評等異動，近14天，非LLM）：{analyst}"
    else:
        summary += " 補充：近14天查無分析師評等異動（或該市場無此資料，例如台股）。"
    return {
        "layer": "stock", "scope": ticker, "source": source,
        "confidence": extra_confidence, "summary": summary,
        "events": [{"market": "TW" if ticker.endswith(".TW") or ticker.isdigit() else "US",
                    "event": event, "date": time.strftime("%Y-%m-%d"), "status": "released"}],
        "ts": time.strftime("%Y-%m-%d"), "cost_usd": 0.0,
    }


def run():
    notes = []

    val_flips = _load("state/valuation_flips_today.json") or []
    for f in val_flips:
        event = f"貴俗價翻貴：現價 ${f['price']:,.2f} ≥ 貴價 ${f['expensive']:,.2f}"
        notes.append(_note(f["ticker"], f["ticker"], "valuation_alert", event))

    st = _load("state/st_flips_today.json") or {}
    for f in st.get("flips_hold", []) + st.get("flips_watch", []):
        event = f"SuperTrend{f['word']}"
        notes.append(_note(f["code"], f.get("name", ""), "st_alert", event))
    for a in st.get("ai_alerts", []):
        event = f"AI訊號變化：{a['sig']}（{a['chain']}）"
        notes.append(_note(a["code"], a.get("name", ""), "board_ai_signal", event, extra_confidence="medium"))

    if not notes:
        print("今天沒有個股層翻面，不寫入 research_notes.jsonl（沒訊號不用硬湊一筆）")
        return []

    os.makedirs("state", exist_ok=True)
    with open(NOTES_PATH, "a", encoding="utf-8") as f:
        for n in notes:
            f.write(json.dumps(n, ensure_ascii=False) + "\n")
    print(f"已存 {len(notes)} 筆個股層研究筆記（零成本）：{[n['scope'] for n in notes]}")
    return notes


if __name__ == "__main__":
    run()
