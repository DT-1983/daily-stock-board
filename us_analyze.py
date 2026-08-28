"""美股判讀層（本機 Claude 版）→ reports/report_YYYYMMDD.md

取代原本 GitHub Actions 上的 `main.py --no-notify --force-run`（Gemini 3 Flash）。
2026-07-31 搬本機，走 Max plan headless claude，零 API 費用。

- 資料層：yfinance 批次抓 90 日 K → 均線 / 乖離率 / 趨勢強度 / 量能（不花錢）
- 判讀層：依產業鏈分批餵給 Claude，一鏈一次呼叫（7 檔上下）
- 輸出：parse_report() 相容的 markdown（board_html.py 直接吃）

用法：python us_analyze.py [-o reports/report_YYYYMMDD.md]
"""
import os
import io
import sys
import json
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


import yfinance as yf

from llm_board import ask_json

SCREEN_JSON = "screen_result.json"
SIG_EMOJI = {"買進": "🟢", "賣出": "🔴", "觀望": "⚪", "持有": "🔵"}


def load_watch():
    d = json.load(open(SCREEN_JSON, encoding="utf-8"))
    return {chain: [(x["code"], x.get("name", x["code"]), x.get("growth"), x.get("inflow"))
                    for x in lst]
            for chain, lst in d["us"].items()}


def _ma(c, n):
    return round(sum(c[-n:]) / n, 2) if len(c) >= n else None


def _trend_strength(c):
    """0-100：MA 排列 + 斜率 + 站上比例，純算術，給 AI 當輸入不是結論。"""
    m5, m10, m20 = _ma(c, 5), _ma(c, 10), _ma(c, 20)
    if not all((m5, m10, m20)):
        return None
    s = 0
    if m5 > m10 > m20:
        s += 50
    elif m5 > m10 or m10 > m20:
        s += 25
    if len(c) >= 25:
        prev20 = sum(c[-25:-5]) / 20
        if m20 > prev20:
            s += 25
    if c[-1] > m20:
        s += 15
    if c[-1] > m5:
        s += 10
    return min(s, 100)


def _news(code, n=3, max_age_days=7):
    """yfinance 內建新聞（免費）。近 7 天內取 n 條標題給 LLM 當輿情輸入。
    2026-08-04 接回：7/31 砍 Tavily 後判讀理由只剩技術面，用戶要求補新聞層（零成本版）。"""
    from datetime import timezone
    try:
        items = yf.Ticker(code).news or []
    except Exception:
        return []
    out, now = [], datetime.now(timezone.utc)
    for it in items:
        c = it.get("content", it)
        title = (c.get("title") or "").strip()
        if not title:
            continue
        stamp = ""
        try:
            dt = datetime.fromisoformat(str(c.get("pubDate", "")).replace("Z", "+00:00"))
            age = (now - dt).days
            if age > max_age_days:
                continue
            stamp = "今天" if age == 0 else f"{age}天前"
        except Exception:
            pass
        out.append(f"[{stamp}] {title}" if stamp else title)
        if len(out) >= n:
            break
    return out


def build_ctx(code, name, chain, df, growth, inflow):
    c = [float(x) for x in df["Close"].dropna().tolist()]
    if len(c) < 25:
        return None
    h = [float(x) for x in df["High"].dropna().tolist()]
    l = [float(x) for x in df["Low"].dropna().tolist()]
    v = [float(x) for x in df["Volume"].dropna().tolist()]
    last, prev = c[-1], c[-2]
    m5, m10, m20 = _ma(c, 5), _ma(c, 10), _ma(c, 20)
    chg = round((last / prev - 1) * 100, 2) if prev else None
    bias5 = round((last / m5 - 1) * 100, 2) if m5 else None
    vol_ratio = round(v[-1] / (sum(v[-21:-1]) / 20), 2) if len(v) >= 21 and sum(v[-21:-1]) else None
    arrange = ("MA5>MA10>MA20 多頭排列" if m5 > m10 > m20 else
               "MA5<MA10<MA20 空頭排列" if m5 < m10 < m20 else "均線糾結")
    g = f"{growth*100:.0f}%" if isinstance(growth, (int, float)) else "N/A"
    news = _news(code)
    news_line = ("\n  近期新聞: " + "；".join(news)) if news else ""
    ctx = (f"{name}({code})｜{chain}\n"
           f"  收盤 {last:.2f}（昨收 {prev:.2f}，漲跌 {chg}%）高 {h[-1]:.2f} 低 {l[-1]:.2f}\n"
           f"  MA5 {m5} MA10 {m10} MA20 {m20}｜{arrange}｜趨勢強度 {_trend_strength(c)}/100\n"
           f"  乖離率(對MA5) {bias5}%｜量比 {vol_ratio}｜近10日收盤 {[round(x,1) for x in c[-10:]]}\n"
           f"  營收成長 {g}｜資金流入 {inflow}{news_line}")
    meta = {"code": code, "name": name, "chain": chain, "last": round(last, 2),
            "prev": round(prev, 2), "high": round(h[-1], 2), "low": round(l[-1], 2),
            "chg": chg, "ma5": m5, "ma10": m10, "ma20": m20, "arrange": arrange,
            "strength": _trend_strength(c), "bias5": bias5, "vol_ratio": vol_ratio,
            "growth": g}
    return ctx, meta


