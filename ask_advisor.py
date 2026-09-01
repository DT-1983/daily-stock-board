# -*- coding: utf-8 -*-
"""臨時單檔評估：把任何一檔股票丟給軍師團看一眼（2026-09-01 建）。

用途：朋友推薦一檔、新聞看到一檔，想知道系統怎麼看——但它不在持股、不在守備
清單、也不在巴菲特候選池，每日排程完全不會碰到它。

    python ask_advisor.py 9914           # 台股裸代號自動補後綴
    python ask_advisor.py NVDA --push    # 同時推 Discord
    python ask_advisor.py 9914 --watch   # 評估完登錄失效條件，進每日日檢

⚠️ 為什麼不直接呼叫 investment_chief.gather_material：那支的材料全部從既有
state 檔讀（signals / valuation_state / buffett_watch / screen_result），對不在
追蹤清單的標的會一路回「查無」，孔明只會得到「資料不足」——**看起來有跑，實際
沒有判斷價值**。所以這裡當場算，再餵同一套 prompt。

⚠️ 判斷會寫進 state/advisor_verdicts.jsonl，但帶 source="ad-hoc"：臨時問的跟
每日自動觸發的性質不同（一個是我挑的、一個是系統挑的），復盤時混在一起統計
會失真，要分得開。
"""
import argparse
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NL = chr(10)
VERDICTS_PATH = "state/advisor_verdicts.jsonl"


def _trend_material(code, sym):
    """當場算趨勢面：現價、SuperTrend 方向、Mansfield RS。"""
    import price_store
    import st_alert
    import technical_indicators as ti

    out = []
    ohlc = price_store.get_ohlc([sym], period="3y")   # 3y 不可改短，見 investment_chief._snapshot_prices
    df = ohlc.get(sym)
    if df is None or df.empty:
        return "查無價量資料（這檔可能代號有誤或已下市）", None, None
    px = float(df["Close"].dropna().iloc[-1])
    asof = str(df.index[-1])[:10]
    out.append(f"現價 {px:,.2f}（收盤日 {asof}）")

    try:
        d = st_alert.cur_dir(df)
        out.append(f"SuperTrend 方向：{'多頭（綠）' if d else '空頭（紅）'}")
    except Exception as e:                            # noqa: BLE001
        out.append(f"SuperTrend 算不出來：{str(e)[:60]}")

    try:
        bench = ti._benchmark(sym)
        b = price_store.get_closes([bench], period="3y").get(bench)
        if b is not None and len(b):
            # mansfield_rs 回的是 {"short":…, "long":…} 兩個窗口，不是單一數字
            rs = ti.mansfield_rs(df["Close"].dropna().tolist(), b.dropna().tolist()) or {}
            seg = [f"{k}({'30日' if k=='short' else '250日'}) {v:+.2f}%"
                   for k, v in rs.items() if v is not None]
            if seg:
                out.append(f"Mansfield RS vs {bench}：" + "、".join(seg)
                           + "（>0 強於大盤、<0 弱於大盤）")
    except Exception as e:                            # noqa: BLE001
        out.append(f"RS 算不出來：{str(e)[:60]}")
    return NL.join(out), px, asof


def _value_material(code, sym):
    """當場算價值面：洪瑞泰四關 + 俗貴價。沿用 buffett_screener，不另立標準。"""
    try:
        from buffett_screener import fetch_fundamentals, evaluate
    except Exception as e:                            # noqa: BLE001
        return f"買不到 buffett_screener：{str(e)[:80]}"
    # ⚠️ 一定要傳帶後綴的 sym：實測 fetch_fundamentals("9914") 直接 404
    #    （Yahoo 找不到裸台股代號），要 "9914.TW"
    f = fetch_fundamentals(sym) or {}
    if not f:
        return "查無基本面資料（洪瑞泰四關與俗貴價都算不出來）"
    try:
        r = evaluate(f) or {}
    except Exception as e:                            # noqa: BLE001
        r = {}
        print(f"  [warn] evaluate 失敗：{str(e)[:80]}")
    # 欄位名以 buffett_screener.evaluate 的實際回傳為準（cheap_price / exp_price /
    # quality_ok / trap_flags），不是自己另取名字——動洪瑞泰相關前先讀
    # memory/hongruitai_method.md。
    parts = []
    if r.get("cheap_price") or r.get("exp_price"):
        parts.append(f"俗價 {r.get('cheap_price')}｜貴價 {r.get('exp_price')}｜"
                     f"現價 {r.get('price')}　訊號 {r.get('signal_emoji','')}{r.get('signal','')}")
    if r.get("changli_eps") is not None:
        parts.append(f"常利 EPS {r['changli_eps']}（基準：{r.get('changli_basis','')}），"
                     f"TTM EPS {r.get('eps_ttm')}")
    if r.get("roe_history"):
        parts.append("ROE 近四年：" + "、".join(
            f"{x*100:.1f}%" if x is not None else "N/A" for x in r["roe_history"]))
    if r.get("eps_history"):
        parts.append("EPS 近四年：" + "、".join(str(x) for x in r["eps_history"]))
    for k, label, pct in (("roe_current", "ROE(現)", True),
                          ("reinvest_ratio", "盈再率", True),
                          ("payout_ratio", "配息率", True),
                          ("debt_to_equity", "負債權益比", False)):
        v = r.get(k)
        if v is not None:
            parts.append(f"{label} {v*100:.1f}%" if pct else f"{label} {v}")
    if r.get("reinvest_grade"):
        parts.append(f"盈再率評等：{r['reinvest_grade']}")
    parts.append(f"洪瑞泰品質關：{'通過' if r.get('quality_ok') else '未通過'}")
    if r.get("trap_flags"):
        parts.append(f"⚠️ 地雷旗標：{r['trap_flags']}")
    if r.get("needs_review"):
        parts.append("⚠️ 這檔被標記為需要人工複核")
    return NL.join(parts) if parts else "基本面資料不足，無法套洪瑞泰四關"


