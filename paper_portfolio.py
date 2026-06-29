"""策略賽馬：產業鏈 vs 巴菲特，真實買股模擬（股數×價格），每週調倉、每日記市值。

2 主倉各投 $10,000 美金：
  ① 產業鏈全：7 鏈守備清單全買，等權重
  ② 巴菲特價值：現價≤俗價折價最大前 30，等權重
另含 7 鏈明細倉（各 $10,000）。

真實模擬：起始把 $10,000 等分買進（可買零股），記下每股「股數/進場價」。
台股價格用即時匯率換成美金 → 全部用美金加總。每日更新現價算市值與損益，
每週跟清單調倉（賣舊買新，市值接續）。

用法:python paper_portfolio.py [init|rebalance|nav]
"""
import sys
import json
import os
from datetime import datetime
import yfinance as yf

STORE = "portfolios.json"
SCREEN = "screen_result.json"
BUFFETT = "buffett_watch.json"
BASE = 10000.0
BUFFETT_NAME = "巴菲特價值"
CHAIN_ALL = "產業鏈精選"
CHAIN_TREND = "產業鏈+趨勢"
BUFFETT_TOPN = 30
TOP_PER_CHAIN = 2              # 產業鏈精選：每鏈取分數最高前 N（重點壓 ~14 檔）
MAIN = [CHAIN_ALL, CHAIN_TREND, BUFFETT_NAME]
FX_FALLBACK = 32.0              # USD/TWD 備援匯率


def tw_yf(code):
    return f"{code}.TW" if str(code).isdigit() else str(code)


def is_tw(tk):
    return tk.endswith(".TW")


def get_fx():
    """USD/TWD（1 美元 = X 台幣），抓不到用備援。"""
    try:
        d = yf.download("TWD=X", period="5d", progress=False, threads=False)
        v = float(d["Close"].dropna().iloc[-1])
        return v if 25 < v < 40 else FX_FALLBACK
    except Exception:
        return FX_FALLBACK


def to_usd(tk, native, fx):
    """台股價(台幣)→美金；美股原樣。"""
    if native is None:
        return None
    return native / fx if is_tw(tk) else native


def chain_holdings():
    d = json.load(open(SCREEN, encoding="utf-8"))
    out = {}
    for chain in d.get("us", {}):
        us = [x["code"] for x in d["us"].get(chain, [])]
        tw = [tw_yf(x["code"]) for x in d["tw"].get(chain, [])]
        out[chain] = sorted(set(us + tw))
    return out


def chain_top_picks(n=TOP_PER_CHAIN):
    """每鏈取分數最高前 n（美+台合併按 score 排）。回 {chain: [yf_ticker,...]}。"""
    d = json.load(open(SCREEN, encoding="utf-8"))
    out = {}
    for chain in d.get("us", {}):
        items = [(x["code"], x.get("score", 0)) for x in d["us"].get(chain, [])]
        items += [(tw_yf(x["code"]), x.get("score", 0)) for x in d["tw"].get(chain, [])]
        items.sort(key=lambda z: -z[1])
        out[chain] = [c for c, _ in items[:n]]
    return out


def chain_select_union():
    """產業鏈精選 = 各鏈前 N 聯集。"""
    return sorted({t for v in chain_top_picks().values() for t in v})


def _supertrend_dir(highs, lows, closes, period=10, mult=3.0):
    """標準 SuperTrend（ATR/Wilder），回最新方向 1多/-1空；資料不足回 1。
    （複製自 board_html.supertrend，避免拉進 markdown/opencc 依賴。）"""
    n = len(closes)
    if n < period + 1 or not highs or not lows:
        return 1
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(n)]
    up = lo = None
    dr = 1
    for i in range(period - 1, n):
        if atr[i] is None:
            continue
        bu, bl = hl2[i] + mult * atr[i], hl2[i] - mult * atr[i]
        if up is None:
            up, lo = bu, bl
            dr = 1 if closes[i] >= hl2[i] else -1
        else:
            nu = bu if (bu < up or closes[i - 1] > up) else up
            nl = bl if (bl > lo or closes[i - 1] < lo) else lo
            if closes[i] > up:
                dr = 1
            elif closes[i] < lo:
                dr = -1
            up, lo = nu, nl
    return dr


