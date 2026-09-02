"""台股 AI 分析模組:FinMind 抓資料(股價+法人籌碼+月營收) + AI 決策 → tw_analysis.json

台股自建版（daily_stock_analysis 不支援台股）。輸出給 board_html.py 用。
用法:python tw_analyze.py

2026-07-31：判讀層改走 llm_board（本機 Claude headless，Max plan 零費用），
Gemini 退為備援；同時把「一檔一次呼叫」改成「一條鏈一次呼叫」，
37 檔從 37 次呼叫降到 7 次。
"""
import os
import json
from datetime import datetime, timedelta
import requests

from llm_board import ask_json_traditional as ask_json  # 2026-08-31：改走繁體驗收版（實測 tw_analysis.json 出現過「几乎持平」）

import sys as _sys
if _sys.stdout.encoding and _sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    _sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 印 emoji 會炸

FINMIND = "https://api.finmindtrade.com/api/v4/data"


def _load_env():
    """讀 .env 進 os.environ（不覆蓋既有值）。
    2026-08-05 修：.env 裡一直有 FINMIND_TOKEN 但這支從沒載入過 → 匿名低額度在跑，
    同日 screen.py + tw_analyze 連跑就撞限流（後段鏈全數跳過）。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")   # 可選，提高額度

# 台股守備清單：優先讀客觀篩選結果 screen_result.json（每鏈 top N），無則用 fallback
def _load_tw_watch():
    try:
        d = json.load(open("screen_result.json", encoding="utf-8"))
        return {chain: [(x["code"], x.get("name", x["code"])) for x in lst]
                for chain, lst in d["tw"].items()}
    except Exception:
        return {
            "AI 伺服器": [("2330", "台積電"), ("2317", "鴻海"), ("2382", "廣達")],
            "機器人": [("2049", "上銀"), ("1536", "和大"), ("2359", "所羅門")],
        }


TW_WATCH = _load_tw_watch()
SIG_EMOJI = {"買進": "🟢", "賣出": "🔴", "觀望": "⚪", "持有": "🔵"}


def fm(dataset, sid, start):
    params = {"dataset": dataset, "data_id": sid, "start_date": start}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
    try:
        return requests.get(FINMIND, params=params, timeout=20).json().get("data", [])
    except Exception:
        return []


def fetch(sid):
    d120 = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    d10 = (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d")
    d400 = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    d200 = (datetime.now() - timedelta(days=250)).strftime("%Y-%m-%d")
    return (fm("TaiwanStockPrice", sid, d120),
            fm("TaiwanStockInstitutionalInvestorsBuySell", sid, d10),
            fm("TaiwanStockMonthRevenue", sid, d400),
            fm("TaiwanStockPER", sid, d10),
            fm("TaiwanStockFinancialStatements", sid, d200))


def _fin_latest(fin):
    """從財報抽最新季的 EPS / 毛利率。"""
    if not fin:
        return None, None
    dates = sorted(set(d["date"] for d in fin))
    last = dates[-1]
    byt = {d["type"]: d["value"] for d in fin if d["date"] == last}
    eps = byt.get("EPS")
    rev, gp = byt.get("Revenue"), byt.get("GrossProfit")
    gm = round(gp / rev * 100, 1) if rev and gp else None
    return eps, gm


def _news(name, n=3, max_age_days=5):
    """鉅亨 ESS 關鍵字搜尋（免費）。近 5 天取 n 條標題給 LLM 當輿情輸入。
    2026-08-04 接回新聞層（零成本版），標題要清 <mark> 標籤。"""
    import re as _re
    import requests as _rq
    from datetime import datetime as _dt
    try:
        r = _rq.get("https://ess.api.cnyes.com/ess/api/v1/news/keyword",
                    params={"q": name, "limit": 8},
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        r.raise_for_status()
        items = (r.json().get("data") or {}).get("items") or []
    except Exception:
        return []
    out, now = [], _dt.now()
    for it in items:
        title = _re.sub(r"</?mark>", "", str(it.get("title") or "")).strip()
        ts = it.get("publishAt")
        if not title or not isinstance(ts, (int, float)):
            continue
        age = (now - _dt.fromtimestamp(ts)).days
        if age > max_age_days:
            continue
        stamp = "今天" if age == 0 else f"{age}天前"
        out.append(f"[{stamp}] {title}")
        if len(out) >= n:
            break
    return out


def collect(code, name, chain):
    """抓資料 + 組 AI 輸入脈絡。回 (ctx 字串, meta dict)，抓不到回 None。"""
    price, inst, rev, per, fin = fetch(code)
    if not price:
        return None
    closes = [d["close"] for d in price]
    last = closes[-1]
    ma = lambda n: round(sum(closes[-n:]) / n, 1) if len(closes) >= n else None
    foreign = sum(d["buy"] - d["sell"] for d in inst if d["name"] == "Foreign_Investor") // 1000
    trust = sum(d["buy"] - d["sell"] for d in inst if d["name"] == "Investment_Trust") // 1000
    rev_yoy = None
    if len(rev) >= 13 and rev[-13]["revenue"]:
        rev_yoy = round((rev[-1]["revenue"] / rev[-13]["revenue"] - 1) * 100, 1)
    pe = per[-1].get("PER") if per else None
    pb = per[-1].get("PBR") if per else None
    yld = per[-1].get("dividend_yield") if per else None
    # 髒 PER 過濾（EPS 失真會噴出 200+ 或負值，不放進 AI 判斷）
    pe_ctx = pe if (isinstance(pe, (int, float)) and 0 < pe < 120) else "N/A(EPS失真)"
    eps, gm = _fin_latest(fin)
    # 當日行情
    t = price[-1]
    chg = round((t["close"] / price[-2]["close"] - 1) * 100, 2) if len(price) >= 2 and price[-2]["close"] else None

    news = _news(name)
    news_line = ("\n新聞: " + "；".join(news)) if news else ""
    ctx = (f"股票:{name}({code}) 產業鏈:{chain}\n"
           f"今日: 開{t['open']} 高{t['max']} 低{t['min']} 收{last} 漲跌{chg}% 量{t.get('Trading_Volume',0)//1000}張\n"
           f"均線: MA5 {ma(5)} MA10 {ma(10)} MA20 {ma(20)}｜近10日收盤 {closes[-10:]}\n"
           f"籌碼: 外資近12日 {foreign} 張、投信 {trust} 張\n"
           f"基本面: 月營收YoY {rev_yoy}%、EPS {eps}、毛利率 {gm}%、PER {pe_ctx}、殖利率 {yld}%{news_line}")
    meta = {
        "code": code, "name": name, "chain": chain, "last": last,
        "ma5": ma(5), "ma10": ma(10), "ma20": ma(20),
        "foreign": foreign, "trust": trust, "rev_yoy": rev_yoy,
        "open": t["open"], "high": t["max"], "low": t["min"], "chg": chg,
        "vol": t.get("Trading_Volume", 0) // 1000,
        "eps": eps, "gross_margin": gm,
        "pe": (pe if isinstance(pe, (int, float)) and 0 < pe < 120 else None),
        "pb": pb, "yield": yld,
        "dates": [x["date"][5:] for x in price[-60:]],
        "closes": closes[-60:],
        "highs": [x["max"] for x in price[-60:]],
        "lows": [x["min"] for x in price[-60:]],
        "opens": [x["open"] for x in price[-60:]],   # 2026-09-02：board.html 蠟燭圖要開盤價
    }
    return ctx, meta


PROMPT_HEAD = """你是台股短線分析師。以下是【題材趨勢股守備清單】(待進場標的,非持股)。

