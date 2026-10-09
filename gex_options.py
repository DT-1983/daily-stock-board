# -*- coding: utf-8 -*-
"""台指選擇權 GEX（造市商 gamma 部位）——期交所開放資料，免費、免金鑰、零 AI。

2026-10-08 Leo 看到老墨直播的「避震器／油門」頁面，問「我們怎麼監控」→ 自己算。

資料（openapi.taifex.com.tw/v1，收盤後才彙整、**不是即時**）：
  · DailyMarketReportOpt  選擇權每日行情（履約價×到期×買賣權；結算價、未平倉量只在「一般」時段有）
  · DailyOptionsDelta     各到期日的最後結算日（ContractSettlementDay）
  · DailyMarketReportFut  台指期（TX）最後成交價＝「現價」
⚠️ 同一網址格式會變（JSON／CSV、英文／中文欄名），沿用 night_session 的作法兩種都吃；取不到會明講。

算法（業界常見的簡化：買權 GEX 算正、賣權 GEX 算負；實際造市商部位看不到，這只是假設，2026-10-09 更正原本「客戶買、造市商賣」的不精確說法）：
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
    "t_offset": 0.0,       # 距到期日數另加（日）
    "year_days": 365.0,    # 一年幾天
    "iv_mode": "own",      # own＝各自反推；otm＝同履約價共用價外那邊的 IV
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
WEB = "https://www.taifex.com.tw/cht/3/"


def _web_post(page, data):
    import requests
    r = requests.post(WEB + page, data=data, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
    r.raise_for_status()
    return r.content.decode("utf-8", "replace")


def _web_rows(html_text):
    import html as _h
    import re
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I):
        c = [_h.unescape(re.sub(r"<[^>]+>", "", x)).strip()
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
        if c:
            out.append(c)
    return out


def fetch_web(day):
    """期交所網站「每日行情」（日盤收盤後約 14:00 就有，比 OpenAPI 檔早一個晚上）。
    回 (txo, expiry, spot, date)；該日沒資料（假日／尚未發布）回 None；網頁改版會丟 RuntimeError。"""
    q = day.strftime("%Y/%m/%d")
    base = {"queryType": "2", "marketCode": "0", "MarketCode": "0", "queryDate": q}
    t = _web_post("optDailyMarketReport", dict(base, commodity_id="TXO", commodity_idt="TXO", settlemon="", pc="", cp="", strike=""))
    txo, expiry = [], {}
    for c in _web_rows(t):
        # 契約, 月份, 到期日, 履約價, 買賣權, 開, 高, 低, 收, 結算, 漲跌, %, 盤後量, 一般量, 合計量, 未沖銷, 買, 賣, 歷高, 歷低
        if len(c) >= 20 and c[0] == "TXO" and c[2].isdigit():
            expiry[c[1]] = c[2]
            txo.append({"Date": day.strftime("%Y%m%d"), "Contract": "TXO", "ContractMonth(Week)": c[1],
                        "StrikePrice": c[3], "CallPut": c[4], "SettlementPrice": c[9],
                        "OpenInterest": c[15], "TradingSession": "一般"})
    if not txo:
        return None
    if not any(_num(o["OpenInterest"]) for o in txo):         # 有列但沒有未平倉量＝還沒發布
        return None
    tf = _web_post("futDailyMarketReport", dict(base, commodity_id="TX", commodity_idt="TX"))
    tx = [c for c in _web_rows(tf) if len(c) >= 10 and c[0] == "TX" and c[1].isdigit() and len(c[1]) == 6
          and _num(c[5]) is not None]
    if not tx:
        raise RuntimeError("期交所網站有選擇權資料但找不到台指期日盤成交價（網頁可能改版）")
    spot = _num(min(tx, key=lambda c: c[1])[5])
    return txo, expiry, spot, day.strftime("%Y%m%d")


def load_inputs(today=None):
    """優先用期交所網站當日資料（收盤後約 14:00 起）；沒有就往前找最近一個有資料的交易日；
    網站失敗才退回 OpenAPI 檔（隔天清晨才含前一日）。"""
    t = today or dt.date.today()
    web_err = ""
    try:
        for back in range(0, 6):
            d = t - dt.timedelta(days=back)
            if d.weekday() >= 5:
                continue
            got = fetch_web(d)
            if got:
                return got
    except Exception as e:  # noqa: BLE001
        web_err = str(e)[:100]
        print(f"[gex] 期交所網站取得失敗，改用 OpenAPI：{web_err}")
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
        T = max(days + params["t_offset"], params["min_t_days"]) / params["year_days"]
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


def _expiry_labels(items):
    """[(月份碼, 最後結算日YYYYMMDD)] → ['10/12（一）週選', ...]；月份碼無 W／F 者：前三個月為月選、其後季選。"""
    wd = "一二三四五六日"
    plain = sorted(m for m, _ in items if m.isdigit())
    monthly = set(plain[:3])
    out = []
    for m, e in items:
        d = dt.datetime.strptime(e, "%Y%m%d")
        kind = "週選" if not m.isdigit() else ("月選" if m in monthly else "季選")
        out.append(f"{d.month}/{d.day}（{wd[d.weekday()]}）{kind}")
    return out


def compute(txo, expiry, spot, date, params=None):
    p = dict(PARAMS, **(params or {}))
    r = p["r"]
    groups = _rows_to_quotes(txo, expiry, date, p)
    months = sorted(groups, key=lambda m: groups[m]["sday"])[:p["max_expiries"]]
    legs = []            # (month, K, cp, oi, T, F, iv)
    for m in months:
        g = groups[m]
        F = _forward(g["q"], g["T"], spot, p)
        otm_iv = {}
        if p["iv_mode"] == "otm":          # 價內外選擇權的結算價含大量內含價值、噪音大 → 同履約價買賣權共用「價外那一邊」的 IV
            for K, cp, sp, oi in g["q"]:
                if (cp == "C" and K >= F) or (cp == "P" and K <= F):
                    v = _iv(sp, F, K, g["T"], cp, r)
                    if v:
                        otm_iv[K] = v
        atm_iv = None
        if p["iv_mode"] == "atm":          # 每個到期日只用一條平的 IV（最接近遠期價那一檔）
            ks = sorted({K for K, *_ in g["q"]}, key=lambda k: abs(k - F))
            for K0 in ks[:6]:
                vs = [_iv(sp, F, K, g["T"], cp, r) for K, cp, sp, oi in g["q"] if K == K0]
                vs = [v for v in vs if v]
                if vs:
                    atm_iv = sum(vs) / len(vs)
                    break
        for K, cp, sp, oi in g["q"]:
            if oi <= 0:
                continue
            s = atm_iv or otm_iv.get(K) or _iv(sp, F, K, g["T"], cp, r)
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

    ev = p.get("eval_spot") or spot          # 用資料日的價格反推 IV，再用「現在的價」評估 gamma
    by = gex_at(ev)
    net = sum(by.values())
    call_wall = max(by, key=lambda k: by[k])
    put_wall = min(by, key=lambda k: by[k])

    # 翻轉點：現價上下 ±8% 掃，找離現價最近的變號點（線性內插）
    grid = [ev * (1 + i / 400.0) for i in range(-32, 33)]          # 每 0.25%
    tot = [(S, sum(gex_at(S).values())) for S in grid]
    flips = []
    for (s0, g0), (s1, g1) in zip(tot, tot[1:]):
        if g0 == 0:
            flips.append(s0)
        elif g0 * g1 < 0:
            flips.append(s0 + (s1 - s0) * (0 - g0) / (g1 - g0))
    flip = min(flips, key=lambda x: abs(x - ev)) if flips else None

    rows = sorted(by.items())
    near = [(k, round(v, 3)) for k, v in rows if ev * 0.92 <= k <= ev * 1.08]

    # 價格假設曲線：假設台指期在各價位時的總 GEX（其他條件不變），每 0.25%、±7%
    profile = [[round(ev * (1 + i / 400.0)), round(sum(gex_at(ev * (1 + i / 400.0)).values()), 2)]
               for i in range(-28, 29)]

    # 到期日×履約價矩陣（3D／熱力圖）：GEX、未平倉（買／賣）、隱含波動率
    lo, hi = ev * 0.92, ev * 1.08
    strikes = sorted({K for m in months for K, *_ in groups[m]["q"] if lo <= K <= hi and K % 50 == 0})
    idx = {K: i for i, K in enumerate(strikes)}
    exp_labels = _expiry_labels([(m, groups[m]["sday"]) for m in months])
    gex_m, oic_m, oip_m, iv_m = [], [], [], []
    for m in months:
        g = groups[m]
        F = _forward(g["q"], g["T"], spot, p)
        gx = gex_at(ev, only_month=m)
        gex_m.append([round(gx.get(K, 0.0), 3) for K in strikes])
        oc, op, ivs = [0] * len(strikes), [0] * len(strikes), [None] * len(strikes)
        for K, cp, sp, oi in g["q"]:
            if K in idx:
                if cp == "C":
                    oc[idx[K]] += int(oi)
                else:
                    op[idx[K]] += int(oi)
                if (cp == "C" and K >= F) or (cp == "P" and K <= F):
                    v = _iv(sp, F, K, g["T"], cp, r)
                    if v:
                        ivs[idx[K]] = round(v * 100, 1)
        oic_m.append(oc); oip_m.append(op); iv_m.append(ivs)
    matrix = {"expiries": exp_labels, "strikes": strikes, "gex": gex_m, "oi_call": oic_m, "oi_put": oip_m, "iv": iv_m}
    return {
        "date": date, "spot": ev, "net_gex": round(net, 3),
        "contracts": round(net * 1e8 / (ev * p["fut_mult"]), 1),
        "call_wall": call_wall, "call_wall_gex": round(by[call_wall], 3),
        "put_wall": put_wall, "put_wall_gex": round(by[put_wall], 3),
        "flip": round(flip) if flip else None,
        "expiries": [{"month": m, "sday": groups[m]["sday"]} for m in months],
        "by_strike": near, "params": p, "n_legs": len(legs),
        "profile": profile, "matrix": matrix,
    }


def _robustness(txo, expiry, spot, date, main):
    """換幾種合理的算法（遠期價取法×IV 取法）重算，看淨 GEX 正負與翻轉點是否一致。
    2026-10-08 實測：同一份資料淨 GEX 可從 -7 到 +17 億，所以「避震器／油門」的判斷不能只信一種算法。"""
    out = []
    for fw, iv in (("parity", "own"), ("parity", "otm"), ("spot", "own"), ("spot", "otm")):
        try:
            r = compute(txo, expiry, spot, date, {"forward": fw, "iv_mode": iv})
            out.append({"fw": fw, "iv": iv, "net": r["net_gex"], "flip": r["flip"],
                        "call_wall": r["call_wall"], "put_wall": r["put_wall"]})
        except Exception:  # noqa: BLE001
            continue
    nets = [v["net"] for v in out] + [main["net_gex"]]
    flips = [v["flip"] for v in out if v["flip"]] + ([main["flip"]] if main["flip"] else [])
    return {"variants": out,
            "sign_agree": all(n > 0 for n in nets) or all(n < 0 for n in nets),
            "net_lo": round(min(nets), 1), "net_hi": round(max(nets), 1),
            "flip_lo": min(flips) if flips else None, "flip_hi": max(flips) if flips else None,
            "walls_agree": len({(v["call_wall"], v["put_wall"]) for v in out} | {(main["call_wall"], main["put_wall"])}) == 1}


def run(save=True, params=None):
    txo, expiry, spot, date = load_inputs()
    res = compute(txo, expiry, spot, date, params)
    res["robust"] = _robustness(txo, expiry, spot, date, res)
    if save:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, f"gex_{date}.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        # 首頁（跑在 Actions、看不到被 gitignore 的 data/）讀這份精簡版
        slim = {k: res[k] for k in ("date", "spot", "net_gex", "call_wall", "put_wall", "flip")}
        slim["sign_agree"] = res["robust"]["sign_agree"]
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
    rb = res.get("robust") or {}
    caveat = ""
    if rb and not rb.get("sign_agree", True):
        caveat = f"　⚠️ 不同算法對偏避震器／偏油門看法不一（淨 GEX {rb['net_lo']:+.0f}～{rb['net_hi']:+.0f} 億），只有牆比較可靠"
    size_note = (f"（換算法 {rb['net_lo']:+.0f}～{rb['net_hi']:+.0f} 億，大小僅供參考）" if rb else "")
    return (f"整體偏{state}{where}{caveat}；上方買權牆 {res['call_wall']:,.0f}（{res['call_wall_gex']:+.1f} 億）、"
            f"下方賣權牆 {res['put_wall']:,.0f}（{res['put_wall_gex']:+.1f} 億）；淨 GEX {res['net_gex']:+.1f} 億"
            f"{size_note}（指數每動 1% 造市商約對沖 {abs(res['contracts']):.0f} 口大台）")


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
    # Discord 的「-#」小字必須在「行首」才會生效；放在句中會原樣顯示（2026-10-09 Leo 手機看到「-#」）→ 另起一行
    return (f"🧲 **台指選擇權 GEX**（{d:%m/%d} 日盤收盤 {res['spot']:,.0f}）{_one_line(res)}{stale}"
            "\n-# 期交所收盤後彙整、非即時・只描述對沖方向，不是買賣訊號")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    r = run()
    print(_one_line(r))
    print({k: v for k, v in r.items() if k not in ("by_strike", "params", "expiries")})