PROMPT_HEAD = """你是美股短線分析師，服務對象是台灣投資人。以下是【題材趨勢股守備清單】（待進場標的，非持股）。

判斷原則：
- 以**均線趨勢 + 量能**為主，營收成長次之；題材股高估值是常態，不要單因漲多就降評。
- **訊號規則（預設觀望）**：
  · 買進：均線多頭排列 **且** 回踩不追高（乖離率 < 5%）
  · 賣出：均線空頭排列 **且** 跌破關鍵支撐（兩者俱備才給，否則不要輕易賣出）
  · 其餘一律觀望（含弱勢但未破底、或多空混雜）
- 用**繁體中文台灣用語**（部位/加碼/減碼/停損/停利/量增/量縮/類股/回檔）。
- 有附「近期新聞」時，理由/風險要納入判斷並點出關鍵訊息（英文新聞翻成繁中重點）；
  新聞與技術面矛盾時要指出，不要硬湊成同方向。**沒附新聞就不要提到新聞**。
- 只根據下方數據判斷，**不要編造新聞、財報數字或日期**。

請針對每一檔輸出，只回 JSON 陣列，不要任何說明文字：
[{"code":"代號","signal":"買進或賣出或觀望或持有","score":0到100整數,
  "trend":"看多或看空或震盪","oneliner":"一句話決策40字內",
  "reason":"理由100字內，要點到均線與量能","risk":"主要風險50字內",
  "watch":["觀察條件1","觀察條件2"],
  "empty":"空手者怎麼做40字內","holder":"持有者怎麼做40字內"}]

【本批標的】
"""


def analyze_chain(chain, rows, prices):
    ctxs, metas = [], []
    for code, name, growth, inflow in rows:
        df = prices.get(code)
        if df is None or df.empty:
            print(f"  [{code}] 無報價，跳過")
            continue
        built = build_ctx(code, name, chain, df, growth, inflow)
        if not built:
            print(f"  [{code}] K 棒不足，跳過")
            continue
        ctxs.append(built[0])
        metas.append(built[1])
    if not metas:
        return []
    print(f"  → Claude 判讀 {len(metas)} 檔 …", end=" ", flush=True)
    try:
        got = ask_json(PROMPT_HEAD + "\n".join(ctxs))
        by = {str(x.get("code", "")).upper(): x for x in got}
        print("完成")
    except Exception as e:
        print(f"失敗：{e}")
        by = {}
    out = []
    for m in metas:
        j = by.get(m["code"].upper(), {})
        m.update({
            "signal": j.get("signal", "觀望"), "score": j.get("score", 50),
            "trend": j.get("trend", "震盪"), "oneliner": j.get("oneliner", "資料分析失敗"),
            "reason": j.get("reason", ""), "risk": j.get("risk", ""),
            "watch": j.get("watch") or [], "empty": j.get("empty", ""),
            "holder": j.get("holder", ""),
            "emoji": SIG_EMOJI.get(j.get("signal", "觀望"), "⚪"),
        })
        out.append(m)
    return out