判斷以**均線趨勢 + 法人籌碼**為主、營收次之;估值(PER)僅參考,題材股高 PER 常態,
別單因估值/漲多降評。

**訊號規則(預設觀望)**:
- 買進:均線多頭排列 **且** 法人買超(雙多才給)
- 賣出:均線空頭 **且** 法人持續大賣 **且** 跌破關鍵支撐(三者俱備才給,否則不要輕易賣出)
- 其餘一律觀望(包含弱勢但未明確破底、或多空訊號混雜)

用繁體中文台灣用語。**只根據下方數據判斷,不要編造新聞或財報數字。**
有附「新聞」時,理由/風險要納入判斷並點出關鍵訊息;新聞與技術面/籌碼矛盾時要指出,
不要硬湊成同方向。**沒附新聞就不要提到新聞。**

請針對每一檔輸出,只回 JSON 陣列,不要任何說明文字:
[{"code":"代號","signal":"買進或賣出或觀望","score":0到100整數,
  "oneliner":"一句話決策30字內","reason":"理由80字內提到籌碼與均線","risk":"主要風險40字內",
  "buy_point":"理想買點(價位或條件)","stop_loss":"停損位(價位)","target":"目標價位",
  "checklist":["檢查項1","檢查項2","檢查項3"]}]

