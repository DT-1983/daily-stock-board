"""SuperTrend 翻面偵測：持股 + 守備清單，翻面（綠↔紅）就回報。

翻面 = SuperTrend 方向 vs 上次不同（state/st_state.json）。
持股翻面優先（你的部位）；守備清單翻面次之（進場機會）。

⚠️ 這支不是獨立排程，是被 `alert_telegram.py` 當函式庫 import 呼叫
（`import st_alert; st_alert.detect_flips()`）——SuperTrend 翻面偵測的核心邏輯，
投資長與 Discord 日報的訊號都源自這裡。2026-08-28 檢查：docstring 原本寫「推
Telegram」，但那是舊設計，實際上 TG 推播一直是 alert_telegram.py 在做，這支
本身從沒真的送過訊息（`__main__` 只印文字）——已清掉沒用到的 TOKEN/CHAT/PAGES_URL。

用法:python -c "import st_alert; st_alert.detect_flips()"　（或直接跑本檔看偵測結果）
"""
import os
import json
import yfinance as yf
from board_html import supertrend, TW_NAME

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


def detect_flips():
    """偵測 SuperTrend 翻面，更新狀態。回傳 (flips_hold, flips_watch, holdings_set)。
    flips 元素：{code, name, word, dir}。給 alert_telegram 合併進投資晨報。"""
    holdings = json.load(open("holdings.json", encoding="utf-8")) if os.path.exists("holdings.json") else []
    scr = json.load(open("screen_result.json", encoding="utf-8")) if os.path.exists("screen_result.json") else {"us": {}, "tw": {}}
    us_watch = sorted({x["code"] for l in scr["us"].values() for x in l})
    tw_watch = sorted({x["code"] for l in scr["tw"].values() for x in l})

    us_syms = sorted(set(holdings) | set(us_watch))
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
            item = {"code": sym, "name": TW_NAME.get(sym, ""),
                    "word": "🔴→🟢 翻多" if d == 1 else "🟢→🔴 翻空", "dir": d}
            (flips_hold if sym in hold_set else flips_watch).append(item)

    os.makedirs("state", exist_ok=True)
    json.dump(dirs, open(ST_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return flips_hold, flips_watch, hold_set


if __name__ == "__main__":
    h, w, _ = detect_flips()
    print(f"翻面：持股 {len(h)}、守備 {len(w)}")
