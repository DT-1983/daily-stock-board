"""Telegram 只推「反轉/警示」（美股+台股）+ 附完整 HTML 看板。

警示 = 🔴 賣出 / 🟢 買進；反轉 = 訊號 vs 上次不同（state/signals.json）
其餘（⚪觀望）不推，完整資料看 HTML 附件。

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
PAGES_URL = "https://dt-1983.github.io/daily-stock-board/"
STATE = "state/signals.json"
TW_JSON = "tw_analysis.json"
ALERT_SIGS = {"🔴", "🟢"}
SIG_WORD = {"🔴": "賣出", "🟢": "買進", "🔵": "持有", "🟡": "觀望", "⚪": "觀望"}


def esc(s):
    return _html.escape(str(s or ""))


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
        elif old in ALERT_SIGS:            # 買/賣 訊號解除 → 轉觀望
            reason = f"{SIG_WORD.get(old,'')}解除→觀望"
        else:
            continue                       # 觀望↔其它非買賣 → 不推
        alerts.append((chain, mkt, sig, code, name, ol, reason))

    # SuperTrend 翻面（持股 + 守備清單）
    try:
        import st_alert
        flips_hold, flips_watch, _ = st_alert.detect_flips()
    except Exception as e:
        print("SuperTrend 偵測失敗:", e)
        flips_hold, flips_watch = [], []

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
    else:
        lines = [f"✅ <b>投資晨報 {date}</b> 今日無訊號（持股趨勢無變化、守備清單無買賣/翻面）。",
                 f'📊 <a href="{PAGES_URL}">完整看板</a>。']
    send_text("\n".join(lines))
    send_doc(html_path, f"{date} 產業鏈看板（美股+台股，7 鏈）")

    os.makedirs("state", exist_ok=True)
    json.dump(cur, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"✅ 投資晨報推送完成：AI {len(alerts)}、持股翻面 {len(flips_hold)}、守備翻面 {len(flips_watch)}")


if __name__ == "__main__":
    main()
