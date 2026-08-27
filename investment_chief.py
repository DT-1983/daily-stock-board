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
from pathlib import Path

import requests
from dotenv import dotenv_values

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_board import _claude_bin

# 跟 valuation_alert.py 同模式：本機排程（researcher_stock_sync.cmd）不會預先
# export 環境變數，直接讀本機 .env（GitHub Actions 那邊吃 Actions Secrets，不同環境）。
_env = {**dotenv_values(Path(__file__).parent / ".env"), **os.environ}
TG_TOKEN = _env.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = _env.get("TELEGRAM_CHAT_ID", "")

NOTES_PATH = "state/research_notes.jsonl"
VERDICTS_PATH = "state/advisor_verdicts.jsonl"

# 2026-08-27 首日真實推播後 Leo 反饋改版：每個角度加 `brief`（一句話完整結論，
# 專門給 Telegram 推播用）——原本推播是把長篇 reasoning 硬截 80 字，句子斷在半空
# 且各檔結構不一致。reasoning 保留完整版存 jsonl 供深讀，推播只用 brief。
SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "trend_angle": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "judgment": {"type": "string", "enum": ["續抱/可買", "觀望", "考慮出場", "資料不足"]},
                "brief": {"type": "string", "maxLength": 60},
                "reasoning": {"type": "string"},
                "invalidation_price": {"type": "string"},
                "support_resistance": {"type": "string"},
                "volume_price_divergence": {"type": "string"},
                "event_risk": {"type": "string"},
                "bull_bear_debate": {"type": "string"},
            },
            "required": ["status", "judgment", "brief", "reasoning"],
        },
        "value_angle": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "judgment": {"type": "string", "enum": ["續抱/可買", "觀望", "考慮出場", "資料不足"]},
                "brief": {"type": "string", "maxLength": 60},
                "reasoning": {"type": "string"},
            },
            "required": ["status", "judgment", "brief", "reasoning"],
        },
    },
    "required": ["ticker", "trend_angle", "value_angle"],
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
{held_line}

已知材料：

【AI綜合訊號】（每天早上Telegram會看到的核心訊號）
{ai_signal}

【長期價值角度材料（洪瑞泰）】
{value_material}

【中短期趨勢角度材料（SuperTrend+RS+產業輪動）】
{trend_material}

【今天研究員產出的新聞/事件】
{today_events}

任務（先趨勢、後價值）：
1. trend_angle：根據趨勢+新聞材料判斷續抱/觀望/考慮出場，並補充5個強化維度：
   失效價位（invalidation_price）、支撐壓力區間（support_resistance）、
   量價背離（volume_price_divergence，材料不夠判斷就寫「材料不足無法判斷」）、
   事件風險（event_risk，今天的新聞算不算風險）、多空辯論（bull_bear_debate，
   一句話講多方觀點、一句話講空方觀點）。
2. value_angle：根據估值材料判斷續抱/觀望/考慮出場，說明理由。不看趨勢材料。

兩個角度各要填：
- brief：**一句完整的話（≤60字）講清楚判斷跟最關鍵的一個理由**，會直接顯示在
  Telegram 推播裡——必須是完整句子，不能只寫半句，不用「事實/推論」標籤。
