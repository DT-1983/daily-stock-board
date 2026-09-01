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

HIST_PATH = "state/chip_history.json"     # {date: {code: 買賣超股數}}
OUT_PATH = "state/chip_events.json"
NAMES_PATH = "state/chip_names.json"      # {code: name}

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
    """證交所 T86。date_str: YYYYMMDD。回 {code: (name, 買賣超股數)}。"""
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
        if v is not None:
            out[code] = (str(row[1]).strip(), v)
    return out


def fetch_tpex(date_str):
    """櫃買 dailyTrade。回 {code: (name, 買賣超股數)}。"""
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
        if v is not None:
            out[code] = (str(row[1]).strip(), v)
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
    """抓多天寫進歷史。回實際新增的天數。"""
    hist = _load(HIST_PATH, {})
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
            else:
                print(f"  {key} 尚未公布（當日資料收盤後才有），不寫入，明天重抓")
            continue
        hist[key] = {c: v for c, (n, v) in data.items()}
        names.update({c: n for c, (n, v) in data.items()})
        added += 1
        print(f"  {key} 取得 {len(data)} 檔")
    _save(HIST_PATH, hist)
    _save(NAMES_PATH, names)
    return added


def detect(date_str=None):
    """對最新一天算異常＋連買連賣。回 events list。"""
    hist = _load(HIST_PATH, {})
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
        if abs(v) < MIN_SHARES:
            continue
        nm = names.get(code, code)
        # ① 異常：跟自己近20日的平均絕對值比（每檔自己的基準，不用全市場統一門檻——
        #    跟 base_rate 同一個思路：大型股天天幾萬張，小型股幾百張就算大）
        vals = [abs(hist[d][code]) for d in past if code in hist[d]]
        if len(vals) >= MIN_HISTORY:
            avg = sum(vals) / len(vals)
            if avg > 0 and abs(v) > avg * ANOMALY_MULT:
                events.append({"code": code, "name": nm,
                               "event": "異常大買" if v > 0 else "異常大賣",
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
                           "event": f"法人連{'買' if sign > 0 else '賣'} {streak} 天",
                           "kind": "streak", "days": streak, "shares": v})
    return events


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


if __name__ == "__main__":
    main()
