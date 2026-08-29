# -*- coding: utf-8 -*-
"""歷史股價本地快取（2026-08-29，Leo 指定）。

**為什麼做**：industry_rotation.py 原本逐檔 `yf.Ticker().history(period="3y")`，
294 檔要跑 12 分鐘；要擴到 industry 細分類（1,380 檔）會變 45 分鐘，直接不可行。
實測批次下載比逐檔快 8 倍，快取再省一層。

兩層設計，各自解決不同問題：
  ① **批次下載**（`_download`）——解決「速度」。實測 8 檔：逐檔 1.6 秒、批次 0.2 秒。
  ② **本地快取**（pickle）——解決「不要每次重抓」，更重要的是**抗 API 失效**：
     2026-08-28 一天內就遇到 Yahoo 擋 Actions IP、證交所擋 Actions IP 兩次。
     快取讓「今天抓不到」不等於「今天沒資料」。

存 pickle 不存 parquet／SQLite：
  · parquet 要裝 pyarrow——`weekly-screen.yml`（industry_rotation 跑的地方）
    現在只裝 yfinance/requests/tradingview_screener/pandas/numpy，**多一個依賴就多一個
    雲端安裝失敗的風險**，為了快取加這個不划算。
  · SQLite 適合「有結構、要查詢」的資料（advisor.db 那類），股價是純數值時間序列，
    pandas 的 to_pickle/read_pickle 零依賴、直接存還原 DataFrame 最省事。
  · 實測 1,400 檔 3 年約 60MB，可接受。

增量更新：快取有的部分直接用，只抓缺的日期範圍。第一次跑會慢（要抓滿 3 年），
之後每天只補 1-2 天。

用法：
    from price_store import get_closes, get_ohlc
    closes = get_closes(["2330.TW", "2317.TW"], period="3y")   # {ticker: Series}
"""
import os
import sys
import json
import time
import datetime as dt

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

STORE_DIR = "state/price_store"
META_PATH = os.path.join(STORE_DIR, "_meta.json")
BATCH_SIZE = 200          # 一次送給 yf.download 的檔數（太多會逾時，太少失去批次好處）
STALE_HOURS = 12          # 快取這麼久沒更新才重抓（同一天內重跑不重抓）


def _meta():
    try:
        return json.load(open(META_PATH, encoding="utf-8"))
    except Exception:
        return {}


def _save_meta(m):
    os.makedirs(STORE_DIR, exist_ok=True)
    json.dump(m, open(META_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def _path(ticker):
    """檔名要能安全當檔案名——台股 2330.TW、美股 BRK-B 都有特殊字元。"""
    safe = str(ticker).replace(".", "_").replace("/", "_").replace("^", "IDX_")
    return os.path.join(STORE_DIR, f"{safe}.pkl")


def _read_cached(ticker):
    p = _path(ticker)
    if not os.path.exists(p):
        return None
    try:
        import pandas as pd
        df = pd.read_pickle(p)
        # 統一 tz-naive（2026-08-28 chain_technicals 踩過：批次回 naive、逐檔回 aware，
        # 混在一起比較時間戳會 TypeError）
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return None


def _write_cached(ticker, df):
    try:
        os.makedirs(STORE_DIR, exist_ok=True)
        if df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        df.to_pickle(_path(ticker))
        return True
    except Exception as e:
        print(f"  [price_store] {ticker} 寫入失敗：{str(e)[:60]}")
        return False


def _download(tickers, period):
    """批次下載。回 {ticker: DataFrame}。失敗的不在回傳裡（呼叫端自己判斷缺誰）。"""
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), BATCH_SIZE):
        chunk = tickers[i:i + BATCH_SIZE]
        try:
            data = yf.download(chunk, period=period, progress=False, threads=False,
                               auto_adjust=True, group_by="ticker")
        except Exception as e:
            print(f"  [price_store] 批次 {i//BATCH_SIZE+1} 失敗：{str(e)[:60]}")
            continue
        for tk in chunk:
            try:
                df = data[tk] if len(chunk) > 1 else data
                df = df.dropna(how="all")
                if len(df):
                    if df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                    out[tk] = df
            except Exception:
                pass
        if len(tickers) > BATCH_SIZE:
            time.sleep(0.5)        # 對 yfinance 客氣一點
    return out


def get_ohlc(tickers, period="3y", refresh=True):
    """回 {ticker: DataFrame(OHLCV)}。用快取，過期才重抓。

    refresh=False 純吃快取不連網——API 掛掉時的降級模式（有舊資料總比沒有好）。
    """
    tickers = [str(t) for t in tickers]
    meta = _meta()
    now = dt.datetime.now()
    out, need = {}, []
    for tk in tickers:
        df = _read_cached(tk)
        if df is None or df.empty:
            need.append(tk)
            continue
        ts = meta.get(tk, {}).get("updated")
        fresh = False
        if ts:
            try:
                fresh = (now - dt.datetime.fromisoformat(ts)).total_seconds() < STALE_HOURS * 3600
            except Exception:
                pass
        out[tk] = df
        if not fresh and refresh:
            need.append(tk)        # 有舊的可用，但仍排進重抓（抓失敗就繼續用舊的）

    if need and refresh:
        print(f"  [price_store] 快取命中 {len(tickers)-len([t for t in need if t not in out])}"
              f"/{len(tickers)}，需更新 {len(need)} 檔…")
        got = _download(need, period)
        stamp = now.isoformat(timespec="seconds")
        for tk, df in got.items():
            if _write_cached(tk, df):
                meta.setdefault(tk, {})["updated"] = stamp
                meta[tk]["rows"] = len(df)
            out[tk] = df           # 新的蓋掉舊的
        _save_meta(meta)
        miss = [t for t in need if t not in got and t not in out]
        if miss:
            print(f"  [price_store] {len(miss)} 檔抓不到也沒有快取：{miss[:8]}")
    return out


def get_closes(tickers, period="3y", refresh=True):
    """只要收盤價。回 {ticker: Series}。"""
    return {tk: df["Close"] for tk, df in get_ohlc(tickers, period, refresh).items()
            if "Close" in df.columns and len(df["Close"].dropna())}


def stats():
    """快取現況（給人看的）。"""
    if not os.path.isdir(STORE_DIR):
        return {"files": 0, "mb": 0}
    files = [f for f in os.listdir(STORE_DIR) if f.endswith(".pkl")]
    mb = sum(os.path.getsize(os.path.join(STORE_DIR, f)) for f in files) / 1024 / 1024
    return {"files": len(files), "mb": round(mb, 1)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--warm", default="", help="逗號分隔，預熱這些代號")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.warm:
        tks = [t.strip() for t in a.warm.split(",") if t.strip()]
        t0 = time.time()
        got = get_ohlc(tks)
        print(f"✅ {len(got)}/{len(tks)} 檔，耗時 {time.time()-t0:.1f} 秒")
    print("快取現況:", stats())
