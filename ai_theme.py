# -*- coding: utf-8 -*-
"""AI 主題分類（2026-09-23，Leo 看老墨戰情室頂端「代理AI基建/記憶體外溢/實體AI/
內需與循環」導覽列，想要同款功能）。

## 分類依據——不是自己編的敘事，是既有 12 條產業鏈的既有分組

`board_html_legacy.CHAIN_ORDER` 前 8 條是 AI 供應鏈本體（伺服器→材料→電源散熱→
電力→光通訊→封裝基板→關鍵金屬），機器人算實體 AI，太陽能／低軌衛星／
Bitcoin→AI 機房是 Leo 自己下指令歸的「主題型、跟 AI 資本支出關聯較遠」三條——
這個分法直接對應老墨的四個主題名稱，不是重新發明一套判斷標準。

## 母體用哪一個——combo_scan.universe()，不是 12 條鏈的守備清單

Leo 問「我們的母體應該還有其它的母體?」查證後confirm：系統裡至少有 4 種不同母體
（12條鏈守備清單~140檔／combo_scan.universe()每日約250檔／base_rate.json的202筆
consensus檢查記錄／巴菲特S&P500+Dow30+S&P600篩選名單），彼此用途不同。

這支選 combo_scan.universe()（`state/combo_result.json` 快取），因為：
①這才是查股戰情室/進出燈號頁實際在掃、Leo 平常在看的母體；②它本來就混了
「守備清單＋持股＋自訂觀察清單＋RRG領先產業成分股＋模擬倉持股」，不是純AI
供應鏈——這代表「不屬於任何AI鏈」的股票本來就會出現在這個母體裡，剛好對應
老墨「內需與循環」通常是四個主題裡最大一類的現象，不用另外找母體湊。

## 記憶體外溢——暫缺

老墨那邊這格也只有 1 檔（利基分類），我們目前沒有對應的鏈可以掛，先留空；
之後有具體要放哪幾檔再補 CHAIN_THEME。
"""
import json
import os
import re

THEME_ORDER = ["代理AI基建", "記憶體外溢", "實體AI", "內需與循環"]
THEME_ICON = {"代理AI基建": "🤖", "記憶體外溢": "💾", "實體AI": "🦾", "內需與循環": "🏠"}

CHAIN_THEME = {
    "AI 伺服器": "代理AI基建",
    "AI 材料/被動元件": "代理AI基建",
    "AI 電源/散熱": "代理AI基建",
    "AI 電力/核能": "代理AI基建",
    "矽光子/光通訊": "代理AI基建",
    "PCB/ABF 載板": "代理AI基建",
    "玻璃基板/TGV": "代理AI基建",
    "關鍵金屬/原物料": "代理AI基建",
    "機器人": "實體AI",
    "太陽能": "內需與循環",
    "低軌衛星": "內需與循環",
    "Bitcoin→AI 機房": "內需與循環",
}

LIT_BRIGHT = 3  # lit >= 3 算「亮燈」，跟 combo_html.py 篩選籤「3 燈以上」同一個門檻
RESULT_PATH = "state/combo_result.json"

_chain_cache = None


def _tw_bare(tk):
    return re.sub(r"\.(TW|TWO)$", "", str(tk or ""))


def _chain_ticker_map():
    """{裸代號: chain}。一檔可能屬多條鏈時取第一個命中的（跟 paper_portfolio
    chain_holdings() 的走訪順序一致）。模組內快取一次，同一輪多次呼叫不重算。"""
    global _chain_cache
    if _chain_cache is not None:
        return _chain_cache
    import paper_portfolio as pp
    out = {}
    for chain, tickers in pp.chain_holdings().items():
        for tk in tickers:
            out.setdefault(_tw_bare(tk), chain)
    _chain_cache = out
    return out


def classify(ticker):
    """回這檔的 AI 主題。不在任何 AI 鏈裡的一律歸『內需與循環』（母體本來就混了
    非 AI 的持股/自訂觀察/輪動領先成分股，見檔頭說明）。"""
    chain = _chain_ticker_map().get(_tw_bare(ticker))
    return CHAIN_THEME.get(chain, "內需與循環")


def theme_summary():
    """回 {theme: {"count":n, "lit_bright":n, "tickers":[(ticker,name,lit),...]}}。
    讀不到 combo_result.json 快取就回空 dict（呼叫端自行處理「尚無資料」）。"""
    out = {t: {"count": 0, "lit_bright": 0, "tickers": []} for t in THEME_ORDER}
    if not os.path.exists(RESULT_PATH):
        return out
    d = json.load(open(RESULT_PATH, encoding="utf-8"))
    for r in d.get("rows", []):
        theme = classify(r.get("ticker"))
        lit = r.get("lit", 0) or 0
        out[theme]["count"] += 1
        if lit >= LIT_BRIGHT:
            out[theme]["lit_bright"] += 1
        out[theme]["tickers"].append((r.get("ticker"), r.get("name"), lit))
    return out


def _main():
    s = theme_summary()
    for t in THEME_ORDER:
        v = s[t]
        print(f"{THEME_ICON[t]} {t}：{v['count']} 檔（{v['lit_bright']} 檔亮{LIT_BRIGHT}燈+）")


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    _main()
