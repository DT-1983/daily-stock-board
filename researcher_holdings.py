"""研究員 Agent —— 持股每日監控。掃實際持股的新聞，只在命中警示關鍵字時才叫 AI。

設計說明（2026-08-26，跟 Leo 討論後定案）：
原本規劃是「每天掃持股所屬產業的新聞」，實作時發現持股跟 RRG 籃子對不太起來
（61檔持股只有8檔落在籃子前5大成分股裡，RRG_HOLDINGS 只存前5大），與其硬做一份
不完整的「持股→產業」映射，不如**直接掃持股本身的新聞**——你真正在乎的是
「我持有的股票出事了嗎」，產業層級的變化 researcher_industry.py 每週那條線已經在看。

三段式，跟總體層/產業層同一套「先規則、才叫AI」：
1. 抓新聞：yfinance `.news`，免費，每檔約1秒（61檔約1分鐘，可接受的日批次成本）
2. 過濾：英文警示關鍵字（tariff/lawsuit/investigation/recall/fraud...）+ 跟昨天比對去重
   （同一則新聞不重複報，state/holdings_news_seen.json）
3. 只在有命中時叫 AI **一次**（把所有命中的合併成一個 prompt，不是每檔各叫一次）

用法: python researcher_holdings.py
"""
import os
import sys
import json
import time
import subprocess

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_board import _claude_bin

NOTES_PATH = "state/research_notes.jsonl"
SEEN_PATH = "state/holdings_news_seen.json"
SEEN_KEEP = 3000        # 記住看過的標題數上限，超過就丟最舊的（避免檔案無限長大）

# 英文警示關鍵字：只抓「可能真的影響持股價值」的事件類新聞，
# 不抓 "5 Dividend Stocks to Buy" 這種常青 listicle（產業層那輪的教訓：
# 沒過濾的話餵給 AI 的全是通論文章，只會得到「這些新聞解釋不了」的空筆記）。
#
# 2026-08-26 首跑後修正：用 `in` 做子字串比對會大量誤命中——實測 ALL(Allstate)
# 命中 "ban" 是因為標題有 "Bank of China"、"sue" 會命中 "issue"/"pursue"。
# 改成用 \b 詞界正則比對。拿掉太泛的詞（stake/miss/warning/ban），這些即使做了
# 詞界比對還是會抓到一堆無關新聞（"High Insider Stakes In Leading Growth Companies"）。
ALERT_KEYWORDS = [
    "tariff", "tariffs", "sanction", "sanctions", "lawsuit", "sued", "investigation",
    "probe", "subpoena", "subpoenas", "recall", "fraud", "bankruptcy", "default",
    "delisting", "restructuring", "layoffs", "plunges", "plummets", "slashes",
    "downgraded", "downgrade", "warns", "halted", "suspends", "antitrust",
    "acquisition", "acquires", "merger", "buyout", "activist",
    "SEC", "FTC", "DOJ", "guidance cut", "cuts guidance", "export control",
]
_KW_RE = None


def _match_keyword(title):
    """詞界比對，避免 Bank→ban、issue→sue 這種子字串誤命中。
    多字詞（guidance cut）也一併處理。"""
    global _KW_RE
    import re
    if _KW_RE is None:
        pat = "|".join(re.escape(k) for k in sorted(ALERT_KEYWORDS, key=len, reverse=True))
        _KW_RE = re.compile(r"\b(" + pat + r")\b", re.IGNORECASE)
    m = _KW_RE.search(title)
    return m.group(1) if m else None

SCHEMA = {
    "type": "object",
    "properties": {
        "layer": {"type": "string", "enum": ["stock"]},
        "scope": {"type": "string"},
        "source": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "summary": {"type": "string"},
    },
    "required": ["layer", "scope", "source", "confidence", "summary"],
}

PROMPT = """你是股票研究員，任務是把已知材料整理成給投資長參考的研究筆記，不是給結論、不是建議買賣。

鐵律（不能違反）：
1. 把事實、推論、假設分開標註
2. 資料不足就直接說缺少什麼，不要自己補值、不要硬掰
3. 不要建議買賣，只整理事實給投資長參考
4. **只根據下面提供的材料寫，不要自己去查其他資料**

今天是 {date}。下面是 Leo 實際持股中，今天出現「事件型新聞」的標的
（已用關鍵字過濾掉通論文章，每則標明是哪檔、哪個關鍵字命中、哪個媒體）：

{items}

任務：
1. 逐檔說明發生了什麼、對這檔股票可能的影響方向（利多/利空/中性），
   標明哪些是新聞寫的事實、哪些是你的推論。
2. 光看標題判斷不了的，直接說「只有標題資訊不足以判斷」——不要腦補內文。
3. 如果多檔命中同一個主題（例如同一波關稅、同一個產業事件），要指出這個共通性。

layer 填 "stock"；scope 填所有命中的股票代號用逗號連接；source 填 "yfinance_news"；
confidence：多數新聞明確可判斷影響填 high，部分明確填 medium，多數只有標題無法判斷填 low。"""


