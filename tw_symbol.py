# -*- coding: utf-8 -*-
"""台股 yfinance 後綴解析：上市＝`.TW`、上櫃＝`.TWO`。

**為什麼要有這支**：yfinance 對上市/上櫃用不同後綴，全部掛 `.TW` 的話上櫃股一律
404，而這種 404 幾乎都被 `except` 吞掉 → **偽裝成「這檔沒資料 / 沒訊號」的正常業務
結果**。2026-07-31 修過一次（`data_tv`），但只修了那一支；2026-08-31 掃出還有五個
呼叫點硬掛 `.TW`，實測 `state/st_state.json` 裡上市 31/31 有 SuperTrend 狀態、
**上櫃 0/13**——那 13 檔從來沒有過翻多/翻空訊號。

兩種用法，對應兩種呼叫形態：

  · **單檔**：`resolve("3105")` → `"3105.TWO"`。第一次會 probe（試 .TW 再試 .TWO），
    結果寫進 `state/tw_suffix.json`，之後零網路成本。
  · **批次**：`batch_with_otc(codes, fetch)`。先用 `.TW` 一次 download，沒拿到的
    才用 `.TWO` 再打一次——**不要對幾十檔逐檔 probe**，那正是當初改批次要省掉的東西。

只快取成功的結果。兩種後綴都抓不到時不寫快取（可能只是當下被限流），
否則一次逾時會被永久記成「這檔沒有」——見 memory `cache_negative_result_bug`。
"""
import os
import re
import json

CACHE_PATH = "state/tw_suffix.json"
_CACHE = None


def is_tw_code(x):
    """裸台股代號（還沒接後綴）。1101 / 2330 / 00878 / 2731A 都算。"""
    return bool(re.fullmatch(r"\d{4,6}[A-Z]?", str(x)))


def _cache():
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.load(open(CACHE_PATH, encoding="utf-8"))
        except Exception:
            _CACHE = {}
    return _CACHE


def remember(code, suffix):
    if suffix in (".TW", ".TWO"):
        _cache()[str(code)] = suffix


def save():
    if _CACHE is None:
        return
    try:
        os.makedirs("state", exist_ok=True)
        json.dump(_CACHE, open(CACHE_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0, sort_keys=True)
    except Exception:
        pass


def candidates(code):
    """要試哪些 yfinance 代號，依序。非台股裸代號原樣回傳（美股不動）。"""
    if not is_tw_code(code):
        return [str(code)]
    known = _cache().get(str(code))
    if known:
        return [f"{code}{known}"]
    return [f"{code}.TW", f"{code}.TWO"]


def resolve(code, probe=True):
    """單檔：回實際抓得到資料的 yfinance 代號。

    非台股裸代號原樣回傳。已知的直接查快取。未知且 probe=True 才連線試；
    probe=False（或兩種都抓不到）就回 `.TW`，維持舊行為不會更糟。
    """
    if not is_tw_code(code):
        return str(code)
    known = _cache().get(str(code))
    if known:
        return f"{code}{known}"
    if not probe:
        return f"{code}.TW"
    import yfinance as yf
    for sfx in (".TW", ".TWO"):
        try:
            h = yf.Ticker(f"{code}{sfx}").history(period="5d")
            if h is not None and not h.empty:
                remember(code, sfx)
                save()
                return f"{code}{sfx}"
        except Exception:
            continue
    return f"{code}.TW"


def batch_with_otc(codes, fetch):
    """批次：`codes` 是裸代號；`fetch` 吃 `[yf_sym]` 回 `{yf_sym: value}`。

    回 `{裸代號: value}`。最多打兩次 fetch（.TW 一次、漏掉的 .TWO 一次）。
    """
    codes = [str(c) for c in codes]
    if not codes:
        return {}
    first = {c: f"{c}{_cache().get(c, '.TW')}" for c in codes}
    got = fetch(list(first.values())) or {}
    out = {}
    for c, sym in first.items():
        if sym in got:
            out[c] = got[sym]
            remember(c, sym[len(c):])
    miss = {c: f"{c}.TWO" for c, sym in first.items()
            if c not in out and sym.endswith(".TW")}
    if miss:
        got2 = fetch(list(miss.values())) or {}
        for c, sym in miss.items():
            if sym in got2:
                out[c] = got2[sym]
                remember(c, ".TWO")
    save()
    return out