- reasoning：完整詳細版（事實/推論分開標註），存檔供深讀。"""


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
    """掃今天新增的 research_notes + 買進機會來源，收集「值得投資長看一眼」的股票。

    2026-08-28 P0 擴充（Leo：「投資長不應該只看我手上持有的股票」）——原本觸發範圍
    偏持股管理（出場側），進場機會半邊缺席。現在回傳 {ticker: {"held": bool,
    "triggers": [...]}}，涵蓋：
    1. stock 層筆記（持股翻面＋守備清單翻面本來就都有寫，不用改）
    2. industry 層：拿掉 `if tk in holdings` 濾網——持股照舊全收；**非持股只收
       「轉入改善/領先」的籃子成分股**（轉弱的籃子對沒持有的股票沒有行動意義，
       全收會讓每次翻象限都噴出10檔AI呼叫，大多數是雜訊）
    3. 巴菲特清單到俗價（buffett_watch.json 41檔現價 ≤ cheap 且未持有）——進場側
       主訊號，原本只活在 buy_digest 週報完全沒接投資長。
       ⚠️ 這是「狀態」不是「事件」（到俗價會持續好幾天），加5天冷卻避免天天重複判斷
       同一檔（state/chief_buy_cooldown.json）。"""
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

    # 2026-08-28 修：held 判斷不能只看 holdings.json（61檔）——跟 trade_plan.load_holdings()
    # 的 Firstrade 實際持股（66檔）是兩個不同來源，首測 MU/LITE 明明持有卻被標非持股。
    # 兩個來源聯集，任一來源說有就算持有（寧可多算持股，也不要把持股當進場機會評）。
    holdings = set(_load_json("holdings.json", []) or [])
    try:
        from trade_plan import load_holdings
        active, _legacy = load_holdings()
        holdings |= {r.get("ticker") for r in active if r.get("ticker")}
    except Exception as e:
        print(f"trade_plan.load_holdings 讀取失敗（退回只用holdings.json）：{e}")
    targets = {}

    def add(tk, trigger):
        tk = tk.strip()
        if not tk:
            return
        t = targets.setdefault(tk, {"held": tk in holdings, "triggers": []})
        if trigger not in t["triggers"]:
            t["triggers"].append(trigger)

    for n in notes:
        if n["layer"] == "stock":
            for tk in n["scope"].split(","):
                add(tk, f"個股事件（{n.get('source','')}）")
        elif n["layer"] == "industry":
            ev = (n.get("events") or [{}])[0].get("event", "")
            entering = ("→改善" in ev) or ("→領先" in ev)
            rev = _ticker_rrg_basket()
            for tk, (mkt, basket) in rev.items():
                if not basket_matches_scope(n, basket):
                    continue
                if tk in holdings:
                    add(tk, f"所屬產業翻象限（{n.get('scope','')}）")
                elif entering:
                    add(tk, f"產業轉強（{n.get('scope','')} {ev.replace('RRG象限','').split('（')[0]}）")

    # 3. 巴菲特清單到俗價（未持有＋5天冷卻）
    try:
        wl = _load_json("buffett_watch.json", {}) or {}
        cool = _load_json("state/chief_buy_cooldown.json", {}) or {}
        cand = [tk for tk, w in wl.items()
                if tk not in holdings and w.get("cheap")]
        if cand:
            import yfinance as yf
            import datetime as _dt
            data = yf.download(cand, period="5d", progress=False, threads=False,
                               auto_adjust=True, group_by="ticker")
            today_d = _dt.date.fromisoformat(date)
            for tk in cand:
                last = cool.get(tk)
                if last and (today_d - _dt.date.fromisoformat(last)).days < 5:
                    continue
                try:
                    df = data[tk] if len(cand) > 1 else data
                    cur = float(df["Close"].dropna().iloc[-1])
                except Exception:
                    continue
                if cur <= wl[tk]["cheap"]:
                    add(tk, f"巴菲特到俗價（現價{cur:.1f} ≤ 俗價{wl[tk]['cheap']:.1f}）")
                    cool[tk] = date
            os.makedirs("state", exist_ok=True)
            json.dump(cool, open("state/chief_buy_cooldown.json", "w", encoding="utf-8"),
                      ensure_ascii=False)
    except Exception as e:
        print(f"巴菲特到俗價檢查失敗（不影響其他觸發）：{e}")

    return targets, notes


def basket_matches_scope(note, basket_key):
    return note.get("scope") in (basket_key,) or basket_key in note.get("summary", "")


def gather_material(ticker, notes):
    # 台股代號兩種形態都要認得：純數字（valuation_state 用 "2412"）跟帶後綴
    # （buffett_watch 用 "5287.TWO"/"2731.TW"）——首測後綴形態被誤判成美股
    is_tw = bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", ticker))
    market_prefix = "TW" if is_tw else "US"
    sig_key = f"{market_prefix}:{ticker}"

    signals = _load_json("state/signals.json", {})
    ai_sig = signals.get(sig_key, "（查無AI綜合訊號，可能不在追蹤清單裡）")

    val_state = _load_json("state/valuation_state.json", {})
    v = val_state.get(ticker)
    if v:
        value_material = (f"貴俗價現況：現價${v['price']:,.2f}，俗價${v['cheap']:,.2f}，"
                          f"貴價${v['expensive']:,.2f}，訊號{v['icon']}（更新於{v.get('updated_at','')}）")
    else:
        # 非持股（valuation_state 只涵蓋持股）→ 退查巴菲特候選池（每週六更新）
        w = (_load_json("buffett_watch.json", {}) or {}).get(ticker)
        value_material = (f"巴菲特候選池資料（每週六更新，更新日{w.get('updated','')}）："
                          f"俗價${w['cheap']:,.2f}，貴價${w['expensive']:,.2f}，"
                          f"ROE {w.get('roe', 0)*100:.0f}%，盈再率{w.get('reinvest', 0)*100:.0f}%"
                          f"（{w.get('reinvest_grade','')}），產業龍頭排名#{w.get('rank','?')}"
                          if w else "查無貴俗價資料")
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
    # 2026-08-28 拿掉 `if not is_tw` 的閘門——Leo抓到矛盾：「台股怎麼會跑不到資料，
    # 那財報卡怎麼跑出來的」。supertrend_invalidation 已擴充台股（RS基準自動切^TWII），
    # 台美股都跑，台股非持股的進場評估不再只有價值單角度。
    try:
        from trade_plan import supertrend_invalidation
        sti = supertrend_invalidation(ticker)
        if sti:
            trend_material += (f"SuperTrend：{'已翻空' if sti['st_bearish'] else '多頭'}／"
                               f"RS(60日)：{'已跌破' if sti['rs60_broken'] else '未跌破'}／"
                               f"{sti['note']}\n")
    except Exception as e:
        trend_material += f"（supertrend_invalidation查詢失敗：{e}）\n"
    trend_material = trend_material or "查無趨勢面資料"

    today_events = "\n".join(f"- [{n['layer']}/{n['source']}] {n['summary'][:300]}" for n in notes
                             if ticker in n.get("scope", "")) or "（今天沒有直接提到這檔的研究員筆記）"

    return sig_key, ai_sig, value_material, trend_material, today_events


def ask_claude(ticker, name, ai_sig, value_material, trend_material, today_events, date,
               held=True, triggers=None):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    # 2026-08-28 P0：非持股的判斷語意不一樣——沒有「出場」可言，judgment 枚舉不變
    # 但要告訴 AI 怎麼解讀（續抱/可買=可考慮進場、考慮出場=不適合進場/避開）
    if held:
        held_line = "Leo 目前【持有】這檔——判斷語意是「要不要繼續持有」。"
    else:
        held_line = ("Leo 目前【未持有】這檔，是進場機會評估——判斷語意：\n"
                     "續抱/可買=建議可考慮進場、觀望=先不進、考慮出場=不適合進場（避開）。")
    if triggers:
        held_line += "\n這次被觸發的原因：" + "；".join(triggers)
    prompt = PROMPT.format(date=date, ticker=ticker, name=name, ai_signal=ai_sig,
                           value_material=value_material, trend_material=trend_material,
                           today_events=today_events, held_line=held_line)
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


_J_ICON = {"續抱/可買": "🟢", "觀望": "🟡", "考慮出場": "🔴", "資料不足": "⚪"}


def _overview_lines(notes):
    """總經/產業總覽（Python 端從當天 research_notes 確定性組出來，不叫 AI）。
    2026-08-27 Leo 反饋首日推播「可以說明一下現在整體狀況（總經、產業）」——
    原本推播只有逐檔判斷，沒有大盤脈絡。
    2026-08-28 Leo 再加兩個：①昨日大指數摘要（像dashboard）②對股市有重大影響的
    財經新聞（打仗/升息/CPI類）——指數讀 market_data.json（market_fetch每天在抓），
    重大新聞用 macro_calendar 的警示關鍵字掃當天總經筆記附的新聞標題，全部零成本。"""
    lines = []

    # ① 昨日大指數（market_data.json，tw-board/market-home 排程維護）。
    # 2026-08-28 Leo反饋「排版有點亂可以分二行嗎」：一行塞7個指數在手機上會折行
    # 折得亂七八糟——拆成美股一行、台股+匯債一行，各自對齊好讀。
    md = _load_json("market_data.json", {}) or {}
    us_parts, tw_parts = [], []
    for it in md.get("indices", []):
        nm, pct, bp = it.get("name", it.get("sym", "")), it.get("chg_pct"), it.get("chg_bp")
        grp = it.get("grp", "")
        if pct is not None:
            arrow = "🔺" if pct > 0 else ("🔻" if pct < 0 else "▪️")
            part = f"{nm} {arrow}{pct:+.2f}%"
        elif bp is not None:
            part = f"{nm} {bp:+.1f}bp"
        else:
            continue
        # 美股四大指數一行；台股/匯率/美債（bp計價的）歸第二行——不然美股行塞5個又爆
        (us_parts if (grp == "US" and pct is not None) else tw_parts).append(part)
    if us_parts or tw_parts:
        lines.append(f"📈 <b>大盤</b>（{md.get('updated','')[:10]}）")
        if us_parts:
            lines.append("　🇺🇸 " + "｜".join(us_parts[:4]))
        if tw_parts:
            lines.append("　🇹🇼 " + "｜".join(tw_parts[:4]))

    # ② 重大財經新聞（警示關鍵字命中的才列——打仗/升息/關稅這類，不是全部頭條）
    macro = [n for n in notes if n.get("layer") == "macro"]
    try:
        from macro_calendar import keyword_hits
        heads = (macro[-1].get("headlines") if macro else None) or []
        hits = keyword_hits(heads)
        for kw, title in hits[:3]:
            lines.append(f"📰 <b>[{kw}]</b> {title[:48]}")
    except Exception:
        pass
    if macro:
        m = macro[-1]
        trig = m.get("trigger")
        if trig:
            lines.append("🌏 <b>總經</b>：今日有觸發事件——" + "；".join(trig)[:180])
        else:
            ev = [e for e in m.get("events", []) if e.get("status") == "scheduled"][:3]
            if ev:
                lines.append("🌏 <b>總經</b>：近期無突發，已排定：" +
                             "、".join(f"{e['date'][5:]} {e['event'].split('（')[0]}" for e in ev))
            else:
                lines.append("🌏 <b>總經</b>：無排定事件、無異常。")
    industry = [n for n in notes if n.get("layer") == "industry"]
    if industry:
        flips = []
        for n in industry:
            ev = (n.get("events") or [{}])[0].get("event", "")
            flips.append(f"{n.get('scope','')}（{ev.replace('RRG象限','')}）")
        lines.append("🔄 <b>產業輪動</b>：" + "、".join(flips[:6]))
    else:
        lines.append("🔄 <b>產業輪動</b>：本週無象限翻轉。")
    return lines


def _send_telegram(verdicts, notes=None):
    """2026-08-26 加推播；2026-08-27 首日真實推播後照 Leo 反饋全面改版：
    ① 開頭加總經/產業總覽（原本只有逐檔、沒有整體狀況）
    ② 先中短期趨勢、再長期價值（Leo 指定順序）
    ③ 每檔統一結構：兩行狀態（judgment icon + AI 的 brief 一句話完整結論），
       不再硬截長篇 reasoning 造成斷句與各檔格式不一致
    ④ 排序：兩角度都喊出場的排最前（最需要看的先看到）
    完整 reasoning 仍存 state/advisor_verdicts.jsonl 供深讀。"""
    if not (TG_TOKEN and TG_CHAT):
        print("缺 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，跳過推播")
        return
    date = time.strftime("%Y-%m-%d")

    def _urgency(v):
        both_exit = (v["trend_angle"]["judgment"] == "考慮出場" and
                     v["value_angle"]["judgment"] == "考慮出場")
        one_exit = (v["trend_angle"]["judgment"] == "考慮出場" or
                    v["value_angle"]["judgment"] == "考慮出場")
        return 0 if both_exit else (1 if one_exit else 2)

    held_vs = sorted([v for v in verdicts if v.get("held", True)], key=_urgency)
    new_vs = sorted([v for v in verdicts if not v.get("held", True)],
                    key=lambda v: 0 if v["trend_angle"]["judgment"] == "續抱/可買" else 1)

    lines = [f"📊 <b>投資長判斷 {date}</b>"]
    if notes:
        lines += _overview_lines(notes)
    lines.append("<i>兩角度各自獨立不合併；🔴出場 🟡觀望 🟢續抱；最終決策是你的</i>")
    lines.append("")

    def _block(v, entry=False):
        ta, va = v["trend_angle"], v["value_angle"]
        both_exit = _urgency(v) == 0 and not entry
        head = f"<b>【{v['ticker']}】</b>" + ("　‼️ 兩角度同喊出場" if both_exit else "")
        if entry and v.get("triggers"):
            head += f"　<i>{v['triggers'][0]}</i>"
        out = [head,
               f"　趨勢 {_J_ICON.get(ta['judgment'],'')}｜{ta.get('brief') or ta['judgment']}",
               f"　價值 {_J_ICON.get(va['judgment'],'')}｜{va.get('brief') or va['judgment']}", ""]
        return out

    if held_vs:
        lines.append("💼 <b>持股</b>")
        for v in held_vs:
            lines += _block(v)
    if new_vs:
        lines.append("🆕 <b>進場機會（非持股）</b>——<i>🟢可考慮進場 🟡先不進 🔴避開</i>")
        for v in new_vs:
            lines += _block(v, entry=True)

    # Telegram 單則上限 4096 字元——超過就按檔切多則，不讓訊息被硬砍
    chunks, cur = [], []
    for ln in lines:
        if sum(len(x) + 1 for x in cur) + len(ln) > 3800:
            chunks.append("\n".join(cur))
            cur = [f"📊 <b>投資長判斷 {date}</b>（續）", ""]
        cur.append(ln)
    chunks.append("\n".join(cur).strip())

    ok = True
    for text in chunks:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
        if r.status_code != 200:
            ok = False
            print(f"telegram推播失敗: {r.status_code} {r.text[:200]}")
    if ok:
        print(f"已推播投資長判斷（{len(chunks)} 則）")
    # 2026-08-28 Discord 雙發（隆中對 #每日戰情，孔明=投資長本尊）
    try:
        from notify_discord import send_discord, tg_html_to_md
        send_discord("daily", tg_html_to_md("\n".join(lines)), persona="孔明")
    except Exception as e:
        print(f"discord 雙發失敗（不影響 Telegram）：{e}")


def run():
    targets, notes = today_tickers()
    if not targets:
        print("今天沒有任何觸發（持股事件/產業轉強/巴菲特到俗價），投資長沒東西可判斷")
        return []

    held_n = sum(1 for t in targets.values() if t["held"])
    print(f"今天觸發 {len(targets)} 檔（持股 {held_n}、非持股 {len(targets)-held_n}）：{sorted(targets)}")
    date = time.strftime("%Y-%m-%d")
    verdicts = []
    for tk in sorted(targets):
        info = targets[tk]
        print(f"  分析 {tk}（{'持股' if info['held'] else '非持股'}｜{'；'.join(info['triggers'])}）...")
        sig_key, ai_sig, value_m, trend_m, events = gather_material(tk, notes)
        try:
            v = ask_claude(tk, tk, ai_sig, value_m, trend_m, events, date,
                           held=info["held"], triggers=info["triggers"])
            v["held"] = info["held"]
            v["triggers"] = info["triggers"]
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
    _send_telegram(verdicts, notes)
    return verdicts


if __name__ == "__main__":
    run()
