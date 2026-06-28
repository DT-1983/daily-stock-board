"""每週買進機會週報：巴菲特價值到價 + 雙確認（守備清單∩到價）。

雙確認 = 既在產業鏈守備清單(題材趨勢+籌碼好)、現價又 ≤ 巴菲特俗價(價值便宜) = 稀有寶石。
用法:python buy_digest.py　需 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
"""
import os
import json
import requests
import yfinance as yf

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
PAGES_URL = "https://dt-1983.github.io/daily-stock-board/"


def send(text):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=30)
    print("send:", r.status_code, "" if r.ok else r.text[:200])


def main():
    if not os.path.exists("buffett_watch.json"):
        print("無 buffett_watch.json，跳過")
        return
    wl = json.load(open("buffett_watch.json", encoding="utf-8"))
    scr = json.load(open("screen_result.json", encoding="utf-8")) if os.path.exists("screen_result.json") else {"us": {}}
    us_watch = set(x["code"] for l in scr["us"].values() for x in l)

    tickers = list(wl.keys())
    data = yf.download(tickers, period="5d", progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    buys = []   # (ticker, cur, cheap, 折價%, 是否守備清單)
    for tk in tickers:
        try:
            cur = float(data[tk]["Close"].dropna().iloc[-1])
            cheap = wl[tk].get("cheap")
            if cheap and cur <= cheap:
                buys.append((tk, cur, cheap, (cheap - cur) / cheap * 100, tk in us_watch))
        except Exception:
            pass
    buys.sort(key=lambda x: -x[3])   # 折價大的在前
    double = [b for b in buys if b[4]]

    lines = ["💰 <b>本週買進機會（巴菲特價值法）</b>", ""]
    if double:
        lines.append("💎 <b>雙確認（題材趨勢＋價值便宜）</b>")
        for tk, cur, cheap, dis, _ in double:
            lines.append(f"　<b>{tk}</b>　現價 {cur:.1f} ≤ 俗價 {cheap:.1f}（折 {dis:.0f}%）")
        lines.append("")
    if buys:
        lines.append(f"🏛️ <b>到俗價清單</b>（{len(buys)} 檔，現價 ≤ 俗價）")
        for tk, cur, cheap, dis, dbl in buys[:15]:
            star = "💎 " if dbl else ""
            lines.append(f"　{star}<b>{tk}</b>　{cur:.1f} / 俗 {cheap:.1f}（折 {dis:.0f}%）")
        if len(buys) > 15:
            lines.append(f"　…還有 {len(buys)-15} 檔")
    else:
        lines.append("本週<b>無到俗價</b>標的（市場不夠便宜，耐心等）")
    lines.append("")
    lines.append("<i>💎=同時在產業鏈守備清單(趨勢好)，雙重確認最強</i>")
    lines.append(f'📊 <a href="{PAGES_URL}">產業鏈看板</a>')
    send("\n".join(lines))
    print(f"✅ 買進機會：到價 {len(buys)}、雙確認 {len(double)}")


if __name__ == "__main__":
    main()
