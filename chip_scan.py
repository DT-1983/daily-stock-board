# -*- coding: utf-8 -*-
"""全市場籌碼異常掃描（2026-08-28）——三大法人買賣超，上市＋上櫃全掃。

**為什麼做**：Leo 研究 tide-tw.app 後指定學習。我們現有的籌碼運用只在
「守備清單裡的股票」（screen.py 的三因子之一、tw_analyze.py 餵進 AI prompt），
等於清單外的股票永遠看不到。這支反過來——**先全市場掃異常，可能比現有邏輯更早
抓到還沒被納入清單的轉強股**。

資料源：證交所 T86（上市，1,079 檔普通股）+ 櫃買 dailyTrade（上櫃），
兩個都是官方公開 API、免登入免 key、零成本。
⚠️ FinMind 的同一份資料**免費版不給全市場查詢**（只能逐檔，實測回
「Your level is register」），所以走官方 API 不走 FinMind。

交叉驗證（2026-08-28）：本模組算出「2303 聯電」買超第一名，跟 tide-tw.app 當天
標記的「異常大買」吻合。

三種訊號（跟 tide 一致，但門檻是我們自己用實測分布訂的，見 THRESHOLDS）：
  異常大買/大賣：當日買賣超金額 vs 該股近 20 日的平均絕對值
  法人連買/連賣：連續 N 日同方向

用法:
    python chip_scan.py              # 掃今天，寫 state/chip_events.json
    python chip_scan.py --date 20260828
    python chip_scan.py --backfill 25   # 補歷史（連買連賣需要歷史才算得出來）
"""
import os
import sys
import json
import time
import argparse
import datetime as dt

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HIST_PATH = "state/chip_history.json"     # {date: {code: 三大法人買賣超股數}}
OUT_PATH = "state/chip_events.json"
NAMES_PATH = "state/chip_names.json"      # {code: name}
# 2026-09-17（Leo 對標老墨「零式系統」逐字稿：三大法人要拆開看，他個人特別偏好
# 投信單獨的訊號，理由是投信慢慢吃股份的動機跟外資/自營不一樣，合計會稀釋訊號）。
# 用**獨立的一份歷史檔＋一套偵測函式**，不去動 HIST_PATH／detect()／calibrate()——
# 那套三大法人合計的異常/連買連賣邏輯已經校準過、正常運作，沒有理由冒風險去改
# 它的資料結構，投信單獨判斷用同一套「跟自己近20日均值比」方法論，接到平行的
# 一份檔案上就好。
HIST_TRUST_PATH = "state/chip_history_trust.json"   # {date: {code: 投信買賣超股數}}
OUT_TRUST_PATH = "state/chip_events_trust.json"
# 2026-09-18：投信「占股本比」——老墨逐字稿講的第二種算法（占股本比 vs 占成交量比，
# 他個人偏好占股本比）。股本很少變（只有增減資才會動），90天快取夠用；
# 只在「已經被偵測出事件」的30-40檔上查，不是對全市場~1900檔都查，
# 不會拖慢每日批次（見 shares_outstanding() 的說明）。
SHARES_PATH = "state/shares_outstanding.json"       # {code: {shares, asof}}
SHARES_CACHE_DAYS = 90
_RECENT_FLOW_CACHE = None    # recent_flow() 的行程內快取，見該函式說明

TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"

