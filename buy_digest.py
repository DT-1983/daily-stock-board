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


DECLINE_RATIO = 0.90   # forward/trailing < 0.9 → EPS 衰退（俗價是用過去算的，未來會掉）
DE_HIGH = 250          # 負債權益比 > 250% → 高槓桿（ROE 被槓桿灌水、俗價不可信）


def quality_check(tk):
    """回傳 (是否疑似陷阱, 標籤list, fwd_ratio, de)。俗價=trailing×12 只回頭看，
    這裡用 forward EPS 和負債照妖：抓「便宜是有理由的便宜」。"""
    tags = []
    try:
        i = yf.Ticker(tk).info
        te, fe, de = i.get("trailingEps"), i.get("forwardEps"), i.get("debtToEquity")
        ratio = (fe / te) if (te and fe and te > 0) else None
        if ratio is not None and ratio < DECLINE_RATIO:
            tags.append(f"EPS估降{(1-ratio)*100:.0f}%")
        if de is not None and de > DE_HIGH:
            tags.append(f"高負債{de:.0f}%")
        return (len(tags) > 0, tags, ratio, de)
    except Exception:
        return (False, [], None, None)   # 抓不到資料 → 不擋，但也不背書


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
    cand = []   # 先抓現價 ≤ 俗價 的候選
    for tk in tickers:
        try:
            cur = float(data[tk]["Close"].dropna().iloc[-1])
            cheap = wl[tk].get("cheap")
            if cheap and cur <= cheap:
                cand.append((tk, cur, cheap, (cheap - cur) / cheap * 100, tk in us_watch))
        except Exception:
            pass
    cand.sort(key=lambda x: -x[3])   # 折價大的在前

    # 只對候選跑體質檢查（≤幾十檔，省 API）
    clean, traps = [], []
    for tk, cur, cheap, dis, dbl in cand:
        is_trap, tags, ratio, de = quality_check(tk)
        row = (tk, cur, cheap, dis, dbl, tags)
        (traps if is_trap else clean).append(row)

    double = [r for r in clean if r[4]]   # 雙確認只取「體質過關」的

    lines = ["💰 <b>本週買進機會（巴菲特價值法）</b>", ""]
    if double:
        lines.append("💎 <b>雙確認（題材趨勢＋價值便宜＋體質過關）</b>")
        for tk, cur, cheap, dis, _, _ in double:
            lines.append(f"　<b>{tk}</b>　現價 {cur:.1f} ≤ 俗價 {cheap:.1f}（折 {dis:.0f}%）")
        lines.append("")
    if clean:
        lines.append(f"✅ <b>體質過關到俗價清單</b>（{len(clean)} 檔，EPS 不衰退＋負債合理）")
        for tk, cur, cheap, dis, dbl, _ in clean[:15]:
            star = "💎 " if dbl else ""
            lines.append(f"　{star}<b>{tk}</b>　{cur:.1f} / 俗 {cheap:.1f}（折 {dis:.0f}%）")
        if len(clean) > 15:
            lines.append(f"　…還有 {len(clean)-15} 檔")
        lines.append("")
    else:
        lines.append("✅ 本週<b>無體質過關</b>的到俗價標的（耐心等）")
        lines.append("")
    if traps:
        lines.append(f"⚠️ <b>便宜但有疑慮</b>（{len(traps)} 檔 · 俗價是用過去 EPS 算，未來恐縮水）")
        for tk, cur, cheap, dis, _, tags in traps[:10]:
            tag = "、".join(tags)
            lines.append(f"　<b>{tk}</b>　{cur:.1f} / 俗 {cheap:.1f}（折 {dis:.0f}%）<i>{tag}</i>")
        if len(traps) > 10:
            lines.append(f"　…還有 {len(traps)-10} 檔")
        lines.append("")
    lines.append("<i>💎=同時在守備清單(趨勢好)，最強｜⚠️=價值陷阱嫌疑(便宜有理由)，別追</i>")
    lines.append(f'📊 <a href="{PAGES_URL}">產業鏈看板</a>')
    send("\n".join(lines))
    print(f"✅ 到俗價 {len(cand)}：體質過關 {len(clean)}、疑似陷阱 {len(traps)}、雙確認 {len(double)}")


if __name__ == "__main__":
    main()
