# -*- coding: utf-8 -*-
"""失效條件日檢（P1，2026-08-27，老墨「失效劇本檢查・報告死亡條件」的我們版）。

investment_chief 給判斷時同時登錄可證偽失效條件（state/thesis_conditions.json），
這支每天對照現實，三態輸出：
  🚫 已觸發（價格跨過失效線）——當天標記，只報一次不重複轟炸
  ⚠️ 逼近（距失效線 ≤ NEAR_PCT）——老墨「逼近、今天要看一眼」那招
  ✅ 健康
價格類（price_below/price_above）零成本日檢（yfinance 收盤價批次抓）；
metric 類（財報門檻）這裡只列「待財報檢」，等該檔財報公布時由 earnings_watch
的 AI 快訊查證（v1.1 要接的 hook，還沒接——先誠實標待檢，不假裝檢查過）。

輸出 state/thesis_check_today.json 給 daily_warroom 組進持股密報。
用法: python thesis_check.py
"""
import os
import sys
import json
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

REG_PATH = "state/thesis_conditions.json"
OUT_PATH = "state/thesis_check_today.json"
NEAR_PCT = 0.02      # 距失效線 2% 內算「逼近」


def _yf_symbol(tk):
    import re
    if re.match(r"^\d{4,6}[A-Z]?$", str(tk)):
        return f"{tk}.TW"
    return str(tk)


def run():
    reg = {}
    if os.path.exists(REG_PATH):
        try:
            reg = json.load(open(REG_PATH, encoding="utf-8"))
        except Exception:
            reg = {}
    if not reg:
        print("沒有登錄任何失效條件（投資長還沒產出過帶conditions的判斷）")
        return None

    price_tks = sorted({tk for tk, e in reg.items()
                        if any(c.get("type") in ("price_below", "price_above")
                               and c.get("status") == "active"
                               and c.get("value") for c in e.get("conditions", []))})
    prices = {}
    if price_tks:
        import yfinance as yf
        syms = [_yf_symbol(t) for t in price_tks]
        data = yf.download(syms, period="5d", progress=False, threads=False,
                           auto_adjust=True, group_by="ticker")
        for tk, sym in zip(price_tks, syms):
            # group_by="ticker" 時就算只有1檔，欄位也可能是 (sym, Close) 多層——
            # 先試 data[sym]，失敗才退平面格式（單檔首測就是栽在這裡，健康數變0）
            try:
                df = data[sym]
            except Exception:
                df = data
            try:
                prices[tk] = float(df["Close"].dropna().iloc[-1])
            except Exception:
                pass

    date = time.strftime("%Y-%m-%d")
    triggered, near, pending_metric, healthy = [], [], [], 0
    for tk, entry in reg.items():
        px = prices.get(tk)
        for c in entry.get("conditions", []):
            if c.get("status") == "triggered":
                continue                      # 已觸發過的不重複報
            ctype, val = c.get("type"), c.get("value")
            if ctype == "metric" or not val:
                pending_metric.append((tk, c.get("desc", "")))
                continue
            if px is None:
                continue                      # 抓不到價，這條今天跳過（不硬判）
            if ctype == "price_below":
                if px <= val:
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"跌破失效線 {val}（現價 {px:.2f}）｜{c.get('desc','')}"))
                elif (px - val) / val <= NEAR_PCT:
                    near.append((tk, f"距失效線 {val} 僅 {(px-val)/val*100:.1f}%（現價 {px:.2f}）"))
                else:
                    healthy += 1
            elif ctype == "price_above":
                if px >= val:
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"升破失效線 {val}（現價 {px:.2f}）｜{c.get('desc','')}"))
                elif (val - px) / val <= NEAR_PCT:
                    near.append((tk, f"距失效線 {val} 僅 {(val-px)/val*100:.1f}%（現價 {px:.2f}）"))
                else:
                    healthy += 1

    json.dump(reg, open(REG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = {"date": date, "triggered": [list(x) for x in triggered],
           "near": [list(x) for x in near],
           "pending_metric": [list(x) for x in pending_metric], "healthy": healthy}
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"失效條件日檢：🚫新觸發 {len(triggered)}｜⚠️逼近 {len(near)}｜"
          f"✅健康 {healthy}｜📋待財報檢 {len(pending_metric)}")
    for tk, msg in triggered:
        print(f"  🚫 {tk}：{msg}")
    for tk, msg in near:
        print(f"  ⚠️ {tk}：{msg}")
    return out


if __name__ == "__main__":
    run()
