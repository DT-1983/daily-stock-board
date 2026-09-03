# -*- coding: utf-8 -*-
"""投顧報告失效線監控器（2026-09-03，路線圖第 5 項）。

## 為什麼做這個

Leo 手上的券商個股報告是**靜態的**：寫完那天之後沒有人幫忙盯。這支把報告裡
「當初憑什麼給這個目標價」的假設抽出來，做成每天檢查得動的失效條件。

⚠️ **價值不在「多一個監控」**（2026-09-03 先查涵蓋率才決定做）：13 份報告涵蓋
9 檔，只有 **2882 國泰金**（持股）與 **4979 華星光**（掃描母體）在我們系統裡，
其餘 **7 檔完全在視線外**（7750/2449/6944/2883/6919/6415/6187）。
另外我們現有系統算的是「市場共識目標價」，**沒有報告的推導過程那一層**
（例如國泰金那份寫明「2027 年底 PBR 1.1 倍」推出 117 元）——
那個假設能不能被證偽，才是真正能盯的東西。

## 為什麼用 LLM 而不是 regex

pdfplumber 抽出來的文字**欄位會交錯**。實測元大 7750 那份首頁：

    收盤價 (2026/08 隱 /14 含 )： 漲 N 幅 T ： $2 3 3 6 5 .3 5 % .0

兩欄的字元逐字互相穿插。regex 在這種輸出上必然脆。走本機 `claude`
（`llm_board`，Max plan 訂閱額度，**不是付費 API、不產生帳單**）結構化。

## 判定線先訂好（同 roadmap_milestones 的作法）

先把「什麼情況代表這份報告的判斷基礎不成立」寫死，**趁還沒有部位、沒有立場**。
不然到時候一定會往「自己看好的方向」事後合理化（見 feedback_no_self_change_criteria）。

型別沿用 `investment_chief` 那一套（price_above / price_below / metric），
不重造第二套詞彙——`thesis_check.py` 已經在用同一組。

用法:
    python advisor_reports.py parse            # 解析尚未解析過的 PDF
    python advisor_reports.py parse --force    # 全部重新解析
    python advisor_reports.py list             # 列出已解析的報告與失效條件
    python advisor_reports.py check            # 日檢（比對現價）
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

PDF_DIR = r"C:\Users\Mophy\Documents\Investment\投顧報告"
STORE = "state/advisor_reports.json"
TODAY_OUT = "state/advisor_reports_today.json"

# 報告發布後跌破這個幅度，就當作「市場不同意這份報告」值得回頭看一眼。
# ⚠️ 這個 15% 是**我訂的**，不是外部來源。理由：券商個股報告的目標價普遍給
# 20-30% 上檔（實測這 13 份潛在漲幅 10.9%~36.3%），跌 15% 等於「原本假設的
# 上檔空間反向吃掉一半以上」。要改跟 Leo 講一聲，不要自己動（不自行變更門檻）。
DROP_PCT = 15.0

SCHEMA_HINT = """只回傳一個 JSON 物件，不要包在其他文字裡，不要加註解。

{
 "ticker": "代號數字，例 2882",
 "name": "公司中文名",
 "broker": "券商中文簡稱，例 中信投顧 / 元大投顧 / 康和 / 宏遠",
 "date": "報告日期 YYYY-MM-DD",
 "rating": "本次評等原文，例 買進 / 增加持股 / 中立",
 "rating_prev": "前次評等；沒有寫就填空字串",
 "target": 目標價數字（沒有填 null）,
 "target_prev": 前次目標價數字（沒有填 null）,
 "close_at_report": 報告上寫的收盤價/前日收盤價數字（沒有填 null）,
 "eps": [{"year": "2026F", "value": 8.27}, ...],
 "valuation_basis": "目標價怎麼推出來的，一句話照抄報告的說法，例「2027年底PBR 1.1倍」「2026-27年預估平均EPS 81.9元與本益比30倍」；找不到填空字串",
 "valuation_multiple": 估值倍數的數字（PE 或 PBR 的倍數，例 30 或 1.1；找不到填 null）,
 "valuation_kind": "PE 或 PBR 或空字串",
 "risks": ["報告寫的風險因子，逐條，繁體中文"],
 "thesis": "這份報告的核心論點，一句話，繁體中文"
}