【本批標的】
"""


def analyze_chain(chain, lst):
    """一條鏈一次 AI 呼叫（原本是一檔一次，37 檔 → 7 次）。"""
    ctxs, metas = [], []
    for code, name in lst:
        got = collect(code, name, chain)
        if not got:
            print(f"  [{code}] FinMind 無資料，跳過")
            continue
        ctxs.append(got[0])
        metas.append(got[1])
    if not metas:
        return []
    print(f"  → AI 判讀 {len(metas)} 檔 …", end=" ", flush=True)
    try:
        got = ask_json(PROMPT_HEAD + "\n\n".join(ctxs))
        by = {str(x.get("code", "")): x for x in got}
        print("完成")
    except Exception as e:
        print(f"失敗：{e}")
        by = {}
    for m in metas:
        d = by.get(m["code"], {})
        m.update({k: d.get(k) for k in
                  ("reason", "risk", "buy_point", "stop_loss", "target", "checklist")})
        m["signal"] = d.get("signal", "觀望")
        m["score"] = d.get("score", 50)
        m["oneliner"] = d.get("oneliner", "資料分析失敗")
        m["emoji"] = SIG_EMOJI.get(m["signal"], "⚪")
    return metas


def main():
    results = []
    for chain, lst in TW_WATCH.items():
        print(f"[{chain}] {len(lst)} 檔")
        results += analyze_chain(chain, lst)
    out = "tw_analysis.json"
    # 保險絲（2026-08-05）：FinMind 限流時大半個股被跳過，直接覆寫會把好檔案
    # 換成殘缺版（當天就發生過只剩 1 檔）。產出低於守備清單一半就拒寫。
    total = sum(len(lst) for lst in TW_WATCH.values())
    if results and len(results) < total * 0.5:
        print(f"\n⚠️ 只完成 {len(results)}/{total} 檔（疑似 FinMind 限流），拒絕覆寫 {out}")
        raise SystemExit(1)
    # 2026-08-28 加第二道守門：跟 us_analyze.py 同一個 bug——上面那道只查「有沒有
    # 抓到報價/財報」（FinMind 限流），沒查「AI 判讀真的成功了沒」。8/28 headless
    # claude 全面失敗那次，每檔都正常抓到資料、只是 AI 判讀失敗退回預設值
    # (oneliner="資料分析失敗")，len(results) 照樣是滿的，上面那道守門完全攔不住。
    ok_n = sum(1 for r in results if r.get("oneliner") != "資料分析失敗")
    ok_rate = ok_n / len(results) if results else 0
    if results and ok_rate < 0.5:
        print(f"\n❌ AI 判讀成功率過低（{ok_n}/{len(results)}={ok_rate:.0%}），"
              f"疑似 claude 呼叫系統性失敗，拒絕覆寫 {out}")
        raise SystemExit(1)
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ 台股分析完成 {len(results)} 檔（判讀成功 {ok_n}/{len(results)}）→ {out}")


if __name__ == "__main__":
    main()
