"""策略賽馬：7 條產業鏈 + 巴菲特價值，各開一個紙上模擬倉，每週調倉、每日記淨值。

淨值用「等權重報酬指數」（起始 100）：用各股報酬率(%)算，美股算美元、台股算台幣 →
天生免換匯，純比選股。每週跟著守備清單/巴菲特買進訊號調倉，NAV 接續累計。

用法:
  python paper_portfolio.py init       # 首次建檔（起始日=今天，做第一次調倉+記NAV）
  python paper_portfolio.py rebalance  # 每週：賣退榜、買新進，NAV 接續
  python paper_portfolio.py nav        # 每日：用現價更新 NAV，記一筆歷史
"""
import sys
import json
import os
from datetime import datetime
import yfinance as yf

STORE = "portfolios.json"
SCREEN = "screen_result.json"
BUFFETT = "buffett_watch.json"
BUFFETT_NAME = "巴菲特價值"


def tw_yf(code):
    """台股代號 → yfinance（純數字加 .TW）。"""
    return f"{code}.TW" if str(code).isdigit() else str(code)


def chain_holdings():
    """從 screen_result.json 取每條鏈的守備清單（美+台），回 {chain: [yf_ticker,...]}。"""
    d = json.load(open(SCREEN, encoding="utf-8"))
    out = {}
    for chain in d.get("us", {}):
        us = [x["code"] for x in d["us"].get(chain, [])]
        tw = [tw_yf(x["code"]) for x in d["tw"].get(chain, [])]
        out[chain] = sorted(set(us + tw))
    return out


def buffett_buy_holdings(prices):
    """巴菲特倉 = 現價 ≤ 俗價（🟢買進訊號）的股。"""
    wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
    buys = []
    for tk, d in wl.items():
        cheap = d.get("cheap")
        p = prices.get(tk)
        if cheap and p and p <= cheap:
            buys.append(tk)
    return sorted(buys)


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
    """批次抓現價，回 {ticker: price}。台股 .TW 抓不到自動退 .TWO（上櫃），
    價格仍掛在原 .TW key 上（持股名穩定）。"""
    tickers = sorted(set(tickers))
    out = _batch(tickers)
    # .TW 失敗 → 試 .TWO（上櫃），存回原 .TW key
    miss_two = {tk: tk.replace(".TW", ".TWO") for tk in tickers
                if tk.endswith(".TW") and tk not in out}
    if miss_two:
        two = _batch(list(miss_two.values()))
        for orig, twocode in miss_two.items():
            if twocode in two:
                out[orig] = two[twocode]
    return out


def load():
    if os.path.exists(STORE):
        return json.load(open(STORE, encoding="utf-8"))
    return None


def save(state):
    json.dump(state, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _nav_now(pf, prices):
    """用現價算當前 NAV：nav_base × 等權報酬因子（只算 entry/現價都有的股）。"""
    factors = []
    for tk in pf["holdings"]:
        e, p = pf["entry"].get(tk), prices.get(tk)
        if e and p:
            factors.append(p / e)
    if not factors:
        return pf["nav"]
    return round(pf["nav_base"] * (sum(factors) / len(factors)), 2)


def _all_tickers(state):
    s = set()
    for pf in state["portfolios"].values():
        s.update(pf["holdings"])
    return s


def update_nav(state, prices, date):
    """每日：算各倉 NAV、報酬%，append 歷史。"""
    for pf in state["portfolios"].values():
        nav = _nav_now(pf, prices)
        pf["nav"] = nav
        pf["ret"] = round(nav - 100, 2)
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, nav])
        else:
            pf["history"][-1][1] = nav
    state["updated"] = date


def rebalance(state, holdings_map, prices, date):
    """每週：先鎖定到今天的績效(nav→nav_base)，再換成新持股、重抓 entry。"""
    for name, pf in state["portfolios"].items():
        new = holdings_map.get(name, pf["holdings"])
        nav = _nav_now(pf, prices)          # 先結算舊持股到今天
        pf["nav"] = nav
        pf["nav_base"] = nav                # 接續基準
        pf["holdings"] = new
        pf["entry"] = {tk: prices[tk] for tk in new if tk in prices}
        pf["ret"] = round(nav - 100, 2)
        pf["rebalanced"] = date
        if not pf["history"] or pf["history"][-1][0] != date:
            pf["history"].append([date, nav])
    state["updated"] = date


def build_holdings_map(prices):
    m = chain_holdings()
    m[BUFFETT_NAME] = buffett_buy_holdings(prices)
    return m


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "nav"
    date = datetime.now().strftime("%Y-%m-%d")

    if cmd == "init":
        if load():
            print("portfolios.json 已存在，改用 rebalance/nav")
            return
        # 先抓守備清單(美+台)+巴菲特候選的價，決定 holdings
        chains = chain_holdings()
        wl = json.load(open(BUFFETT, encoding="utf-8")) if os.path.exists(BUFFETT) else {}
        allt = set(wl.keys())
        for v in chains.values():
            allt.update(v)
        prices = fetch_prices(allt)
        hmap = dict(chains)
        hmap[BUFFETT_NAME] = buffett_buy_holdings(prices)
        state = {"inception": date, "updated": date, "portfolios": {}}
        for name, hold in hmap.items():
            entry = {tk: prices[tk] for tk in hold if tk in prices}
            state["portfolios"][name] = {
                "holdings": hold, "entry": entry, "nav_base": 100.0,
                "nav": 100.0, "ret": 0.0, "rebalanced": date,
                "history": [[date, 100.0]],
            }
        save(state)
        print(f"✅ init 完成：{len(state['portfolios'])} 倉，起始 {date}")
        for n, pf in state["portfolios"].items():
            print(f"  {n}: {len(pf['holdings'])} 檔")
        return

    state = load()
    if not state:
        print("無 portfolios.json，先跑 init")
        return

    if cmd == "rebalance":
        prices = fetch_prices(_all_tickers(state) | set(json.load(open(BUFFETT, encoding="utf-8")).keys()))
        hmap = build_holdings_map(prices)
        rebalance(state, hmap, prices, date)
        save(state)
        print(f"✅ rebalance {date}")
        for n, pf in state["portfolios"].items():
            print(f"  {n}: {len(pf['holdings'])} 檔 NAV {pf['nav']} ({pf['ret']:+.2f}%)")
    elif cmd == "nav":
        prices = fetch_prices(_all_tickers(state))
        update_nav(state, prices, date)
        save(state)
        rank = sorted(state["portfolios"].items(), key=lambda kv: -kv[1]["ret"])
        print(f"✅ nav {date}　排行:")
        for n, pf in rank:
            print(f"  {pf['ret']:+6.2f}%  {n}  NAV {pf['nav']}")


if __name__ == "__main__":
    main()
