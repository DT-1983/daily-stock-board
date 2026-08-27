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


def sec2_signals(date):
    """② 今日訊號異動——有變的才列，沒變就一行帶過"""
    lines = ["**② 今日訊號異動**"]
    items = []
    st = _load("state/st_flips_today.json", {}) or {}
    stale = st.get("date") not in (None, date) and st.get("date") != date
    tag = "" if st.get("date") == date else "（⚠️非今日資料）" if st.get("date") else ""
    for f in st.get("flips_hold", []):
        items.append(f"💼 {f['code']} {f.get('name','')} SuperTrend{f['word']}{tag}")
    for f in st.get("flips_watch", []):
        items.append(f"🎯 {f['code']} {f.get('name','')} SuperTrend{f['word']}{tag}")
    for a in st.get("ai_alerts", []):
        items.append(f"{a['sig']} {a['code']} {a.get('name','')} AI訊號 {a.get('reason','')}{tag}")
    for f in _load("state/valuation_flips_today.json", []) or []:
        items.append(f"💰 {f['ticker']} 翻貴：現價 {f['price']:,.1f} ≥ 貴價 {f['expensive']:,.1f}")
    if items:
        lines += ["・" + x for x in items[:12]]
        if len(items) > 12:
            lines.append(f"・…還有 {len(items)-12} 條")
    else:
        lines.append("今日無翻面/轉買賣/翻貴。")
    return lines


def sec3_chief(date):
    """③ 投資長判斷（讀 verdicts，兩角度 brief）"""
    lines = ["**③ 投資長判斷**（趨勢/價值兩角度獨立，不合併）"]
    vs = _today_verdicts(date)
    if not vs:
        lines.append("今日無觸發標的。")
        return lines

    def urg(v):
        t, va = v["trend_angle"]["judgment"], v["value_angle"]["judgment"]
        return 0 if (t == "考慮出場" and va == "考慮出場") else (1 if "考慮出場" in (t, va) else 2)

    held = sorted([v for v in vs if v.get("held", True)], key=urg)
    new = sorted([v for v in vs if not v.get("held", True)],
                 key=lambda v: 0 if v["trend_angle"]["judgment"] == "續抱/可買" else 1)

    def block(v, entry=False):
        ta, va = v["trend_angle"], v["value_angle"]
        head = f"**【{v['ticker']}】**" + ("　‼️ 兩角度同喊出場" if (urg(v) == 0 and not entry) else "")
        if entry and v.get("triggers"):
            head += f"　*{v['triggers'][0]}*"
        return [head,
                f"　趨勢 {J_ICON.get(ta['judgment'],'')}｜{ta.get('brief') or ta['judgment']}",
                f"　價值 {J_ICON.get(va['judgment'],'')}｜{va.get('brief') or va['judgment']}"]

    if held:
        lines.append("💼 持股")
        for v in held:
            lines += block(v)
    if new:
        lines.append("🆕 進場機會（🟢可考慮進場 🟡先不進 🔴避開）")
        for v in new:
            lines += block(v, entry=True)
    return lines


def sec4_research(notes):
    """④ 研究員筆記——一行一條"""
    lines = ["**④ 研究員筆記**"]
    got = False
    for n in notes:
        if n.get("layer") == "industry":
            ev = (n.get("events") or [{}])[0].get("event", "")
            lines.append(f"・🔄 {n.get('scope','')}：{ev.replace('RRG象限','')[:40]}")
            got = True
    for n in notes:
        if n.get("layer") == "stock" and n.get("source") == "yfinance_news":
            for h in (n.get("headlines") or [])[:4]:
                lines.append(f"・📰 [{h.get('kw','')}] {h.get('title','')[:46]}")
                got = True
    if not got:
        lines.append("今日無產業翻轉/持股事件新聞。")
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


def compose(date=None):
    date = date or time.strftime("%Y-%m-%d")
    notes = _today_notes(date)
    wd = "一二三四五六日"[datetime.date.fromisoformat(date).weekday()]
    parts = [f"# 📋 每日戰情 · {date}（{wd}）"]
    for sec in (sec1_market(notes), sec2_signals(date), sec3_chief(date),
                sec4_research(notes), sec5_watch(date)):
        parts.append("\n".join(sec))
    return "\n\n".join(parts)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    msg = compose()
    print(msg)
    if args.dry_run:
        print("\n(dry-run：沒發 Discord)")
        return
    from notify_discord import send_discord
    ok = send_discord("daily", msg, persona="孔明")
    print("\n✅ 已發 Discord #每日戰情" if ok else "\n⚠️ Discord 發送失敗")


if __name__ == "__main__":
    main()
