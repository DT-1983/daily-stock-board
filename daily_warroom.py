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
    if us:
        lines.append("🇺🇸 " + "｜".join(us[:4]))
    if tw:
        lines.append("🇹🇼 " + "｜".join(tw[:4]))

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
        from chain_technicals import overview_line as _rot
        r = _rot()
        if r:
            lines.append(r)
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


def sec4_research(notes, scope="public"):
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
    if len(lines) == 1:
        lines.append("近10天無排定事件/財報。")
    return lines


def sec_thesis(date):
    """⑤ 失效條件日檢（P1，2026-08-27）——讀 thesis_check.py 的當日結果。
    老墨式三態：🚫觸發/⚠️逼近/✅健康＋📋待財報檢。"""
    lines = ["**⑤ 失效條件日檢**"]
    d = _load("state/thesis_check_today.json", {}) or {}
    if not d:
        lines.append("尚無登錄的失效條件（投資長判斷產出後自動登錄）。")
        return lines
    tag = "" if d.get("date") == date else "（⚠️非今日資料）"
    for tk, msg in d.get("triggered", []):
        lines.append(f"・🚫 **{tkname(tk)}** {msg}{tag}")
    for tk, msg in d.get("near", []):
        lines.append(f"・⚠️ {tkname(tk)} {msg}{tag}")
    pm = d.get("pending_metric", [])
    lines.append(f"・✅ 健康 {d.get('healthy', 0)} 條"
                 + (f"｜📋 待財報檢 {len(pm)} 條" if pm else ""))
    return lines


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
        research = [sec2_signals(date, "private"), sec4_research(notes, "private"),
                    sec_thesis(date)]
        chief = [sec3_chief(date, "private")]
    else:
        research = [sec1_market(notes), sec2_signals(date, "public"),
                    sec4_research(notes, "public"), sec5_watch(date)]
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