_NAME_CACHE = {}


def _short_name(ticker):
    """公司短名（Apple Inc. → Apple），用來判斷標題是不是真的在講這檔。
    yfinance 的 info 有 shortName；抓不到就只用代號比對。"""
    if ticker in _NAME_CACHE:
        return _NAME_CACHE[ticker]
    name = ""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        raw = info.get("shortName") or info.get("longName") or ""
        # 去掉 Inc./Corp./Ltd. 這些後綴，留主體字
        for suf in (" Inc.", " Inc", " Corporation", " Corp.", " Corp", " Ltd.", " Ltd",
                    " plc", " PLC", " Company", " Co.", " Group", " Holdings", " N.V.", " S.A."):
            raw = raw.replace(suf, "")
        name = raw.split(",")[0].strip()
    except Exception:
        pass
    _NAME_CACHE[ticker] = name
    return name


def _mentions(title, ticker, content):
    """標題有沒有真的提到這檔（代號用詞界比對，或公司短名）。"""
    import re
    if re.search(r"\b" + re.escape(ticker) + r"\b", title, re.IGNORECASE):
        return True
    nm = _short_name(ticker)
    if nm and len(nm) >= 3 and nm.lower() in title.lower():
        return True
    return False


def _load_seen():
    if not os.path.exists(SEEN_PATH):
        return []
    try:
        return json.load(open(SEEN_PATH, encoding="utf-8"))
    except Exception:
        return []


def scan(tickers):
    """回 [(ticker, keyword, title, provider, ts), ...]，已過濾關鍵字且排除看過的。"""
    try:
        import yfinance as yf
    except Exception as e:
        print("yfinance 不可用：", e)
        return []
    seen = set(_load_seen())
    hits, fetched = [], 0
    for tk in tickers:
        try:
            news = yf.Ticker(tk).news or []
        except Exception:
            continue
        fetched += 1
        for it in news:
            c = it.get("content", it)
            title = c.get("title") or ""
            if not title or title in seen:
                continue
            kw = _match_keyword(title)
            if not kw:
                continue
            # 2026-08-26：yfinance 的 .news 常回傳「相關但不是這檔」的新聞
            # （實測查 API 回傳 XPeng、查 ALL 回傳 Bank of China）。要求標題裡
            # 真的提到這個代號或公司名，才算這檔的新聞——寧可漏報也不要張冠李戴。
            if not _mentions(title, tk, c):
                continue
            prov = c.get("provider")
            prov = prov.get("displayName") if isinstance(prov, dict) else c.get("publisher", "")
            hits.append((tk, kw.strip(), title, prov or "",
                         str(c.get("pubDate") or "")[:16].replace("T", " ")))
            seen.add(title)
    print(f"掃了 {fetched}/{len(tickers)} 檔，命中 {len(hits)} 則事件型新聞")
    return hits


def _save_seen(hits):
    seen = _load_seen()
    seen += [h[2] for h in hits]
    os.makedirs("state", exist_ok=True)
    json.dump(seen[-SEEN_KEEP:], open(SEEN_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def ask_claude(hits, date):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    items = "\n".join(f"- [{tk} / 命中「{kw}」 / {prov} / {ts}] {title}"
                      for tk, kw, title, prov, ts in hits)
    prompt = PROMPT.format(date=date, items=items)
    r = subprocess.run(
        [exe, "-p", "--dangerously-skip-permissions", "--tools", "",
         "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude 失敗 (exit {r.returncode}): {(r.stderr or '')[:300]}")
    out = json.loads(r.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude 回錯誤: {out}")
    note = out.get("structured_output")
    if not note:
        raise RuntimeError(f"沒有 structured_output：{r.stdout[:300]}")
    note["events"] = [{"market": "US", "date": date, "status": "released",
                       "event": f"[{tk}] {title}"} for tk, kw, title, prov, ts in hits]
    note["headlines"] = [{"title": t, "ts": ts, "kw": f"{tk}/{kw}", "src": p}
                          for tk, kw, t, p, ts in hits]
    note["ts"] = date
    note["cost_usd"] = out.get("total_cost_usd")
    return note


def run():
    if not os.path.exists("holdings.json"):
        print("找不到 holdings.json，跳過")
        return None
    tickers = json.load(open("holdings.json", encoding="utf-8"))
    hits = scan(tickers)
    if not hits:
        print("今天持股無事件型新聞，不寫入（沒訊號不用硬湊一筆）")
        return None

    for tk, kw, title, prov, ts in hits[:10]:
        print(f"  {tk} [{kw}] {title[:60]}")
    note = ask_claude(hits, time.strftime("%Y-%m-%d"))
    os.makedirs("state", exist_ok=True)
    with open(NOTES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    _save_seen(hits)
    print(f"已存持股監控筆記（{len(hits)} 則新聞，等值標價約 ${note.get('cost_usd') or 0:.2f}）")
    return note


if __name__ == "__main__":
    run()
