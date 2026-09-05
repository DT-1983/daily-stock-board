# -*- coding: utf-8 -*-
"""每日戰情組報器（Phase 2，2026-08-27）——把當天各流的產出合成一則五段式日報，
發到 Discord 隆中對 #每日戰情。設計對談定案（Leo 2026-08-27）：

    分工：Telegram 維持逐則即時推播（07:00/08:19/08:45 各自發）；
         Discord 收「一則合成日報」＝好讀版。所以本組報器只發 Discord 不發 TG，
         同時 alert_telegram/valuation_alert/investment_chief 的個別 Discord 雙發
         已移除（不然同內容在 #每日戰情 出現兩次）。

五段結構（骨架借老墨戰情室，見 memory/mofi_warroom_structure.md）：
    ① 大盤/總經：指數兩行（美/台）+ 排定事件 + 警示關鍵字新聞
    ② 今日訊號異動：SuperTrend翻面/AI轉買賣/貴俗價翻貴——**有變的才列**
    🔄 剛轉進領先象限的類股（2026-09-05 加）：連續 ≥2 天、轉進 ≤20 天，附母體內個股
    ⭐⭐ 四燈+風報比≥1（2026-09-05 加，老墨課堂第 3 條）：跟②段不同，
       **②是事件（今天變了什麼）、這段是存量（現在符合什麼）**
    ③ 投資長判斷：讀當天 advisor_verdicts.jsonl（含 held/triggers/兩角度brief）
    ④ 研究員筆記：產業翻象限/持股事件新聞，一行一條
    ⑤ 近日要看：總經行事曆 + 未來7天要出的財報

排程：researcher_stock_sync.cmd 最後一步（08:45 investment_chief 之後）——
那是一天中所有資料最齊的時間點。組報是純讀檔+格式化，零 AI 呼叫零成本。

用法: python daily_warroom.py [--dry-run]
"""
import os
import sys
import json
import time
import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NL = chr(10)
J_ICON = {"續抱/可買": "🟢", "觀望": "🟡", "考慮出場": "🔴", "資料不足": "⚪"}

_NAMES = None


def tkname(tk):
    """代號＋台股中文名（2026-08-27 Leo：「台股可以加中文嗎」）。
    美股維持代號；台股查證交所/櫃買官方簡稱（industry_rotation 那套，含快取自癒）。"""
    global _NAMES
    if _NAMES is None:
        try:
            from industry_rotation import _tw_chinese_names
            _NAMES = _tw_chinese_names()
        except Exception:
            _NAMES = {}
    code = str(tk).split(".")[0]
    nm = _NAMES.get(code)
    return f"{tk} {nm}" if nm else str(tk)


def _is_tw(tk):
    import re
    return bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(tk)))


