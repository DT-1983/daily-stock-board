# -*- coding: utf-8 -*-
"""每日分析師共識快照（2026-10-02 開始存，Leo：「今天開始存」「產業鏈為主」）

**為什麼要存**：yfinance 只給「現在」的共識（EPS／營收預估、目標價高低均值、分析師人數、買賣家數），
過去的版本事後拿不回來。要做的三件事都需要共識的**歷史**：
  ① 自己的評價系統：共識 EPS 怎麼隨時間被調整（上修／下修），比只看當下一個數字有資訊
  ② 券商報告的檢驗：報告發布當天的共識 vs 報告的預估（報告比共識樂觀多少）、之後共識往哪邊靠
  ③ 財報前後：公布前最後一份共識（earnings_watch 只存 T-7 以內、只有美股 11 檔）
越早開始存越有價值——這種資料**無法事後補**。

**名單（產業鏈為主）**：產業鏈守備清單（screen_result.json，台＋美）＋持股＋報告庫裡有報告的股票＋自訂觀察清單。
不含「輪動領先類股自動拉進來的成分股」——那批每天變動，會讓歷史斷斷續續。

**存法**：`state/consensus_history/YYYY-MM-DD.json`，一天一個檔、{代號: 快照}。本機私人資料（已 gitignore），
不進公開 repo（體積會一直長，而且沒有理由公開）。
  每檔快照：price_target(mean/high/low/median/current)、eps(0q/+1q/0y/+1y 的 avg/low/high/yearAgo/人數/成長)、
  revenue(同)、eps_trend(現在／7／30／60／90 天前)、recs(強買/買/持有/賣/強賣)。

**零成本**：yfinance 免費；一檔約 5 次請求，序列跑（yfinance 多執行緒會回錯格式），名單約 150～200 檔約 10～15 分鐘。
**可續跑**：同一天重跑會跳過已存的；連續失敗太多（疑似被擋）就停下並回傳非 0。

用法:
    python consensus_snapshot.py            # 存今天（已存的跳過）
    python consensus_snapshot.py --force    # 今天整份重抓
    python consensus_snapshot.py --list     # 只印名單
    python consensus_snapshot.py --show 2330   # 看某檔的歷史時間序列
"""
import argparse
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

DIR = os.path.join("state", "consensus_history")
TW = dt.timezone(dt.timedelta(hours=8))
_SUF = re.compile(r"\.(TW|TWO)$")


def today():
    return dt.datetime.now(TW).date().isoformat()


def tickers():
    """{代號: 名稱}。產業鏈為主（見檔頭）。"""
    uni = {}

    def add(tk, name):
        tk = _SUF.sub("", str(tk or "").strip())
        if tk and tk not in uni:
            uni[tk] = name or tk
    try:
        scr = json.load(io.open("screen_result.json", encoding="utf-8"))
        for mkt in ("us", "tw"):
            for _chain, rows in (scr.get(mkt) or {}).items():
                for r in rows or []:
                    add(r.get("code"), r.get("name"))
    except Exception as e:                                   # noqa: BLE001
        print(f"  [warn] 讀不到守備清單：{str(e)[:70]}")
    try:
        from trade_plan import monitored_holdings
        for tk, _owner, name in monitored_holdings():
            add(tk, name)
    except Exception as e:                                   # noqa: BLE001
        print(f"  [warn] 讀不到持股：{str(e)[:70]}")
    try:
        import advisor_reports as AR
        for r in AR._live_reports():
            add(r.get("ticker"), r.get("name"))
    except Exception as e:                                   # noqa: BLE001
        print(f"  [warn] 讀不到報告庫：{str(e)[:70]}")
    try:
        import combo_scan
        for row in combo_scan._load(combo_scan.WATCHLIST_PATH, []):
            add(row.get("ticker"), row.get("name"))
    except Exception as e:                                   # noqa: BLE001
        print(f"  [warn] 讀不到自訂觀察清單：{str(e)[:70]}")
    return uni


def _num(x, nd=4):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else round(f, nd)


def _frame(df, cols, rows=None, as_int=()):
    """DataFrame → {列名: {欄名: 值}}，NaN 變 None。"""
    if df is None or getattr(df, "empty", True):
        return None
    out = {}
    for idx in df.index:
        if rows and str(idx) not in rows:
            continue
        r = {}
        for c in cols:
            if c in df.columns:
                v = df.loc[idx, c]
                r[c] = (int(v) if (c in as_int and _num(v) is not None) else _num(v))
        out[str(idx)] = r
    return out or None


