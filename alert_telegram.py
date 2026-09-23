"""Telegram 只推「反轉/警示」（美股+台股）+ 附完整 HTML 看板。

警示 = 🔴 賣出 / 🟢 買進；反轉 = 訊號 vs 上次不同（state/signals.json）
其餘（⚪觀望）不推，完整資料看 HTML 附件。

🔴🔴 **這支不只是通知程式，它是訊號狀態的唯一寫入者。要精簡 Telegram 時千萬別停掉它。**

    本檔結尾會寫兩個檔（見 main 最後幾行）：
        state/signals.json         ← investment_chief 的「AI綜合訊號」材料
        state/st_flips_today.json  ← researcher_stock 的 SuperTrend 翻面來源

    也就是說 08:45 那整批（研究員、投資長、失效條件日檢、Discord 日報）的訊號輸入，
    全部來自這支在 08:19 寫下的檔案。**停掉它 = 切斷投資長的輸入，而畫面上只會看到
    「今天沒訊號」，不會報錯。**（2026-08-27 GitHub 排程被丟掉兩天就是這樣：
    不只沒收到晨報，08:45 整批都在用前一天的訊號——所以才加了 actions_watchdog。）

    真的要停 Telegram 推播，改法是**只拿掉 send_text 那幾行**，寫檔的部分留著；
    或把寫檔搬到獨立模組再讓兩邊各自呼叫。不要整支刪掉。
    （2026-08-28 Leo：「TG 應該會被拿掉或只推更重要的」→ 補上這段警告。）

用法:python alert_telegram.py reports/report_YYYYMMDD.md board.html
"""
import sys
import os
import json
import html as _html
from datetime import datetime
import requests
from board_html import parse_report, oneliner, CHAIN_MAP, CHAIN_ICON, CHAIN_ORDER, TW_NAME
from tw_report import convert

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
PAGES_URL = "https://dt-1983.github.io/daily-stock-board/board.html"  # 2026-08-04 首頁改版：看板搬到 board.html
STATE = "state/signals.json"
TW_JSON = "tw_analysis.json"
ALERT_SIGS = {"🔴", "🟢"}
SIG_WORD = {"🔴": "賣出", "🟢": "買進", "🔵": "持有", "🟡": "觀望", "⚪": "觀望"}


def esc(s):
    return _html.escape(str(s or ""))


SIG_LABEL = {"st": "SuperTrend", "rs60": "RS60"}


def _send_priority_alert(flips_hold):
    """持股翻面/RS60跌破 → 立刻另發一則獨立、高辨識度的Discord警示（見main()裡的說明）。
    沒有DISCORD_LEO_USER_ID就不@mention，訊息照發（缺這個env不該讓警示整個發不出去）。"""
    if not flips_hold:
        return
    try:
        from notify_discord import send_discord
    except Exception as e:                                   # noqa: BLE001
        print(f"[priority_alert] 讀不到 notify_discord（跳過）：{str(e)[:80]}")
        return

    # 同一檔今天兩個訊號都觸發（像CEG那次SuperTrend+RS60同天）→ 這檔升級成雙訊號警示。
    by_code = {}
    for f in flips_hold:
        by_code.setdefault(f["code"], []).append(f)

    uid = os.environ.get("DISCORD_LEO_USER_ID", "")
    mention = f"<@{uid}> " if uid else ""
    lines = [f"{mention}🚨 **持股訊號觸發**"]
    for code, fs in by_code.items():
        name = fs[0].get("name") or ""
        dual = len(fs) > 1
        head = "🚨🚨" if dual else "🚨"
        lines.append(f"{head} **{esc(code)}**{(' ' + esc(name)) if name else ''}")
        for f in fs:
            lines.append(f"　{SIG_LABEL.get(f.get('sig',''), '')}：{esc(f['word'])}")
        if dual:
            lines.append("　⚠️ 兩個訊號同時觸發，比單一訊號嚴重")
    lines.append("-# 完整彙總稍後在每日戰情室（08:45）還會再列一次，這則是先讓你現在就看到。")
    msg = "\n".join(lines)
    ok = send_discord("private", msg, persona="仲達")
    print(f"[priority_alert] 持股警示 {len(by_code)} 檔　發送{'成功' if ok else '失敗'}")