def _load(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _today_notes(date):
    out = []
    if os.path.exists("state/research_notes.jsonl"):
        for line in open("state/research_notes.jsonl", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                n = json.loads(line)
                if n.get("ts") == date:
                    out.append(n)
            except Exception:
                pass
    return out


def _today_verdicts(date):
    out = []
    if os.path.exists("state/advisor_verdicts.jsonl"):
        for line in open("state/advisor_verdicts.jsonl", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
                if v.get("ts") == date:
                    out.append(v)
            except Exception:
                pass
    # 同一檔同一天可能有多筆（重跑），留最後一筆
    dedup = {}
    for v in out:
        dedup[v.get("ticker")] = v
    return list(dedup.values())


def sec1_market(notes):
    """① 大盤/總經（沿用 investment_chief._overview_lines 的資料源，格式轉 Discord md）"""
    lines = ["**① 大盤／總經**"]
    md = _load("market_data.json", {}) or {}
    us, tw = [], []
    for it in md.get("indices", []):
        nm, pct, bp = it.get("name", it.get("sym", "")), it.get("chg_pct"), it.get("chg_bp")
        if pct is not None:
            arrow = "🔺" if pct > 0 else ("🔻" if pct < 0 else "▪️")
            part = f"{nm} {arrow}{pct:+.2f}%"
        elif bp is not None:
            part = f"{nm} {bp:+.1f}bp"
        else:
            continue
        (us if (it.get("grp") == "US" and pct is not None) else tw).append(part)
    # 2026-09-01 Leo：「大盤可以一個指數一段嗎？」——原本 4 個指數用「｜」串一行，
    # 手機一行放得下約 20 字，4 個指數會折成 3 行且斷在奇怪的地方（實測截圖）。
    # 改成一個指數一行：行數變多但每行都完整，掃視反而快。
    for p_ in us[:4]:
        lines.append("🇺🇸 " + p_)
    for p_ in tw[:4]:
        lines.append("🇹🇼 " + p_)

    # 🌡️ 大盤體溫計（P2，2026-08-27）：電金比 vs 100MA。只報狀態不下行動指令——
    # 老墨的「連N日轉弱→清倉」門檻是他自己系統的規則，我們沒有對應回測依據
    # （Leo 硬規則：不自行發明投資判定門檻）。資料累積中會顯示進度。
    try:
        from market_thermometer import summary_line as _therm
        t = _therm()
        if t:
            lines.append(t)
    except Exception:
        pass

    # 📊 產業輪動一句話（2026-08-28，零成本模板不叫 AI，靈感來自 tide-tw.app 的
    # daily_brief）。跟④段的 researcher_industry 不重複：這個講「今天誰強誰弱」
    # （每天都有、純排序），researcher_industry 講「為什麼會翻象限」（有翻才寫、
    # 值得花 AI 額度）。
    try:
        from chain_technicals import overview_line as _rot, bears_line as _bear
        r = _rot()
        if r:
            lines.append(r)
        b = _bear()
        if b:
            lines.append(b)      # 獨立一段（Leo 2026-09-01）
    except Exception:
        pass

    macro = [n for n in notes if n.get("layer") == "macro"]
    if macro:
        m = macro[-1]
        if m.get("trigger"):
            lines.append("🌏 今日觸發：" + "；".join(m["trigger"])[:180])
        else:
            ev = [e for e in m.get("events", []) if e.get("status") == "scheduled"][:3]
            if ev:
                lines.append("🌏 近期排定：" + "、".join(
                    f"{e['date'][5:]} {e['event'].split('（')[0]}" for e in ev))
        try:
            from macro_calendar import keyword_hits
            for kw, title in keyword_hits(m.get("headlines") or [])[:3]:
                lines.append(f"📰 **[{kw}]** {title[:48]}")
        except Exception:
            pass
    return lines


def sec2_signals(date, scope="public"):
    """② 今日訊號異動——有變的才列。2026-08-27 拆 public/private：
    public=守備清單訊號（不透露持股）；private=持股翻面+翻貴。"""
    lines = ["**② 今日訊號異動**" if scope == "public" else "**② 持股訊號**"]
    items = []
    st = _load("state/st_flips_today.json", {}) or {}
    tag = "" if st.get("date") == date else "（⚠️非今日資料）" if st.get("date") else ""
    if scope == "private":
        for f in st.get("flips_hold", []):
            items.append(f"💼 {tkname(f['code'])} SuperTrend{f['word']}{tag}")
        for f in _load("state/valuation_flips_today.json", []) or []:
            items.append(f"💰 {tkname(f['ticker'])} 翻貴：現價 {f['price']:,.1f} ≥ 貴價 {f['expensive']:,.1f}")
    else:
        for f in st.get("flips_watch", []):
            items.append(f"🎯 {tkname(f['code'])} SuperTrend{f['word']}{tag}")
        for a in st.get("ai_alerts", []):
            items.append(f"{a['sig']} {tkname(a['code'])} AI訊號 {a.get('reason','')}{tag}")
        # 2026-09-03：進出燈號倉（模擬倉，非持股 → public）昨日動作。Actions 09:00 寫檔、
        # 本機 08:45 隔天讀，所以是「昨天做了什麼」，日期標在句尾不假裝即時。超過 3 天不列。
        lt = _load("state/lamp_trades_today.json", {}) or {}
        try:
            age = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(lt.get("date", ""))).days
        except Exception:
            age = 99
        if age <= 3:
            when = f"（{lt['date']}）" if age else ""
            for tk in lt.get("buy", []):
                items.append(f"🚦 燈號倉 打點買進 {tkname(tk)}{when}")
            for tk in lt.get("half_sell", []):
                items.append(f"🚦 燈號倉 ST翻空賣半 {tkname(tk)}{when}")
            for tk in lt.get("full_exit", []):
                items.append(f"🚦 燈號倉 RS跌破全出 {tkname(tk)}{when}")
    if items:
        lines += ["・" + x for x in items[:12]]
        if len(items) > 12:
            lines.append(f"・…還有 {len(items)-12} 條")
    else:
        lines.append("今日無新訊號。")
    return lines


def _urg(v):
    t, va = v["trend_angle"]["judgment"], v["value_angle"]["judgment"]
    return 0 if (t == "考慮出場" and va == "考慮出場") else (1 if "考慮出場" in (t, va) else 2)


def _vblock(v, entry=False):
    """單檔判斷區塊。2026-08-27 手機版面重排（Leo：「手機上排版不是很好閱讀」）：
    ① 燈號 emoji 移到**行首**——手機掃視時一眼看到紅綠，不用讀到句中才知道
    ② 拿掉全形空白縮排——手機上縮排效果微弱，反而讓折行更亂
    ③ 觸發原因另起一行並縮短（原本接在標題後面，把標題那行擠爆）
    搭配 brief 從 60 字縮到 35 字（investment_chief schema），每檔從 6-8 行壓到 3-4 行。"""
    ta, va = v["trend_angle"], v["value_angle"]
    head = f"**{tkname(v['ticker'])}**"
    if _urg(v) == 0 and not entry:
        head += "　‼️ 兩角度同喊出場"
    out = [head]
    if entry and v.get("triggers"):
        t = v["triggers"][0].replace("巴菲特到俗價", "到俗價").replace("產業轉強", "產業轉強")
        out.append(f"-# {t}")          # Discord 小字體，不搶主要內容的視線
    out += [f"{J_ICON.get(ta['judgment'],'')} 趨勢｜{ta.get('brief') or ta['judgment']}",
            f"{J_ICON.get(va['judgment'],'')} 價值｜{va.get('brief') or va['judgment']}",
            ""]
    return out


def sec_setup(date, scope="public"):
    """⭐⭐ 四燈 + 風報比 ≥ 1（2026-09-05，老墨課堂第 3 條）。

    老墨：「拿報告，然後四個燈且風報比大於 1，是需要觀察的股票」。

    ## 為什麼不把「有券商報告」當必要條件

    實查：194 檔 → 四燈 43 → 加風報比>1 剩 14 → **再加「有報告」只剩 1 檔**。
    ⚠️ 卡住的是**我們的報告覆蓋率**（只有 16 份）不是市場——老墨手上有法人報告庫。
    ⭐ 所以「有報告」做成**加分標記 📑**，不做成過濾條件，否則這段永遠只有一檔。

    ## 為什麼要標產業象限

    2026-09-05 回測（`backtest_mofi_rrg.py`，5 年 131 檔美股）：技術訊號單獨用
    **四個版本全部輸給「隨便哪天買」**；只在**產業處於 RRG 領先象限**時才進場，
    **4 版本 × 3 期間 = 12 格全部改善**（最好一格 +1.39pp、勝率 61.7% vs 57.8%）。
    ⭐ 做工的是「先挑產業」，不是那三個技術指標 → 領先象限的排最前面並標 🔵。
    ⚠️ 幅度不大（n=81），這是方向性證據不是聖杯，所以只排序不過濾。

    ## 這一段不是「今天剛發生」是「現在符合」

    跟②段的訊號異動不同——那段是事件，這段是**存量**。所以不會因為「昨天也符合」
    就不顯示。

    scope 分流同②段：持股的進🔒密報、非持股的進公開版（進場候選）。
    """
    priv = scope == "private"
    lines = ["**⭐⭐ 四燈 + 風報比 ≥ 1**" if priv else "**⭐⭐ 四燈 + 風報比 ≥ 1（進場候選）**"]
    cr = _load("state/combo_result.json", {}) or {}
    rows = cr.get("rows") or cr.get("items") or []
    if not rows:
        return []

    # 有券商報告的代號（📑 加分標記）
    import re as _re
    def _n(t):
        return _re.sub(r"\.(TW|TWO)$", "", str(t).upper()).replace(".", "-")
    st = _load("state/advisor_reports.json", {}) or {}
    has_report = {_n(r.get("ticker")) for r in st.values()
                  if not r.get("_notreport") and r.get("ticker")}
    try:
        from investment_chief import held_universe, norm_ticker
        held = {norm_ticker(t) for t in held_universe()}
    except Exception:                                       # noqa: BLE001
        held = set()

    QL = {"leading": "領先", "improving": "改善", "weakening": "弱化", "lagging": "落後"}
    hit = []
    for r in rows:
        if r.get("lit") != 4 or (r.get("rr") or 0) < 1:
            continue
        n = _n(r.get("ticker"))
        if (n in held) != priv:
            continue
        q = (r.get("quad") or {}).get("60")
        # 排序：領先象限 → 有券商報告 → 風報比高。
        # ⚠️ 首測時把唯一有報告的那檔（2454，落後象限）排到第 9 名被截掉了——
        # 而「拿報告」是老墨那句話裡的**第一個**條件。產業象限有回測支持所以擺第一，
        # 但有報告的不能被擠出畫面。
        # 🔴 2026-09-06：**停損很近的往後放。**
        # 首版用風報比排序，結果前 10 檔有 7 檔帶「⚠️停損僅 x%」——
        # 因為風報比 = 上檔 ÷（現價−停損線），停損越近分母越小、數字越大，
        # **用它排序等於把被放大的那些排到最前面**，我親手把假象放在第一位。
        # ⚠️ 這是**顯示排序**的取捨不是訊號門檻：停損近的仍然列出來、只是排後面
        #    （停損近＝每股風險小，但也更容易被雜訊掃到，兩面都成立）。
        #    5% 沿用燈號頁 ⚠️ 的同一條線，不另外發明一個數字。
        gap = r.get("gap_pct")
        tight = 1 if (gap is not None and gap < 5) else 0
        hit.append((0 if q == "leading" else 1,
                    0 if n in has_report else 1,
                    tight,
                    -(r.get("rr") or 0), r, q, n))
    if not hit:
        return []
    hit.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    for _k, _rp, _tg, _rr, r, q, n in hit[:10]:
        mark = "📑" if n in has_report else "　"
        qs = ("🔵 " + QL[q]) if q == "leading" else (QL.get(q, "—"))
        gap = r.get("gap_pct")
        # ⚠️ 停損很近時風報比的分母趨近 0，數字會被放大——標出來，不要只給大數字
        warn = f"　⚠️停損僅 {gap:.1f}%" if (gap is not None and gap < 5) else ""
        lines.append(f"{mark} **{tkname(r.get('ticker'))}**　風報比 {r.get('rr'):.1f}"
                     f"　{qs}{warn}")
    if len(hit) > 10:
        lines.append(f"-# 　…另有 {len(hit)-10} 檔，完整清單在進出燈號頁按"
                     "「⭐⭐ 4 燈 + 風報比 ≥ 1」")
    n_lead = sum(1 for x in hit if x[0] == 0)
    try:
        from board_theme import PAGES_URL as _P
    except Exception:                                       # noqa: BLE001
        _P = "https://dt-1983.github.io/daily-stock-board"
    lines.append(f"-# 共 {len(hit)} 檔，其中 {n_lead} 檔的產業在 🔵 領先象限"
                 "（回測顯示產業過濾是這裡面最有價值的一層）"
                 "　📑＝有券商報告")
    lines.append(f"-# 🔗 [進出燈號頁]({_P}/combo.html)"
                 "　按「⭐⭐ 4 燈 + 風報比 ≥ 1」看完整清單與個股圖表")
    return lines


def sec_rrg_turn(date, scope="public"):
    """🔄 剛轉進 RRG 領先象限的類股（2026-09-05，Leo：「rrg 轉到領先（2-3天以上）」）。

    只放**公開版**：講的是類股輪動與母體內的個股，不是持股資訊；持股用 💼 標。

    ⚠️ 這一段**只列不判斷**。9/5 的回測只證明「產業在領先象限」當**過濾條件**
    有幫助（12 格全改善但幅度不大）；**沒測過「剛轉進領先」本身是進場訊號**。
    """
    if scope != "public":
        return []
    try:
        import rrg_turns
        from investment_chief import held_universe, norm_ticker
        try:
            held = {norm_ticker(t) for t in held_universe()}
        except Exception:                                   # noqa: BLE001
            held = set()
        body = rrg_turns.lines(period="60", min_days=2, max_days=20,
                               top_stocks=4, held=held)
    except Exception as e:                                  # noqa: BLE001
        return [f"**🔄 剛轉進領先象限的類股**", f"・讀取失敗：{str(e)[:60]}"]
    if not body:
        return []
    try:
        from board_theme import PAGES_URL as _P
    except Exception:                                       # noqa: BLE001
        _P = "https://dt-1983.github.io/daily-stock-board"
    return (["**🔄 剛轉進領先象限的類股**（連續 ≥2 天、轉進 ≤20 天）"] + body
            + [f"-# 🔗 [產業輪動雷達]({_P}/rotation.html)　"
               f"[進出燈號]({_P}/combo.html)（可篩「4 燈」＋「領先」）",
               "-# 💼＝持股　⚠️ 只是「產業轉強」不是買進訊號——"
               "回測證明的是「產業在領先象限」當過濾條件有幫助，"
               "**沒測過「剛轉進去」本身**"])


def sec3_chief(date, scope="public"):
    """③ 投資長判斷。public=進場機會（非持股，美台分段）；private=持股判斷。"""
    vs = _today_verdicts(date)
    if scope == "private":
        lines = ["**③ 持股判斷**（趨勢/價值兩角度獨立，不合併）"]
        held = sorted([v for v in vs if v.get("held", True)], key=_urg)
        if not held:
            lines.append("今日持股無觸發。")
            return lines
        for v in held:
            lines += _vblock(v)
        return lines

    lines = ["**③ 進場機會**（非持股評估：🟢可考慮進場 🔴便宜但別碰）"]
    new = sorted([v for v in vs if not v.get("held", True)],
                 key=lambda v: 0 if v["trend_angle"]["judgment"] == "續抱/可買" else 1)
    # 2026-08-27 Leo：「都是黃燈或白燈就不要呈現，除非是持股」——非持股兩個角度
    # 都是🟡觀望/⚪資料不足＝沒有任何可行動資訊，只是佔版面。留🟢（可考慮進場）
    # 與🔴（便宜但別碰＝價值陷阱警示，那是有用的反向資訊）。持股不套這個篩選。
    def _actionable(v):
        js = {v["trend_angle"]["judgment"], v["value_angle"]["judgment"]}
        return bool(js & {"續抱/可買", "考慮出場"})
    total_new = len(new)
    new = [v for v in new if _actionable(v)]
    hidden = total_new - len(new)
    if not new:
        lines.append(f"今日無進場機會觸發。" if not hidden
                     else f"今日 {total_new} 檔觸發但全數為觀望/資料不足，不列出。")
        return lines
    if hidden:
        lines[0] += f"　*（另有 {hidden} 檔觀望/資料不足未列）*"
    # 2026-08-27 Leo：「進場機會可以分段嗎」——美股/台股分小節，各檔之間留空行
    us = [v for v in new if not _is_tw(v["ticker"])]
    tw = [v for v in new if _is_tw(v["ticker"])]
    if us:
        lines.append("🇺🇸 美股")
        for v in us:
            lines += _vblock(v, entry=True)
    if tw:
        lines.append("🇹🇼 台股")
        for v in tw:
            lines += _vblock(v, entry=True)
    return lines


def sec4_research(notes, scope="public", date=None):
    """④ 研究員筆記。public=產業層（不涉持股）；private=持股事件新聞。"""
    got = False
    if scope == "private":
        lines = ["**④ 持股新聞**"]
        for n in notes:
            if n.get("layer") == "stock" and n.get("source") == "yfinance_news":
                for h in (n.get("headlines") or [])[:6]:
                    lines.append(f"・📰 [{h.get('kw','')}] {h.get('title','')[:46]}")
                    got = True
        if not got:
            lines.append("今日持股無事件型新聞。")
        return lines
    lines = ["**④ 研究員筆記**"]
    for n in notes:
        if n.get("layer") == "industry":
            ev = (n.get("events") or [{}])[0].get("event", "")
            lines.append(f"・🔄 {n.get('scope','')}：{ev.replace('RRG象限','')[:40]}")
            got = True
    if not got:
        lines.append("今日無產業象限翻轉。")

    # 全市場籌碼異常（2026-08-28，chip_scan.py）。放公開版：這是全市場公開資訊、
    # 跟持股無關，不會洩漏部位。跟我們既有的籌碼運用互補——screen.py/tw_analyze.py
    # 只看守備清單內的股票，這裡是**清單外**也掃得到，可能更早抓到轉強股。
    try:
        import chip_scan as _cs
        ce = _cs._load(_cs.OUT_PATH, {})
        cd = ce.get("date")
        # 用「資料日期在 3 天內」而不是「等於今天」：台股收盤後才有籌碼資料，
        # 週末/連假的日報要顯示的是最近一個交易日的結果（週六看週五的才對）。
        # 非當日的標出日期，不要讓人以為是今天的。
        if cd and ce.get("events"):
            try:
                gap = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(cd)).days
            except Exception:
                gap = 99
            if 0 <= gap <= 3:
                # 2026-08-31：訊息只列每類 2 檔＋連結到完整頁面（Leo：「會不會太多資訊？」）。
                # 分工＝訊息回答「今天有沒有事」、頁面回答「細節是什麼」——
                # 頁面還能標註哪幾檔在七鏈裡，那是訊息塞不下的資訊。
                ls = _cs.summary_lines(ce["events"], max_each=2)
                if ls:
                    when = "" if gap == 0 else f"・{cd}"
                    lines.append("")
                    lines.append(f"**🔍 全市場籌碼異常**（{len(ce['events'])} 筆・三大法人{when}）")
                    lines += ls
                    lines.append("-# [完整清單＋七鏈標註]"
                                 "(https://dt-1983.github.io/daily-stock-board/chip.html)")
    except Exception as e:
        # 不要完全靜默——2026-08-28 第一版寫錯（sec4_research 當時沒有 date 參數，
        # 引用了不存在的變數）就是被 `except: pass` 吞掉，畫面上看起來像「今天沒有
        # 籌碼異常」而不是「程式錯了」。今天已經因為這個模式踩了四五次坑。
        print(f"  [warn] 籌碼異常區塊失敗：{e}")
    return lines


def sec5_watch(date):
    """⑤ 近日要看——總經行事曆 + 未來7天財報"""
    lines = ["**⑤ 近日要看**"]
    try:
        from macro_calendar import upcoming_events
        for e in upcoming_events(date, days_before=0, days_after=10)[:3]:
            lines.append(f"・📅 {e['date'][5:]} {e['event'].split('（')[0]}")
    except Exception:
        pass
    st = _load("state/earnings_seen.json", {}) or {}
    today_d = datetime.date.fromisoformat(date)
    ups = []
    for key in st.get("upcoming", {}):
        tk, ds = key.rsplit("@", 1)
        try:
            ed = datetime.date.fromisoformat(ds)
        except ValueError:
            continue
        if 0 <= (ed - today_d).days <= 7:
            ups.append((ed, tk))
    for ed, tk in sorted(ups)[:5]:
        lines.append(f"・📊 {ed.strftime('%m-%d')} {tk} 財報")
    # 2026-09-03 老墨三段時程「驗證日程」（行動 5）：到期前 21 天列出、逾期未驗證持續提醒。
    # 行事曆型，零成本；不自動上網查證（那是付費呼叫），驗證在對談中做、用 roadmap_milestones.py 更新狀態。
    rm = _load("state/roadmap_milestones.json", {}) or {}
    due_soon = []
    for m in rm.get("milestones", []):
        if m.get("status") != "pending":
            continue
        try:
            dd = (datetime.date.fromisoformat(m["due"]) - today_d).days
        except Exception:
            continue
        if dd <= 21:
            due_soon.append((dd, m))
    for dd, m in sorted(due_soon, key=lambda x: x[0])[:4]:
        tag = f"逾期 {-dd} 天未驗證" if dd < 0 else f"{m['due'][5:]} 前"
        lines.append(f"・📌 驗證日程｜{m['claim']}（{tag}）")
        # 2026-09-03：只列宣稱等於還是要自己去翻——把「算過的標準」跟「已經抓到的
        # 法說會線索」一起端出來，看到提醒當下就能判斷，不用再開檔案。
        c = (m.get("criteria") or {}).get("confirmed")
        if c:
            lines.append(f"　　✅ 算過：{c[:60]}")
        try:
            import roadmap_milestones
            for tk, q, it in roadmap_milestones.clues(m)[:2]:
                lines.append(f"　　📄 {tk} {q}｜{str(it.get('value',''))[:60]}")
        except Exception:                                   # noqa: BLE001
            pass
    # 投顧報告失效線（2026-09-03，路線圖第 5 項）。零成本：只比對現價，
    # 資料由 advisor_reports.check() 寫進 state/advisor_reports_today.json。
    # 全健康時也給一行計數——沒有那行的話「健康」跟「壞掉」長得一樣
    # （同 silent_failure_pattern：沒被檢查 ≠ 檢查過沒事）。
    try:
        import advisor_reports
        lines += advisor_reports.summary_lines()
    except Exception as e:                                  # noqa: BLE001
        lines.append(f"・📑 投顧報告失效線讀取失敗：{str(e)[:60]}")
    # 券商目標價／評等異動（2026-09-03，Leo：「做異動提醒」）。
    # **只推 target_changes.TRUSTED 名單內的券商 ∩ 我們母體內**——Leo 明講
    # 那份異動表裡他只信高盛。其餘只給一行計數，數字未經覆核不進判斷。
    try:
        import target_changes
        lines += target_changes.summary_lines()
    except Exception as e:                                  # noqa: BLE001
        lines.append(f"・🎯 券商異動讀取失敗：{str(e)[:60]}")
    if len(lines) == 1:
        lines.append("近10天無排定事件/財報。")
    return lines


def sec_thesis(date, scope="private"):
    """⑤ 失效條件日檢（P1，2026-08-27）——讀 thesis_check.py 的當日結果。
    老墨式三態：🚫觸發/⚠️逼近/✅健康＋📋待財報檢。

    2026-08-31 加 scope 分流（Leo：「也推了不是持股的？」）——投資長 P0 擴充後
    非持股的進場評估也會登錄失效條件，48 檔裡有 41 檔是非持股，全部被推進
    🔒持股密報。現在 private 只出持股、public 只出非持股（那是進場觀察，
    放公開版才對）。
    """
    lines = ["**⑤ 失效條件日檢**" if scope == "private" else "**⑥ 觀察名單失效條件**"]
    d = _load("state/thesis_check_today.json", {}) or {}
    if not d:
        return []                     # 沒登錄過就整段不出現，不要放佔位語佔版面
    tag = "" if d.get("date") == date else "（⚠️非今日資料）"
    want_held = (scope == "private")

    def _pick(rows):
        """相容三代格式：(tk,msg) → (tk,msg,held) → (tk,msg,held,angle)。
        缺 held 一律當持股（跟改版前行為一致，不會突然消失）；
        缺 angle 一律當價值——8/31 之前登錄的 83 條實測 39/44 條寫的就是俗貴價，
        標 value 比標 unknown 誠實。"""
        out = []
        for r in rows:
            tk, msg = r[0], r[1]
            held = r[2] if len(r) > 2 else True
            angle = r[3] if len(r) > 3 else "value"
            # 第五代格式（2026-09-05）多帶條件型別，用來把持股的出場訊號標紅。
            # 逼近/待檢那兩串沒有這一欄，缺就是 None——不猜。
            ctype = r[4] if len(r) > 4 else None
            if bool(held) == want_held:
                out.append((tk, msg, angle, ctype))
        return out

    # 2026-08-31（Leo：「失效條件也可以分兩個嗎，不是只有價值投資」）：
    # 每行掛角度符號而不是拆成兩個小節——拆節會讓行數翻倍，跟 8/31 才剛修好的
    # 「排版很難懂」衝突。趨勢排前面（它是每天會動的那類，價值是慢變數）。
    AI_ = {"trend": "📉", "value": "💰"}
    try:
        from thesis_check import EXIT_TYPES as _EXIT_TYPES
    except Exception:                                       # noqa: BLE001
        _EXIT_TYPES = ("supertrend_bear", "supertrend_flip", "rs_below")

    # 標記持有人（2026-08-31 Leo：「一起在持股密報裡，但幫我標明」）
    # 👦 小孩｜🏠 Leo 的繼承台股（監控但不參與風控）｜空＝Firstrade 核心部位
    try:
        from trade_plan import kids_tickers, legacy_tickers
        _MK = {t: "🏠 " for t in legacy_tickers()}
        _MK.update({t: "👦 " for t in kids_tickers()})
    except Exception:
        _MK = {}

    def _who(tk):
        return _MK.get(tk, "")

    def _srt(rows):
        return sorted(rows, key=lambda r: 0 if r[2] == "trend" else 1)

    trig, near = _srt(_pick(d.get("triggered", []))), _srt(_pick(d.get("near", [])))
    pend = _pick(d.get("pending_metric", []))
    hz = d.get("healthy", 0)
    n_ok = (hz.get("held" if want_held else "watch", 0) if isinstance(hz, dict)
            else (hz if want_held else 0))

    # 🔴 2026-09-05（Leo：「SuperTrend 翻空／RS(60) 跌破自身均線，可以幫我針對
    # 持股特別標示嗎？」）——把持股的這兩型抽出來單獨放最前面。
    # 起因：9/5 日檢一次觸發 40 條，其中 **32 條意思是相反的**（RS 站回均線＝
    # 之前的出場疑慮解除），而真正該看的只有 TSLA、GOOG 兩條，排版上完全一樣。
    # ⚠️ 只收 EXIT_TYPES 那兩型（型別本身就等於方向）；`price_above` 不收，
    # 因為同一型別兩種意思（漲破貴價＝出場／站回翻空點＝解除）。
    exit_rows, other = [], []
    for r in trig:
        (exit_rows if (want_held and r[3] in _EXIT_TYPES) else other).append(r)
    for tk, msg, ang, _t in exit_rows[:5]:
        lines.append(f"🔴 {_who(tk)}**{tkname(tk)}**　{msg[:34]}")
    if len(exit_rows) > 5:
        lines.append(f"-# 　…另有 {len(exit_rows)-5} 檔出場訊號")

    # 只列前 5 檔——8/31 那次持股密報一次噴出十幾檔🚫，每檔還帶一整句說明，
    # 手機上完全看不完（Leo：「排版很難懂不易閱讀」）。觸發的按「超過幅度」排序，
    # 最誇張的先看。
    for tk, msg, ang, _t in other[:5]:
        lines.append(f"🚫{AI_.get(ang, '💰')} {_who(tk)}**{tkname(tk)}**　{msg[:34]}")
    if len(other) > 5:
        lines.append(f"-# 　…另有 {len(other)-5} 檔已觸發")
    for tk, msg, ang, _t in near[:3]:
        lines.append(f"⚠️{AI_.get(ang, '💰')} {_who(tk)}{tkname(tk)}　{msg[:34]}")
    if len(near) > 3:
        lines.append(f"-# 　…另有 {len(near)-3} 檔逼近")

    # 存量：持股「現在」處在哪一階段（2026-09-05）。
    # 上面那些是**今天剛發生的事件**；多數翻空的持股是更早翻的、甚至登錄條件時
    # 就已經是空方，永遠不會再被報成新事件 → 只看事件流會以為沒事。
    # ⭐ 只給計數＋最嚴重那一格的代號，不整串列出來（24 檔會把版面吃光）。
    if want_held:
        es = d.get("exit_state") or []
        both = [r[0] for r in es if r[1] and r[2]]
        st_only = [r[0] for r in es if r[1] and not r[2]]
        rs_only = [r[0] for r in es if r[2] and not r[1]]
        unk = [r[0] for r in es if r[1] is None]
        if es:
            lines.append(f"-# 🔻 **出場訊號現況（存量，非今日新增）**　"
                         f"ST翻空＋RS跌破 {len(both)}｜只有ST翻空 {len(st_only)}｜"
                         f"只有RS跌破 {len(rs_only)}｜沒事 "
                         f"{len(es)-len(both)-len(st_only)-len(rs_only)-len(unk)}"
                         + (f"｜⚪算不出來 {len(unk)}" if unk else ""))
            if both:
                head = "、".join(both[:14]) + ("…" if len(both) > 14 else "")
                lines.append(f"-# 　兩條都成立：{head}")

    tail = f"✅ 健康 {n_ok} 條"
    if pend:
        tail += f"｜📋 待財報檢 {len(pend)} 條"
    if trig or near:
        tail += "　📉趨勢／💰價值"
    lines.append(f"-# {tail}{tag}")

    # 2026-09-03：**「沒被檢查」不能長得像「沒事」**。上面的健康/觸發數字只涵蓋
    # 有登錄失效條件的股票；沒被投資長判斷過的持股連出現的機會都沒有，是靜默盲區。
    # 只出現在持股密報（private），因為它會列出持股代號。
    if want_held:
        unc = d.get("uncovered") or []
        if unc:
            cov = d.get("covered_count", 0)
            head = ", ".join(unc[:8]) + ("…" if len(unc) > 8 else "")
            lines.append(f"-# 🔕 監控涵蓋率 {cov}/{cov + len(unc)}　"
                         f"{len(unc)} 檔持股沒有任何失效條件在檢查：{head}")
    return lines if len(lines) > 1 else []


def _empty(sec_lines):
    """這一段是不是「沒東西」——只有標題、或內容全是那幾句佔位語。
    2026-08-27 拆兩則後需要：某一則整份沒內容就不發，不要推空訊息。"""
    body = [x for x in sec_lines[1:] if x.strip()]
    if not body:
        return True
    placeholders = ("今日無新訊號", "今日無觸發標的", "今日無進場機會觸發",
                    "今日持股無觸發", "今日無產業象限翻轉", "今日持股無事件型新聞")
    return all(any(p in b for p in placeholders) for b in body)


def baserate_message(scope):
    """P3 預估前提檢查——**獨立一則**，不併進日報（Leo 2026-08-28：「多一則」）。
    週跑，只在產出當天有內容；持股→持股密報、非持股→#財報。
    回 None 表示今天沒有內容，呼叫端不要發。"""
    try:
        import base_rate as BR
        d = BR._load() or {}
        if d.get("date") != datetime.date.today().isoformat():
            return None
        held = BR._held_set()
        mine = [c for c in d.get("checks", [])
                if ((c["ticker"] in held) if scope == "private" else (c["ticker"] not in held))]
        # 每月 11 號推完整清單（台股月營收 10 號前公布完，那天資料最新）；
        # 其他週一只推**燈號有變的**。同一份清單每週貼一次，第二週就沒人看了
        # ——沿用系統裡既有的「變化才推」模式（Leo 2026-08-28 指定）。
        full = datetime.date.today().day in (11, 12, 13)   # 11 號可能不是週一，給三天窗
        hot = [c for c in mine
               if (c.get("requirement") or {}).get("tier") in ("unprecedented", "rare")]
        if not full:
            hot = [c for c in hot if c.get("changed")]
            # 降級也是新聞（🚫→✅ 表示壓力解除），所以變化清單不能只留高危的
            hot += [c for c in mine if c.get("changed")
                    and (c.get("requirement") or {}).get("tier") == "normal"]
        if not hot:
            return None
        hot.sort(key=lambda c: (0 if c["requirement"]["tier"] == "unprecedented" else 1,
                                -(c["requirement"].get("excess") or 0)))
        who = "持股" if scope == "private" else "觀察名單"
        if full:
            out = [f"# 📐 預估前提檢查・{who}（每月完整清單）",
                   "分析師預估要求的成長，這家公司自己做過嗎？"
                   "（🚫要破自己的紀錄　⚠️剛好貼在紀錄上）", ""]
        else:
            out = [f"# 📐 預估前提檢查・{who}（本週異動）",
                   f"燈號跟上次（{d.get('prev_date','')}）不一樣的才列，沒變的不重複貼。", ""]
        for c in hot[:3]:                       # 前三名完整展開
            block = BR.card(c)
            if not full and c.get("prev_tier"):
                block.insert(1, f"　變化：{BR.TIER.get(c['prev_tier'],'')} → "
                                f"{BR.TIER.get(c['requirement']['tier'],'')}")
            out += block + [""]
        rest = hot[3:]
        if rest:
            out.append("**同樣要破紀錄，數字較小的**")
            bits = []
            for c in rest[:12]:
                r = c["requirement"]
                need = r.get("need_qoq") if r["kind"] == "us_quarterly" else r.get("need_yoy")
                mx = r.get("qoq_max") if r["kind"] == "us_quarterly" else r.get("yoy_max")
                bits.append(f"{BR.TIER[r['tier']]}{c['ticker']}"
                            f"（要求{need*100:+.0f}%／最好{mx*100:+.0f}%）")
            out.append("　".join(bits))
            if len(rest) > 12:
                out.append(f"-# 還有 {len(rest)-12} 檔")
        ok = sum(1 for c in d["checks"]
                 if (c.get("requirement") or {}).get("tier") == "normal")
        out.append(f"-# 另有 {ok} 檔的預估落在它們過去做得到的範圍內。"
                   f"共檢查 {len(d['checks'])} 檔，每週一更新。")
        return NL.join(out)
    except Exception:
        return None


def compose(date=None, scope="public", part="all"):
    """scope: public（#每日戰情，可給家人看，不含持股資訊）／private（私人頻道）
    part（2026-08-27 Leo 要求拆兩則，讓分工看得見）：
        research＝龐統的情報彙整（大盤/訊號/產業筆記/近日要看）
        chief   ＝孔明的判斷
        all     ＝合併成一則（--dry-run 預覽與日後想改回去用）
    回 None＝這一則沒有實質內容 → 呼叫端別發（避免空訊息洗版）。"""
    date = date or time.strftime("%Y-%m-%d")
    notes = _today_notes(date)
    wd = "一二三四五六日"[datetime.date.fromisoformat(date).weekday()]
    priv = scope == "private"
    title = f"# {'🔒 持股密報' if priv else '📋 每日戰情'} · {date}（{wd}）"

    if priv:
        research = [sec2_signals(date, "private"), sec_setup(date, "private"),
                    sec4_research(notes, "private"), sec_thesis(date)]
        chief = [sec3_chief(date, "private")]
    else:
        research = [sec1_market(notes), sec2_signals(date, "public"),
                    sec_rrg_turn(date, "public"), sec_setup(date, "public"),
                    sec4_research(notes, "public", date), sec5_watch(date),
                    sec_thesis(date, "public")]
        chief = [sec3_chief(date, "public")]

    if part == "research":
        secs, suffix = research, ""
    elif part == "chief":
        secs, suffix = chief, "・判斷"
    else:
        secs, suffix = research[:2] + chief + research[2:], ""

    if part != "all" and all(_empty(s) for s in secs):
        return None
    # 空的段落要整段跳過，不能 append 空字串——"\n\n".join 會把它變成訊息裡的空洞。
    # 2026-08-28 加第⑥段（週跑，週二~週五本來就是空的）時才踩到，但這是通用問題：
    # 任何一段沒內容都會留下空行。
    parts = [title + suffix] + ["\n".join(sec) for sec in secs if sec]
    return "\n\n".join(parts)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    # 2026-08-27：每個頻道拆兩則——龐統發情報、孔明發判斷（分工看得見、各則更短，
    # 也不容易撞到 Discord 2000 字上限被切成好幾則）。沒實質內容的那則不發。
    from notify_discord import send_discord, CHANNELS
    for ch, scope in (("daily", "public"), ("private", "private")):
        if ch == "private" and not CHANNELS.get("private") and not args.dry_run:
            print("⚠️ DISCORD_WH_PRIVATE 未設定，持股密報跳過（Telegram 照舊有）")
            continue
        for part, persona in (("research", "龐統"), ("chief", "孔明")):
            msg = compose(scope=scope, part=part)
            if not msg:
                # 2026-09-01 Leo：「投資長在持股密報可以推一個今日無消息的訊息嗎？」
                # ——原本沒內容就整則不發，於是「今天持股真的沒事」跟「投資長掛了/
                # 批次沒跑」在 Discord 上長得一模一樣（今天 08:45 就是這樣，Leo 以為壞了）。
                # 跟 stocks_forum 的心跳同一個道理：**沒消息也要說一聲沒消息**。
                # 只在持股密報的投資長那則補心跳——#每日戰情是公開頻道，
                # 每天多一則「無事」是雜訊；而持股密報是 Leo 每天在等的那一則。
                if ch == "private" and part == "chief":
                    hb = (f"# 🧭 持股判斷 · {datetime.date.today():%Y-%m-%d}"
                          + NL + "今日持股無新事件，投資長不出手。"
                          + NL + "-# 沒有持股被觸發（產業翻象限／個股訊號／到俗價都沒發生）。"
                            "這是「已檢查、無事」，不是漏推。")
                    if args.dry_run:
                        print(f"\n───── {ch} / {persona}（心跳）─────\n{hb}")
                    else:
                        print(f"[{ch}/{part}→{persona}] 心跳",
                              send_discord(ch, hb, persona=persona))
                else:
                    print(f"[{ch}/{part}] 今天沒有實質內容，不發")
                continue
            if args.dry_run:
                print(f"\n───── {ch} / {persona} ─────\n{msg}")
            else:
                print(f"[{ch}/{part}→{persona}]", send_discord(ch, msg, persona=persona))

    # P3 預估前提檢查——**獨立一則**（Leo 2026-08-28：「多一則」），一週一次（週一）。
    # 持股→持股密報、非持股→#財報（不是#每日戰情：這是估值前提不是當日戰況，
    # 跟財報四段快訊同一個性質，放一起 Leo 才找得到）。沒內容就不發。
    for scope, ch in (("private", "private"), ("public", "earnings")):
        if ch == "private" and not CHANNELS.get("private") and not args.dry_run:
            continue
        msg = baserate_message(scope)
        if not msg:
            print(f"[baserate/{scope}] 今天沒有內容，不發")
            continue
        if args.dry_run:
            print(f"\n───── baserate / {ch} ─────\n{msg}")
        else:
            print(f"[baserate/{scope}→{ch}]", send_discord(ch, msg, persona="龐統"))

    if args.dry_run:
        print("\n(dry-run：沒發 Discord)")


if __name__ == "__main__":
    main()
