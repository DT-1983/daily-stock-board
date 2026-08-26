"""投資長 Agent —— 質化判斷層。讀研究員（researcher_*.py）今天新產出的 research_notes，
只針對「今天有新事件」的持股給進出場判斷，不是每天列全部66+41檔的表格。

核心規則（2026-08-26 跟 Leo 定案，來自 investment_advisor_architecture.md 的硬規則）：
**兩個獨立角度，各自給進出場判斷，不合併成一個結論**：
- 長期價值角度（洪瑞泰）：看估值，年為單位，EXIT_RULES 講得很清楚「不看短線波動」
- 中短期趨勢角度（SuperTrend+RS+產業輪動整合）：這三個本質上是同一種「順勢/動能」
  哲學，整合成一個連貫判斷不算違反「不同哲學不能混」的規則——它們本來就是同一路人。
兩條角度可能給出相反的建議（例如長期角度說便宜可以買、趨勢角度說破線要小心），
**都要照實列出，不強迫湊成一個結論**，最終決定是 Leo 的。

資料來源全部讀原始檔案，不解析 Telegram 訊息文字：
- state/signals.json：AI綜合訊號（🔴🟢🔵🟡⚪，us_analyze.py/tw_analyze.py算出來的，
  每天早上Telegram看到的核心訊號）
- state/valuation_state.json + trade_plan.buffett_targets()：洪瑞泰價值角度
- trade_plan.supertrend_invalidation()：SuperTrend+RS現況（Firstrade美股持股適用）
- industry_rotation_history.json + RRG_HOLDINGS：這檔所屬產業籃子的最新象限
- state/research_notes.jsonl：今天研究員產出的新聞/事件（narrative context）

AI 只做「讀材料寫判斷」，`--tools ""` 關掉所有工具，不會自己再去查——材料已經
在上面備齊，跟 researcher_industry.py 同一套已驗證的模式。

用法: python investment_chief.py
"""
import os
import re
import sys
import json
import time
import subprocess

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_board import _claude_bin

NOTES_PATH = "state/research_notes.jsonl"
VERDICTS_PATH = "state/advisor_verdicts.jsonl"

SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "value_angle": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "judgment": {"type": "string", "enum": ["續抱/可買", "觀望", "考慮出場", "資料不足"]},
                "reasoning": {"type": "string"},
            },
            "required": ["status", "judgment", "reasoning"],
        },
        "trend_angle": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "judgment": {"type": "string", "enum": ["續抱/可買", "觀望", "考慮出場", "資料不足"]},
                "reasoning": {"type": "string"},
                "invalidation_price": {"type": "string"},
                "support_resistance": {"type": "string"},
                "volume_price_divergence": {"type": "string"},
                "event_risk": {"type": "string"},
                "bull_bear_debate": {"type": "string"},
            },
            "required": ["status", "judgment", "reasoning"],
        },
    },
    "required": ["ticker", "value_angle", "trend_angle"],
}

