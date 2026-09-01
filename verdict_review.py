# -*- coding: utf-8 -*-
"""陳壽-復盤官（骨架，2026-09-01 建）：回頭檢查孔明的判斷準不準。

回答的是「**這套系統的判斷有沒有價值**」，不是「Leo 有沒有照著做」——
後者要逐筆成交紀錄（Firstrade/IB/台股），還沒有，見 dev_log。

    python verdict_review.py                # 看現況
    python verdict_review.py --backfill     # 回填舊判斷缺的基準價
    python verdict_review.py --push         # 推 Discord

## 四個評估設計（借鑑 ZhuLinsen/daily_stock_analysis 的 backtest_engine）

1. **評估窗口**：判斷後 N 個「交易日」才算數（不是日曆天，台美股休市日不同）
2. **中性帶**：±BAND% 內不算對也不算錯——沒有這個，勝率會被雜訊灌水
3. **first_hit**：論點失效價有沒有在窗口內被真的觸發（比只看終點誠實）
4. **對照組**：照判斷做 vs 單純持有，才知道判斷有沒有加值

## ⚠️ 參數是起步值，不是有依據的門檻

EVAL_DAYS=20 / BAND=2.0 目前是**沿用上游預設**，還沒用實測分布校準。
累積夠樣本後要照 chip_scan_thresholds / margin_cycle 的紀律重訂：
**先看實際分布的天然斷點，再訂門檻**，不要拍腦袋。
台股與美股的日波動不同，最終很可能要分開設。
"""
import argparse
import io
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NL = chr(10)
VERDICTS_PATH = "state/advisor_verdicts.jsonl"

EVAL_DAYS = 20        # 交易日；起步值，待實測校準
BAND = 2.0            # 中性帶 %；起步值，待實測校準

# judgment → 方向。「觀望」不計入方向準確度（它本來就沒有方向主張），
# 但仍記錄後續走勢——「觀望之後其實大漲」是有意義的訊息。
DIRECTION = {"續抱/可買": "bull", "考慮出場": "bear", "觀望": "neutral"}


def _load():
    if not os.path.exists(VERDICTS_PATH):
        return []
    out = []
    for ln in io.open(VERDICTS_PATH, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:      # noqa: BLE001
                pass
    return out


def _bars(sym):
    """回該代號的日 OHLC。period 固定 3y——price_store 寫快取是直接覆蓋不合併，
    用短天期會洗掉 industry_rotation(RRG) 依賴的三年資料。"""
    import price_store
    return price_store.get_ohlc([sym], period="3y").get(sym)


def backfill(rows):
    """回填舊判斷缺的基準價。

    ⚠️ 回填值一律標 price_src="backfilled"：判斷是盤中做的，回填只能拿當天
    收盤價，兩者不同。混進統計會讓結果看起來比實際精確，必須分得開。
    """
    import tw_symbol
    need = [r for r in rows if r.get("price") is None and r.get("ts")]
    if not need:
        print("沒有需要回填的判斷")
        return rows, 0
    syms = {}
    for r in need:
        syms.setdefault(tw_symbol.resolve(r["ticker"]), []).append(r)
    n = 0
    for sym, rs in syms.items():
        df = _bars(sym)
        if df is None or df.empty:
            continue
        s = df["Close"].dropna()
        idx = [str(x)[:10] for x in s.index]
        for r in rs:
            d = r["ts"][:10]
            hit = [i for i, x in enumerate(idx) if x <= d]
            if not hit:
                continue
            k = hit[-1]
            r["price"] = round(float(s.iloc[k]), 4)
            r["price_asof"] = idx[k]
            r["price_symbol"] = sym
            r["price_src"] = "backfilled"
            n += 1
    with io.open(VERDICTS_PATH, "w", encoding="utf-8", newline=NL) as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + NL)
    print(f"已回填 {n}/{len(need)} 筆（標記 price_src=backfilled，統計時與實時記錄分開）")
    return rows, n


def evaluate(r, angle):
    """回單筆的評估結果，或 None（不可評）。"""
    import tw_symbol
    a = r.get(angle) or {}
    j = a.get("judgment")
    if j not in DIRECTION or r.get("price") is None:
        return None
    sym = r.get("price_symbol") or tw_symbol.resolve(r["ticker"])
    df = _bars(sym)
    if df is None or df.empty:
        return None
    base_day = (r.get("price_asof") or r.get("ts", ""))[:10]
    idx = [str(x)[:10] for x in df.index]
    pos = [i for i, x in enumerate(idx) if x <= base_day]
    if not pos:
        return None
    i0 = pos[-1]
    after = df.iloc[i0 + 1:]                 # 基準日「之後」的交易日
    elapsed = len(after)
    base = float(r["price"])
    res = {"ticker": r["ticker"], "angle": angle, "judgment": j,
           "dir": DIRECTION[j], "base": base, "base_day": base_day,
           "elapsed": elapsed, "src": r.get("source", "daily"),
           "price_src": r.get("price_src", "live"), "mature": elapsed >= EVAL_DAYS}
    if elapsed == 0:
        res.update({"ret": None, "outcome": "評估中", "first_hit": None})
        return res
    win = after.iloc[:EVAL_DAYS]
    last = float(win["Close"].dropna().iloc[-1])
    res["ret"] = round((last / base - 1) * 100, 2)

    # first_hit：論點失效價有沒有在窗口內真的被觸發（用當日高低點，不是收盤價）
    inv = a.get("invalidation_price")
    if isinstance(inv, (int, float)) and inv:
        lo, hi = win["Low"].min(), win["High"].max()
        if res["dir"] == "bull":
            res["first_hit"] = "失效價被跌破" if float(lo) <= inv else None
        elif res["dir"] == "bear":
            res["first_hit"] = "失效價被突破" if float(hi) >= inv else None
        else:
            res["first_hit"] = None
    else:
        res["first_hit"] = None

    if not res["mature"]:
        res["outcome"] = "評估中"
    elif res["dir"] == "neutral":
        res["outcome"] = "無方向主張"
    elif abs(res["ret"]) <= BAND:
        res["outcome"] = "持平"
    elif (res["ret"] > 0) == (res["dir"] == "bull"):
        res["outcome"] = "對"
    else:
        res["outcome"] = "錯"
    return res


