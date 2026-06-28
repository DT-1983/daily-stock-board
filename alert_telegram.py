"""Telegram 只推「反轉/警示」的產業鏈 + 其下個股,並附完整 HTML 看板。

警示 = 🔴 賣出 / 🟢 買進（actionable）
反轉 = 訊號 vs 上次不同（需 state/signals.json）
其餘（⚪觀望/🟡）不推，完整資料看 HTML 附件。

用法:python alert_telegram.py reports/report_YYYYMMDD.md board.html
"""
import sys
import os
import json
import html as _html
from datetime import datetime
import requests
from board_html import parse_report, oneliner, score, CHAIN_MAP, CHAIN_ICON, CHAIN_ORDER
from tw_report import convert

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
STATE = "state/signals.json"
ALERT_SIGS = {"🔴", "🟢"}          # 警示:賣出 / 買進
SIG_WORD = {"🔴": "賣出", "🟢": "買進", "🔵": "持有", "🟡": "觀望", "⚪": "觀望"}


def esc(s):
    return _html.escape(s or "")


def send_text(text):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=30)
    print("text:", r.status_code, "" if r.ok else r.text[:200])


def send_doc(path, caption):
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                          data={"chat_id": CHAT, "caption": caption},
                          files={"document": (os.path.basename(path), f, "text/html")},
                          timeout=60)
    print("doc:", r.status_code, "" if r.ok else r.text[:200])


def main():
    report, html_path = sys.argv[1], sys.argv[2]
    raw = convert(open(report, encoding="utf-8").read())
    _, stocks = parse_report(raw)

    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            prev = {}

    cur, alerts = {}, []
    for sig, tk, nm, block in stocks:
        cur[tk] = sig
        reasons = []
        if sig in ALERT_SIGS:
            reasons.append("警示")
        if prev.get(tk) and prev[tk] != sig:
            reasons.append(f"反轉 {prev[tk]}{SIG_WORD.get(prev[tk],'')}→{sig}{SIG_WORD.get(sig,'')}")
        if reasons:
            alerts.append((CHAIN_MAP.get(tk, "其他"), sig, tk, nm, oneliner(block), " / ".join(reasons)))

    date = datetime.now().strftime("%Y-%m-%d")

    if alerts:
        lines = [f"🔔 <b>美股訊號提醒 {date}</b>", f"<i>{len(alerts)} 檔反轉/警示，完整看板見附件</i>", ""]
        for c in CHAIN_ORDER + ["其他"]:
            cs = [a for a in alerts if a[0] == c]
            if not cs:
                continue
            lines.append(f"{CHAIN_ICON.get(c,'📦')} <b>{esc(c)}</b>")
            for _, sig, tk, nm, ol, reason in cs:
                lines.append(f"{sig} <b>{esc(tk)}</b> {esc(nm)}（{esc(reason)}）")
                if ol:
                    lines.append(f"　{esc(ol)}")
            lines.append("")
        send_text("\n".join(lines))
    else:
        send_text(f"✅ <b>{date}</b> 今日無反轉/警示。完整看板見附件。")

    send_doc(html_path, f"{date} 美股完整看板（7 鏈）")

    os.makedirs("state", exist_ok=True)
    json.dump(cur, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"✅ 推送完成，alerts={len(alerts)}")


if __name__ == "__main__":
    main()
