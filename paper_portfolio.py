"""策略賽馬：產業鏈 vs 巴菲特，紙上模擬倉，每週調倉、每日記淨值。

2 主倉對決：
  ① 產業鏈全：7 條鏈守備清單全買，等權重，$10,000
  ② 巴菲特價值：現價≤俗價中折價最大前 30，等權重，$10,000
另含 7 鏈明細倉（各 $10,000）看哪條鏈領先。

淨值＝$10,000 ×（等權重報酬因子）：用各股報酬率(%)算，美股美元、台股台幣 →
天生免換匯，純比選股。每週跟清單調倉，淨值接續累計。

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
BASE = 10000.0                  # 每倉起始本金（美金）
BUFFETT_NAME = "巴菲特價值"
CHAIN_ALL = "產業鏈全"
BUFFETT_TOPN = 30
MAIN = [CHAIN_ALL, BUFFETT_NAME]  # 2 主倉（其餘為 7 鏈明細）


def tw_yf(code):
    return f"{code}.TW" if str(code).isdigit() else str(code)


def chain_holdings():
    """每條鏈守備清單（美+台），回 {chain: [yf_ticker,...]}。"""
    d = json.load(open(SCREEN, encoding="utf-8"))
    out = {}
    for chain in d.get("us", {}):
        us = [x["code"] for x in d["us"].get(chain, [])]
        tw = [tw_yf(x["code"]) for x in d["tw"].get(chain, [])]
        out[chain] = sorted(set(us + tw))
    return out


def buffett_top30(prices):
    """巴菲特倉 = 現價≤俗價中，折價(=(俗價-現價)/俗價)最大前 30。"""
    wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
    scored = []
    for tk, d in wl.items():
        cheap, p = d.get("cheap"), prices.get(tk)
        if cheap and p and p <= cheap:
            scored.append((tk, (cheap - p) / cheap))
    scored.sort(key=lambda x: -x[1])
    return sorted(tk for tk, _ in scored[:BUFFETT_TOPN])


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
    """批次抓現價；台股 .TW 抓不到自動退 .TWO（上櫃），價仍掛原 .TW key。"""
    tickers = sorted(set(tickers))
    out = _batch(tickers)
    miss_two = {tk: tk.replace(".TW", ".TWO") for tk in tickers
                if tk.endswith(".TW") and tk not in out}
    if miss_two:
        two = _batch(list(miss_two.values()))
        for orig, twocode in miss_two.items():
            if twocode in two:
                out[orig] = two[twocode]
    return out


def build_holdings_map(prices):
    """2 主倉 + 7 鏈。產業鏈全=7 鏈聯集。"""
    chains = chain_holdings()
    union = sorted({t for v in chains.values() for t in v})
    m = {CHAIN_ALL: union, BUFFETT_NAME: buffett_top30(prices)}
    m.update(chains)
    return m


def load():
    return json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else None


def save(state):
    json.dump(state, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _value_now(pf, prices):
    """當前淨值 = nav_base × 等權報酬因子（只算 entry/現價都有的股）。"""
    factors = [prices[t] / pf["entry"][t] for t in pf["holdings"]
               if pf["entry"].get(t) and prices.get(t)]
    if not factors:
        return pf["nav"]
    return round(pf["nav_base"] * (sum(factors) / len(factors)), 2)


def _ret(nav):
    return round((nav / BASE - 1) * 100, 2)


def _all_tickers(state):
    s = set()
    for pf in state["portfolios"].values():
        s.update(pf["holdings"])
    return s


def _entry_for(prices, holdings):
    return {tk: prices[tk] for tk in holdings if tk in prices}


def update_nav(state, prices, date):
    for pf in state["portfolios"].values():
        nav = _value_now(pf, prices)
        pf["nav"] = nav
        pf["ret"] = _ret(nav)
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, nav])
        else:
            pf["history"][-1][1] = nav
    state["updated"] = date


def rebalance(state, hmap, prices, date):
    for name, pf in state["portfolios"].items():
        nav = _value_now(pf, prices)        # 先結算舊持股到今天
        pf["nav"] = nav
        pf["nav_base"] = nav                # 接續基準
        pf["holdings"] = hmap.get(name, pf["holdings"])
        pf["entry"] = _entry_for(prices, pf["holdings"])
        pf["ret"] = _ret(nav)
        pf["rebalanced"] = date
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, nav])
    state["updated"] = date


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "nav"
    date = datetime.now().strftime("%Y-%m-%d")

    if cmd == "init":
        if load():
            print("portfolios.json 已存在，改用 rebalance/nav")
            return
        chains = chain_holdings()
        wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
        allt = set(wl.keys())
        for v in chains.values():
            allt.update(v)
        prices = fetch_prices(allt)
        hmap = build_holdings_map(prices)
        state = {"inception": date, "updated": date, "base": BASE,
                 "main": MAIN, "portfolios": {}}
        for name, hold in hmap.items():
            state["portfolios"][name] = {
                "holdings": hold, "entry": _entry_for(prices, hold),
                "nav_base": BASE, "nav": BASE, "ret": 0.0, "rebalanced": date,
                "history": [[date, BASE]],
            }
        save(state)
        print(f"✅ init：{len(state['portfolios'])} 倉（2 主+7 鏈），各 ${BASE:,.0f}，起始 {date}")
        for n, pf in state["portfolios"].items():
            tag = "主倉" if n in MAIN else "鏈"
            print(f"  [{tag}] {n}: {len(pf['holdings'])} 檔")
        return

    state = load()
    if not state:
        print("無 portfolios.json，先跑 init")
        return

    if cmd == "rebalance":
        allt = _all_tickers(state) | set(json.load(open(BUFFETT, encoding="utf-8")).keys())
        prices = fetch_prices(allt)
        rebalance(state, build_holdings_map(prices), prices, date)
        save(state)
        print(f"✅ rebalance {date}")
        for n, pf in state["portfolios"].items():
            print(f"  {n}: {len(pf['holdings'])} 檔 ${pf['nav']:,.0f} ({pf['ret']:+.2f}%)")
    elif cmd == "nav":
        prices = fetch_prices(_all_tickers(state))
        update_nav(state, prices, date)
        save(state)
        rank = sorted(state["portfolios"].items(), key=lambda kv: -kv[1]["ret"])
        print(f"✅ nav {date}　排行:")
        for n, pf in rank:
            print(f"  {pf['ret']:+6.2f}%  ${pf['nav']:>9,.0f}  {n}")


if __name__ == "__main__":
    main()
