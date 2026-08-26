"""研究員 Agent —— 產業層。偵測 RRG 象限翻轉，查相關新聞，叫 AI 統整成研究筆記。

分工（比照總體層 researcher_macro.py 的「先規則、才叫AI」）：
1. 偵測翻象限：純比對 industry_rotation_history.json 這週 vs 上週，零成本零AI
   （industry_rotation.py 是週排程 weekly-screen.yml 每週六台灣08:00才跑，
    所以這裡也是一週最多一次有新東西可比）。
2. 查相關新聞：鉅亨網 search/news 關鍵字搜尋 API（公開免key，2026-08-26查證過
   會照日期排序回傳真的相關的新聞，不是只能在通用新聞裡碰運氣抓關鍵字）。
3. 叫 AI 統整：把上面兩步查到的材料**直接餵進 prompt 當已知材料**，
   明確要求不要自己再查（--tools "" 關掉所有工具，實測 web_search_requests=0）。
   這步是研究員的本職（把原始資料變成可讀的研究筆記），不是可有可無的加值——
   只丟一堆新聞標題進 research_notes.jsonl 等於沒做完研究員該做的事。

用法: python researcher_industry.py [--period 60]
"""
import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_board import _claude_bin

NOTES_PATH = "state/research_notes.jsonl"
HIST_PATH = "industry_rotation_history.json"
SEARCH_API = "https://api.cnyes.com/media/api/v1/search/news"
TPE = timezone(timedelta(hours=8))
QLABEL = {"leading": "領先", "improving": "改善", "lagging": "落後", "weakening": "弱化"}

SCHEMA = {
    "type": "object",
    "properties": {
        "layer": {"type": "string", "enum": ["industry"]},
        "scope": {"type": "string"},
        "source": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "summary": {"type": "string"},
    },
    "required": ["layer", "scope", "source", "confidence", "summary"],
}

PROMPT = """你是產業研究員，任務是把已知材料整理成給投資長參考的研究筆記，不是給結論、不是建議買賣。

鐵律（不能違反）：
1. 把事實、推論、假設分開標註
2. 資料不足就直接說缺少什麼，不要自己補值、不要硬掰一個理由
3. 不要建議買賣，只整理事實給投資長參考
4. **只根據下面提供的材料寫，不要自己去查其他資料**

已知材料：
產業籃子「{name}」（{market}）本週 RRG 象限從「{old_q}」轉為「{new_q}」（{period}日週期）。
RS-Ratio {old_ratio} → {new_ratio}；RS-Momentum {old_mom} → {new_mom}。

相關新聞（依這個籃子前3大成分股查到的，已附上，不用再查；美股走 yfinance 英文新聞、
台股走鉅亨網。每則前面的 [代號/來源] 標示它是查哪一檔、來自哪個媒體）：
{news}

注意：這些新聞是「成分股個股新聞」，不是「整個產業的新聞」——個股新聞不一定能解釋
整個籃子的相對強弱變化，判斷時要考慮這個落差，不要把單一檔的消息當成整個產業的原因。

任務：判斷這些新聞能不能解釋這次象限轉變。能解釋就說明是什麼在推動；
不能解釋就明確說「這些新聞解釋不了這次轉變」並列出還缺什麼資料——
硬掰一個理由比承認資料不足更糟。
layer 填 "industry"；scope 填 "{name}"；source 填 "rrg+cnyes_search"；
confidence：新聞明確能解釋填 high，部分相關填 medium，解釋不了填 low。"""


