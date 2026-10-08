# -*- coding: utf-8 -*-
"""台指選擇權 GEX（造市商 gamma 部位）——期交所開放資料，免費、免金鑰、零 AI。

2026-10-08 Leo 看到老墨直播的「避震器／油門」頁面，問「我們怎麼監控」→ 自己算。

資料（openapi.taifex.com.tw/v1，收盤後才彙整、**不是即時**）：
  · DailyMarketReportOpt  選擇權每日行情（履約價×到期×買賣權；結算價、未平倉量只在「一般」時段有）
  · DailyOptionsDelta     各到期日的最後結算日（ContractSettlementDay）
  · DailyMarketReportFut  台指期（TX）最後成交價＝「現價」
⚠️ 同一網址格式會變（JSON／CSV、英文／中文欄名），沿用 night_session 的作法兩種都吃；取不到會明講。

算法（標準 dealer-gamma 假設：客戶買、造市商賣 → 買權 +、賣權 −）：
  1. 每個到期日用「買賣權平價」從結算價反推遠期價 F_e
  2. Black-76 用結算價反推隱含波動率 → gamma
  3. GEX（億元／指數漲跌 1%）＝ gamma × 未平倉量 × 50 元/點 × F² × 1% ÷ 1e8
     （老墨頁面「58 口大台」＝淨 GEX ÷（現價×200），單位一致）
  4. 買權牆＝正 GEX 最大履約價；賣權牆＝負 GEX 最大履約價；
     翻轉點＝假想指數上下移動時，總 GEX 由正轉負的價位（隱含波動率固定在原履約價）

不是買賣訊號——只描述「造市商被迫對沖的方向」。
"""
import csv
import datetime as dt
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data", "gex")
BASE = "https://openapi.taifex.com.tw/v1/"

# 校準用參數（2026-10-08 對老墨頁面調整，見 dev_log）
PARAMS = {
    "r": 0.015,            # 無風險利率
    "mult": 50,            # 台指選擇權每點 50 元
    "fut_mult": 200,       # 大台每點 200 元（換算「口數」用）
    "min_t_days": 0.5,     # 到期當天 T 的下限（日）
    "forward": "parity",   # parity＝每個到期日用平價反推；spot＝全部用現價
    "max_expiries": 99,    # 納入最近幾個到期日
}

_KEYS = {
    "date": ("Date", "日期"),
    "contract": ("Contract", "契約"),
    "month": ("ContractMonth(Week)", "到期月份(週別)"),
    "strike": ("StrikePrice", "履約價"),
    "cp": ("CallPut", "買賣權"),
    "settle": ("SettlementPrice", "結算價"),
    "oi": ("OpenInterest", "未沖銷契約數"),
    "last": ("Last", "最後成交價"),
    "session": ("TradingSession", "交易時段"),
    "sday": ("ContractSettlementDay", "最後結算日"),
}


def _g(row, name):
    for k in _KEYS[name]:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return ""


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def _load_rows(raw):
    txt = raw.decode("utf-8-sig", "replace") if isinstance(raw, bytes) else raw
    if txt.lstrip()[:1] in ("[", "{"):
        data = json.loads(txt)
        return data if isinstance(data, list) else data.get("data", [])
    rows = list(csv.DictReader(io.StringIO(txt)))
    if not rows:
        raise ValueError("回傳不是 JSON 也不是 CSV（前 80 字：%r）" % txt[:80])
    return rows


def _fetch(name):
    import requests
    err = ""
    for _ in range(2):
        try:
            r = requests.get(BASE + name, headers={"accept": "application/json"}, timeout=60)
            r.raise_for_status()
            return _load_rows(r.content)
        except Exception as e:  # noqa: BLE001
            err = str(e)[:100]
    raise RuntimeError(f"{name} 取得失敗（{err}）")