def trend_longs(tickers):
    """從候選裡只留 SuperTrend 多頭（綠燈）的；抓不到 OHLC 的保留（不過濾）。"""
    if not tickers:
        return []
    data = yf.download(sorted(tickers), period="3mo", progress=False,
                       threads=False, auto_adjust=True, group_by="ticker")
    longs = []
    for tk in tickers:
        try:
            df = data[tk].dropna()
            d = _supertrend_dir(df["High"].tolist(), df["Low"].tolist(), df["Close"].tolist())
            if d == 1:
                longs.append(tk)        # 多頭（資料不足時 _supertrend_dir 回 1 → 保留）
        except Exception:
            longs.append(tk)
    return sorted(longs)


def _hong_score(rank, roe, rr):
    """洪瑞泰品質分：龍頭 + 高ROE + 低盈再率（好生意=不用一直砸錢就會賺）。"""
    s = {1: 3, 2: 2, 3: 1}.get(rank, 0)        # 龍頭加權（產業龍頭優先）
    s += min(roe or 0, 0.6) * 3                  # ROE 越高越好
    if rr is not None:
        s += max(0, 0.80 - rr) * 4              # 盈再率越低越好（權重最高）
    return s


def buffett_top30(prices):
    """洪瑞泰選股：好公司（龍頭 + ROE≥15% + 盈再率<80% + 排照妖鏡）在便宜時買。
    優先現價≤俗價，不足 30 才放寬到≤合理價。取品質分前 30。"""
    wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
    tier1, tier2 = [], []   # ≤俗價 / ≤合理價
    for tk, d in wl.items():
        p, cheap, fair = prices.get(tk), d.get("cheap"), d.get("fair")
        roe, rr = d.get("roe") or 0, d.get("reinvest")
        if not (p and cheap and fair):
            continue
        if d.get("trap_flags"):           # 照妖鏡：EPS估降/高負債 → 排除
            continue
        if roe < 0.15:                     # 洪瑞泰第一關：ROE ≥ 15%
            continue
        if rr is not None and rr >= 0.80:  # 第二關：盈再率 < 80%（吃資本的爛生意淘汰）
            continue
        s = _hong_score(d.get("rank"), roe, rr)
        if p <= cheap:
            tier1.append((tk, s))
        elif p <= fair:
            tier2.append((tk, s))
    tier1.sort(key=lambda x: -x[1])
    tier2.sort(key=lambda x: -x[1])
    picked = [tk for tk, _ in tier1[:BUFFETT_TOPN]]
    if len(picked) < BUFFETT_TOPN:
        picked += [tk for tk, _ in tier2[:BUFFETT_TOPN - len(picked)]]
    return sorted(picked)


def _batch(tickers):
    out = {}
    if not tickers:
        return out
    data = yf.download(tickers, period="5d", progress=False, threads=False,
                       auto_adjust=True, group_by="ticker")
    for tk in tickers:
        try:
            out[tk] = float(data[tk]["Close"].dropna().iloc[-1])
        except Exception:
            pass
    return out


def fetch_prices(tickers):
    """回原幣別現價（美股美元、台股台幣）。台股 .TW 抓不到退 .TWO。"""
    tickers = sorted(set(tickers))
    out = _batch(tickers)
    miss = {tk: tk.replace(".TW", ".TWO") for tk in tickers
            if tk.endswith(".TW") and tk not in out}
    if miss:
        two = _batch(list(miss.values()))
        for orig, tc in miss.items():
            if tc in two:
                out[orig] = two[tc]
    return out


def build_holdings_map(prices):
    """3 主倉 + 7 鏈明細。
    產業鏈精選=各鏈前N聯集；產業鏈+趨勢=精選裡只留SuperTrend多頭；巴菲特=折價前30。"""
    select = chain_select_union()
    m = {CHAIN_ALL: select,
         CHAIN_TREND: trend_longs(select),
         BUFFETT_NAME: buffett_top30(prices)}
    m.update(chain_holdings())   # 7 鏈明細（各鏈完整守備清單）
    return m


def load():
    return json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else None


