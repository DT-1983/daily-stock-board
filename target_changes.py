# -*- coding: utf-8 -*-
"""券商目標價／評等異動提醒（2026-09-03，Leo 指定「做異動提醒」）。

## 這支跟 advisor_reports.py 的差別

| | `advisor_reports.py` | 這支 |
|---|---|---|
| 資料 | 一家券商的**完整研究報告**（PDF）| **每日跨券商異動表**（永豐金證券法人部編製，截圖）|
| 粒度 | 一檔一份，含論點/推導/風險 | 一天幾十檔，只有「誰調了、往哪調」|
| 用途 | 抽出假設 → 做成失效條件每天檢查 | **異動偵測**：今天有沒有人改了對我們持股的看法 |

## 🔴 為什麼**不**拿這份表的數字建失效條件

Leo 2026-09-03 給的兩張表（`0903_01/02.webp`）實際內容裡，`TP Old` 欄有明顯
不合理的值：

    PANW   0 → 390
    奇鋐   78 → 4500
    南電   2444 → 2460    但「潛在幅度」寫 105%

看起來來源本身就有欄位錯位或空值。**拿這種數字直接建判斷條件會產生假訊號**，
而且錯了不會有任何地方報錯（典型靜默錯誤）。
所以這支**只做「誰調了、往哪個方向」的提醒**，New 值當參考並標明未經覆核。
要看完整推導請走 `advisor_reports.py`（那是原始 PDF，數字可以覆核）。

## 可信度：只推 Goldman Sachs

Leo 2026-09-03：「做異動提醒，因為可信度只有 goldenman 比較可信」。
→ `TRUSTED` 名單內的券商才進提醒；其餘照樣存檔（可查、可回溯），但不推播。
名單是**設定**不是判斷——要加減券商改這個常數，不要在別處另寫規則。

## 為什麼截圖也能讀

`llm_board._ask_claude()` 走 `claude -p --dangerously-skip-permissions`，
**沒有停用工具**，所以那個 subprocess 裡的 Read 可以直接讀圖片檔
（跟 `earnings_call.py` 能上網抓逐字稿同一個道理）。
本機 Max plan 訂閱額度，**不是付費 API、不產生帳單**。

用法:
    python target_changes.py parse      # 解析尚未讀過的截圖
    python target_changes.py list       # 列出所有異動
    python target_changes.py alert      # 只列「我們母體內 + 可信券商」的異動
"""
import os
import re
import sys
import json
import glob
import argparse
import datetime as dt

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IMG_DIR = r"C:\Users\Mophy\Documents\Investment\投顧目標價"
STORE = "state/target_changes.json"
TODAY_OUT = "state/target_changes_today.json"

# Leo 2026-09-03 指定：這份表裡他只信高盛。要加減券商改這裡，不要在別處另寫規則。
#
# 🔴 2026-09-03 修：原本寫 `["goldman", "gs ", "高盛"]` 並用 `t.strip() in b` 比對，
# `.strip()` 把 "gs " 的尾空白吃掉 → 變成裸的 "gs" 子字串比對 →
# **"mornin(gs)tar" 命中**，於是「AAPL 被 Morningstar 降評為賣出」被當成高盛的異動
# 推了出來。假訊號而且看起來很像真的（AAPL 降到 Sell 很戲劇性）。
# 改成**詞邊界比對**：兩側必須不是英數字，"gs" 才算獨立的縮寫。
TRUSTED = ["goldman", "gs", "高盛", "goldman sachs"]

SCHEMA_HINT = """只回傳一個 JSON 陣列，不要包在其他物件裡，不要有陣列以外的文字。

陣列每個元素：
{"date": "YYYY-MM-DD", "ticker": "代號（台股是數字如 2454；美股是英文如 AAPL）",
 "name": "股票名稱", "broker": "券商名稱照表上寫的",
 "rating": "評等欄照抄，例 Buy / Overwt / Neutral / Downgrade to Sell",
 "tp_old": 舊目標價數字（空白或看不清填 null）,
 "tp_new": 新目標價數字（空白或看不清填 null）,
 "direction": "up 或 down 或 flat"（依表上的 ▲ / ↘ 箭頭；沒有箭頭填 flat）,
 "section": "目標價調整 或 評等調整 或 Coverage調整"（表格分區的標題）}

規則：
- **看不清楚就填 null，絕對不要猜數字**。這份資料會拿去做提醒，編出來的數字比缺漏更糟。
- `direction` 以**箭頭符號**為準，不要自己用 tp_old/tp_new 相減推——那兩欄本身就有錯位。
- 「本日無調整」的分區不要產生任何元素。
- 全部用繁體中文（台灣用語），一個簡體字都不能出現。
"""


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _save(p, o):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def parse(force=False):
    """讀 IMG_DIR 裡還沒讀過的截圖。回 {檔名: [異動, ...]}。"""
    import llm_board
    store = _load(STORE, {})
    files = []
    for ext in ("webp", "png", "jpg", "jpeg"):
        files += glob.glob(os.path.join(IMG_DIR, f"*.{ext}"))
    done = 0
    for f in sorted(files):
        key = os.path.basename(f)
        if key in store and not force:
            continue
        print(f"  讀 {key} …", flush=True)
        prompt = (
            f"請用 Read 工具讀取這個圖片檔：{f}\n\n"
            "它是一張「券商目標價／評等異動表」的截圖（永豐金證券國內法人部編製），"
            "表格欄位是：日期／代號／股票／券商／評等／TP Old／TP New／上下調箭頭／潛在幅度。"
            "把表格裡每一列轉成結構化資料。\n\n" + SCHEMA_HINT)
        try:
            rows = llm_board.ask_json_traditional(prompt, tries=2)
        except Exception as e:                              # noqa: BLE001
            print(f"    讀取失敗：{str(e)[:120]}")
            continue
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("items") or []
        if not isinstance(rows, list) or not rows:
            print("    沒有回傳可用的列表，跳過（不記入，下次會再試）")
            continue
        store[key] = {"_read": dt.date.today().isoformat(), "rows": rows}
        _save(STORE, store)
        done += 1
        n_tr = sum(1 for r in rows if is_trusted(r.get("broker")))
        print(f"    ✅ {len(rows)} 筆異動（其中可信券商 {n_tr} 筆）")
    tot = sum(len(v.get("rows", [])) for v in store.values())
    print(f"\n完成 {done} 張；登錄簿 {len(store)} 張／{tot} 筆異動")
    return store