def render(rows, date):
    """產 parse_report() 相容的 markdown。

    格式契約（board_html.py）：
      · 摘要區標題含「分析結果摘要」，每行 `EMOJI **名稱(代號)**: 動作 | 評分 N | 趨勢`
      · 個股區 `## EMOJI 名稱 (代號)`，內文含 `**一句話決策**: …` 與 `評分 N`
    """
    n = len(rows)
    cnt = {}
    for r in rows:
        cnt[r["emoji"]] = cnt.get(r["emoji"], 0) + 1
    head = [f"# 🎯 {date} 決策儀表板", "",
            f"> 共分析 **{n}** 檔股票 | "
            + " ".join(f"{k}{v}" for k, v in sorted(cnt.items()))
            + "　·　判讀：Claude（本機）", "",
            "## 📊 分析結果摘要", ""]
    for r in sorted(rows, key=lambda x: -(x["score"] or 0)):
        head.append(f'{r["emoji"]} **{r["name"]}({r["code"]})**: {r["signal"]} '
                    f'| 評分 {r["score"]} | {r["trend"]}')
    body = []
    for r in sorted(rows, key=lambda x: -(x["score"] or 0)):
        watch = "".join(f"\n- {w}" for w in (r["watch"] or [])) or "\n- —"
        body += [
            "", f'## {r["emoji"]} {r["name"]} ({r["code"]})', "",
            "### 📌 核心結論", "",
            f'**{r["emoji"]} {r["signal"]}** | {r["trend"]} | 評分 {r["score"]}', "",
            f'> **一句話決策**: {r["oneliner"]}', "",
            f'**理由**：{r["reason"]}', "",
            f'**主要風險**：{r["risk"]}', "",
            "**觀察條件**：" + watch, "",
            "| 持倉情況 | 操作建議 |", "|---|---|",
            f'| 🆕 **空手者** | {r["empty"] or "—"} |',
            f'| 💼 **持有者** | {r["holder"] or "—"} |', "",
            "### 📈 當日行情", "",
            "| 收盤 | 昨收 | 最高 | 最低 | 漲跌幅 |", "|---|---|---|---|---|",
            f'| {r["last"]} | {r["prev"]} | {r["high"]} | {r["low"]} | {r["chg"]}% |', "",
            "### 📊 數據透視", "",
            f'**均線排列**: {r["arrange"]} | 趨勢強度: {r["strength"]}/100', "",
            "| MA5 | MA10 | MA20 | 乖離率(MA5) | 量比 | 營收成長 |",
            "|---|---|---|---|---|---|",
            f'| {r["ma5"]} | {r["ma10"]} | {r["ma20"]} | {r["bias5"]}% '
            f'| {r["vol_ratio"]} | {r["growth"]} |', "",
        ]
    return "\n".join(head + body) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    watch = load_watch()
    codes = sorted({c for lst in watch.values() for c, *_ in lst})
    print(f"美股守備清單 {len(codes)} 檔，{len(watch)} 條鏈")

    print("抓報價 …", end=" ", flush=True)
    raw = yf.download(codes, period="6mo", progress=False, threads=False,
                      auto_adjust=True, group_by="ticker")
    prices = {}
    for c in codes:
        try:
            prices[c] = raw[c].dropna(how="all")
        except Exception:
            pass
    print(f"取得 {len(prices)}/{len(codes)} 檔")

    rows = []
    for chain, lst in watch.items():
        print(f"[{chain}] {len(lst)} 檔")
        rows += analyze_chain(chain, lst, prices)

    # 去重：同一檔可能同時在多條鏈（NVDA/AMD/MU…），不去重看板會渲染兩張卡。
    # board_html 的 CHAIN_MAP 本來就把一檔歸到單一鏈，所以留評分最高那筆即可。
    best = {}
    for r in rows:
        cur = best.get(r["code"])
        if cur is None or (r["score"] or 0) > (cur["score"] or 0):
            best[r["code"]] = r
    if len(best) != len(rows):
        print(f"去重：{len(rows)} → {len(best)} 檔（跨鏈重複）")
    rows = list(best.values())

    # 2026-08-28 加完整性守門。背景：8/28 07:00 headless claude OAuth 過期，
    # analyze_chain() 的 ask_json() 對每一條鏈都失敗，但只是印一行「失敗：...」、
    # 不拋例外——所有股票照樣落回預設值(觀望/50分/oneliner="資料分析失敗")寫進
    # report，主程式正常結束（exit 0）。board_analyze_daily.cmd 完全沒有察覺，
    # 網站直接發布了一份「全部60檔都判讀失敗」但看起來像正常資料的看板。
    # 現在算真正判讀成功的比例，太低就非零結束——讓 .cmd 的失敗通知抓到，
    # 也不覆蓋昨天還算數的舊報告（同 buffett_scan.py 的 MIN_FETCH_RATE 精神）。
    ok_n = sum(1 for r in rows if r.get("oneliner") != "資料分析失敗")
    ok_rate = ok_n / len(rows) if rows else 0
    if rows and ok_rate < 0.5:
        print(f"❌ AI 判讀成功率過低（{ok_n}/{len(rows)}={ok_rate:.0%}），"
              f"疑似 claude 呼叫系統性失敗（OAuth過期/額度等），不覆蓋今天的報告")
        sys.exit(1)

    date = datetime.now().strftime("%Y-%m-%d")
    out = args.output or f"reports/report_{datetime.now():%Y%m%d}.md"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w", encoding="utf-8").write(render(rows, date))
    print(f"\n✅ 美股分析 {len(rows)} 檔（判讀成功 {ok_n}/{len(rows)}）→ {out}")


if __name__ == "__main__":
    main()
