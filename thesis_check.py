# -*- coding: utf-8 -*-
"""失效條件日檢（P1，2026-08-27，老墨「失效劇本檢查・報告死亡條件」的我們版）。

investment_chief 給判斷時同時登錄可證偽失效條件（state/thesis_conditions.json），
這支每天對照現實，三態輸出：
  🚫 已觸發（價格跨過失效線）——當天標記，只報一次不重複轟炸
  ⚠️ 逼近（距失效線 ≤ NEAR_PCT）——老墨「逼近、今天要看一眼」那招
  ✅ 健康
檢查得動的條件型別（2026-08-31 從 2 種擴到 4 種）：
  price_below / price_above ── 價格線，yfinance 收盤價批次抓，零成本
  supertrend_flip           ── SuperTrend 由多翻空
  rs_below                  ── RS(60日) 跌破自身均線
  metric                    ── 財報門檻，只列「待財報檢」，等該檔財報公布時查證
後兩種走 trade_plan.supertrend_invalidation()（Leo 2026-08-11 自己回測出來的規則，
這裡不重新設計，只是每天問「現在觸發到哪一階段」）。

**為什麼要加後兩種**（2026-08-31 Leo：「失效條件也可以分兩個嗎，不是只有價值投資」）：
盤點當時登錄的 83 條，44 條價格類裡有 39 條寫的是俗貴價、39 條 metric 全部標
「待財報檢」從沒被檢查過——等於**每天真正在檢查的只有估值一個角度**，趨勢角度
形同沒有失效條件。SuperTrend 和 RS 其實每天都算得出來，不需要等財報。

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


_ST_CACHE = {}


def _st_state(tk):
    """這檔的 SuperTrend / RS 現況，回 {st_bearish, rs60_broken, note} 或 None。
    一次 run 內同一檔只算一次——同一檔可能同時登了 supertrend_flip 和 rs_below，
    重算就是白花兩倍時間抓同一份 1 年歷史。"""
    if tk in _ST_CACHE:
        return _ST_CACHE[tk]
    try:
        from trade_plan import supertrend_invalidation
        v = supertrend_invalidation(tk)
    except Exception as e:
        print(f"  ⚠️ {tk} 趨勢狀態算不出來（{type(e).__name__}），這條今天跳過")
        v = None
    _ST_CACHE[tk] = v
    return v


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
    triggered, near, pending_metric = [], [], []
    healthy = {"held": 0, "watch": 0}
    for tk, entry in reg.items():
        px = prices.get(tk)
        # 2026-08-31 修：thesis_conditions.json 登錄時本來就有記 held（投資長 P0 擴充後
        # 非持股的進場評估也會登錄失效條件），但這裡完全沒讀它，結果 48 檔裡 41 檔
        # 非持股的全被推進「🔒持股密報」——Leo 反饋「也推了不是持股的？」。
        # 帶著 held 往下傳，日報才能分流（持股→密報、非持股→公開版）。
        _h = bool(entry.get("held"))
        _trend_needed = any(c.get("type") in ("supertrend_flip", "rs_below")
                            and c.get("status") == "active"
                            for c in entry.get("conditions", []))
        inval = _st_state(tk) if _trend_needed else None
        for c in entry.get("conditions", []):
            if c.get("status") == "triggered":
                continue                      # 已觸發過的不重複報
            ctype, val = c.get("type"), c.get("value")
            ang = c.get("angle", "value")
            desc = c.get("desc", "")

            # ── 趨勢型（每日算得出來，不必等財報）
            if ctype in ("supertrend_flip", "rs_below"):
                if not inval:
                    # 算不出來就誠實掛「待檢」，不要因為抓不到資料就當健康——
                    # 那正是 8 月連踩多次的「綠燈但沒做事」模式
                    pending_metric.append((tk, f"{desc}（趨勢資料不足，今日未檢）", _h, ang))
                    continue
                hit = (inval.get("st_bearish") if ctype == "supertrend_flip"
                       else inval.get("rs60_broken"))
                label = "SuperTrend 翻空" if ctype == "supertrend_flip" else "RS 跌破60MA"
                if hit:
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"{label}｜{desc}", _h, ang))
                else:
                    healthy["held" if _h else "watch"] += 1
                continue

            if ctype == "metric" or not val:
                pending_metric.append((tk, desc, _h, ang))
                continue
            if px is None:
                continue                      # 抓不到價，這條今天跳過（不硬判）
            if ctype == "price_below":
                if px <= val:
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"跌破失效線 {val}（現價 {px:.2f}）｜{desc}", _h, ang))
                elif (px - val) / val <= NEAR_PCT:
                    near.append((tk, f"距失效線 {val} 僅 {(px-val)/val*100:.1f}%（現價 {px:.2f}）", _h, ang))
                else:
                    healthy["held" if _h else "watch"] += 1
            elif ctype == "price_above":
                if px >= val:
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"升破失效線 {val}（現價 {px:.2f}）｜{desc}", _h, ang))
                elif (val - px) / val <= NEAR_PCT:
                    near.append((tk, f"距失效線 {val} 僅 {(val-px)/val*100:.1f}%（現價 {px:.2f}）", _h, ang))
                else:
                    healthy["held" if _h else "watch"] += 1

    json.dump(reg, open(REG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = {"date": date, "triggered": [list(x) for x in triggered],
           "near": [list(x) for x in near],
           "pending_metric": [list(x) for x in pending_metric], "healthy": healthy}
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n_tr = sum(1 for v in reg.values() for c in v.get("conditions", [])
               if c.get("angle") == "trend")
    n_va = sum(1 for v in reg.values() for c in v.get("conditions", [])
               if c.get("angle", "value") == "value")
    print(f"失效條件日檢：🚫新觸發 {len(triggered)}｜⚠️逼近 {len(near)}｜"
          f"✅健康 {healthy}｜📋待檢 {len(pending_metric)}")
    print(f"　登錄簿角度分佈：趨勢 {n_tr} 條｜價值 {n_va} 條")
    # 原本寫 `for tk, msg in triggered`——8/31 加 held 後 tuple 變 3 元素，
    # 這行只要有任何一條真的觸發就會 ValueError。沒炸過只是因為一直沒觸發。
    for tk, msg, _h, ang in triggered:
        print(f"  🚫 [{ang}] {tk}：{msg}")
    for tk, msg, _h, ang in near:
        print(f"  ⚠️ [{ang}] {tk}：{msg}")
    return out


if __name__ == "__main__":
    run()