def send_text(text):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=30)
    print("text:", r.status_code, "" if r.ok else r.text[:200])


def send_doc(path, caption):
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                          data={"chat_id": CHAT, "caption": caption},
                          files={"document": (os.path.basename(path), f, "text/html")}, timeout=60)
    print("doc:", r.status_code, "" if r.ok else r.text[:200])


def collect(report):
    """回傳 [(chain, market, sig, code, name, oneliner), ...]（全部，後面再判 alert）"""
    out = []
    # 美股
    raw = convert(open(report, encoding="utf-8").read())
    _, stocks = parse_report(raw)
    for sig, tk, nm, block in stocks:
        out.append((CHAIN_MAP.get(tk, "其他"), "US", sig, tk, nm, oneliner(block)))
    # 台股
    if os.path.exists(TW_JSON):
        for r in json.load(open(TW_JSON, encoding="utf-8")):
            out.append((r["chain"], "TW", r.get("emoji", "⚪"), r["code"],
                        TW_NAME.get(r["code"], r.get("name", r["code"])), r.get("oneliner", "")))
    return out


def main():
    report, html_path = sys.argv[1], sys.argv[2]
    items = collect(report)

    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            prev = {}

    # 變化才推：只在訊號「改變」時推（不再天天重複同樣的買/賣清單）
    cur, alerts = {}, []
    for chain, mkt, sig, code, name, ol in items:
        key = f"{mkt}:{code}"
        cur[key] = sig
        old = prev.get(key)
        if not old or old == sig:
            continue                       # 無前狀態 或 無變化 → 不推
        if sig in ALERT_SIGS:              # 轉成 買進/賣出（新訊號）
            reason = f"{SIG_WORD.get(old,'觀望')}→{SIG_WORD.get(sig,'')}"
        else:
            # 2026-08-27 Leo：「可以顯示 轉買進、賣出的就好」——原本「買進解除→觀望」
            # 這類降級也推，一次出一排⚪️解除訊息變成雜訊。解除不推了；
            # 訊號現況在看板頁本來就看得到，不差這一則。
            continue
        alerts.append((chain, mkt, sig, code, name, ol, reason))

    # SuperTrend 翻面（持股 + 守備清單）
    try:
        import st_alert
        flips_hold, flips_watch, _ = st_alert.detect_flips()
    except Exception as e:
        print("SuperTrend 偵測失敗:", e)
        flips_hold, flips_watch = [], []

    # 🔴 2026-09-23（Leo：「discord提醒不夠明顯」——查CEG案例發現持股訊號被埋在
    # 每天一則的大合併日報裡，沒有@提及、也要等08:45排程才發）：持股任何一個訊號
    # 觸發（SuperTrend翻空／RS60跌破），**立刻**另發一則獨立訊息到#持股密報，
    # 用🚨標記＋@Leo（觸發手機推播）。跟 daily_warroom 08:45 那則大合併日報是
    # 兩件事——這則是「現在就要看」的警示，daily_warroom 那則才是完整彙總，
    # 內容不衝突（08:27原本決定Discord只在daily_warroom發，是為了避免持股訊號
    # 重複出現；這裡不是重複同一段文字，是把「持股觸發」單獨拉出來提早發、
    # 加重要性標記，daily_warroom照舊會再完整列一次給沒看到這則的人）。
    _send_priority_alert(flips_hold)

    date = datetime.now().strftime("%Y-%m-%d")
    lines = [f"📊 <b>投資晨報 {date}</b>",
             f'📈 <a href="{PAGES_URL}">完整看板</a>（或見附件）', ""]
    has = False

    # 1) 持股動態（風險）— SuperTrend 翻面
    if flips_hold:
        has = True
        lines.append("💼 <b>持股動態</b>（你的部位 · SuperTrend）")
        for f in flips_hold:
            nm = f" {f['name']}" if f['name'] else ""
            lines.append(f"　{f['word']}　<b>{esc(f['code'])}</b>{esc(nm)}")
        lines.append("")

    # 2) 守備清單 — AI 訊號（買賣/反轉）
    if alerts:
        has = True
        lines.append("🎯 <b>守備清單 — AI 訊號</b>")
        for c in CHAIN_ORDER + ["其他"]:
            cs = [a for a in alerts if a[0] == c]
            if not cs:
                continue
            lines.append(f"{CHAIN_ICON.get(c,'📦')} <b>{esc(c)}</b>")
            for _, mkt, sig, code, name, ol, reason in cs:
                flag = "🇹🇼" if mkt == "TW" else "🇺🇸"
                lines.append(f"{sig} {flag} <b>{esc(code)}</b> {esc(name)}（{esc(reason)}）")
                if ol:
                    lines.append(f"　{esc(ol)}")
        lines.append("")

    # 3) 守備清單 — SuperTrend 翻面
    if flips_watch:
        has = True
        lines.append("📈 <b>守備清單 — SuperTrend 翻面</b>")
        for f in flips_watch:
            nm = f" {f['name']}" if f['name'] else ""
            lines.append(f"　{f['word']}　<b>{esc(f['code'])}</b>{esc(nm)}")
        lines.append("")

    if has:
        lines.append("<i>💼 持股看風險（翻空/賣訊）｜🎯 守備清單看機會（買進/翻多）</i>")
        lines.append(f'📊 <a href="{PAGES_URL}">完整看板</a>')
    else:
        lines = [f"✅ <b>投資晨報 {date}</b> 今日無訊號（持股趨勢無變化、守備清單無買賣/翻面）。",
                 f'📊 <a href="{PAGES_URL}">完整看板</a>。']
    msg = "\n".join(lines)
    send_text(msg)
    # Discord 不在這裡發（2026-08-27 Phase 2 定案）：#每日戰情 收的是 daily_warroom
    # 08:45 的合成日報（本訊息內容經由 state/st_flips_today.json 進日報②段），
    # 這裡再發會同內容出現兩次。Telegram 維持逐則即時推播。
    # 2026-08-26：拿掉 send_doc() 附檔——Leo反饋「這個會推一份html給我，但都不能點」，
    # 用 Telegram 傳原始 HTML 檔本來就只會顯示成可下載的檔案，不會渲染成網頁、
    # 裡面的連結當然點不了。上面已經改成一律附 PAGES_URL 這個可點的看板連結
    # （原本只有「無訊號」那個分支有連結，「有訊號」分支完全沒有替代方案，
    # 拿掉附檔後要是沒補這個會直接失去看板入口，不是單純刪掉就好）。

    # 2026-08-26：另存一份「這次翻面/AI訊號變化清單」給 researcher_stock.py 讀。
    # 這支腳本跑在 GitHub Actions（台灣09:00），researcher_stock.py 跑在本機排程
    # （台灣07:00，比這裡早2小時）——本機明天07:00讀到的會是「今天09:00這次」的結果，
    # 落後一天，是刻意的已知限制，不是bug（兩邊執行環境不同，要即時對齊需要更大改動）。
    os.makedirs("state", exist_ok=True)
    json.dump(cur, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump({"date": date,   # 2026-08-27 加：讓 daily_warroom 組報時能判斷資料是不是今天的
               "flips_hold": flips_hold, "flips_watch": flips_watch,
               "ai_alerts": [{"chain": c, "market": m, "sig": s, "code": code, "name": name,
                              "reason": reason}
                              for c, m, s, code, name, ol, reason in alerts]},
              open("state/st_flips_today.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"✅ 投資晨報推送完成：AI {len(alerts)}、持股翻面 {len(flips_hold)}、守備翻面 {len(flips_watch)}")


if __name__ == "__main__":
    main()
