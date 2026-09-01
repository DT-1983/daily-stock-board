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

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_board import _claude_bin

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
                "brief": {"type": "string", "maxLength": 38},
                "reasoning": {"type": "string"},
                "invalidation_price": {"type": "string"},
                "support_resistance": {"type": "string"},
                "volume_price_divergence": {"type": "string"},
                "event_risk": {"type": "string"},
                "bull_bear_debate": {"type": "string"},
            },
            "required": ["status", "judgment", "brief", "reasoning"],
        },
        # 2026-08-27 P1（老墨「報告死亡條件」）：這個判斷的可證偽失效條件。
        # 2026-08-31 拆成兩組（Leo：「失效條件也可以分兩個嗎，不是只有價值投資」）——
        # 原本單一 conditions 陣列，實測 44 條價格類裡有 39 條是俗貴價，因為系統餵給
        # AI 最明確的數字就是貴俗價，它自然往那邊寫。拆成 trend/value 兩組**強制
        # 每個角度各自給條件**，跟本檔既有的「兩角度獨立判斷不合併」硬規則一致。
        # 型別：
        #   price_below/above ── 價格線，每日對現價檢查（零成本）
        #   supertrend_bear   ── SuperTrend 由多翻空（看多的人用）
        #   supertrend_bull   ── SuperTrend 由空翻多（看空/避開的人用）
        #   rs_below / rs_above ── RS(60日) 跌破 / 站回自身均線
        # ⚠️ 2026-09-01 補方向：原本只有單向的 supertrend_flip，非持股的看空判斷
        # 沒有對應型別可用，AI 只能硬套 → desc 寫「由空翻多」卻被當成「由多翻空」
        # 檢查，實測 5 個「新觸發」裡 3 個是假訊號（1580/2731/4763）。
        #   metric            ── 財報/基本面門檻，等下次財報才驗證
        "trend_conditions": {
            "type": "array", "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string",
                             "enum": ["price_below", "price_above",
                                      "supertrend_bear", "supertrend_bull",
                                      "rs_below", "rs_above", "metric"]},
                    "value": {"type": ["number", "null"]},
                    "desc": {"type": "string", "maxLength": 50},
                },
                "required": ["type", "desc"],
            },
        },
        "value_conditions": {
            "type": "array", "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string",
                             "enum": ["price_below", "price_above", "metric"]},
                    "value": {"type": ["number", "null"]},
                    "desc": {"type": "string", "maxLength": 50},
                },
                "required": ["type", "desc"],
            },
        },
        "value_angle": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "judgment": {"type": "string", "enum": ["續抱/可買", "觀望", "考慮出場", "資料不足"]},
                "brief": {"type": "string", "maxLength": 38},
                "reasoning": {"type": "string"},
            },
            "required": ["status", "judgment", "brief", "reasoning"],
        },
    },
    "required": ["ticker", "trend_angle", "value_angle",
                 "trend_conditions", "value_conditions"],
}