# 門檻：用實測分布校準（見 calibrate()），不是憑感覺設的。
# 門檻校準（2026-08-28 實測 304 檔分布，不是憑感覺設）：
#   第50百分位 1.46x｜第75 3.04x｜第90 4.73x｜第95 5.88x｜第99 10.58x
#   2.0x→39.5%觸發、3.0x→25.3%、4.0x→15.5%、5.0x→9.2%
# 取 5.0x（≈第92百分位，約9%觸發）。第一版設 3.0x 會讓 1/4 的股票都算「異常」，
# 那就不叫異常了——跟今天 base_rate 犯的同一個錯（門檻太寬沒鑑別度），
# 這次先跑 calibrate() 看分布再訂。
ANOMALY_MULT = 5.0        # 當日 |買賣超| > 近20日平均絕對值 × 這個倍數 → 異常
DAILY_LOOKBACK = 5      # 每日跑往回補幾個日曆日（涵蓋週末+連假）
MIN_HISTORY = 10          # 少於這麼多天歷史就不判異常（算不出穩定的基準）
# 連續天數門檻同樣用實測分布訂（2026-08-28）：
#   連買 ≥3天 60檔、≥4天 30檔、≥5天 13檔｜連賣 ≥3天 45檔、≥4天 30檔、≥5天 18檔
# 原本抄 tide 的「連買5/連賣3」，實測發現連賣3天會出45檔（比連買5天的13檔多3倍），
# 兩邊數量差太多會讓「連賣」洗版蓋掉「連買」。統一5天，兩邊各13/18檔量級相當。
STREAK_BUY = 5            # 連買幾天算訊號
STREAK_SELL = 5           # 連賣幾天算訊號
MIN_SHARES = 500_000      # 買賣超低於這個股數不看（雜訊，小型股單日幾張也會超標）


def _num(s):
    try:
        return int(str(s).replace(",", "").strip())
    except Exception:
        return None


def fetch_twse(date_str):
    """證交所 T86。date_str: YYYYMMDD。回 {code: (name, 三大法人合計, 投信買賣超)}。

    2026-09-17：欄位順序用 6488 環球晶當天資料逐欄跟 FinMind
    TaiwanStockInstitutionalInvestorsBuySell 交叉核對過（Investment_Trust
    buy/sell 完全對上 row[8]/row[9]），確認 row[10]＝投信買賣超股數：
    0代號 1名稱 2-4外陸資(不含自營) 5-7外資自營商 8-10投信 11自營合計
    12-14自營自行 15-17自營避險 18三大法人合計。
    """
    try:
        r = requests.get(TWSE_URL, params={"date": date_str, "selectType": "ALL",
                                           "response": "json"}, timeout=30)
        if "json" not in (r.headers.get("content-type") or ""):
            return None            # 被限流（同 market_thermometer 的 307 狀況）
        j = r.json()
    except Exception:
        return None
    if j.get("stat") != "OK":
        return {}                  # 非交易日：正常回應但沒資料
    out = {}
    for row in j.get("data") or []:
        code = str(row[0]).strip()
        if len(code) != 4 or not code.isdigit():
            continue               # 只留4位數普通股，濾掉 ETF/權證/特別股
        v = _num(row[18])          # 三大法人買賣超股數（最後一欄）
        trust = _num(row[10])      # 投信買賣超股數
        if v is not None:
            out[code] = (str(row[1]).strip(), v, trust)
    return out


def fetch_tpex(date_str):
    """櫃買 dailyTrade。回 {code: (name, 三大法人合計, 投信買賣超)}。

    2026-09-17：欄位順序同樣用 6488 環球晶交叉核對過（Investment_Trust
    buy=42600/sell=154000 對上 row[11]/row[12]），確認 row[13]＝投信買賣超股數：
    0代號 1名稱 2-4外資(不含自營) 5-7外資自營商 8-10外資合計 11-13投信
    14-16自營自行 17-19自營避險 20-22自營合計 23三大法人合計。
    """
    d = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
    try:
        r = requests.get(TPEX_URL, params={"type": "Daily", "sect": "AL", "date": d,
                                           "id": "", "response": "json"}, timeout=30)
        if "json" not in (r.headers.get("content-type") or ""):
            return None
        j = r.json()
    except Exception:
        return None
    tables = j.get("tables") or []
    if not tables or not tables[0].get("data"):
        return {}
    out = {}
    for row in tables[0]["data"]:
        code = str(row[0]).strip()
        if len(code) != 4 or not code.isdigit():
            continue
        v = _num(row[23])          # 三大法人買賣超股數合計（最後一欄）
        trust = _num(row[13])      # 投信買賣超股數
        if v is not None:
            out[code] = (str(row[1]).strip(), v, trust)
    return out