def detect_flips(market, period="60"):
    """比對最新兩筆歷史快照的象限差異。零成本純比對。"""
    if not os.path.exists(HIST_PATH):
        return []
    hist = json.load(open(HIST_PATH, encoding="utf-8"))
    rows = hist.get(market, {}).get("index", [])
    if len(rows) < 2:
        return []
    last, prev = rows[-1], rows[-2]
    out = []
    for key, v in last["snapshot"].items():
        p = prev["snapshot"].get(key)
        if not p:
            continue
        a = (p["periods"].get(period) or {})
        b = (v["periods"].get(period) or {})
        if a.get("quadrant") and b.get("quadrant") and a["quadrant"] != b["quadrant"]:
            out.append({"key": key, "name": v["name"], "market": market.upper(),
                        "old_q": a["quadrant"], "new_q": b["quadrant"],
                        "old_ratio": a["ratio"], "new_ratio": b["ratio"],
                        "old_mom": a["momentum"], "new_mom": b["momentum"],
                        "from_date": prev["date"], "to_date": last["date"]})
    return out


def _search_one(keyword, n=5):
    """鉅亨網關鍵字搜尋（公開免key）。失敗回空list不中斷——新聞查不到不該讓整個研究員掛掉。"""
    import requests
    try:
        r = requests.get(SEARCH_API, params={"q": keyword, "limit": n}, timeout=15)
        r.raise_for_status()
        out = []
        for it in r.json()["items"]["data"][:n]:
            ts = datetime.fromtimestamp(it["publishAt"], tz=TPE)
            out.append({"title": it["title"], "ts": ts.strftime("%Y-%m-%d %H:%M"),
                        "kw": keyword, "url": f'https://news.cnyes.com/news/id/{it["newsId"]}'})
        return out
    except Exception as e:
        print(f"  新聞查詢失敗（{keyword}）：{e}")
        return []


def _top_holdings(market, key, n=3):
    """從 docs/rotation.html 內嵌的 RRG_HOLDINGS 取這個籃子的前幾大成分股代號。
    industry_rotation.py 產頁時本來就會把成分股寫進去，不用另外打API。"""
    import re
    path = "docs/rotation.html"
    if not os.path.exists(path):
        return []
    try:
        html = open(path, encoding="utf-8").read()
        m = re.search(r"window\.RRG_HOLDINGS\s*=\s*(\{.*?\});", html, re.S)
        if not m:
            return []
        d = json.loads(m.group(1))
        return [h["ticker"] for h in d.get(market.lower(), {}).get(key, [])][:n]
    except Exception:
        return []


def _us_news(tickers, per=4):
    """美股走 yfinance 的 .news（免費，跟現有套件同源，不用另接API）。
    2026-08-26 實測：回傳真的相關、當天/前一天的新聞，來源是 Zacks/WSJ/Motley Fool
    這些真財經媒體，比拿中文譯名去搜中文媒體準得多。"""
    out = []
    try:
        import yfinance as yf
    except Exception:
        return out
    for tk in tickers:
        try:
            for it in (yf.Ticker(tk).news or [])[:per]:
                c = it.get("content", it)
                title = c.get("title")
                if not title:
                    continue
                prov = c.get("provider")
                prov = prov.get("displayName") if isinstance(prov, dict) else c.get("publisher", "")
                out.append({"title": title, "ts": str(c.get("pubDate") or "")[:16].replace("T", " "),
                            "kw": tk, "src": prov or "",
                            "url": c.get("canonicalUrl", {}).get("url", "") if isinstance(c.get("canonicalUrl"), dict) else ""})
        except Exception as e:
            print(f"  yfinance新聞查詢失敗（{tk}）：{e}")
    return out


