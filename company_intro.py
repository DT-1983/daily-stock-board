# -*- coding: utf-8 -*-
"""個股一句話簡介（2026-09-07 Leo：「整合報告可以前面寫個簡介嗎?」）。

整合報告原本一打開就是燈號表格 —— **整份報告沒有任何一句話說這家在做什麼**。
你要先知道自己在看誰，才有辦法讀後面那堆數字。

## 為什麼分成兩半

- **「這家在做什麼」交給 AI**：yfinance 的 `longBusinessSummary` 是一大段英文
  （台股也多半是英文），要濃縮成一句好讀的繁中，那是文字轉文字，AI 該做的事。
- **「現在是什麼狀態」不給 AI**：燈數、SuperTrend、距目標、RS、報告份數
  全部是我們自己算好的欄位，**由程式直接填**。
  ⭐ 記憶 advisor_reports_pipeline 的教訓：**能算的不要讓 AI 用講的**。
     讓 AI 順手把數字寫進句子裡，它遲早會寫錯一個，而且錯得很流暢。

所以 prompt 只給業務描述、**不給任何數字**，它想寫也沒得寫。

## 快取

公司在做什麼不會天天變，但 yfinance 偶爾會改寫那段文字。
`state/company_intro.json` 以「原文的雜湊」當版本：原文沒變就直接用快取，
變了才重寫一次。這樣零成本、也不會永遠卡在一份過期的描述。

⚠️ 走本機 claude（Max plan 訂閱額度），**不是付費 API、不產生帳單**。
"""
import hashlib
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "state", "company_intro.json")


def _load():
    try:
        return json.load(io.open(CACHE, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}


def _save(d):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(
        json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, CACHE)


def profile(ticker):
    """yfinance 的公司資料。查不到就回 None——**不要編一個出來**。"""
    import re
    try:
        import yfinance as yf
        import tw_symbol
        sym = (tw_symbol.resolve(ticker)
               if re.match(r"^[0-9]{4,6}[A-Z]?$", str(ticker)) else str(ticker))
        i = yf.Ticker(sym).info or {}
    except Exception:                                       # noqa: BLE001
        return None
    if not (i.get("longBusinessSummary") or i.get("longName")):
        return None
    return {"name": i.get("longName") or "",
            "sector": i.get("sector") or "", "industry": i.get("industry") or "",
            "summary": i.get("longBusinessSummary") or "",
            "employees": i.get("fullTimeEmployees"),
            "country": i.get("country") or ""}


PROMPT = """把下面這家公司的英文業務說明，濃縮成**一段繁體中文（台灣用語）**。

===== 原文 =====
{summary}
產業分類：{sector} / {industry}
===== 原文結束 =====

要求：
- **80～110 字**，一段，不要條列、不要標題。
  ⚠️ 這是硬上限，不是建議。超過就會被打回重寫。
- 產品線**只挑最重要的兩三項**，不要把原文的清單整串搬過來
  （原文常常列十幾樣，全抄等於沒有濃縮）。
- 第一句就講**它靠什麼賺錢**（賣什麼給誰），不要用「該公司成立於…」開場。
- 講得出**主要產品線或客戶**就講，原文沒有就不要補。
- 讀者是台灣的個人投資人：專有名詞用台灣的講法
  （例如 foundry＝晶圓代工、semiconductor＝半導體、connector＝連接器）。
- 🔴 **不准出現任何股價、市值、營收、目標價、成長率之類的數字**。
  那些我們自己算，不需要你講；你講了反而會跟我們的數字打架。
  原文裡的年份、成立時間也不要寫進去。
- 🔴 一個簡體字都不能出現。
- 標點用**全形**（，。；：），不要半形逗號。
- 只輸出那一段文字本身，不要任何前言、引號或說明。"""


def intro(ticker, force=False):
    """回 (簡介文字, 來源dict)。查不到資料回 ("", None)。"""
    p = profile(ticker)
    if not p or not p.get("summary"):
        return "", p
    key = str(ticker).upper()
    h = hashlib.sha1(p["summary"].encode("utf-8")).hexdigest()[:12]
    cache = _load()
    hit = cache.get(key)
    if hit and hit.get("hash") == h and hit.get("text") and not force:
        return hit["text"], p
    import llm_board
    try:
        txt = (llm_board._ask_claude(
            PROMPT.format(summary=p["summary"][:2500],
                          sector=p["sector"] or "—",
                          industry=p["industry"] or "—")) or "").strip()
        # 繁體是硬規則，而且 prompt 寫了不等於做到（simplified_chinese_guard）。
        bad = sorted(llm_board.simplified_chars(txt))
        if bad:
            txt = (llm_board._ask_claude(
                PROMPT.format(summary=p["summary"][:2500],
                              sector=p["sector"] or "—",
                              industry=p["industry"] or "—")
                + "\n\n⚠️ 你上一次用了簡體字："
                + "".join(bad) + "。整段重寫，全部繁體。") or "").strip()
            if llm_board.simplified_chars(txt):
                print(f"  [warn] {ticker} 簡介還是有簡體字，捨棄不用")
                return "", p
    except Exception as e:                                  # noqa: BLE001
        print(f"  [warn] {ticker} 簡介失敗：{str(e)[:70]}")
        return (hit or {}).get("text", ""), p
    # 半形標點一律轉全形。⭐ 這種**能用程式保證的**就不要靠 prompt——
    # 實測 NVDA 那份整段用半形逗號，規則寫了照樣沒做到。
    for x, y in ((",", "，"), (";", "；"), (":", "："), ("(", "（"), (")", "）")):
        txt = txt.replace(x, y)
    # 太長就打回重寫一次。⚠️ **不要硬切**——切在句子中間比長更難讀，
    # 而且被切掉的通常是後半段的重點（同 war_room 超字數的處理）。
    if len(txt) > 140:
        txt2 = (llm_board._ask_claude(
            PROMPT.format(summary=p["summary"][:2500],
                          sector=p["sector"] or "—",
                          industry=p["industry"] or "—")
            + "\n\n⚠️ 你上一次寫了 " + str(len(txt)) + " 字，上限 110 字。"
              "整段重寫，只留最重要的業務與兩三項主要產品，其餘全部砍掉。")
                or "").strip()
        for x, y in ((",", "，"), (";", "；"), (":", "："), ("(", "（"), (")", "）")):
            txt2 = txt2.replace(x, y)
        if txt2 and not llm_board.simplified_chars(txt2) and len(txt2) < len(txt):
            txt = txt2
    # 🔴 寫死的守門：prompt 說了不准有數字，但**prompt 寫了不等於做到**
    # （simplified_chinese_guard 記過同一件事）。真的混進價格類數字就不要用它，
    # 寧可只給公司名與產業，也不要在報告最上面放一個沒人驗過的數字。
    import re
    if re.search(r"(股價|市值|營收|目標價|年增|季增|成長率)\s*[0-9]", txt):
        print(f"  [warn] {ticker} 簡介出現數字，捨棄不用")
        return "", p
    if not txt:
        return (hit or {}).get("text", ""), p
    cache[key] = {"hash": h, "text": txt}
    _save(cache)
    return txt, p


def main():
    import argparse
    ap = argparse.ArgumentParser(description="個股一句話簡介")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--force", action="store_true", help="不用快取，重寫一次")
    a = ap.parse_args()
    for t in a.tickers:
        txt, p = intro(t, force=a.force)
        print(f"── {t}　{(p or {}).get('name', '（查無資料）')}")
        print(f"   {(p or {}).get('sector', '')} / {(p or {}).get('industry', '')}")
        print(f"   {txt or '（沒有簡介）'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