PROMPT = """你是投資長，讀研究員整理好的材料，給這檔股票兩個獨立角度的進出場判斷。

鐵律（不能違反）：
1. 把事實、推論、假設分開標註
2. 資料不足就直接說缺少什麼、judgment 填「資料不足」，不要硬掰
3. **不要替 Leo 執行交易，最終決策是他的**——你的 judgment 是建議，不是指令
4. **只根據下面提供的材料寫，不要自己去查其他資料**
5. **兩個角度要獨立判斷，不要互相影響**——長期價值角度不看短線趨勢好壞，
   中短期趨勢角度不因為長期便宜就樂觀。就算兩個角度給出相反的建議也照實寫，
   不要為了看起來一致而修改任一邊。

今天是 {date}，股票代號 {ticker}（{name}）。

已知材料：

【AI綜合訊號】（每天早上Telegram會看到的核心訊號）
{ai_signal}

【長期價值角度材料（洪瑞泰）】
{value_material}

【中短期趨勢角度材料（SuperTrend+RS+產業輪動）】
{trend_material}

【今天研究員產出的新聞/事件】
{today_events}

任務：
1. value_angle：根據估值材料判斷續抱/觀望/考慮出場，說明理由。不看趨勢材料。
2. trend_angle：根據趨勢+新聞材料判斷續抱/觀望/考慮出場，並補充5個強化維度：
   失效價位（invalidation_price）、支撐壓力區間（support_resistance）、
   量價背離（volume_price_divergence，材料不夠判斷就寫「材料不足無法判斷」）、
   事件風險（event_risk，今天的新聞算不算風險）、多空辯論（bull_bear_debate，
   一句話講多方觀點、一句話講空方觀點）。"""


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _ticker_rrg_basket():
    """讀 docs/rotation.html 內嵌的 RRG_HOLDINGS，建 ticker→(market,basket) 反查表。"""
    rev = {}
    path = "docs/rotation.html"
    if not os.path.exists(path):
        return rev
    try:
        html = open(path, encoding="utf-8").read()
        m = re.search(r"window\.RRG_HOLDINGS\s*=\s*(\{.*?\});", html, re.S)
        if not m:
            return rev
        d = json.loads(m.group(1))
        for mkt in ("us", "tw"):
            for basket, lst in d.get(mkt, {}).items():
                for h in lst:
                    rev[h["ticker"]] = (mkt, basket)
    except Exception:
        pass
    return rev


def _basket_quadrant(market, basket, period="60"):
    hist = _load_json("industry_rotation_history.json")
    if not hist:
        return None
    rows = hist.get(market, {}).get("index", [])
    if not rows:
        return None
    snap = rows[-1]["snapshot"].get(basket)
    if not snap:
        return None
    p = snap.get("periods", {}).get(period)
    return {"basket": snap.get("name", basket), "date": rows[-1]["date"],
            "quadrant": p.get("quadrant") if p else None,
            "ratio": p.get("ratio") if p else None, "momentum": p.get("momentum") if p else None}