def _tokens(name):
    """把券商名切成詞：英數字連續段 + 每個中文字。用來做**整詞**比對。"""
    b = str(name or "").lower()
    toks = set(re.findall(r"[a-z0-9]+", b))
    toks |= set(re.findall(r"[一-鿿]+", b))
    return toks


def is_trusted(broker):
    """券商名在不在可信名單。

    **整詞比對，不是子字串比對**——見 TRUSTED 上方註解（"gs" 當子字串會命中
    "mornin(gs)tar"）。多字的名單項（"goldman sachs"）用子字串，單詞的用整詞。
    """
    b = str(broker or "").lower()
    toks = _tokens(b)
    for t in TRUSTED:
        t = t.lower()
        if " " in t:
            if t in b:
                return True
        elif t in toks:
            return True
    return False


def all_rows(store=None):
    store = store if store is not None else _load(STORE, {})
    out = []
    for k, v in store.items():
        for r in v.get("rows", []):
            r = dict(r)
            r["_src"] = k
            out.append(r)
    out.sort(key=lambda r: (str(r.get("date")), str(r.get("ticker"))), reverse=True)
    return out


def _our_universe():
    """我們「看得到」的代號集合＝持股 ∪ 守備清單 ∪ 自訂觀察清單。

    ⚠️ 用途是「這筆異動關不關我們的事」，寧可寬不要漏——所以三個來源聯集，
    而且同時收數字與帶後綴的寫法（比對更寬鬆）。
    """
    uni = set()
    try:
        import investment_chief
        uni |= {investment_chief.norm_ticker(t) for t in investment_chief.held_universe()}
    except Exception as e:                                  # noqa: BLE001
        print(f"  （持股讀取失敗：{str(e)[:60]}）")
    try:
        sr = _load("screen_result.json", {}) or {}
        for mk in ("tw", "us"):
            for lst in (sr.get(mk) or {}).values():
                for row in lst or []:
                    if row.get("code"):
                        uni.add(str(row["code"]).upper())
    except Exception:                                       # noqa: BLE001
        pass
    try:
        wl = _load("state/combo_watchlist.json", {}) or {}
        items = wl.get("tickers") or wl.get("items") or wl
        if isinstance(items, dict):
            items = list(items)
        for t in items or []:
            uni.add(re.sub(r"\.(TW|TWO)$", "", str(t).upper()))
    except Exception:                                       # noqa: BLE001
        pass
    return uni


def alerts(store=None):
    """要提醒的異動＝**可信券商** ∩ **我們母體內**。回 (要提醒的, 其餘統計)。"""
    rows = all_rows(store)
    uni = _our_universe()
    hit, other_ours, untrusted = [], [], 0
    for r in rows:
        tk = re.sub(r"\.(TW|TWO)$", "", str(r.get("ticker") or "").upper())
        ours = tk in uni
        trust = is_trusted(r.get("broker"))
        if trust and ours:
            hit.append(r)
        elif ours:
            other_ours.append(r)
        else:
            untrusted += 1
    _save(TODAY_OUT, {"date": dt.date.today().isoformat(),
                      "alerts": hit, "ours_untrusted": other_ours,
                      "outside": untrusted})
    return hit, other_ours, untrusted


def _line(r):
    d = {"up": "▲ 調升", "down": "▼ 調降"}.get(r.get("direction"), "－")
    tp = (f"{r['tp_old']:g} → {r['tp_new']:g}"
          if r.get("tp_old") and r.get("tp_new")
          else (f"新目標 {r['tp_new']:g}" if r.get("tp_new") else "無目標價"))
    return (f"{r.get('date')}｜{r.get('name')}（{r.get('ticker')}）"
            f"｜{r.get('broker')}｜{r.get('rating')}｜{d}　{tp}")


def summary_lines():
    """給日報用。**只推可信券商 ∩ 我們母體內**；其餘只給一行計數。"""
    d = _load(TODAY_OUT, {})
    hit = d.get("alerts") or []
    oth = d.get("ours_untrusted") or []
    if not hit and not oth:
        return []
    out = []
    for r in hit[:5]:
        out.append(f"・🎯 券商異動｜{_line(r)}")
    if oth:
        out.append(f"　　（另有 {len(oth)} 筆我們母體內的異動來自其他券商，"
                   f"未列入提醒；數字未經覆核）")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["parse", "list", "alert"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "parse":
        parse(force=a.force)
        return 0
    if a.cmd == "list":
        for r in all_rows():
            print(("★ " if is_trusted(r.get("broker")) else "  ") + _line(r))
        return 0
    hit, oth, outside = alerts()
    print(f"可信券商 × 我們母體內：{len(hit)} 筆")
    for r in hit:
        print("  ★ " + _line(r))
    print(f"\n我們母體內但券商不在可信名單：{len(oth)} 筆（存檔可查，不推播）")
    for r in oth[:10]:
        print("  · " + _line(r))
    print(f"\n母體外：{outside} 筆")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