def fetch_one(sym):
    """一檔的共識快照。任何一塊失敗就是 None，不影響其他塊。"""
    import yfinance as yf
    t = yf.Ticker(sym)
    snap = {}
    try:
        pt = t.analyst_price_targets
        if pt:
            snap["price_target"] = {k: _num(pt.get(k)) for k in ("current", "mean", "median", "high", "low")}
    except Exception:                                        # noqa: BLE001
        pass
    for key, attr in (("eps", "earnings_estimate"), ("revenue", "revenue_estimate")):
        try:
            fr = _frame(getattr(t, attr), ("avg", "low", "high", "yearAgoEps" if key == "eps" else "yearAgoRevenue",
                                            "numberOfAnalysts", "growth"), as_int=("numberOfAnalysts",))
            if fr:
                snap[key] = fr
        except Exception:                                    # noqa: BLE001
            pass
    try:
        fr = _frame(t.eps_trend, ("current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo"))
        if fr:
            snap["eps_trend"] = fr
    except Exception:                                        # noqa: BLE001
        pass
    try:
        rs = t.recommendations_summary
        fr = _frame(rs.set_index("period") if (rs is not None and "period" in getattr(rs, "columns", [])) else rs,
                    ("strongBuy", "buy", "hold", "sell", "strongSell"), rows=("0m",), as_int=("strongBuy", "buy", "hold", "sell", "strongSell"))
        if fr:
            snap["recs"] = fr.get("0m")
    except Exception:                                        # noqa: BLE001
        pass
    return snap or None


def run(force=False, limit=None):
    os.makedirs(DIR, exist_ok=True)
    day = today()
    path = os.path.join(DIR, f"{day}.json")
    data = {}
    if os.path.exists(path) and not force:
        try:
            data = json.load(io.open(path, encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            data = {}
    uni = tickers()
    todo = [(tk, nm) for tk, nm in uni.items() if tk not in data]
    if limit:
        todo = todo[:limit]
    print(f"[consensus] {day}｜名單 {len(uni)} 檔｜已存 {len(data)}｜這次要抓 {len(todo)}")
    import tw_symbol
    fails = got = empty = consec = 0
    t0 = time.time()
    for i, (tk, nm) in enumerate(todo, 1):
        try:
            sym = tw_symbol.resolve(tk) if re.match(r"^\d{4,6}[A-Z]?$", tk) else tk
            snap = fetch_one(sym)
        except Exception as e:                               # noqa: BLE001
            snap, fails, consec = None, fails + 1, consec + 1
            print(f"  [{tk}] 失敗：{str(e)[:70]}")
        else:
            consec = 0
        if snap:
            snap["name"] = nm
            snap["symbol"] = sym
            data[tk] = snap
            got += 1
        else:
            empty += 1
            data.setdefault(tk, {"name": nm, "empty": True})   # 記「今天這檔沒有共識」，也是資訊（覆蓋範圍）
        if i % 25 == 0:
            io.open(path, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))   # 中途存檔，掛掉可續
            print(f"  …{i}/{len(todo)}（{time.time() - t0:.0f}s）")
        if consec >= 15:
            io.open(path, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
            print("[consensus] 連續失敗 15 檔，疑似被擋，先停（已存的保留，下次續跑）")
            return 2
        time.sleep(0.25)
    meta = {"_meta": {"date": day, "fetched_at": dt.datetime.now(TW).isoformat(timespec="seconds"),
                      "universe": len(uni), "with_data": sum(1 for v in data.values() if v.get("eps") or v.get("price_target")),
                      "source": "yfinance"}}
    data.update(meta)
    io.open(path, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
    print(f"[consensus] 完成：抓到 {got}、沒共識 {empty}、失敗 {fails}｜有資料 {meta['_meta']['with_data']}/{len(uni)}｜{path}")
    return 0


def history(ticker, fields=("price_target.mean", "eps.0y.avg", "eps.+1y.avg", "eps.0q.avg")):
    """某檔的共識時間序列：[(日期, {欄位: 值})]。給估值工具／回測用。"""
    out = []
    if not os.path.isdir(DIR):
        return out
    tk = _SUF.sub("", str(ticker))
    for fn in sorted(os.listdir(DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            d = json.load(io.open(os.path.join(DIR, fn), encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            continue
        s = d.get(tk)
        if not s or s.get("empty"):
            continue
        row = {}
        for f in fields:
            cur = s
            for part in f.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            row[f] = cur
        out.append((fn[:-5], row))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.list:
        u = tickers()
        print(f"{len(u)} 檔：", ", ".join(f"{k} {v}" for k, v in list(u.items())[:400]))
        return 0
    if a.show:
        for d, r in history(a.show):
            print(d, r)
        return 0
    return run(a.force, a.limit)


if __name__ == "__main__":
    raise SystemExit(main())