PROMPT = """你是投資長，讀研究員整理好的材料，給這檔股票兩個獨立角度的進出場判斷。

鐵律（不能違反）：
1. 把事實、推論、假設分開標註
2. 資料不足就直接說缺少什麼、judgment 填「資料不足」，不要硬掰
3. **不要替 Leo 執行交易，最終決策是他的**——你的 judgment 是建議，不是指令
4. **只根據下面提供的材料寫，不要自己去查其他資料**
4b. **全部用繁體中文（台灣用語）**，一個簡體字都不能出現
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
   材料裡若有「預估前提檢查」，它量的是**市場對這檔的期待被堆到多高**，怎麼讀：
   - 它不是「公司好壞」的評價，是「容錯空間大小」的刻度。要求超出自身歷史紀錄
     ＝好消息已被寫進預估、預估已被寫進股價，做得不錯但沒到就會被修正。
   - **不要**把它讀成「分析師在亂喊」——同一段裡的「分析師準頭」多半顯示這些公司
     的共識長期偏保守，是公司一直超乎預期才把期待越堆越高。
   - 它跟貴俗價是兩件事：貴俗價講價格貴不貴，這個講期待高不高。兩個都要提到，
     不要用其中一個取代另一個。若兩者同向（已到貴價＋要求破紀錄），明講容錯空間最小。
   - 樣本數 n 有標出來，n 小的時候要在 reasoning 裡說明這點，不要當統計結論。

兩個角度各要填：
- brief：**一句完整的話（≤35字）講清楚判斷跟最關鍵的一個理由**，會顯示在手機推播上——
  必須是完整句子、不能只寫半句、不用「事實/推論」標籤。**寧可只講最關鍵那一個理由，
  也不要塞兩三個理由把句子拉長**（手機一行只放得下約20字，太長會折成好幾行很難讀）。
- reasoning：完整詳細版（事實/推論分開標註），存檔供深讀。

另外**兩個角度各自**填失效條件（死亡條件）——「出現什麼情況代表這個角度的判斷錯了」。
⚠️ **兩組要真的不一樣，不要兩邊都寫估值**。2026-08 實測發現：因為材料裡貴俗價的
數字最明確，AI 幾乎全部往估值寫（44條價格條件裡39條是貴俗價），結果趨勢角度形同沒有
失效條件。趨勢就寫趨勢的失效（破線/翻空/RS轉弱），價值就寫價值的失效（估值/財報數字）。

**trend_conditions（1-2條，趨勢角度的失效）** 可用型別（value 都不用填，系統每天自己算）：
- supertrend_bear：SuperTrend **由多翻空** ← 你判斷「趨勢向上/可進場」時用這個
- supertrend_bull：SuperTrend **由空翻多** ← 你判斷「趨勢向下/避開」時用這個
- rs_below：RS(60日) **跌破**自身均線 ← 看多時用
- rs_above：RS(60日) **站回**自身均線 ← 看空時用
⚠️ **方向要跟你的判斷相反**：失效條件是「什麼情況代表我錯了」。
   說「趨勢轉弱不宜進場」→ 失效條件是它**轉強**（supertrend_bull / rs_above）；
   說「趨勢向上可續抱」→ 失效條件是它**轉弱**（supertrend_bear / rs_below）。
⚠️ **必須是還沒發生的事**。不要寫「RS 持續低於均線未收復」這種**描述現況**的句子
   ——那登錄當下就成立，不是可證偽的條件。要寫「如果…就代表我錯了」。
- price_below/price_above：具體價格線（value 必須給數字，例如跌破支撐 185.5）
- metric：要等財報才驗證的（趨勢角度很少用到）

**value_conditions（1-2條，價值角度的失效）** 可用型別：
- price_below/price_above：估值線，value 必須給數字（例如漲破貴價 148.32）
- metric：財報/基本面門檻，desc 必須含具體數字（例「毛利率跌破70%」「單季營收年增轉負」），
  這類會在該公司下次財報公布時被查證

共同規則：
- 只寫真的可證偽的條件，不要寫「市場情緒轉差」這種驗證不了的
- desc 要具體到「看到什麼數字就知道成立了」"""


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

    2026-08-27 P0 擴充（Leo：「投資長不應該只看我手上持有的股票」）——原本觸發範圍
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

    # 2026-08-27 修：held 判斷不能只看 holdings.json（61檔）——跟 trade_plan.load_holdings()
    # 的 Firstrade 實際持股（66檔）是兩個不同來源，首測 MU/LITE 明明持有卻被標非持股。
    # 兩個來源聯集，任一來源說有就算持有（寧可多算持股，也不要把持股當進場機會評）。
    holdings = set(_load_json("holdings.json", []) or [])
    try:
        from trade_plan import load_holdings
        active, _legacy = load_holdings()
        holdings |= {r.get("ticker") for r in active if r.get("ticker")}
    except Exception as e:
        print(f"trade_plan.load_holdings 讀取失敗（退回只用holdings.json）：{e}")
    try:
        # 2026-08-31：小孩的券商帳戶持股也算「持有」——否則會被當成進場機會評估，
        # 語意完全錯（那些已經在手上了）。load_holdings 是風控母體不含小孩，
        # 所以另外從監控母體補進來。
        from trade_plan import monitored_holdings
        import re as _re
        for tk, ow, _nm in monitored_holdings():
            if ow == "Leo":
                continue
            holdings.add(tk)
            if _re.match(r"^\d{4,6}[A-Z]?$", str(tk)):
                holdings.add(f"{tk}.TW")
    except Exception as e:
        print(f"小孩持股讀取失敗（不影響 Leo 的判定）：{e}")
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
    """研究筆記的 scope 是**中文**產業名（researcher_industry 存的是 flip["name"]），
    RRG_HOLDINGS 的 key 是**英文** sector（Non-Energy Minerals）——2026-08-27 查出
    這兩個永遠比對不成立，**「產業轉強」從上線到現在一次都沒真的觸發過**
    （靜默失效，屬 unexecuted_code_paths 那類：程式在跑、路徑從沒執行）。
    修法：用 industry_rotation.SECTOR_TW_LABEL 做中英對照（英→中），兩邊都認。"""
    scope = (note.get("scope") or "").strip()
    if not scope:
        return False
    if scope == basket_key or basket_key in (note.get("summary") or ""):
        return True
    try:
        from industry_rotation import SECTOR_TW_LABEL
        return SECTOR_TW_LABEL.get(basket_key) == scope
    except Exception:
        return False


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

    # 2026-08-28 P3：預估前提檢查併入**價值角度**的材料。理由：它量的是「市場對這檔的
    # 期待被堆到多高」，而股價正是照那個期待訂的——本質是估值前提不是趨勢。
    # 放進來是給孔明多一份材料（維持多鏡頭獨立原則），**不是門檻**，不擋任何判斷。
    # ⚠️ 一定要同時給「分析師歷史準頭」：被標記的幾檔（CLS/TSM 24季全部低估）分析師
    # 其實是長期猜太保守，沒有這個脈絡會被誤讀成「分析師在亂喊」。
    try:
        from base_rate import _load as _br_load, line as _br_line
        _br = _br_load() or {}
        _c = next((c for c in _br.get("checks", []) if c.get("ticker") == ticker), None)
        if _c and _c.get("requirement"):
            _t = _c["requirement"]["tier"]
            _tag = {"unprecedented": "要求超出這檔自身歷史紀錄一大截",
                    "rare": "要求剛好貼在自身歷史紀錄上",
                    "normal": "要求落在這檔過去做得到的範圍內",
                    "low_coverage": "分析師覆蓋太少，不列入判斷"}.get(_t, "")
            value_material += (f"\n預估前提檢查（{_br.get('date','')}，"
                               f"分析師共識隱含的要求 vs 這檔自己的歷史）：{_tag}\n"
                               f"  {_br_line(_c)}")
    except Exception as e:
        value_material += f"\n（預估前提檢查查詢失敗：{e}）"

    trend_material = ""
    # 2026-08-27：所屬七鏈的技術面（chain_technicals.py 每日算）——**當參考不當門檻**，
    # 只是多一份背景材料給投資長，不擋任何個股訊號（Leo 明確決定，維持多鏡頭獨立原則）。
    # 定位：七鏈看「長期趨勢還健不健康」，個股訊號看「買點到了沒」。
    ct = _load_json("state/chain_technicals.json", {}) or {}
    if ct.get("chains"):
        scr = _load_json("screen_result.json", {}) or {}
        for mkt in ("us", "tw"):
            for chain, rows in (scr.get(mkt) or {}).items():
                if any(str(r.get("code")) == str(ticker).split(".")[0] for r in rows):
                    d = ct["chains"].get(f"{mkt}:{chain}")
                    if d and d.get("summary"):
                        trend_material += (f"所屬產業鏈「{chain}」技術面（{ct.get('date','')}）："
                                           f"{d['summary']}\n")
                    break
    rev = _ticker_rrg_basket()
    if ticker in rev:
        mkt, basket = rev[ticker]
        bq = _basket_quadrant(mkt, basket)
        if bq:
            trend_material += (f"所屬產業籃子「{bq['basket']}」目前象限：{bq['quadrant']}"
                               f"（RS-Ratio {bq['ratio']}／RS-Momentum {bq['momentum']}，"
                               f"資料日期{bq['date']}）\n")
    # 2026-08-27 拿掉 `if not is_tw` 的閘門——Leo抓到矛盾：「台股怎麼會跑不到資料，
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
    # 2026-08-27 P0：非持股的判斷語意不一樣——沒有「出場」可言，judgment 枚舉不變
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
    # 2026-08-31：加簡體字驗收。實測最近 40 筆判斷有 6 筆帶簡體（价/现/体/撑/综），
    # 這些會直接進 Discord 持股密報。Leo 硬規則禁簡體，改稿重試一次；
    # 兩次都簡體就照原樣回（判斷內容比字體重要，但會印出來讓人看得到）。
    from llm_board import simplified_chars, walk_strings
    fix, verdict = "", None
    for attempt in range(2):
        r = subprocess.run(
            [exe, "-p", "--dangerously-skip-permissions", "--tools", "",
             "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
            input=prompt + fix, capture_output=True, text=True,
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
        bad = sorted(simplified_chars("".join(walk_strings(verdict))))
        if not bad:
            break
        if attempt == 0:
            print(f"    ⚠️ {ticker} 判斷含簡體字 {''.join(bad[:8])}，重寫一次")
            fix = ("\n" * 2 + "⚠️ 你上一次的回答用了簡體字（" + "".join(bad[:8])
                   + "）。整份重寫，全部用繁體中文（台灣用語）。")
        else:
            print(f"    ⚠️ {ticker} 重試後仍含簡體 {''.join(bad[:8])}，照原樣採用")
    verdict["ts"] = date
    verdict["cost_usd"] = out.get("total_cost_usd")
    return verdict


_J_ICON = {"續抱/可買": "🟢", "觀望": "🟡", "考慮出場": "🔴", "資料不足": "⚪"}


def _overview_lines(notes):
    """總經/產業總覽（Python 端從當天 research_notes 確定性組出來，不叫 AI）。
    2026-08-27 Leo 反饋首日推播「可以說明一下現在整體狀況（總經、產業）」——
    原本推播只有逐檔判斷，沒有大盤脈絡。
    2026-08-27 Leo 再加兩個：①昨日大指數摘要（像dashboard）②對股市有重大影響的
    財經新聞（打仗/升息/CPI類）——指數讀 market_data.json（market_fetch每天在抓），
    重大新聞用 macro_calendar 的警示關鍵字掃當天總經筆記附的新聞標題，全部零成本。"""
    lines = []

    # ① 昨日大指數（market_data.json，tw-board/market-home 排程維護）。
    # 2026-08-27 Leo反饋「排版有點亂可以分二行嗎」：一行塞7個指數在手機上會折行
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


# 2026-08-28 Leo：TG 精簡，投資長判斷這則已拿掉——內容跟 Discord 日報③段完全重複（同一份 state/advisor_verdicts.jsonl，daily_warroom 讀出來合成日報）。原本的 _send_telegram()（含格式化+分段+推播邏輯）整段刪除，不留半死不活的函式。

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
    # 補上判斷當下的基準價（沒有它就無法回測判斷準不準）。
    # 抓不到也明確寫 None，才分得出「當天沒抓到」和「舊版本沒有這個欄位」。
    px = _snapshot_prices([v["ticker"] for v in verdicts])
    for v in verdicts:
        v.update(px.get(v["ticker"]) or
                 {"price": None, "price_asof": None, "price_symbol": None})
    got = sum(1 for v in verdicts if v.get("price") is not None)
    print(f"  基準價：{got}/{len(verdicts)} 檔取得")
    os.makedirs("state", exist_ok=True)
    with open(VERDICTS_PATH, "a", encoding="utf-8") as f:
        for v in verdicts:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    total = sum(v.get("cost_usd") or 0 for v in verdicts)
    print(f"已存 {len(verdicts)} 筆投資長判斷（等值標價合計約 ${total:.2f}，Max plan走訂閱額度）")
    _register_conditions(verdicts)
    return verdicts



def _snapshot_prices(tickers):
    """判斷當下的收盤價，寫進 verdict 當日後復盤的基準（2026-09-01 加）。

    ⚠️ 為什麼一定要「當場」記：沒有基準價就算不出「照這個判斷做會賺賠多少」，
    而事後回頭補抓歷史收盤價，等於把盤中做成的判斷用收盤價重新定錨。
    同一個坑已經踩過兩次（RRG 資金規模、analyst_price_targets 都只有現在、
    沒有歷史）——資料源不留歷史，越晚開始存越虧。

    ⚠️ period 必須維持 "3y"，不可以為了省事改 "5d"：price_store._write_cached
    是 to_pickle **直接覆蓋不合併**，用短天期會把 industry_rotation(RRG) 依賴的
    三年快取洗掉。

    ⚠️ targets 的代號格式是混的（1229 / 1580.TWO / 1615.TW / NVDA），裸台股代號
    一定要過 tw_symbol.resolve() 補後綴，否則上櫃股會靜默抓不到（見 memory
    otc_suffix_coverage_gap）。
    """
    import price_store, tw_symbol
    sym = {tk: tw_symbol.resolve(tk) for tk in tickers}
    try:
        closes = price_store.get_closes(sorted(set(sym.values())), period="3y")
    except Exception as e:                       # noqa: BLE001
        print(f"  [price] 取價失敗，這批判斷不記基準價：{str(e)[:80]}")
        return {}
    out = {}
    for tk, s in sym.items():
        ser = closes.get(s)
        if ser is None or not len(ser.dropna()):
            continue          # 抓不到就留空，不要寫進一個錯的基準價
        ser = ser.dropna()
        out[tk] = {"price": round(float(ser.iloc[-1]), 4),
                   "price_asof": str(ser.index[-1])[:10],
                   "price_symbol": s}
    return out

def _register_conditions(verdicts):
    """P1（2026-08-27）：把投資長給的失效條件登錄進 state/thesis_conditions.json。
    同一檔新判斷=新論點=覆蓋舊條件（狀態重置 active）；thesis_check.py 每天對照。

    2026-08-31：改收 trend_conditions / value_conditions 兩組，每條多帶一個
    `angle` 欄（trend/value），下游 thesis_check 與日報才分得開是哪個角度失效。
    仍相容舊的單一 conditions 欄位——歷史 verdicts 重跑時不會整批掉條件。"""
    path = "state/thesis_conditions.json"
    reg = _load_json(path, {}) or {}
    n = n_stock = 0
    for v in verdicts:
        conds = []
        for key, angle in (("trend_conditions", "trend"),
                           ("value_conditions", "value")):
            for c in (v.get(key) or []):
                conds.append({"type": c.get("type"), "value": c.get("value"),
                              "desc": c.get("desc"), "angle": angle,
                              "status": "active"})
        # 舊格式回落：2026-08-31 之前產生的 verdict 只有平的 conditions，沒有角度。
        # 標 angle="value" 而不是留空——那批實測 39/44 條寫的就是俗貴價，
        # 標成 value 比標 unknown 誠實，也讓日報不用處理第三種狀態。
        if not conds:
            for c in (v.get("conditions") or []):
                conds.append({"type": c.get("type"), "value": c.get("value"),
                              "desc": c.get("desc"), "angle": "value",
                              "status": "active"})
        if not conds:
            continue
        reg[v["ticker"]] = {
            "source_date": v.get("ts"),
            "held": v.get("held", True),
            "conditions": conds,
        }
        n += len(conds)
        n_stock += 1
    if n:
        os.makedirs("state", exist_ok=True)
        json.dump(reg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        nt = sum(1 for v in reg.values() for c in v["conditions"] if c.get("angle") == "trend")
        print(f"已登錄 {n} 條失效條件（{n_stock} 檔）｜登錄簿趨勢類 {nt} 條")


if __name__ == "__main__":
    run()