def today_tickers():
    """掃今天新增的 research_notes，收集出「值得投資長看一眼」的股票代號。
    stock層直接列ticker(逗號分隔可能有多檔)；industry層要反查籃子裡有沒有Leo的持股。"""
    date = time.strftime("%Y-%m-%d")
    notes = []
    if os.path.exists(NOTES_PATH):
        for line in open(NOTES_PATH, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                n = json.loads(line)
            except Exception:
                continue
            if n.get("ts") == date:
                notes.append(n)

    holdings = set(_load_json("holdings.json", []) or [])
    tickers = set()
    for n in notes:
        if n["layer"] == "stock":
            for tk in n["scope"].split(","):
                tickers.add(tk.strip())
        elif n["layer"] == "industry":
            # 產業翻象限，反查這個籃子裡有沒有 Leo 的持股（只有前5大成分股資料可查，
            # 已知限制——不在前5大的持股即使受影響也查不到，見 dev_log）
            rev = _ticker_rrg_basket()
            for tk, (mkt, basket) in rev.items():
                if basket_matches_scope(n, basket) and tk in holdings:
                    tickers.add(tk)
    return sorted(tickers), notes


def basket_matches_scope(note, basket_key):
    return note.get("scope") in (basket_key,) or basket_key in note.get("summary", "")


def gather_material(ticker, notes):
    is_tw = bool(re.match(r"^\d{4,6}[A-Z]?$", ticker))
    market_prefix = "TW" if is_tw else "US"
    sig_key = f"{market_prefix}:{ticker}"

    signals = _load_json("state/signals.json", {})
    ai_sig = signals.get(sig_key, "（查無AI綜合訊號，可能不在追蹤清單裡）")

    val_state = _load_json("state/valuation_state.json", {})
    v = val_state.get(ticker)
    value_material = (f"貴俗價現況：現價${v['price']:,.2f}，俗價${v['cheap']:,.2f}，"
                      f"貴價${v['expensive']:,.2f}，訊號{v['icon']}（更新於{v.get('updated_at','')}）"
                      if v else "查無貴俗價資料")
    try:
        from trade_plan import buffett_targets
        bt = buffett_targets(ticker)
        if bt:
            value_material += (f"\n洪瑞泰品質關：{'未過（失效）' if bt['invalidated'] else '通過'}，"
                               f"目標價（貴價）${bt['target_price']:,.2f}"
                               if bt.get("target_price") else "")
    except Exception as e:
        value_material += f"\n（buffett_targets查詢失敗：{e}）"

    trend_material = ""
    rev = _ticker_rrg_basket()
    if ticker in rev:
        mkt, basket = rev[ticker]
        bq = _basket_quadrant(mkt, basket)
        if bq:
            trend_material += (f"所屬產業籃子「{bq['basket']}」目前象限：{bq['quadrant']}"
                               f"（RS-Ratio {bq['ratio']}／RS-Momentum {bq['momentum']}，"
                               f"資料日期{bq['date']}）\n")
    if not is_tw:
        try:
            from trade_plan import supertrend_invalidation
            sti = supertrend_invalidation(ticker)
            if sti:
                trend_material += (f"SuperTrend：{'已翻空' if sti['st_bearish'] else '多頭'}／"
                                   f"RS(60日)：{'已跌破' if sti['rs60_broken'] else '未跌破'}／"
                                   f"{sti['note']}\n")
        except Exception as e:
            trend_material += f"（supertrend_invalidation查詢失敗：{e}）\n"
    trend_material = trend_material or "查無趨勢面資料（可能是台股，目前SuperTrend僅涵蓋美股持股）"

    today_events = "\n".join(f"- [{n['layer']}/{n['source']}] {n['summary'][:300]}" for n in notes
                             if ticker in n.get("scope", "")) or "（今天沒有直接提到這檔的研究員筆記）"

    return sig_key, ai_sig, value_material, trend_material, today_events


def ask_claude(ticker, name, ai_sig, value_material, trend_material, today_events, date):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    prompt = PROMPT.format(date=date, ticker=ticker, name=name, ai_signal=ai_sig,
                           value_material=value_material, trend_material=trend_material,
                           today_events=today_events)
    r = subprocess.run(
        [exe, "-p", "--dangerously-skip-permissions", "--tools", "",
         "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude 失敗 (exit {r.returncode}): {(r.stderr or '')[:300]}")
    out = json.loads(r.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude 回錯誤: {out}")
    verdict = out.get("structured_output")
    if not verdict:
        raise RuntimeError(f"沒有 structured_output：{r.stdout[:300]}")
    verdict["ts"] = date
    verdict["cost_usd"] = out.get("total_cost_usd")
    return verdict


def run():
    tickers, notes = today_tickers()
    if not tickers:
        print("今天沒有新研究筆記涉及任何持股，投資長沒東西可判斷")
        return []

    print(f"今天有 {len(tickers)} 檔持股有新研究筆記：{tickers}")
    date = time.strftime("%Y-%m-%d")
    verdicts = []
    for tk in tickers:
        print(f"  分析 {tk}...")
        sig_key, ai_sig, value_m, trend_m, events = gather_material(tk, notes)
        try:
            v = ask_claude(tk, tk, ai_sig, value_m, trend_m, events, date)
            verdicts.append(v)
        except Exception as e:
            print(f"  {tk} 分析失敗：{e}")

    if not verdicts:
        return []
    os.makedirs("state", exist_ok=True)
    with open(VERDICTS_PATH, "a", encoding="utf-8") as f:
        for v in verdicts:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    total = sum(v.get("cost_usd") or 0 for v in verdicts)
    print(f"已存 {len(verdicts)} 筆投資長判斷（等值標價合計約 ${total:.2f}，Max plan走訂閱額度）")
    return verdicts


if __name__ == "__main__":
    run()
