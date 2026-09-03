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
        # 已經存進快取的盤中列（Close 是 NaN）在這裡也要擋——不然要等下次重抓
        # 才會消失，而 STALE_HOURS 內不會重抓。見 _download 那邊的說明。
        if "Close" in df.columns:
            df = df.dropna(subset=["Close"])
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
                # 2026-08-29：yfinance 批次下載偶爾回 MultiIndex 欄位
                # （('STRF','Close') 而不是 'Close'）——實測 1,246 檔裡有 1 檔這樣，
                # 沒攤平會讓下游 df["Close"] 直接 KeyError，而且因為只有一檔，
                # 整個細分類會被一個 except 吞掉變成「計算失敗」。這裡統一攤平。
                if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                    df = df.copy()
                    df.columns = [c[-1] if isinstance(c, tuple) else c for c in df.columns]
                # 2026-08-30 修：原本 dropna(how="all") 只清「整列全 NaN」，
                # 但 yfinance 在美股尚未收盤時會回一列 OHLC 全 NaN、**Volume 卻有值**
                # 的當日列（實測 ^GSPC 8/28）——how="all" 攔不住。
                # 後果很嚴重：籃子指數有值、基準是 NaN → 相除全 NaN →
                # **美股「加權指數」基準的 RRG 整個算不出來（0 個籃子）**，
                # 台股沒事只是因為 ^TWII 那天剛好沒有盤中列。
                # 改成以 Close 為準：沒有收盤價的那列對所有下游計算都沒有意義。
                if "Close" in df.columns:
                    df = df.dropna(subset=["Close"])
                else:
                    df = df.dropna(how="all")
                if len(df) and "Close" in df.columns:
                    if df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                    out[tk] = df
            except Exception:
                pass
        if len(tickers) > BATCH_SIZE:
            time.sleep(0.5)        # 對 yfinance 客氣一點
    _fill_tw_gaps(out)
    return out


# ── 台股缺 K 棒補洞（2026-09-03）──────────────────────────────────
# 起因：Leo 對照 XQ 發現 00981A 少一天。實測 yfinance 在 2026-09-02 對台股
# **ETF 整批漏 K 棒**（00981A、0050 都少一根），個股不受影響。
#
# ⚠️ **為什麼是補洞不是換資料源**：Leo 原本要求整個換成 FinMind，實測後發現代價太大——
#   ① FinMind 是**原始價**、yfinance 是**還原權值價**：實測一年前差 1.3~4.7%
#      （2618 差 4.72%），全換等於所有台股的 SuperTrend/RS 位移，**燈號可能翻**
#   ② 成交量兩邊對不上：2330 在 9/1 是 3,185 萬 vs 1,721 萬（1.85 倍，且比例每天不同）
#      → 雙重颱風那盞燈也會變
#   在沒有回測依據下改變策略行為，就是今天早上換匯那個坑的翻版。
#
# 所以：**yfinance 當主（維持還原價體系），FinMind 只補它缺的那幾根**。
# 近期缺口（最後一次除權息之後）兩邊價格完全相同，補進去零誤差；
# 久遠缺口會有還原差，但那種情況本來就只影響單根，且會印出來。
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def _fm_token():
    try:
        from dotenv import dotenv_values
        here = os.path.dirname(os.path.abspath(__file__))
        return (dotenv_values(os.path.join(here, ".env")) or {}).get("FINMIND_TOKEN", "")
    except Exception:                                       # noqa: BLE001
        return ""


GAP_WINDOW_DAYS = 120     # 只回頭檢查這麼多天的缺口


def _fill_tw_gaps(frames, window_days=GAP_WINDOW_DAYS):
    """對台股 frame 補上 yfinance 漏掉的交易日（資料取自 FinMind 官方）。就地修改。

    ⚠️ 只檢查最近 `window_days` 天，不是整段 3 年——每天掃描約 130 檔台股，
    每檔都拉 3 年 JSON 是 ~13MB/天的無謂流量。實際遇到的失效模式是**近期**
    K 棒漏掉（yfinance 當天/前一天的資料不完整），久遠的缺口就算存在，
    對 60-250 日的指標影響也遠小於這個成本。要補久遠缺口就手動放大 window_days。
    """
    tw = [tk for tk in frames if str(tk).upper().endswith((".TW", ".TWO"))]
    if not tw:
        return
    tok = _fm_token()
    if not tok:
        return
    import requests
    import pandas as pd
    filled_total, touched = 0, []
    for tk in tw:
        df = frames[tk]
        if df is None or df.empty:
            continue
        have = {str(i)[:10] for i in df.index}
        start = max(df.index.min().date(),
                    dt.date.today() - dt.timedelta(days=window_days))
        s = start.isoformat()
        code = str(tk).upper().replace(".TWO", "").replace(".TW", "")
        try:
            r = requests.get(FINMIND_URL, timeout=20, params={
                "dataset": "TaiwanStockPrice", "data_id": code,
                "start_date": s, "end_date": dt.date.today().isoformat(), "token": tok})
            rows = (r.json() or {}).get("data") or []
        except Exception:                                   # noqa: BLE001
            continue
        add = []
        for x in rows:
            if x["date"] in have or not x.get("close"):
                continue
            add.append({"Date": pd.Timestamp(x["date"]),
                        "Open": x.get("open"), "High": x.get("max"),
                        "Low": x.get("min"), "Close": x.get("close"),
                        "Volume": x.get("Trading_Volume")})
        if not add:
            continue
        extra = pd.DataFrame(add).set_index("Date")
        merged = pd.concat([df, extra]).sort_index()
        merged = merged[~merged.index.duplicated(keep="first")]   # 既有的優先，不覆蓋
        frames[tk] = merged
        filled_total += len(add)
        touched.append(f"{tk}+{len(add)}")
    if filled_total:
        print(f"  [price_store] FinMind 補回 {filled_total} 根台股缺漏 K 棒："
              f"{'、'.join(touched[:8])}" + ("…" if len(touched) > 8 else ""))


def get_ohlc(tickers, period="3y", refresh=True, force=False):
    """回 {ticker: DataFrame(OHLCV)}。用快取，過期才重抓。

    refresh=False 純吃快取不連網——API 掛掉時的降級模式（有舊資料總比沒有好）。

    `force=True` 無視 STALE_HOURS 直接重抓。什麼時候需要（2026-09-03 踩到）：
    每天 07:45 的掃描會把快取標成「新鮮」，而 STALE_HOURS=12 表示到 19:45 前都不重抓——
    但 07:45 時台股還沒收盤，快取裡是**前一交易日**的收盤。使用者下午對照看盤軟體
    會發現數字差一天，這時「即時重算」如果只重算指標不重抓價格就是騙人的。
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
        if ts and not force:
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


def get_closes(tickers, period="3y", refresh=True, force=False):
    """只要收盤價。回 {ticker: Series}。"""
    return {tk: df["Close"] for tk, df in get_ohlc(tickers, period, refresh, force).items()
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
