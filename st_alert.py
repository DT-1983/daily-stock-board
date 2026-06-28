"""SuperTrend 翻面警示：監控 持股 + 守備清單，翻面（綠↔紅）才推 Telegram。

翻面 = SuperTrend 方向 vs 上次不同（state/st_state.json）。
持股翻面優先（你的部位）；守備清單翻面次之（進場機會）。
用法:python st_alert.py
"""
import os
import json
import yfinance as yf
from board_html import supertrend, TW_NAME

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
PAGES_URL = "https://dt-1983.github.io/daily-stock-board/"
ST_STATE = "state/st_state.json"


def cur_dir(df):
    try:
        h = df.dropna()
        st = supertrend(h["High"].round(2).tolist(), h["Low"].round(2).tolist(),
                        h["Close"].round(2).tolist())
        if not st:
            return None
        d = [x for x in st["dir"] if x]
        return d[-1] if d else None
    except Exception:
        return None


def batch_dirs(yf_syms):
    """回傳 {yf_sym: dir}"""
    out = {}
    if not yf_syms:
        return out
    data = yf.download(yf_syms, period="3mo", progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    for s in yf_syms:
        try:
            df = data[s] if len(yf_syms) > 1 else data
            d = cur_dir(df)
            if d:
                out[s] = d
        except Exception:
            pass
    return out


def main():
    # 監控宇宙
    holdings = json.load(open("holdings.json", encoding="utf-8")) if os.path.exists("holdings.json") else []
    scr = json.load(open("screen_result.json", encoding="utf-8"))
    us_watch = sorted({x["code"] for l in scr["us"].values() for x in l})
    tw_watch = sorted({x["code"] for l in scr["tw"].values() for x in l})

    us_syms = sorted(set(holdings) | set(us_watch))     # 持股都美股
    tw_syms = sorted(set(tw_watch))

    dirs = {}
    dirs.update(batch_dirs(us_syms))
    dirs.update({k.replace(".TW", ""): v for k, v in batch_dirs([c + ".TW" for c in tw_syms]).items()})

    prev = {}
    if os.path.exists(ST_STATE):
        try:
            prev = json.load(open(ST_STATE, encoding="utf-8"))
        except Exception:
            prev = {}

    hold_set = set(holdings)
    flips_hold, flips_watch = [], []
    for sym, d in dirs.items():
        old = prev.get(sym)
        if old and old != d:
            word = "🔴→🟢 翻多" if d == 1 else "🟢→🔴 翻空"
            name = TW_NAME.get(sym, "")
            label = f"{sym}{(' '+name) if name else ''}"
            (flips_hold if sym in hold_set else flips_watch).append((label, word))

    if flips_hold or flips_watch:
        lines = ["📈 <b>SuperTrend 趨勢翻面</b>", ""]
        if flips_hold:
            lines.append("💼 <b>你的持股</b>")
            for lb, w in flips_hold:
                lines.append(f"　{w}　<b>{lb}</b>")
            lines.append("")
        if flips_watch:
            lines.append("🎯 <b>守備清單</b>")
            for lb, w in flips_watch:
                lines.append(f"　{w}　<b>{lb}</b>")
            lines.append("")
        lines.append(f'📊 <a href="{PAGES_URL}">看走勢圖</a>')
        import requests
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": "\n".join(lines),
                            "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30)
        print(f"推送翻面：持股 {len(flips_hold)}、守備 {len(flips_watch)}")
    else:
        print("無翻面，不推")

    os.makedirs("state", exist_ok=True)
    json.dump(dirs, open(ST_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"狀態已存 {len(dirs)} 檔")


if __name__ == "__main__":
    main()