def save(state):
    json.dump(state, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _alloc_shares(tickers, capital, prices, fx):
    """把 capital 等分買進 tickers，回 {tk: {sh,eu,en}}（eu=進場美金價,en=進場原幣價）。"""
    valid = [t for t in tickers if prices.get(t)]
    if not valid:
        return {}
    each = capital / len(valid)
    h = {}
    for t in valid:
        pu = to_usd(t, prices[t], fx)
        if pu and pu > 0:
            h[t] = {"sh": round(each / pu, 4), "eu": round(pu, 4), "en": round(prices[t], 2)}
    return h


def _value(pf, prices, fx):
    """市值（美金）= Σ 股數 × 現價(美金)；無現價的用進場價（視為持平）。"""
    v = 0.0
    for tk, h in pf["holdings"].items():
        pu = to_usd(tk, prices.get(tk), fx) or h["eu"]
        v += h["sh"] * pu
    return round(v, 2)


def _refresh_current(pf, prices, fx):
    """把每股現價(原幣)寫回 holdings，html 直接讀。"""
    for tk, h in pf["holdings"].items():
        if prices.get(tk):
            h["cur"] = round(prices[tk], 2)
            h["cu"] = round(to_usd(tk, prices[tk], fx), 4)


def _all_tickers(state):
    s = set()
    for pf in state["portfolios"].values():
        s.update(pf["holdings"].keys())
    return s


def update_nav(state, prices, fx, date):
    for pf in state["portfolios"].values():
        _refresh_current(pf, prices, fx)
        v = _value(pf, prices, fx)
        pf["value"] = v
        pf["pnl"] = round(v - BASE, 2)
        pf["ret"] = round((v / BASE - 1) * 100, 2)
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, v])
        else:
            pf["history"][-1][1] = v
    state["updated"] = date
    state["fx"] = round(fx, 3)


def rebalance(state, hmap, prices, fx, date):
    for name, pf in state["portfolios"].items():
        v = _value(pf, prices, fx) if pf["holdings"] else BASE
        pf["holdings"] = _alloc_shares(hmap.get(name, list(pf["holdings"])), v, prices, fx)
        _refresh_current(pf, prices, fx)
        pf["value"] = round(v, 2)
        pf["pnl"] = round(v - BASE, 2)
        pf["ret"] = round((v / BASE - 1) * 100, 2)
        pf["rebalanced"] = date
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, round(v, 2)])
    state["updated"] = date
    state["fx"] = round(fx, 3)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "nav"
    date = datetime.now().strftime("%Y-%m-%d")

    if cmd == "init":
        if load():
            print("portfolios.json 已存在")
            return
        chains = chain_holdings()
        wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
        allt = set(wl.keys())
        for v in chains.values():
            allt.update(v)
        fx = get_fx()
        prices = fetch_prices(allt)
        hmap = build_holdings_map(prices)
        state = {"inception": date, "updated": date, "base": BASE, "fx": round(fx, 3),
                 "main": MAIN, "portfolios": {}}
        for name, hold in hmap.items():
            h = _alloc_shares(hold, BASE, prices, fx)
            pf = {"holdings": h, "value": BASE, "pnl": 0.0, "ret": 0.0,
                  "rebalanced": date, "history": [[date, BASE]]}
            _refresh_current(pf, prices, fx)
            state["portfolios"][name] = pf
        save(state)
        print(f"✅ init：{len(state['portfolios'])} 倉，各 ${BASE:,.0f}，匯率 {fx:.2f}，起始 {date}")
        for n, pf in state["portfolios"].items():
            print(f"  [{'主' if n in MAIN else '鏈'}] {n}: {len(pf['holdings'])} 檔")
        return

    state = load()
    if not state:
        print("無 portfolios.json，先 init")
        return
    fx = get_fx()

    if cmd == "rebalance":
        allt = _all_tickers(state) | set(json.load(open(BUFFETT, encoding="utf-8")).keys())
        prices = fetch_prices(allt)
        rebalance(state, build_holdings_map(prices), prices, fx, date)
        save(state)
        print(f"✅ rebalance {date}（匯率 {fx:.2f}）")
        for n, pf in state["portfolios"].items():
            print(f"  {n}: {len(pf['holdings'])} 檔 ${pf['value']:,.0f} ({pf['ret']:+.2f}%)")
    elif cmd == "nav":
        prices = fetch_prices(_all_tickers(state))
        update_nav(state, prices, fx, date)
        save(state)
        rank = sorted(state["portfolios"].items(), key=lambda kv: -kv[1]["ret"])
        print(f"✅ nav {date}（匯率 {fx:.2f}）:")
        for n, pf in rank:
            print(f"  {pf['ret']:+6.2f}%  ${pf['value']:>9,.0f}  損益 {pf['pnl']:+,.0f}  {n}")


if __name__ == "__main__":
    main()