def fetch_day(date_str):
    """上市＋上櫃合併。回 (資料dict, 是否成功)。非交易日回 ({}, True)。"""
    tw = fetch_twse(date_str)
    time.sleep(0.4)
    tp = fetch_tpex(date_str)
    if tw is None and tp is None:
        return {}, False           # 兩邊都被擋 → 這天沒抓到，不要記成「沒資料」
    # 2026-09-01：原本只要有一邊成功就當整天完成存進歷史。實測 8/31 就這樣只存到
    # 上市 1,085 檔（櫃買當下 SSL 失敗），少掉 782 檔上櫃股——而歷史一旦寫入就
    # 不再重抓，那天的上櫃籌碼永遠是缺的。半套資料比沒有更糟：它會讓「異常」
    # 的分母（近20日平均）失真，卻看不出來。
    # 改成任一邊失敗就整天判定未完成（ok=False），下次重抓。
    # 非交易日兩邊都會回**空 dict 而不是 None**，所以不受影響。
    if tw is None or tp is None:
        which = "證交所" if tw is None else "櫃買"
        print(f"  {date_str} {which}抓取失敗，整天不寫入（避免存半套資料），下次重抓")
        return {}, False
    merged = {}
    merged.update(tw)
    merged.update(tp)
    return merged, True


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    os.makedirs("state", exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def collect(dates):
    """抓多天寫進歷史。回實際新增的天數。

    2026-09-17：同一次抓回來的資料，除了原本的三大法人合計（HIST_PATH），
    也順手把投信單獨的買賣超存進 HIST_TRUST_PATH——反正 fetch_twse/fetch_tpex
    已經解析出這個數字了，不多打一次 API，只是多存一份。"""
    hist = _load(HIST_PATH, {})
    hist_trust = _load(HIST_TRUST_PATH, {})
    names = _load(NAMES_PATH, {})
    added = 0
    today = dt.date.today()
    for d in dates:
        key = d.isoformat()
        if hist.get(key):
            continue               # 已經有**實際資料**才跳過（空的要留著重試，見下）
        data, ok = fetch_day(d.strftime("%Y%m%d"))
        if not ok:
            print(f"  {key} 抓取被擋，跳過（下次會再試）")
            continue
        if not data:
            # 2026-09-01 修：原本無條件 `hist[key] = {}` 當成非交易日永久記下來。
            # 但**「當天資料還沒公布」跟「非交易日」都回空**——而批次在 08:45 跑、
            # 證交所要收盤後才發當日籌碼，所以每天抓「今天」必然是空的，
            # 然後被永久標記成沒資料、再也不重抓。
            # 實測後果：chip_scan 8/29 上線後**每日收集從來沒成功過一次**，
            # 8/31 有資料卻整天被跳過，events 一直停在 8/28（8/24~28 是當初
            # --backfill 補的），而它每天照印「✅ N 筆籌碼異常」exit 0。
            # 修法：只有**過去的日期**才敢認定是非交易日；今天/未來一律不寫，
            # 留給明天重抓。同 [[cache_negative_result_bug]]。
            if d < today:
                hist[key] = {}     # 過去的日期還是空 → 真的是非交易日/休市
                hist_trust[key] = {}
            else:
                print(f"  {key} 尚未公布（當日資料收盤後才有），不寫入，明天重抓")
            continue
        hist[key] = {c: v for c, (n, v, t) in data.items()}
        hist_trust[key] = {c: t for c, (n, v, t) in data.items() if t is not None}
        names.update({c: n for c, (n, v, t) in data.items()})
        added += 1
        print(f"  {key} 取得 {len(data)} 檔")
    _save(HIST_PATH, hist)
    _save(HIST_TRUST_PATH, hist_trust)
    _save(NAMES_PATH, names)
    return added


def _detect_from(hist_path, who, date_str=None):
    """對最新一天算異常＋連買連賣。回 events list。

    2026-09-17 從 detect() 抽出來，讓「三大法人合計」跟「投信單獨」共用同一套
    方法論（跟自己近20日均值比、連續天數）——差別只在讀哪份歷史檔、事件文字
    要不要標明「投信」，數學邏輯完全一樣，不要維護兩份幾乎一樣的程式碼。
    `who`：事件文字前綴，例如「」（三大法人，維持原文字不變）或「投信」。
    """
    hist = _load(hist_path, {})
    names = _load(NAMES_PATH, {})
    days = sorted(d for d in hist if hist[d])      # 只看有資料的交易日
    if not days:
        return []
    today = date_str or days[-1]
    if today not in hist or not hist[today]:
        return []
    idx = days.index(today)
    past = days[max(0, idx - 20):idx]              # 今天之前的 20 個交易日

    events = []
    for code, v in hist[today].items():
        if v is None or abs(v) < MIN_SHARES:
            continue
        nm = names.get(code, code)
        # ① 異常：跟自己近20日的平均絕對值比（每檔自己的基準，不用全市場統一門檻——
        #    跟 base_rate 同一個思路：大型股天天幾萬張，小型股幾百張就算大）
        vals = [abs(hist[d][code]) for d in past if hist[d].get(code) is not None]
        if len(vals) >= MIN_HISTORY:
            avg = sum(vals) / len(vals)
            if avg > 0 and abs(v) > avg * ANOMALY_MULT:
                events.append({"code": code, "name": nm,
                               "event": f"{who}異常大買" if v > 0 else f"{who}異常大賣",
                               "kind": "anomaly", "shares": v,
                               "vs_avg": round(abs(v) / avg, 1)})
        # ② 連買/連賣：從今天往回數同方向的連續天數
        streak = 0
        sign = 1 if v > 0 else -1
        for d in reversed(days[:idx + 1]):
            x = hist[d].get(code)
            if x is None or (1 if x > 0 else -1) != sign or x == 0:
                break
            streak += 1
        need = STREAK_BUY if sign > 0 else STREAK_SELL
        if streak >= need:
            events.append({"code": code, "name": nm,
                           "event": f"{who}連{'買' if sign > 0 else '賣'} {streak} 天",
                           "kind": "streak", "days": streak, "shares": v})
    return events


def detect(date_str=None):
    """三大法人合計版（原本的邏輯，行為不變）。"""
    return _detect_from(HIST_PATH, "", date_str)


def detect_trust(date_str=None):
    """投信單獨版（2026-09-17 新增，對標老墨「投信慢慢吃股份」的訊號）。"""
    return _detect_from(HIST_TRUST_PATH, "投信", date_str)


def calibrate():
    """印出實測分布，用來訂門檻（不是憑感覺設 ANOMALY_MULT）。"""
    hist = _load(HIST_PATH, {})
    days = sorted(d for d in hist if hist[d])
    if len(days) < MIN_HISTORY + 1:
        print(f"歷史只有 {len(days)} 個交易日，至少要 {MIN_HISTORY+1} 天才能校準")
        return
    today = days[-1]
    past = days[-21:-1]
    ratios = []
    for code, v in hist[today].items():
        if abs(v) < MIN_SHARES:
            continue
        vals = [abs(hist[d][code]) for d in past if code in hist[d]]
        if len(vals) >= MIN_HISTORY:
            avg = sum(vals) / len(vals)
            if avg > 0:
                ratios.append(abs(v) / avg)
    if not ratios:
        print("沒有足夠樣本")
        return
    ratios.sort()
    n = len(ratios)
    print(f"樣本 {n} 檔｜今日|買賣超| ÷ 近20日平均的分布：")
    for p in (50, 75, 90, 95, 99):
        print(f"  第{p}百分位: {ratios[int(n*p/100)-1]:.2f}x")
    for m in (2.0, 3.0, 4.0, 5.0):
        hit = sum(1 for r in ratios if r > m)
        print(f"  門檻 {m}x → {hit} 檔觸發（{hit/n:.1%}）")


def shares_outstanding(codes):
    """{code: 已發行股數 或 None}。只查傳進來的代號（通常是當天事件的30-40檔），
    不是全市場——股本查詢是逐檔打 FinMind，全市場~1900檔會很慢，但事件觸發後
    的子集合小很多，這樣做才划算。

    2026-09-18：資料源 FinMind `TaiwanStockShareholding` 的 `NumberOfSharesIssued`
    欄位（跟外資持股比同一個資料集，本來就有這個數字，不用另外找資料源）。
    股本只有增減資才會動，用 90 天快取——跟 sector_map()/price_targets() 同一個
    「查過的東西留久一點」的慣例。
    """
    cache = _load(SHARES_PATH, {})
    today = dt.date.today()

    def fresh(e):
        try:
            return bool(e) and e.get("shares") is not None and \
                (today - dt.date.fromisoformat(e["asof"])).days < SHARES_CACHE_DAYS
        except Exception:                                   # noqa: BLE001
            return False

    out = {}
    need = []
    for c in codes:
        e = cache.get(c)
        if fresh(e):
            out[c] = e["shares"]
        else:
            need.append(c)
    if need:
        try:
            from fundamentals_reality import _fm
        except Exception as e:                              # noqa: BLE001
            print(f"  [warn] 股本查詢模組載入失敗：{str(e)[:60]}")
            for c in need:
                out[c] = None
            need = []
        for c in need:
            shares = None
            try:
                rows = _fm("TaiwanStockShareholding", c, "2026-01-01")
                if rows:
                    shares = rows[-1].get("NumberOfSharesIssued")
            except Exception:                                # noqa: BLE001
                pass
            out[c] = shares
            cache[c] = {"shares": shares, "asof": today.isoformat()}
            time.sleep(0.15)
        _save(SHARES_PATH, cache)
        print(f"  股本查詢：補查 {len(need)} 檔，"
             f"{sum(1 for c in need if out.get(c))} 檔查到")
    return out


def recent_flow(code, days=5):
    """單一個股近N個交易日的三大法人合計＋投信買賣超（2026-09-18，接個股查詢用）。

    對標老墨「零式系統」的「點進個股看籌碼」——之前 chip_scan 只做了
    「全市場掃描找異常」（chip.html/chip_trust.html），這支是反過來：
    「已經知道要看哪一檔，給它最近幾天的籌碼走勢」。直接讀現有的兩份歷史檔
    （HIST_PATH/HIST_TRUST_PATH），不用另外抓資料——這兩份本來就是全市場逐日
    存的，任何一檔隨時查得到，只是之前沒有一個函式把它組成「單檔視角」。

    回傳 {"days": [{"date","total","trust"}, ...]}（由舊到新），查不到回空list。

    ⚠️ 兩份歷史檔各約1MB，combo.html這種一次要查上百檔的呼叫端如果每檔都重新
    load 一次會很浪費（跑一次生頁面要重複解析上百MB的JSON）。用模組層級快取，
    只在**同一個 process** 裡的第一次呼叫真的讀檔，之後直接沿用——這是一次性
    腳本的常見做法（跑完就結束，不用擔心資料過期），跟 chip_scan 其他常駐/
    重跑一次的用法一致。
    """
    global _RECENT_FLOW_CACHE
    if _RECENT_FLOW_CACHE is None:
        _RECENT_FLOW_CACHE = (_load(HIST_PATH, {}), _load(HIST_TRUST_PATH, {}))
    hist, hist_trust = _RECENT_FLOW_CACHE
    all_days = sorted(set(hist) | set(hist_trust))
    have_data = [d for d in all_days if hist.get(d) or hist_trust.get(d)]
    out = []
    for d in have_data[-days:]:
        out.append({"date": d, "total": (hist.get(d) or {}).get(code),
                    "trust": (hist_trust.get(d) or {}).get(code)})
    return {"days": out}


def recent_flow_line(code, days=5):
    """recent_flow() 的一行文字版，給 /查 這種空間有限的地方用。

    只講「投信」（老墨個人偏好那個），三大法人合計太容易被外資避險單洗掉方向，
    放進一行摘要反而混淆——完整兩者都要看的人，去查 chip.html/chip_trust.html。
    """
    flow = recent_flow(code, days)["days"]
    trust_vals = [d["trust"] for d in flow if d.get("trust") is not None]
    if not trust_vals:
        return None
    n_buy = sum(1 for v in trust_vals if v > 0)
    n_sell = sum(1 for v in trust_vals if v < 0)
    total_lots = sum(trust_vals) / 1000
    return (f"投信近{len(trust_vals)}天：買{n_buy}天／賣{n_sell}天，"
           f"累計{'買超' if total_lots >= 0 else '賣超'}{abs(total_lots):,.0f}張")


def chart_html(code, days=60, uid=None):
    """個股籌碼面時間序列圖（2026-09-18，對標老墨「籌碼分析」分頁的「法人力度」，
    Leo：「進出燈號…我指的是籌碼分析」「像之前給你老墨的頁面一樣，一個可以看
    技術分析、一個看籌碼面」）。

    只做查得到資料的那塊——三大法人合計／投信單獨的**每日買賣超（張）**長條圖，
    切換算法沿用跟 chip.html 同一套 `.seg` 按鈕（BASE_CSS 既有元件，不必另外
    寫 CSS）。**刻意不做的部分**：老墨截圖裡的「分點力度」（分點/大戶集中度）
    要 XQ 那種付費看盤軟體才有的逐筆分點資料，FinMind／證交所免費資料源查不到，
    做不出來；「占股本比」算法切換也是 v2 再說，這版先給看得到、算得出來的
    股數版本，不假裝有分點力度那塊。

    嵌進頁面前提：呼叫端已經載入 Chart.js（跟 technical_indicators 用同一顆
    全域 `Chart`）——combo.html／lamp_room／lookup_page 本來就因為技術面圖表
    載過了，這裡不重複載 CDN。

    回傳空字串：非台股，或近 `days` 天完全查不到資料（新掛牌/太冷門/美股)。
    """
    import re as _re
    if not _re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(code)):
        return ""
    flow = recent_flow(code, days)["days"]
    dates = [d["date"][5:].replace("-", "/") for d in flow]
    total = [None if d["total"] is None else round(d["total"] / 1000, 1) for d in flow]
    trust = [None if d["trust"] is None else round(d["trust"] / 1000, 1) for d in flow]
    if not any(v is not None for v in total) and not any(v is not None for v in trust):
        return ""
    uid = uid or _re.sub(r"[.\-]", "_", str(code))
    Q = chr(34)
    data_json = json.dumps({"dates": dates, "total": total, "trust": trust}, ensure_ascii=False)
    # ⚠️ 這個分頁預設是隱藏的（外層技術分析／籌碼面切換），Chart.js 在容器
    # display:none 時建圖會量到 0 寬高、畫出來是壓扁的一條線——跟
    # technical_indicators.py 處理「展開圖表」同一個坑（見該檔 _autodraw 說明）。
    # 所以這裡不在載入當下就建圖，改成掛一個 window.chip_draw_{uid}()，
    # 由外層切分頁的地方（combo_html._tech_chip_html）在**第一次真的顯示**
    # 這個分頁時才呼叫，容器此時才有真正的寬度可以量。
    return f"""<div class="chipchart">
<div class="tclabel">籌碼面 - 法人力度（每日買賣超，單位：張；{Q}三大法人合計{Q}／{Q}投信單獨{Q}切換）</div>
<div class="ctrl" style="position:static;padding:0 0 8px;border:0;margin:0">
<div class="seg" role="group" aria-label="切換算法">
<button data-cv="total" aria-pressed="true">三大法人合計</button>
<button data-cv="trust" aria-pressed="false">投信單獨</button>
</div></div>
<div class="tcbox"><canvas id="chip_c_{uid}"></canvas></div>
</div>
<script>
window.chip_draw_{uid} = function(){{
  if (window.chip_drawn_{uid}) return;
  window.chip_drawn_{uid} = true;
  var d = {data_json};
  var css = getComputedStyle(document.documentElement);
  var up = (css.getPropertyValue('--up') || '#22C55E').trim() || '#22C55E';
  var dn = (css.getPropertyValue('--down') || '#EF4444').trim() || '#EF4444';
  function colorize(arr){{ return arr.map(function(v){{ return v==null?'transparent':(v>=0?up:dn); }}); }}
  var canvas = document.getElementById({Q}chip_c_{uid}{Q});
  var chart = new Chart(canvas, {{type:'bar',
    data:{{labels:d.dates, datasets:[
      {{label:'三大法人合計(張)', data:d.total, backgroundColor:colorize(d.total), borderRadius:2}},
      {{label:'投信單獨(張)', data:d.trust, backgroundColor:colorize(d.trust), borderRadius:2, hidden:true}}
    ]}},
    options:{{responsive:true, maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}, tooltip:{{callbacks:{{label:function(c){{
        return c.dataset.label+'：'+(c.parsed.y==null?'—':c.parsed.y.toLocaleString()+' 張');
      }}}}}}}},
      scales:{{x:{{ticks:{{color:'#9aa0a6',maxRotation:0,autoSkip:true,font:{{size:9}}}},grid:{{display:false}}}},
               y:{{ticks:{{color:'#9aa0a6',font:{{size:10}}}},grid:{{color:'rgba(255,255,255,.06)'}}}}}}}}
  }});
  canvas.closest('.chipchart').querySelectorAll('.seg button[data-cv]').forEach(function(b){{
    b.addEventListener('click', function(){{
      canvas.closest('.chipchart').querySelectorAll('.seg button[data-cv]').forEach(function(x){{
        x.setAttribute('aria-pressed', x===b?'true':'false'); }});
      chart.data.datasets[0].hidden = (b.dataset.cv !== 'total');
      chart.data.datasets[1].hidden = (b.dataset.cv !== 'trust');
      chart.update();
    }});
  }});
}};
</script>"""