規則：
- **全部用繁體中文（台灣用語）**，一個簡體字都不能出現。
- 數字只填數字不要帶單位與逗號。
- **抽不到就填 null 或空字串，不要猜、不要編**。這份資料會拿去做失效判斷，
  編出來的數字比缺漏更糟。
- 這份 PDF 的文字是程式抽出來的，**欄位可能交錯穿插**（例如兩欄的字互相夾雜）。
  遇到看起來錯亂的段落，以數字本身的合理性判斷，判斷不了就填 null。
"""


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _save(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def pdf_text(path, pages=2):
    """抽前 N 頁文字。個股報告的關鍵欄位（評等/目標價/EPS/估值基礎）都在前兩頁，
    抽整份只是把雜訊餵給 LLM。"""
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages[:pages]:
            out.append(pg.extract_text() or "")
    return "\n".join(out)


def conditions_for(r):
    """把報告翻成**每天檢查得動**的失效條件。

    只產生「零成本、程式判得出來」的條件：
      price_above  達到目標價 ── 報告的上檔空間用完，這份報告的任務結束
      price_below  跌破報告日收盤 DROP_PCT% ── 市場不同意，論點要重新檢視
      metric       EPS 預估 ── 要等財報才驗證（thesis_check 的 metric 型別同義）

    ⚠️ 刻意**不**把評等變化做成條件：那要等下一份報告，不是我們算得出來的。
    """
    cs = []
    if r.get("target"):
        cs.append({"type": "price_above", "value": float(r["target"]),
                   "desc": f"現價達到目標價 {r['target']}，報告的上檔空間用完"})
    c0 = r.get("close_at_report")
    if c0:
        line = round(float(c0) * (1 - DROP_PCT / 100), 2)
        cs.append({"type": "price_below", "value": line,
                   "desc": f"跌破報告日收盤 {c0} 的 -{DROP_PCT:.0f}%（{line}），市場不同意這份報告"})
    for e in (r.get("eps") or []):
        if e.get("value") is not None:
            cs.append({"type": "metric", "value": None,
                       "desc": f"{e['year']} 實際 EPS 低於預估 {e['value']} 元"})
    return cs


def parse(force=False, only=None):
    store = _load(STORE, {})
    files = sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf")))
    if only:
        files = [f for f in files if only in os.path.basename(f)]
    import llm_board
    done = 0
    for f in files:
        key = os.path.basename(f)
        if key in store and not force:
            continue
        print(f"  解析 {key} …", flush=True)
        try:
            txt = pdf_text(f)
        except Exception as e:                              # noqa: BLE001
            print(f"    PDF 讀取失敗：{str(e)[:100]}")
            continue
        prompt = (f"下面是一份券商個股研究報告的前兩頁文字（程式抽取，欄位可能交錯）。"
                  f"把它結構化。\n\n{SCHEMA_HINT}\n\n---報告文字開始---\n{txt[:9000]}\n---報告文字結束---")
        try:
            d = llm_board.ask_json_traditional(prompt, tries=2)
        except Exception as e:                              # noqa: BLE001
            print(f"    結構化失敗：{str(e)[:100]}")
            continue
        if not isinstance(d, dict) or not d.get("ticker"):
            print("    結構化沒有回傳可用的 JSON，跳過")
            continue
        d["_file"] = key
        d["_parsed"] = dt.date.today().isoformat()
        d["conditions"] = conditions_for(d)
        store[key] = d
        _save(STORE, store)          # 逐份存，中途掛掉不會全丟
        done += 1
        print(f"    ✅ {d.get('name')}({d['ticker']}) {d.get('broker')} "
              f"{d.get('date')}｜目標價 {d.get('target')}｜{len(d['conditions'])} 條失效條件")
    print(f"\n完成 {done} 份；登錄簿共 {len(store)} 份")
    return store


def _norm(tk):
    """報告只寫數字代號；轉成 price_store 要的寫法（上市/上櫃後綴走 tw_symbol）。"""
    t = str(tk).strip().upper()
    if re.match(r"^\d{4,6}[A-Z]?$", t):
        try:
            import tw_symbol
            return tw_symbol.resolve(t)
        except Exception:                                   # noqa: BLE001
            return t + ".TW"
    return t.replace(".", "-")



def norm_ticker_num(tk):
    """報告裡的純數字代號 → 跟 investment_chief.norm_ticker() 同一種正規化寫法，
    才比得起來（那邊會把 .TW/.TWO 去掉、把 . 換成 -）。"""
    try:
        import investment_chief
        return investment_chief.norm_ticker(tk)
    except Exception:                                       # noqa: BLE001
        return str(tk).strip().upper()


def check(quiet=False):
    """日檢：拿現價比對每份報告的失效條件。回 [(報告, 觸發的條件, 現價)]。"""
    store = _load(STORE, {})
    if not store:
        print("還沒有解析過任何報告，先跑 parse")
        return []
    syms = {}
    for k, r in store.items():
        syms.setdefault(_norm(r["ticker"]), []).append(k)
    import price_store
    closes = price_store.get_closes(sorted(syms), period="1y")
    hits, rows = [], []
    for sym, keys in syms.items():
        s = closes.get(sym)
        if s is None or s.empty:
            if not quiet:
                print(f"  ⚠️ {sym} 抓不到價格，這幾份無法檢查：{keys}")
            continue
        px = float(s.dropna().iloc[-1])
        for k in keys:
            r = store[k]
            fired = []
            for c in r.get("conditions", []):
                if c["type"] == "price_above" and c.get("value") and px >= c["value"]:
                    fired.append(c)
                elif c["type"] == "price_below" and c.get("value") and px <= c["value"]:
                    fired.append(c)
            rows.append({"file": k, "ticker": r["ticker"], "name": r.get("name"),
                         "broker": r.get("broker"), "date": r.get("date"),
                         "price": round(px, 2), "target": r.get("target"),
                         "fired": fired})
            if fired:
                hits.append((r, fired, px))
    _save(TODAY_OUT, {"date": dt.date.today().isoformat(), "rows": rows})
    return hits


def summary_lines():
    """給日報用：只回觸發的，沒有就回一行「N 份健康」。"""
    d = _load(TODAY_OUT, {})
    rows = d.get("rows") or []
    if not rows:
        return []
    fired = [r for r in rows if r.get("fired")]
    if not fired:
        return [f"・📑 投顧報告失效線：{len(rows)} 份全部健康"]
    out = []
    for r in fired[:4]:
        why = r["fired"][0]["desc"]
        out.append(f"・📑 {r['name']}({r['ticker']}) {r['broker']} {r['date']}｜{why}"
                   f"（現價 {r['price']}）")
    return out


def listing():
    store = _load(STORE, {})
    for k, r in sorted(store.items(), key=lambda x: str(x[1].get("date"))):
        print(f"{r.get('date')}  {r.get('name')}({r['ticker']})  {r.get('broker')}"
              f"  {r.get('rating')}  目標 {r.get('target')}"
              + (f"（前次 {r.get('target_prev')}）" if r.get("target_prev") else ""))
        if r.get("valuation_basis"):
            print(f"        依據：{r['valuation_basis']}")
        for c in r.get("conditions", []):
            print(f"        · {c['desc']}")
    print(f"\n共 {len(store)} 份")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["parse", "list", "check"])
    ap.add_argument("--force", action="store_true", help="parse：全部重新解析")
    ap.add_argument("--only", default="", help="parse：只處理檔名含這個字的")
    a = ap.parse_args()
    if a.cmd == "parse":
        parse(force=a.force, only=a.only or None)
    elif a.cmd == "list":
        listing()
    else:
        hits = check()
        if not hits:
            print("沒有報告被觸發失效條件")
        for r, fired, px in hits:
            print(f"🚫 {r.get('name')}({r['ticker']}) {r.get('broker')} {r.get('date')}"
                  f"　現價 {px:.2f}")
            for c in fired:
                print(f"    · {c['desc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
