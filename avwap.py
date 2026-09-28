# -*- coding: utf-8 -*-
"""錨定均價 AVWAP（2026-09-28，參考老墨「AVWAP 錨定均價」模式一：過去 N 期）。

Leo 看過模擬圖 v4 後定案「好，做吧」：
- 算法：從最新一根往回數 N 根當起點，每根 K 棒用典型價格 (H+L+C)/3 × 成交量一路累加，
  中途不重算 →「從 N 根前到現在，所有進場的錢平均買在這個價位」。
- 「距 60 日成本」＝收盤 / 60 日錨定均價 − 1。
- 顏色門檻用**全市場當天的分布**（market_relay_scan.py 每天 07:00 算），不寫死：
  🔴 最偏離的前 1%、🟡 前 1～5%、🟢 其他。只顯示，不影響燈號／接力／排序。

⚠️ 技術圖說明卡上的「20 日平均成本」是另一個東西（收盤價量加權的滾動 20 日，已對上老墨
雙重颱風的 135.95），不要跟這裡的 20 日錨定均價混在一起改。

四個地方共用這一支：technical_indicators（圖＋按鈕）、market_relay_scan（全市場分布）、
industry_rotation（強勢股清單欄位）、lamp_room（燈號戰情室關鍵數字）。
"""
import bisect
import json
import math
import os

PERIODS = (20, 60, 120, 240)
DIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "market_relay.json")
_DIST_CACHE = {}


def _ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def avwap_from(highs, lows, closes, vols, start):
    """從第 start 根開始累加的錨定均價；start 之前都是 None（圖上不畫）。缺值那根沿用前一個值。"""
    n = len(closes)
    out = [None] * n
    pv = vv = 0.0
    for i in range(max(0, start), n):
        h, l, c, v = highs[i], lows[i], closes[i], vols[i]
        if _ok(h) and _ok(l) and _ok(c) and _ok(v) and v > 0:
            pv += (float(h) + float(l) + float(c)) / 3.0 * float(v)
            vv += float(v)
        out[i] = pv / vv if vv > 0 else None
    return out


def avwap_n(highs, lows, closes, vols, n):
    """過去 N 期：起點＝最後一根往回數 N 根（含最後一根）。資料不足 N 根回全 None。"""
    if len(closes) < n:
        return [None] * len(closes)
    return avwap_from(highs, lows, closes, vols, len(closes) - n)


def dist_from_df(h, n=60):
    """DataFrame（High/Low/Close/Volume）→ 收盤距 N 日錨定均價 %（小數點 1 位）；算不出回 None。"""
    try:
        if h is None or len(h) < n or "Volume" not in h.columns:
            return None
        t = h.iloc[-n:]
        av = avwap_from(t["High"].tolist(), t["Low"].tolist(), t["Close"].tolist(), t["Volume"].tolist(), 0)[-1]
        c = float(t["Close"].iloc[-1])
        return round((c / av - 1) * 100, 1) if av and c == c else None
    except Exception:                                          # noqa: BLE001
        return None


def market_of(ticker):
    t = str(ticker).upper()
    return "tw" if (t[:1].isdigit() or t.endswith(".TW") or t.endswith(".TWO")) else "us"


RES = 10   # 每 0.1 百分位一個點：只存 1% 一格時，最頂端 1% 只能線性內插，健策實際 99.6 會算成 99.2


def quantiles(vals):
    """0～100 每 0.1 一個分位點，共 1001 個（給任何一檔股票換算「贏過全市場幾 %」用，存進 market_relay.json）。"""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n, m = len(v), 100 * RES
    return [round(v[min(n - 1, int(round(p / m * (n - 1))))], 2) for p in range(m + 1)]


def _res(dist):
    return (len(dist) - 1) // 100 or 1


def load_dist(market, path=DIST_FILE):
    """讀 market_relay.json 裡該市場的距 60 日成本分布（每次讀檔時看 mtime，檔案更新就重讀）。"""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    c = _DIST_CACHE.get(path)
    if not c or c[0] != mt:
        try:
            with open(path, encoding="utf-8") as f:
                c = (mt, json.load(f))
        except Exception:                                      # noqa: BLE001
            return None
        _DIST_CACHE[path] = c
    m = ((c[1] or {}).get("markets") or {}).get(market) or {}
    return m.get("d60_dist")


def pct_rank(d, dist):
    """d 贏過全市場幾 %（0～100，小數點 1 位）。dist 是 quantiles() 的分位點（舊檔 101 點也能讀）。"""
    if d is None or not dist:
        return None
    k = bisect.bisect_right(dist, d)
    if k <= 0:
        return 0.0
    if k >= len(dist):
        return 100.0
    lo, hi = dist[k - 1], dist[k]
    frac = 0.0 if hi == lo else (d - lo) / (hi - lo)
    return round(min(100.0, (k - 1 + frac) / _res(dist)), 1)


def tier(d, dist):
    """🔴 hot＝前 1%（≥ 第 99 百分位）、🟡 warm＝前 1～5%（≥ 第 95）、🟢 ok＝其他。沒分布回 None。"""
    if d is None or not dist:
        return None
    r = _res(dist)
    if d >= dist[99 * r]:
        return "hot"
    if d >= dist[95 * r]:
        return "warm"
    return "ok"


TIER_COLOR = {"hot": "#F87171", "warm": "#FACC15", "ok": "#4ADE80"}
TIER_TEXT = {"hot": "過熱：全市場最偏離的前 1%", "warm": "偏熱：全市場前 1～5%", "ok": "正常範圍"}
