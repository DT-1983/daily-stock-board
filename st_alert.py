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
    """Leo 的持股代號集合。

    🔴 2026-09-23：這支是被 `alert_telegram.py` 從 **GitHub Actions（ubuntu-latest
    雲端）** 呼叫的，不是本機——`trade_plan.py`（讀 `C:\\Users\\...\\holdings.json`
    這種本機絕對路徑）在雲端環境**沒有這個檔案、甚至這支程式本身被 gitignore，
    import 就會直接失敗**。第一版改讀 `trade_plan.load_holdings()` 在本機測試
    通過，但沒意識到正式排程根本不在本機跑——等於重蹈原本那份 2026-09-03 靜態
    `holdings.json` 的同一種「跟真實環境脫節」錯誤，只是換了一種脫節方式。

    改讀 `state/held_universe.json`——這是 repo 追蹤檔（不是 gitignore），
    由本機排程 `researcher_holdings.py`（06:00，board_analyze_daily.cmd）算好
    `investment_chief.held_universe()` 之後存下、commit、push；GitHub Actions
    08:19 跑這支的時候該檔已經在 checkout 出來的 repo 裡，跟 `combo_result.json`／
    `screen_result.json` 走的是同一個「本機算、雲端讀」模式。
    本機測試（trade_plan.py 讀得到）時如果這份 repo 檔還沒 commit，退回直接
    呼叫 `trade_plan.load_holdings()`，維持本機可測試性。
    """
    try:
        d = json.load(open("state/held_universe.json", encoding="utf-8"))
        tickers = d.get("tickers") or []
        if tickers:
            return set(tickers)
    except Exception:
        pass
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
    # 🔴 2026-09-29：持股代號是「2454.TW」，燈號掃描的代號是裸「2454」——原本 `tk in hold_set`
    # 直接比對，**台股持股從沒對上過**（rs60_state 裡台股持股全部是 None），台股 RS60 跌破從沒警示過。
    # 兩邊都去掉 .TW/.TWO 再比，狀態檔的鍵沿用持股那邊的寫法。
    def _n(t):
        t = str(t or "").upper()
        return t[:-4] if t.endswith(".TWO") else (t[:-3] if t.endswith(".TW") else t)
    hold_by_norm = {_n(t): t for t in hold_set}
    cur = {}
    for r in d.get("rows", []):
        tk, rs = hold_by_norm.get(_n(r.get("ticker"))), r.get("rs_short")
        if tk and rs is not None:
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


def _dirs_dated(yf_syms):
    """同 batch_dirs，另外回最後一根 K 棒日期：{yf_sym: (dir, 'YYYY-MM-DD')}。"""
    out = {}
    if not yf_syms:
        return out
    data = yf.download(yf_syms, period="3mo", progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    for s in yf_syms:
        try:
            df = (data[s] if len(yf_syms) > 1 else data).dropna()
            d = cur_dir(df)
            if d and len(df):
                out[s] = (d, str(df.index[-1].date()))
        except Exception:
            pass
    return out


def detect_close(market, today):
    """收盤後用**最新收盤**偵測急件（本機排程：台股平日 14:05、美股週二～六 05:35），**不寫任何狀態檔**
    （狀態仍由 08:19 的 detect_flips() 更新，兩邊比的是同一份「上一次」）。
    2026-09-29 Leo：「台股 telegram 早點做」「美股也可以提早嗎? 同一個邏輯」。
    - 台股：基準日＝今天（台灣日期）；美股：基準日＝這批資料最新的交易日（台灣清晨看到的是美國前一個交易日），
      且不能早於 4 天前。
    回 (flips_hold, flips_watch, fresh_ratio, bar_date)；fresh_ratio＝拿到基準日 K 棒的比例（休市或資料還沒到就很低）。"""
    import datetime as _d
    holdings = _live_holdings()
    is_tw = market == "tw"
    hold = sorted(t for t in holdings if str(t)[:1].isdigit() == is_tw)
    scr = json.load(open("screen_result.json", encoding="utf-8")) if os.path.exists("screen_result.json") else {}
    watch = sorted({x["code"] for l in (scr.get(market) or {}).values() for x in l})
    got = dict(_dirs_dated(hold))                                    # 持股：鍵同 st_state（台股含後綴）
    if is_tw:
        got.update(tw_symbol.batch_with_otc(watch, _dirs_dated))     # 台股守備：裸代號（同 st_state）
    else:
        got.update(_dirs_dated([w for w in watch if w not in got]))
    if not got:
        return [], [], 0.0, None
    if is_tw:
        bar_date = today
    else:
        bar_date = max(v[1] for v in got.values())
        if bar_date < (_d.date.fromisoformat(today) - _d.timedelta(days=4)).isoformat():
            return [], [], 0.0, bar_date
    fresh = {k: v for k, v in got.items() if v[1] == bar_date}
    ratio = len(fresh) / len(got)
    prev = json.load(open(ST_STATE, encoding="utf-8")) if os.path.exists(ST_STATE) else {}
    hold_set = set(hold)
    flips_hold, flips_watch = [], []
    for sym, (d, _dt) in fresh.items():
        old = prev.get(sym)
        if old and old != d:
            item = {"code": sym, "name": TW_NAME.get(sym, "") or TW_NAME.get(str(sym).split(".")[0], ""),
                    "word": "🔴→🟢 翻多" if d == 1 else "🟢→🔴 翻空", "dir": d, "sig": "st"}
            (flips_hold if sym in hold_set else flips_watch).append(item)
    # RS60：用跟燈號掃描同一支 scan_one 以最新收盤重算 rs_short，正負號跟 rs60_state（上一次）比
    bench = "^TWII" if is_tw else "^GSPC"
    try:
        import combo_scan as CS
        import price_store
        px = price_store.get_ohlc(hold + [bench], period="3y", force=True)
        b = px.get(bench)
        prev_rs = json.load(open(RS60_STATE, encoding="utf-8")) if os.path.exists(RS60_STATE) else {}
        for sym in hold:
            df = px.get(sym)
            if df is None or df.empty or b is None or str(df.index[-1].date()) != bar_date:
                continue
            row = CS.scan_one(sym.split(".")[0] if is_tw else sym, sym, df, b["Close"].dropna().tolist())
            rs = (row or {}).get("rs_short")
            old = prev_rs.get(sym)
            if rs is None or not old:
                continue
            sign = 1 if rs >= 0 else -1
            if sign != old:
                flips_hold.append({"code": sym, "name": TW_NAME.get(sym.split(".")[0], ""),
                                   "word": "RS60站回多方" if sign == 1 else "RS60跌破自身均線",
                                   "dir": sign, "sig": "rs60"})
    except Exception as e:                                   # noqa: BLE001
        print(f"  [st_alert] {market} RS60 收盤偵測失敗（SuperTrend 照常）：{str(e)[:100]}")
    return flips_hold, flips_watch, ratio, bar_date


if __name__ == "__main__":
    h, w, _ = detect_flips()
    print(f"翻面：持股 {len(h)}、守備 {len(w)}")