def summary_lines(events, max_each=4):
    """給日報/Discord 用。分四類，每類最多列 max_each 檔。

    2026-08-29 版面（Leo：「看一下段落，不要太亂」）：
    · 一檔一行不要用｜串長串——實測串起來每類 150 字，手機一行約 20 字會折 7-8 行，
      四類糊成 31 行完全看不出斷點
    · 每類之間空一行，讓四個區塊在手機上分得開
    · 「連賣」只列 3 檔——四類裡它對決策的參考價值最低（賣壓通常已反映在股價上），
      買方訊號（異常大買、連買）才是要找的進場線索
    """
    if not events:
        return []
    groups = {"異常大買": [], "異常大賣": [], "連買": [], "連賣": []}
    for e in events:
        if e["kind"] == "anomaly":
            groups[e["event"]].append(e)
        elif "連買" in e["event"]:
            groups["連買"].append(e)
        else:
            groups["連賣"].append(e)
    icons = {"異常大買": "🟢", "異常大賣": "🔴", "連買": "📈", "連賣": "📉"}
    out = []
    for k, lst in groups.items():
        if not lst:
            continue
        lst.sort(key=lambda e: -(e.get("vs_avg") or e.get("days") or 0))
        # 2026-08-29 版面（Leo：「看一下段落，不要太亂」）：一檔一行，不要全部用
        # ｜串成一長串。實測串起來每類 150 字、手機一行約 20 字 → 折成 7-8 行，
        # 四類糊成 31 行看不出斷點。改成標題一行、每檔一行縮排，並從 6 檔收到 4 檔
        # （排序已由大到小，第 5 名之後的參考價值遞減，要看全部可查完整清單）。
        if out:
            out.append("")           # 類別之間空一行，手機上才分得開
        n_show = 3 if k == "連賣" else max_each
        out.append(f"{icons[k]} **{k}**（{len(lst)} 檔）")
        for e in lst[:n_show]:
            # 台股 1 張 = 1000 股。直接講「張」不要換算成「千張」——
            # 「42千張」讀起來像 42,000 張但實際是 42,448 張，小額的更誤導。
            lots = abs(e.get("shares") or 0) / 1000
            detail = (f"{e['vs_avg']:.1f} 倍" if e.get("vs_avg")
                      else f"連 {e.get('days')} 天")
            out.append(f"　{e['code']} {e['name']}　{detail}・{lots:,.0f} 張")
        if len(lst) > n_show:
            out.append(f"-# 　…還有 {len(lst)-n_show} 檔")
    return out


