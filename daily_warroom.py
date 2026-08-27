# -*- coding: utf-8 -*-
"""每日戰情組報器（Phase 2，2026-08-28）——把當天各流的產出合成一則五段式日報，
發到 Discord 隆中對 #每日戰情。設計對談定案（Leo 2026-08-28）：

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

J_ICON = {"續抱/可買": "🟢", "觀望": "🟡", "考慮出場": "🔴", "資料不足": "⚪"}

_NAMES = None


def tkname(tk):
    """代號＋台股中文名（2026-08-28 Leo：「台股可以加中文嗎」）。
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
    """② 今日訊號異動——有變的才列。2026-08-28 拆 public/private：
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
    """單檔判斷區塊。結尾帶空行（2026-08-28 Leo：「進場機會可以分段嗎」——
    原本各檔擠在一起沒有間隔）。"""
    ta, va = v["trend_angle"], v["value_angle"]
    head = f"**【{tkname(v['ticker'])}】**" + ("　‼️ 兩角度同喊出場" if (_urg(v) == 0 and not entry) else "")
    if entry and v.get("triggers"):
        head += f"　*{v['triggers'][0]}*"
    return [head,
            f"　趨勢 {J_ICON.get(ta['judgment'],'')}｜{ta.get('brief') or ta['judgment']}",
            f"　價值 {J_ICON.get(va['judgment'],'')}｜{va.get('brief') or va['judgment']}",
            ""]


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

    lines = ["**③ 進場機會**（非持股評估：🟢可考慮進場 🟡先不進 🔴避開）"]
    new = sorted([v for v in vs if not v.get("held", True)],
                 key=lambda v: 0 if v["trend_angle"]["judgment"] == "續抱/可買" else 1)
    if not new:
        lines.append("今日無進場機會觸發。")
        return lines
    # 2026-08-28 Leo：「進場機會可以分段嗎」——美股/台股分小節，各檔之間留空行
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


def compose(date=None, scope="public"):
    """scope: public（#每日戰情，之後可能開放家人看，不含任何持股資訊）
             private（私人頻道，持股訊號/判斷/新聞）"""
    date = date or time.strftime("%Y-%m-%d")
    notes = _today_notes(date)
    wd = "一二三四五六日"[datetime.date.fromisoformat(date).weekday()]
    if scope == "private":
        parts = [f"# 🔒 持股密報 · {date}（{wd}）"]
        secs = (sec2_signals(date, "private"), sec3_chief(date, "private"),
                sec4_research(notes, "private"))
    else:
        parts = [f"# 📋 每日戰情 · {date}（{wd}）"]
        secs = (sec1_market(notes), sec2_signals(date, "public"),
                sec3_chief(date, "public"), sec4_research(notes, "public"), sec5_watch(date))
    for sec in secs:
        parts.append("\n".join(sec))
    return "\n\n".join(parts)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    pub = compose(scope="public")
    prv = compose(scope="private")
    print(pub)
    print("\n" + "═" * 40 + "\n")
    print(prv)
    if args.dry_run:
        print("\n(dry-run：沒發 Discord)")
        return
    from notify_discord import send_discord, CHANNELS
    ok1 = send_discord("daily", pub, persona="孔明")
    if CHANNELS.get("private"):
        ok2 = send_discord("private", prv, persona="孔明")
    else:
        ok2 = False
        print("⚠️ DISCORD_WH_PRIVATE 未設定——持股密報這次沒發 Discord（Telegram 照舊有）。"
              "建私人頻道拉 webhook 後把 URL 加進 .env 即可。")
    print(f"\npublic: {ok1} | private: {ok2}")


if __name__ == "__main__":
    main()
