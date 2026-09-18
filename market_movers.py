# -*- coding: utf-8 -*-
"""全市場強勢股掃描：找出「今天表現很強、但不在母體裡」的候選（2026-09-20）。

**為什麼做**：Leo 問「怎麼樣才不會漏掉創意跟愛普」——查出漏掉的原因是
`combo_scan.py` 的母體只有 281 檔（守備清單＋持股＋自訂觀察＋RRG領先類股
前8大成分股），市值不夠大、產業沒轉強、沒人手動加的股票，不管當天漲多少，
永遠不會被算進四燈系統，不會自動被看到。

**做法**：用免費、全市場、一次 call 就拿到全部的官方 bulk 行情（TWSE
`MI_INDEX` 的「每日收盤行情」表＋TPEx openapi `tpex_mainboard_quotes`），
不逐檔查 yfinance（那才是真正貴/慢的部分）。算出今天漲幅最大的一批股票，
跟目前 281 檔母體（`combo_scan.universe()`）比對，列出「今天大漲但不在
母體裡」的候選——這是給 Leo 看一眼、自己決定要不要 `/加自選` 的名單，
**不是自動加入母體**。

**這個做法的邊界（誠實講清楚）**：只用「今天單日漲幅」當篩選條件，抓得到
像創意那種單日噴出（+32%）的情況，但抓不到像愛普那種靠幾週慢慢墊出漲幅、
當天可能還小跌的情況——那種要看「N天累積漲幅」或「RS強度持續擴大」，
是不同、更複雜的信號，這支先不做，篩選範圍先講清楚，不要假裝這支能抓到
所有值得注意的股票。

用法：
    python market_movers.py                 # 預設抓漲幅≥8%的候選
    python market_movers.py --min-pct 12     # 改門檻
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

import requests                                                 # noqa: E402

OUT_PATH = "state/market_movers.json"
MIN_PCT_DEFAULT = 8.0


def _load(path, default):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        return default


def _twse_movers(date_str):
    """TWSE 每日收盤行情（MI_INDEX 的第9個表，index=8），全市場一次拿。
    回 [(code, name, pct)]。pct 用「漲跌價差 ÷ 昨收（今收-漲跌價差）」算，
    官方只給價差不給百分比。"""
    try:
        r = requests.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                         params={"date": date_str, "type": "ALLBUT0999", "response": "json"},
                         timeout=20)
        j = r.json()
    except Exception as e:                                      # noqa: BLE001
        print(f"  [warn] TWSE MI_INDEX 抓取失敗：{str(e)[:60]}")
        return []
    tables = j.get("tables") or []
    quote_table = None
    for t in tables:
        if t.get("fields") and len(t["fields"]) >= 10 and "股票代號" in t["fields"][0]:
            quote_table = t
            break
    if not quote_table:
        return []
    out = []
    for row in quote_table.get("data", []):
        try:
            code = str(row[0]).strip()
            if not (code.isdigit() and len(code) == 4):
                continue
            name = str(row[1]).strip()
            close = float(str(row[8]).replace(",", ""))
            sign = "-" if "-" in str(row[9]) else "+"
            diff = float(str(row[10]).replace(",", "") or 0)
            if diff == 0:
                continue
            prev = close - diff if sign == "+" else close + diff
            if prev <= 0:
                continue
            pct = (diff / prev * 100) * (1 if sign == "+" else -1)
            out.append((code, name, pct))
        except (ValueError, IndexError):
            continue
    return out


def _tpex_movers():
    """TPEx openapi 每日行情（全市場一次拿，沒有date參數＝最新交易日）。
    回 [(code, name, pct)]。Change 是絕對價差（含正負號字串），一樣要自己除昨收。"""
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=20)
        rows = r.json() or []
    except Exception as e:                                      # noqa: BLE001
        print(f"  [warn] TPEx openapi 抓取失敗：{str(e)[:60]}")
        return []
    out = []
    for row in rows:
        try:
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not (code.isdigit() and len(code) == 4):
                continue
            name = str(row.get("CompanyName", "")).strip()
            close = float(row.get("Close") or 0)
            diff = float(str(row.get("Change", "0")).replace("+", "") or 0)
            if close <= 0 or diff == 0:
                continue
            prev = close - diff
            if prev <= 0:
                continue
            pct = diff / prev * 100
            out.append((code, name, pct))
        except (ValueError, TypeError):
            continue
    return out


def current_universe():
    """目前四燈母體的代號集合（守備清單＋持股＋自訂＋RRG領先成分股）。"""
    import combo_scan as cs
    return set(cs.universe().keys())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pct", type=float, default=MIN_PCT_DEFAULT)
    ap.add_argument("--date", default=None, help="YYYYMMDD，只影響TWSE（TPEx openapi固定抓最新）")
    a = ap.parse_args()

    date_str = a.date or dt.date.today().strftime("%Y%m%d")
    print(f"抓全市場行情（TWSE {date_str} + TPEx 最新）…")
    movers = _twse_movers(date_str) + _tpex_movers()
    if not movers:
        print("✗ 兩邊都抓不到資料，中止")
        return 1
    uni = current_universe()
    print(f"母體 {len(uni)} 檔；全市場行情 {len(movers)} 檔")

    hits = [(c, n, p) for c, n, p in movers if abs(p) >= a.min_pct]
    hits.sort(key=lambda x: -abs(x[2]))
    outside = [(c, n, p) for c, n, p in hits if c not in uni]

    print(f"漲跌幅≥{a.min_pct}% 共 {len(hits)} 檔，其中不在母體 {len(outside)} 檔：")
    for c, n, p in outside[:30]:
        print(f"  {c} {n}　{p:+.1f}%")

    _save = {
        "date": date_str, "min_pct": a.min_pct,
        "outside_universe": [{"code": c, "name": n, "pct": round(p, 2)} for c, n, p in outside],
    }
    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    io.open(OUT_PATH, "w", encoding="utf-8").write(json.dumps(_save, ensure_ascii=False, indent=1))
    print(f"已存 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
