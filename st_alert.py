"""SuperTrend 翻面＋RS60 跌破偵測：持股 + 守備清單，翻面就回報。

翻面 = SuperTrend 方向 vs 上次不同（state/st_state.json）；
RS60跌破 = combo_result.json 的 rs_short 正負號 vs 上次不同（state/rs60_state.json）。
持股翻面優先（你的部位）；守備清單翻面次之（進場機會）。

⚠️ 這支不是獨立排程，是被 `alert_telegram.py` 當函式庫 import 呼叫
（`import st_alert; st_alert.detect_flips()`）——SuperTrend 翻面偵測的核心邏輯，
投資長與 Discord 日報的訊號都源自這裡。2026-08-28 檢查：docstring 原本寫「推
Telegram」，但那是舊設計，實際上 TG 推播一直是 alert_telegram.py 在做，這支
本身從沒真的送過訊息（`__main__` 只印文字）——已清掉沒用到的 TOKEN/CHAT/PAGES_URL。

🔴 2026-09-23 修（Leo 問 CEG 9/14 SuperTrend+RS60 同天轉空，Discord 有沒有推）查出
兩個真坑：
① `holdings` 原本讀專案根目錄一份 `holdings.json`——**2026-09-03 建立後從沒被任何
   程式更新過**（跟 Leo 買 CEG 同一天，純屬巧合），完全沒連到 IBKR/Firstrade 的
   即時持股，CEG 從沒在這份清單裡過。改讀 `trade_plan.load_holdings("Leo")[0]`
   （Firstrade+IBKR 的即時同步資料，跟風控母體同一份，2026-09-23 剛修過即時查詢
   那邊少傳 advisor 參數的同類問題——同一份持股資料要在多處保持一致，不能各自
   維護一份快照）。
② 只偵測 SuperTrend，完全沒有 RS(60) 跌破自身均線這個獨立的出場訊號（跟
   `paper_portfolio.py` 的「RS跌破60MA全出」規則是同一條，但那邊是模擬倉專用，
   這支持股警示原本沒有對應邏輯）。RS60 判斷**不重算**，直接讀
   `state/combo_result.json` 的 `rs_short`（跟燈號頁、風報比同一份數字來源，
   不要另外算一次——兩邊各算一次遲早會漂移，見 combo_html.py 檔頭同樣的教訓）。

用法:python -c "import st_alert; st_alert.detect_flips()"　（或直接跑本檔看偵測結果）
"""
import os
import json
import yfinance as yf
import tw_symbol
# 2026-09-02：策略層統一改用 SMA 版 ATR（與顯示層／老墨畫面一致）。
# 不統一的話會出現「網站顯示翻空、但不發翻空警示」這種前後矛盾——
# 三年回測兩版差在雜訊內（Wilder +5.83%/勝率31%、SMA +6.74%/勝率29%），
# 沒有績效理由維持兩套。
from board_html import TW_NAME
from technical_indicators import supertrend_sma as supertrend

ST_STATE = "state/st_state.json"
RS60_STATE = "state/rs60_state.json"


def _live_holdings():
    """Leo 自己操作帳戶（Firstrade+IBKR）的即時持股代號集合——不是快照檔。"""
    try:
        import trade_plan
        active, _legacy = trade_plan.load_holdings("Leo")
        return {r["ticker"] for r in active if r.get("ticker")}
    except Exception as e:                                   # noqa: BLE001
        print(f"  [st_alert] 讀即時持股失敗（改用空集合，不擋SuperTrend偵測）：{str(e)[:80]}")
        return set()


def _rs60_flips(hold_set):
    """RS60 正負號翻轉（跌破/站回自身60日均線）。只查持股，不查守備清單——
    守備清單的進場邏輯本來就用燈四（RS60乖離>+3%），不需要另一套RS警示。"""
    try:
        d = json.load(open("state/combo_result.json", encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        print(f"  [st_alert] 讀 combo_result.json 失敗（RS60偵測跳過）：{str(e)[:80]}")
        return []
    cur = {}
    for r in d.get("rows", []):
        tk, rs = r.get("ticker"), r.get("rs_short")
        if tk in hold_set and rs is not None:
            cur[tk] = 1 if rs >= 0 else -1

    prev = {}
    if os.path.exists(RS60_STATE):
        try:
            prev = json.load(open(RS60_STATE, encoding="utf-8"))
        except Exception:
            prev = {}

    flips = []
    for tk, sign in cur.items():
        old = prev.get(tk)
        if old and old != sign:
            flips.append({"code": tk, "name": TW_NAME.get(tk, ""),
                          "word": "RS60站回多方" if sign == 1 else "RS60跌破自身均線",
                          "dir": sign})

    os.makedirs("state", exist_ok=True)
    json.dump(cur, open(RS60_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return flips


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
    """偵測 SuperTrend 翻面 + 持股 RS60 跌破，更新狀態。
    回傳 (flips_hold, flips_watch, holdings_set)。
    flips 元素：{code, name, word, dir}。給 alert_telegram 合併進投資晨報。"""
    holdings = _live_holdings()
    scr = json.load(open("screen_result.json", encoding="utf-8")) if os.path.exists("screen_result.json") else {"us": {}, "tw": {}}
    us_watch = sorted({x["code"] for l in scr["us"].values() for x in l})
    tw_watch = sorted({x["code"] for l in scr["tw"].values() for x in l})

    us_syms = sorted(set(holdings) | set(us_watch))
    tw_syms = sorted(set(tw_watch))
    dirs = {}
    dirs.update(batch_dirs(us_syms))
    # 2026-08-31 修：原本一律 `c + ".TW"`，上櫃股全部抓不到 → 被 batch_dirs 的
    # except 吞掉，結果不是報錯而是「這檔今天沒有翻面」。實測當時 st_state.json
    # 裡上市 31/31 有狀態、上櫃 0/13，等於守備清單三成的股票從來沒被偵測過。
    dirs.update(tw_symbol.batch_with_otc(tw_syms, batch_dirs))

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
                    "word": "🔴→🟢 翻多" if d == 1 else "🟢→🔴 翻空", "dir": d,
                    "sig": "st"}
            (flips_hold if sym in hold_set else flips_watch).append(item)

    os.makedirs("state", exist_ok=True)
    json.dump(dirs, open(ST_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    for f in _rs60_flips(hold_set):
        f["sig"] = "rs60"
        flips_hold.append(f)

    return flips_hold, flips_watch, hold_set


if __name__ == "__main__":
    h, w, _ = detect_flips()
    print(f"翻面：持股 {len(h)}、守備 {len(w)}")
