# -*- coding: utf-8 -*-
"""全市場 3 年 OHLCV backfill，走 FinMind 免費方案（2026-09-20）。

**為什麼做**：Leo 問「創意(3443) 四燈全亮卻沒進 COMBO」——查出根因是 combo_scan.py
的母體只有 281 檔（守備清單＋持股＋自訂＋RRG領先類股前8大成分股），市值不夠大、
產業沒轉強、沒人手動加的股票永遠不會被算到，不管表現多強都看不到。

Leo 提議：「如果我們有 FinMind 資料，是不是就可以每天做（全市場）？」——查證後
確認可行且**零成本**：FinMind 免費方案（有註冊帳號 600 次/小時）本來就包含
`TaiwanStockPrice`（個股日OHLCV）這個資料集，不是要付費 Sponsor 才解鎖的那種
（那個是分點資料表，跟這個是兩份不同的資料集）。`price_store.py` 也已經有
串接這個資料集的現成程式碼（`_fill_tw_gaps()`，原本只拿來補近期缺漏K棒）。

**這支腳本做什麼**：對全市場（不只 281 檔母體）逐檔檢查 `price_store` 現有快取
夠不夠 3 年，不夠的才用 FinMind 補（增量，不是每檔都重抓）。寫入沿用
`price_store.py` 原本的快取格式（`_write_cached`/`_meta`/`_save_meta`），
所以 `combo_scan.py` 既有的 `scan_one()` 完全不用改，之後只要把母體清單
換成全市場，就能直接吃到這裡 backfill 好的資料。

**代號清單哪裡來**：不重新打一次官方 API——直接讀 `chip_scan.py` 每天已經在
collect() 的 `state/chip_history.json`（T86/櫃買 dailyTrade 全市場都有），
拿最近一天的 keys 當作「今天有交易的代號」全集，本來就免費、本來就有。

**速率控制**：FinMind 免費會員 600 次/小時，這裡保守抓 500 次/小時
（每次呼叫間隔 7.2 秒），留一點安全空間給同時在跑的其他排程。全市場約
1,800 檔，扣掉已經有 yfinance 快取撐得住 3 年的（281 檔母體本來就有），
真正需要新抓的預估落在 1,500~1,700 檔區間，約 3~3.5 小時跑完，設計成
可以中斷重跑（每抓完一檔就存檔+更新進度檔，不是全部抓完才一次寫入）。

用法：
    python full_market_backfill.py             # 全市場，可能跑 3+ 小時
    python full_market_backfill.py --limit 50   # 只跑前 50 檔，測試用
    python full_market_backfill.py --resume     # 從上次中斷的地方接著跑
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

import requests                                                # noqa: E402
import pandas as pd                                            # noqa: E402

import price_store as ps                                       # noqa: E402
import chip_scan as cs                                         # noqa: E402
import tw_symbol                                                # noqa: E402

PROGRESS_PATH = "state/full_market_backfill_progress.json"
CALLS_PER_HOUR = 500          # 免費會員上限600，留安全空間
SLEEP_SEC = 3600 / CALLS_PER_HOUR
PERIOD_YEARS = 3


def all_tw_codes():
    """全市場代號清單，來源：chip_scan 每天已經在存的全市場籌碼歷史檔——
    免費、已經有、不用另外打一次官方 API。"""
    hist = cs._load(cs.HIST_PATH, {}) or {}
    if not hist:
        return []
    latest = sorted(hist.keys())[-1]
    codes = sorted(hist[latest].keys())
    print(f"  全市場代號清單：{latest} 這天共 {len(codes)} 檔")
    return codes


def _load_progress():
    try:
        return json.load(io.open(PROGRESS_PATH, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return {"done": [], "failed": []}


def _save_progress(p):
    os.makedirs(os.path.dirname(PROGRESS_PATH) or ".", exist_ok=True)
    io.open(PROGRESS_PATH, "w", encoding="utf-8").write(
        json.dumps(p, ensure_ascii=False, indent=1))


def _needs_backfill(sym):
    """跟 price_store.get_ohlc() 同一套判斷邏輯：快取涵蓋天數夠不夠 3 年。"""
    df = ps._read_cached(sym)
    if df is None or df.empty or len(df) < 2:
        return True
    span_days = (df.index.max() - df.index.min()).days
    return span_days < ps._period_days(f"{PERIOD_YEARS}y") * 0.85


def _fetch_finmind(code, tok, start, end):
    try:
        r = requests.get(ps.FINMIND_URL, timeout=25, params={
            "dataset": "TaiwanStockPrice", "data_id": code,
            "start_date": start, "end_date": end, "token": tok})
        rows = (r.json() or {}).get("data") or []
    except Exception as e:                                     # noqa: BLE001
        print(f"    [warn] {code} FinMind 請求失敗：{str(e)[:60]}")
        return None
    if not rows:
        return None
    recs = []
    for x in rows:
        if not x.get("close"):
            continue
        recs.append({"Date": pd.Timestamp(x["date"]), "Open": x.get("open"),
                     "High": x.get("max"), "Low": x.get("min"),
                     "Close": x.get("close"), "Volume": x.get("Trading_Volume")})
    if not recs:
        return None
    return pd.DataFrame(recs).set_index("Date").sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只跑前N檔（測試用）")
    ap.add_argument("--resume", action="store_true", help="跳過上次已完成的代號")
    a = ap.parse_args()

    tok = ps._fm_token()
    if not tok:
        print("✗ 找不到 FINMIND_TOKEN（.env），無法呼叫 FinMind")
        return 1

    codes = all_tw_codes()
    if not codes:
        print("✗ 讀不到全市場代號清單（state/chip_history.json 是空的）")
        return 1
    if a.limit:
        codes = codes[:a.limit]

    progress = _load_progress() if a.resume else {"done": [], "failed": []}
    done_set = set(progress.get("done", []))

    end = dt.date.today().isoformat()
    start = (dt.date.today() - dt.timedelta(days=int(365.25 * PERIOD_YEARS) + 10)).isoformat()

    todo = [c for c in codes if c not in done_set]
    print(f"  待處理 {len(todo)}/{len(codes)} 檔（已完成 {len(done_set)} 檔）")
    n_fetched, n_skipped, n_failed = 0, 0, 0
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        sym = tw_symbol.resolve(code)
        if not _needs_backfill(sym):
            # 已經有夠長的快取，不用打 API——不佔速率額度，也不用睡那 7.2 秒。
            n_skipped += 1
            progress["done"].append(code)
            continue
        df = _fetch_finmind(code, tok, start, end)
        if df is None or df.empty:
            n_failed += 1
            progress.setdefault("failed", []).append(code)
        else:
            if ps._write_cached(sym, df):
                meta = ps._meta()
                meta.setdefault(sym, {})["updated"] = dt.datetime.now().isoformat(timespec="seconds")
                meta[sym]["rows"] = len(df)
                ps._save_meta(meta)
                n_fetched += 1
        progress["done"].append(code)
        if i % 50 == 0:
            _save_progress(progress)
            elapsed = time.time() - t0
            print(f"    …{i}/{len(todo)}（已抓{n_fetched}／跳過{n_skipped}／失敗{n_failed}，"
                  f"耗時{elapsed/60:.1f}分）")
        time.sleep(SLEEP_SEC)   # 只有真的打了 FinMind API 才需要睡，維持速率限制
    _save_progress(progress)
    print(f"✅ 完成：新抓 {n_fetched} 檔／已足夠跳過 {n_skipped} 檔／失敗 {n_failed} 檔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