def summary_lines_trust(events, max_each=4):
    """投信單獨版的 summary_lines（2026-09-17）——跟 summary_lines() 版面邏輯
    一樣，但事件文字帶「投信」前綴（來自 detect_trust() 的 who="投信"），
    分組要對到那個前綴，不能沿用 summary_lines() 的固定 key。

    2026-09-18 加占股本比：只查「真的會顯示出來」的那些檔（每組最多 max_each，
    通常十幾檔），不是整份 events（可能有 35 檔但只顯示一小部分）——
    再省一點 FinMind 查詢量。
    """
    if not events:
        return []
    groups = {"投信異常大買": [], "投信異常大賣": [], "投信連買": [], "投信連賣": []}
    for e in events:
        if e["kind"] == "anomaly":
            groups[e["event"]].append(e)
        elif "連買" in e["event"]:
            groups["投信連買"].append(e)
        else:
            groups["投信連賣"].append(e)
    for k in groups:
        groups[k].sort(key=lambda e: -(e.get("vs_avg") or e.get("days") or 0))
    shown_codes = set()
    for k, lst in groups.items():
        n_show = 3 if k == "投信連賣" else max_each
        shown_codes.update(e["code"] for e in lst[:n_show])
    shares = shares_outstanding(sorted(shown_codes)) if shown_codes else {}

    icons = {"投信異常大買": "🟢", "投信異常大賣": "🔴", "投信連買": "📈", "投信連賣": "📉"}
    out = []
    for k, lst in groups.items():
        if not lst:
            continue
        if out:
            out.append("")
        n_show = 3 if k == "投信連賣" else max_each
        out.append(f"{icons[k]} **{k}**（{len(lst)} 檔）")
        for e in lst[:n_show]:
            lots = abs(e.get("shares") or 0) / 1000
            detail = (f"{e['vs_avg']:.1f} 倍" if e.get("vs_avg")
                      else f"連 {e.get('days')} 天")
            so = shares.get(e["code"])
            pct = (f"　占股本{e.get('shares', 0)/so*100:+.2f}%"
                  if so else "")
            out.append(f"　{e['code']} {e['name']}　{detail}・{lots:,.0f} 張{pct}")
        if len(lst) > n_show:
            out.append(f"-# 　…還有 {len(lst)-n_show} 檔")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYYMMDD，預設今天")
    ap.add_argument("--backfill", type=int, default=0, help="往回補幾個日曆日")
    ap.add_argument("--calibrate", action="store_true", help="印門檻校準用的分布")
    a = ap.parse_args()

    today = dt.date.today()
    if a.backfill:
        ds = [today - dt.timedelta(days=i) for i in range(a.backfill)]
        ds = [d for d in ds if d.weekday() < 5]
        print(f"補歷史 {len(ds)} 個工作日…")
        collect(sorted(ds))
    else:
        if a.date:
            collect([dt.datetime.strptime(a.date, "%Y%m%d").date()])
        else:
            # 2026-09-01：原本只抓 `today`，但 08:45 跑的時候當日資料還沒公布，
            # 等於每天都抓空的。改成回溯 DAILY_LOOKBACK 個日曆日——昨天(或上週五)
            # 的資料這時候一定有了。已經有資料的日期會在 collect() 裡被跳過，
            # 所以多抓幾天幾乎不花時間。
            ds = [today - dt.timedelta(days=i) for i in range(DAILY_LOOKBACK)]
            collect(sorted(d for d in ds if d.weekday() < 5))

    if a.calibrate:
        calibrate()
        return

    events = detect()
    hist = _load(HIST_PATH, {})
    days = sorted(x for x in hist if hist[x])
    _save(OUT_PATH, {"date": days[-1] if days else None,
                     "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                     "events": events})
    print(f"\n✅ {len(events)} 筆籌碼異常 → {OUT_PATH}")
    for l in summary_lines(events):
        print(" ", l)

    # 2026-09-17：投信單獨版，跟三大法人合計版平行跑、平行存，兩份互不影響。
    events_trust = detect_trust()
    hist_trust = _load(HIST_TRUST_PATH, {})
    days_trust = sorted(x for x in hist_trust if hist_trust[x])
    _save(OUT_TRUST_PATH, {"date": days_trust[-1] if days_trust else None,
                          "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                          "events": events_trust})
    print(f"\n✅ {len(events_trust)} 筆投信異常 → {OUT_TRUST_PATH}")
    for l in summary_lines_trust(events_trust):
        print(" ", l)


if __name__ == "__main__":
    main()