def search_news(flip, n=6):
    """2026-08-26 兩輪失敗後定案的雙路線做法（過程見 dev_log 續十五/十六）：

    美股 → yfinance `.news`（英文、ticker精確、來源是真財經媒體）。
      前兩輪失敗原因：用中文產業譯名搜中文媒體，「通訊」搜到台股大立光、跟美股
      Communication Services 語意對不上；改用代號搜更糟，短代號被中文搜尋當子字串
      亂命中（KO→KOSPI、HCA→CASHCAT、PM→DeepMind）。
    台股 → 鉅亨網搜尋，但**用4位數股票代號**（2330/1101/2412）不是 TradingView 的
      翻譯分類名。實測鉅亨網資料很新（當天17:45的新聞都有）、代號在中文媒體是精確
      錨點不會亂命中；失敗的只有「非能源礦業」這種台灣市場根本沒人在講的翻譯詞。
    """
    seen, out = set(), []
    tickers = _top_holdings(flip["market"], flip["key"], 3)
    if flip["market"] == "US":
        cand = _us_news(tickers, 4)
    else:
        cand = []
        for tk in tickers:
            cand += _search_one(tk, 3)
    for it in cand:
        if it["title"] in seen:
            continue
        seen.add(it["title"])
        out.append(it)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:n + 3]


def ask_claude(flip, news, period):
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    news_txt = "\n".join(
        f"- {n['ts']} [{n.get('kw','')}{'/' + n['src'] if n.get('src') else ''}] {n['title']}"
        for n in news) or "（查無相關新聞）"
    prompt = PROMPT.format(name=flip["name"], market=flip["market"],
                           old_q=QLABEL.get(flip["old_q"], flip["old_q"]),
                           new_q=QLABEL.get(flip["new_q"], flip["new_q"]), period=period,
                           old_ratio=flip["old_ratio"], new_ratio=flip["new_ratio"],
                           old_mom=flip["old_mom"], new_mom=flip["new_mom"], news=news_txt)
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
    note["events"] = [{"market": flip["market"], "date": flip["to_date"], "status": "released",
                       "event": f"RRG象限{QLABEL.get(flip['old_q'])}→{QLABEL.get(flip['new_q'])}"
                                f"（RS-Ratio {flip['old_ratio']}→{flip['new_ratio']}）"}]
    note["headlines"] = news
    note["ts"] = time.strftime("%Y-%m-%d")
    note["cost_usd"] = out.get("total_cost_usd")
    return note


DONE_PATH = "state/industry_flips_done.json"


def _done_key(flips, period):
    """這批翻轉的識別碼＝(最新快照日期, 週期)。象限資料每週六才更新
    （industry_rotation.py 走 weekly-screen.yml），但這支跑在本機每日排程——
    不去重的話週一到五會重複報同一批翻轉五次。"""
    return f"{flips[0]['to_date']}|{period}" if flips else ""


def run(period="60"):
    flips = []
    for mkt in ("us", "tw"):
        flips += detect_flips(mkt, period)
    if not flips:
        print("本週無產業象限翻轉，不寫入（沒訊號不用硬湊一筆）")
        return []

    key = _done_key(flips, period)
    done = []
    if os.path.exists(DONE_PATH):
        try:
            done = json.load(open(DONE_PATH, encoding="utf-8"))
        except Exception:
            done = []
    if key in done:
        print(f"這批翻轉（{key}）已經處理過，跳過（象限資料每週六才更新，不重複報）")
        return []

    print(f"偵測到 {len(flips)} 個籃子翻象限（{period}日週期）")
    notes = []
    for f in flips:
        print(f"  {f['name']}（{f['market']}）{QLABEL.get(f['old_q'])}→{QLABEL.get(f['new_q'])}")
        news = search_news(f)
        try:
            notes.append(ask_claude(f, news, period))
        except Exception as e:
            print(f"  AI統整失敗（{f['name']}）：{e}")

    if not notes:
        return []
    os.makedirs("state", exist_ok=True)
    with open(NOTES_PATH, "a", encoding="utf-8") as fh:
        for n in notes:
            fh.write(json.dumps(n, ensure_ascii=False) + "\n")
    json.dump((done + [key])[-50:], open(DONE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    total = sum(n.get("cost_usd") or 0 for n in notes)
    print(f"已存 {len(notes)} 筆產業層研究筆記（等值標價合計約 ${total:.2f}，Max plan 走訂閱額度）")
    return notes


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="60", help="用哪個週期判斷象限（預設60日波段）")
    run(ap.parse_args().period)