# ───────── 數學 ─────────
def _N(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _price(F, K, T, s, cp, r):
    d1 = (math.log(F / K) + .5 * s * s * T) / (s * math.sqrt(T))
    d2 = d1 - s * math.sqrt(T)
    df = math.exp(-r * T)
    return df * (F * _N(d1) - K * _N(d2)) if cp == "C" else df * (K * _N(-d2) - F * _N(-d1))


def _iv(p, F, K, T, cp, r):
    intrinsic = max(0.0, (F - K) if cp == "C" else (K - F)) * math.exp(-r * T)
    if p <= intrinsic + 1e-9:
        return None
    lo, hi = 0.01, 3.0
    if _price(F, K, T, hi, cp, r) < p:
        return None
    for _ in range(50):
        m = (lo + hi) / 2
        if _price(F, K, T, m, cp, r) > p:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def _gamma(F, K, T, s, r):
    d1 = (math.log(F / K) + .5 * s * s * T) / (s * math.sqrt(T))
    return math.exp(-r * T) * math.exp(-.5 * d1 * d1) / math.sqrt(2 * math.pi) / (F * s * math.sqrt(T))


# ───────── 組裝 ─────────
def load_inputs():
    """抓三份原始資料 → (opt_rows, expiry_map, spot, date)。失敗丟 RuntimeError（呼叫端明講）。"""
    opt = _fetch("DailyMarketReportOpt")
    dl = _fetch("DailyOptionsDelta")
    fut = _fetch("DailyMarketReportFut")
    return parse_inputs(opt, dl, fut)


def parse_inputs(opt, dl, fut):
    txo = [o for o in opt if _g(o, "contract") == "TXO" and "盤後" not in _g(o, "session")]
    if not txo:
        raise RuntimeError("期交所資料裡沒有台指選擇權（可能還沒彙整）")
    date = max(_g(o, "date") for o in txo)
    txo = [o for o in txo if _g(o, "date") == date]
    expiry = {}
    for d in dl:
        if _g(d, "contract") == "TXO" and _g(d, "sday"):
            expiry[_g(d, "month")] = _g(d, "sday")
    tx = [x for x in fut if _g(x, "contract") == "TX" and "盤後" not in _g(x, "session")
          and _g(x, "date") == date and _g(x, "month").isdigit() and len(_g(x, "month")) == 6
          and _num(_g(x, "last")) is not None]
    if not tx:
        raise RuntimeError("期交所資料裡沒有台指期日盤成交價")
    near = min(tx, key=lambda x: _g(x, "month"))          # 最近月份（日盤＝一般時段）
    spot = _num(_g(near, "last"))
    return txo, expiry, spot, date


def _rows_to_quotes(txo, expiry, date, params):
    """→ {month: {"T":年, "sday":date, "q":[(K, cp, settle, oi)]}}"""
    today = dt.datetime.strptime(date, "%Y%m%d").date()
    out = {}
    for o in txo:
        m = _g(o, "month")
        e = expiry.get(m)
        if not e:
            continue
        K, sp, oi = _num(_g(o, "strike")), _num(_g(o, "settle")), _num(_g(o, "oi"))
        cpraw = _g(o, "cp")
        cp = "C" if ("買" in cpraw or cpraw.upper().startswith("C")) else ("P" if ("賣" in cpraw or cpraw.upper().startswith("P")) else None)
        if None in (K, sp, oi) or cp is None or sp <= 0:
            continue
        days = (dt.datetime.strptime(e, "%Y%m%d").date() - today).days
        if days < 0:
            continue
        T = max(days, params["min_t_days"]) / 365.0
        out.setdefault(m, {"T": T, "sday": e, "q": []})["q"].append((K, cp, sp, oi))
    return out


def _forward(q, T, spot, params):
    if params["forward"] == "spot":
        return spot
    r = params["r"]
    calls = {K: sp for K, cp, sp, _ in q if cp == "C"}
    puts = {K: sp for K, cp, sp, _ in q if cp == "P"}
    both = [K for K in calls if K in puts]
    if not both:
        return spot
    K0 = min(both, key=lambda K: abs(calls[K] - puts[K]))
    return K0 + (calls[K0] - puts[K0]) * math.exp(r * T)


def compute(txo, expiry, spot, date, params=None):
    p = dict(PARAMS, **(params or {}))
    r = p["r"]
    groups = _rows_to_quotes(txo, expiry, date, p)
    months = sorted(groups, key=lambda m: groups[m]["sday"])[:p["max_expiries"]]
    legs = []            # (month, K, cp, oi, T, F, iv)
    for m in months:
        g = groups[m]
        F = _forward(g["q"], g["T"], spot, p)
        for K, cp, sp, oi in g["q"]:
            if oi <= 0:
                continue
            s = _iv(sp, F, K, g["T"], cp, r)
            if s:
                legs.append((m, K, cp, oi, g["T"], F, s))
    if not legs:
        raise RuntimeError("算不出任何一檔有未平倉的 IV（資料異常）")

    def gex_at(S, only_month=None):
        """假想現價 S 時，各履約價的 GEX（億元/1%）。遠期價隨現價等比移動。"""
        by = {}
        for m, K, cp, oi, T, F, s in legs:
            if only_month and m != only_month:
                continue
            Fs = F * S / spot
            g = _gamma(Fs, K, T, s, r) * oi * p["mult"] * Fs * Fs * 0.01 / 1e8
            by[K] = by.get(K, 0.0) + (g if cp == "C" else -g)
        return by

    by = gex_at(spot)
    net = sum(by.values())
    call_wall = max(by, key=lambda k: by[k])
    put_wall = min(by, key=lambda k: by[k])

    # 翻轉點：現價上下 ±8% 掃，找離現價最近的變號點（線性內插）
    grid = [spot * (1 + i / 400.0) for i in range(-32, 33)]          # 每 0.25%
    tot = [(S, sum(gex_at(S).values())) for S in grid]
    flips = []
    for (s0, g0), (s1, g1) in zip(tot, tot[1:]):
        if g0 == 0:
            flips.append(s0)
        elif g0 * g1 < 0:
            flips.append(s0 + (s1 - s0) * (0 - g0) / (g1 - g0))
    flip = min(flips, key=lambda x: abs(x - spot)) if flips else None

    rows = sorted(by.items())
    near = [(k, round(v, 3)) for k, v in rows if spot * 0.92 <= k <= spot * 1.08]
    return {
        "date": date, "spot": spot, "net_gex": round(net, 3),
        "contracts": round(net * 1e8 / (spot * p["fut_mult"]), 1),
        "call_wall": call_wall, "call_wall_gex": round(by[call_wall], 3),
        "put_wall": put_wall, "put_wall_gex": round(by[put_wall], 3),
        "flip": round(flip) if flip else None,
        "expiries": [{"month": m, "sday": groups[m]["sday"]} for m in months],
        "by_strike": near, "params": p, "n_legs": len(legs),
    }


def run(save=True, params=None):
    txo, expiry, spot, date = load_inputs()
    res = compute(txo, expiry, spot, date, params)
    if save:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, f"gex_{date}.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        # 首頁（跑在 Actions、看不到被 gitignore 的 data/）讀這份精簡版
        slim = {k: res[k] for k in ("date", "spot", "net_gex", "call_wall", "put_wall", "flip")}
        os.makedirs(os.path.join(HERE, "state"), exist_ok=True)
        with open(os.path.join(HERE, "state", "gex_latest.json"), "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False)
    return res


def _one_line(res):
    s = res["spot"]
    state = "避震器（正 GEX）" if res["net_gex"] > 0 else "油門（負 GEX）"
    fl = res["flip"]
    where = ""
    if fl:
        where = "，在翻轉點 %s 上方 %+d 點" % (f"{fl:,}", round(s - fl)) if s >= fl else "，已跌破翻轉點 %s（%d 點）" % (f"{fl:,}", round(fl - s))
    return (f"整體偏{state}{where}；上方買權牆 {res['call_wall']:,.0f}（{res['call_wall_gex']:+.1f} 億）、"
            f"下方賣權牆 {res['put_wall']:,.0f}（{res['put_wall_gex']:+.1f} 億）；淨 GEX {res['net_gex']:+.1f} 億"
            f"（指數每動 1% 造市商約對沖 {abs(res['contracts']):.0f} 口大台）")


def summary_line(today=None):
    """給 08:45 戰情用：讀最近一次存好的 latest.json（不在早上重抓）。取不到就明講。"""
    t = dt.date.fromisoformat(today) if today else dt.date.today()
    try:
        with open(os.path.join(OUT_DIR, "latest.json"), encoding="utf-8") as f:
            res = json.load(f)
    except (OSError, ValueError):
        return "⚠️ **台指選擇權 GEX**：還沒有資料（排程尚未成功跑過）"
    d = dt.datetime.strptime(res["date"], "%Y%m%d").date()
    stale = ""
    exp = t - dt.timedelta(days=1)
    while exp.weekday() >= 5:
        exp -= dt.timedelta(days=1)
    if d < exp:
        stale = f"　⚠️ 資料只到 {d:%m/%d}，較新的還沒算出來"
    return (f"🧲 **台指選擇權 GEX**（{d:%m/%d} 日盤收盤 {res['spot']:,.0f}）{_one_line(res)}{stale}"
            f"　-# 期交所收盤後彙整、非即時・只描述對沖方向，不是買賣訊號")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    r = run()
    print(_one_line(r))
    print({k: v for k, v in r.items() if k not in ("by_strike", "params", "expiries")})