def _extra_material(code):
    """預估前提檢查（base_rate）＋ 毛利率循環位階（margin_cycle）。"""
    out = []
    try:
        import base_rate
        c = base_rate.check(code)
        if c and c.get("requirement"):
            out.append("預估前提檢查：" + base_rate.line(c))
    except Exception as e:                            # noqa: BLE001
        out.append(f"（預估前提檢查失敗：{str(e)[:60]}）")
    try:
        import margin_cycle
        ln = margin_cycle.line(code)
        if ln:
            out.append("毛利率循環位階：" + ln)
    except Exception as e:                            # noqa: BLE001
        out.append(f"（毛利率位階失敗：{str(e)[:60]}）")
    return NL.join(out)


def main():
    ap = argparse.ArgumentParser(description="臨時請軍師評估單一標的")
    ap.add_argument("ticker", help="代號：9914 / 1580.TWO / NVDA")
    ap.add_argument("--push", action="store_true", help="同時推 Discord 持股密報")
    ap.add_argument("--watch", action="store_true",
                    help="登錄失效條件進 state/thesis_conditions.json（納入每日日檢）")
    a = ap.parse_args()

    import tw_symbol
    code = a.ticker.strip().upper()
    sym = tw_symbol.resolve(code)
    print(f"=== 臨時評估 {code}（yfinance 代號 {sym}）===" + NL)

    print("[1/4] 趨勢面…")
    trend_m, px, asof = _trend_material(code, sym)
    print("[2/4] 價值面…")
    value_m = _value_material(code, sym)
    print("[3/4] 預估前提 + 毛利率位階…")
    extra = _extra_material(code)
    if extra:
        value_m = value_m + NL + extra

    print("[4/4] 請孔明判斷…")
    from investment_chief import ask_claude
    date = time.strftime("%Y-%m-%d")
    v = ask_claude(code, code,
                   "（臨時評估：這檔不在每日追蹤清單，無 AI 綜合訊號）",
                   value_m, trend_m, "", date,
                   held=False, triggers=["臨時評估（ask_advisor）"])
    v["held"] = False
    v["triggers"] = ["臨時評估（ask_advisor）"]
    v["source"] = "ad-hoc"
    v["price"] = round(px, 4) if px is not None else None
    # ⚠️ 用實際收盤日不是執行日：美股在台灣時間白天跑，最後收盤是前一天，
    #    寫成今天會讓回測的基準價對錯日期。
    v["price_asof"] = asof or date
    v["price_symbol"] = sym

    for angle in ("trend_angle", "value_angle"):
        d = v.get(angle) or {}
        print(NL + f"── {'趨勢角度' if angle=='trend_angle' else '價值角度'}："
                   f"{d.get('judgment','?')} ──")
        print(d.get("brief") or "")
        if d.get("reasoning"):
            print(NL + d["reasoning"][:600])

    os.makedirs("state", exist_ok=True)
    with open(VERDICTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(v, ensure_ascii=False) + NL)
    print(NL + f"已存進 {VERDICTS_PATH}（source=ad-hoc，基準價 {v['price']}）")

    if a.watch:
        from investment_chief import _register_conditions
        _register_conditions([v])
        print("已登錄失效條件，明天起進每日日檢")

    if a.push:
        from notify_discord import send_discord
        msg = (f"# 🧭 臨時評估 · {code}" + NL
               + f"-# {date}　現價 {v['price']}　（Leo 指定，不在每日追蹤清單）" + NL * 2
               + f"**趨勢角度：{(v.get('trend_angle') or {}).get('judgment','?')}**" + NL
               + ((v.get("trend_angle") or {}).get("brief") or "") + NL * 2
               + f"**價值角度：{(v.get('value_angle') or {}).get('judgment','?')}**" + NL
               + ((v.get("value_angle") or {}).get("brief") or ""))
        ok = send_discord("private", msg, persona="孔明")
        print("已推 Discord" if ok else "⚠️ Discord 推送失敗（判斷已存檔，沒有遺失）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