def summarize(results):
    from collections import Counter
    NLx = chr(10)
    mature = [r for r in results if r["mature"] and r["outcome"] in ("對", "錯", "持平")]
    pend = [r for r in results if r["outcome"] == "評估中"]
    L = [f"# 📜 判斷復盤　{time.strftime('%Y-%m-%d')}", ""]

    if mature:
        ok = sum(1 for r in mature if r["outcome"] == "對")
        ng = sum(1 for r in mature if r["outcome"] == "錯")
        fl = sum(1 for r in mature if r["outcome"] == "持平")
        L += [f"已滿 {EVAL_DAYS} 交易日：**{len(mature)} 筆**　"
              f"對 {ok}／錯 {ng}／持平 {fl}（中性帶 ±{BAND}%）", ""]
        if len(mature) < 30:
            L.append(f"-# ⚠️ 只有 {len(mature)} 筆，樣本太小，勝率**不要當成結論**。")
        for r in sorted(mature, key=lambda x: -(abs(x["ret"] or 0)))[:12]:
            mark = {"對": "✅", "錯": "❌", "持平": "➖"}[r["outcome"]]
            fh = f"　{r['first_hit']}" if r["first_hit"] else ""
            L.append(f"{mark} `{r['ticker']}` {r['judgment']}　{r['ret']:+.1f}%{fh}")
        L.append("")

    # 就算還沒有任何一筆到期，也要讓人看得到「累積到哪了」——
    # 只印一句「樣本不足」看起來跟壞掉沒兩樣。
    if pend:
        need = min(EVAL_DAYS - r["elapsed"] for r in pend)
        L += [f"## 累積中（{len(pend)} 筆判斷尚未滿 {EVAL_DAYS} 交易日）", "",
              f"最快 **{need}** 個交易日後出現第一批結果。"]
        jc = Counter(r["judgment"] for r in pend)
        L.append("判斷分布：" + "、".join(f"{k} {v}" for k, v in jc.most_common()))
        bf = sum(1 for r in pend if r["price_src"] == "backfilled")
        if bf:
            L.append(f"-# 其中 {bf} 筆的基準價是**事後回填**（判斷是盤中做的、"
                     f"回填只能取當日收盤），統計時會與實時記錄分開看。")
        hits = [r for r in pend if r.get("first_hit")]
        if hits:
            L += ["", f"**已觸發論點失效價：{len(hits)} 筆**（窗口未滿，但失效價已被摸到）"]
            for r in hits[:8]:
                L.append(f"　⚡ `{r['ticker']}` {r['judgment']}　{r['first_hit']}"
                         f"　目前 {r['ret']:+.1f}%")
        rets = [r["ret"] for r in pend if r["ret"] is not None]
        if rets:
            rets.sort()
            L += ["", f"-# 目前浮動：中位 {rets[len(rets)//2]:+.1f}%、"
                      f"區間 {rets[0]:+.1f}% ~ {rets[-1]:+.1f}%。"
                      f"**這不是準確度**——窗口未滿，只是讓你看到資料有在動。"]
    if not mature and not pend:
        L.append("目前沒有任何可評估的判斷（需要基準價，用 --backfill 回填舊資料）。")
    return NLx.join(L)


def main():
    ap = argparse.ArgumentParser(description="判斷準確度復盤（陳壽）")
    ap.add_argument("--backfill", action="store_true", help="回填舊判斷缺的基準價")
    ap.add_argument("--push", action="store_true", help="推 Discord 持股密報")
    a = ap.parse_args()

    rows = _load()
    print(f"讀到 {len(rows)} 筆判斷")
    if a.backfill:
        rows, _ = backfill(rows)

    results = []
    for r in rows:
        for angle in ("trend_angle", "value_angle"):
            e = evaluate(r, angle)
            if e:
                results.append(e)
    print(f"可評估 {len(results)} 筆（角度分開算）")
    have_price = sum(1 for r in rows if r.get("price") is not None)
    print(f"  其中有基準價的判斷：{have_price}/{len(rows)}"
          f"（沒有基準價就無法評估，用 --backfill 回填）")

    msg = summarize(results)
    print(NL + msg)
    if a.push:
        from notify_discord import send_discord
        if send_discord("private", msg, persona="陳壽"):
            print(NL + "已推 Discord")
        else:
            print(NL + "⚠️ Discord 推送失敗")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
