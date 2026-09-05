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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tw_symbol

REG_PATH = "state/thesis_conditions.json"
OUT_PATH = "state/thesis_check_today.json"
NEAR_PCT = 0.02      # 距失效線 2% 內算「逼近」

# 趨勢型條件：型別 → (是否觸發的判斷式, 顯示標籤)。
# 2026-09-01 補反向型別：原本只有「由多翻空」，但**非持股的看空判斷需要反向的
# 失效條件**（「如果它由空翻多，代表我看空錯了」），AI 只能硬套同一個 type，
# 結果 desc 寫「由空翻多」卻被拿去對 st_bearish 檢查 → 實測 5 個新觸發裡
# 3 個是假訊號（1580/2731/4763，畫面上「翻空」跟 desc 的「翻多」自相矛盾，
# Leo 一眼看出來）。方向必須跟判斷相反，型別就要成對。
TREND_TYPES = {
    "supertrend_bear": lambda bear, rsdn: bear,          # 由多翻空
    "supertrend_bull": lambda bear, rsdn: not bear,      # 由空翻多
    "rs_below":        lambda bear, rsdn: rsdn,          # 跌破 60MA
    "rs_above":        lambda bear, rsdn: not rsdn,      # 站回 60MA
    # 舊型別相容：9/1 之前登錄的都是這個名字，語意等同 supertrend_bear
    "supertrend_flip": lambda bear, rsdn: bear,
}
TREND_LABEL = {
    "supertrend_bear": "SuperTrend 翻空", "supertrend_bull": "SuperTrend 翻多",
    "rs_below": "RS 跌破60MA", "rs_above": "RS 站回60MA",
    "supertrend_flip": "SuperTrend 翻空",
}

# 🔴 2026-09-05（Leo：「SuperTrend 翻空／RS(60) 跌破自身均線，可以幫我針對持股
# 特別標示嗎？」）——這兩型是**唯二方向不會有歧義的出場訊號**。
#
# 為什麼要獨立成一組：9/5 當天日檢一次觸發 40 條，其中 32 條意思是**相反的**
# （RS 站回均線＝之前的出場疑慮解除），版面上跟真正該看的兩條長得一模一樣。
# ⚠️ `price_above` 不能放進來——同一個型別兩種意思：BEN 身上一條是「漲破貴價
# 45.30 → 出場」，另一條是「站回翻空點 35.55 → 減碼訊號解除」。
# ⭐ 只把「型別本身就等於方向」的兩型標紅，其餘維持原樣，寧可少標不要標錯。
EXIT_TYPES = ("supertrend_bear", "supertrend_flip", "rs_below")


def _yf_symbol(tk):
    # 2026-08-31：原本裸代號一律接 .TW，上櫃股（3264/3265 已在登錄名單裡）拿不到
    # 收盤價，price_below/above 這類條件會靜默地永遠檢不了。改走共用解析。
    return tw_symbol.resolve(tk)


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


def coverage_gap(reg):
    """哪些持股**根本沒有任何條件在被檢查**——這支每天回報的「✅健康 N 條」只涵蓋
    有登錄條件的股票，沒登錄的不會出現在任何一個數字裡，是徹底的靜默盲區。

    2026-09-03 首次量測：持股母體 87 個代號（含多種寫法），去重後仍有一大半
    **從來沒被投資長判斷過**，所以沒有失效條件，所以每天的日檢完全碰不到它們。
    原因不是 bug 是設計——投資長是事件驅動，沒事件就不判；但「沒被判過」跟
    「判過而且沒事」在日報上長得一模一樣，這才是問題。

    ⚠️ 這裡只**回報**不自動重判。強制重判要花 AI 錢（實測每檔約 $0.14），
    要花多少、補哪些是 Leo 的決定，見 [[feedback_no_auto_paid_provider]]。

    回 (未覆蓋清單, 已覆蓋數)。清單元素 (正規化代號, 顯示用原代號)。
    """
    try:
        from investment_chief import held_universe, norm_ticker
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠️ 持股涵蓋率檢查略過（讀不到持股母體）：{e}")
        return [], 0
    # 登錄簿裡「至少有一條每天檢查得動的 active 條件」才算真的有在監控——
    # 只剩 metric（待財報檢）的等於每天什麼都沒檢查，不能算覆蓋。
    covered = set()
    for tk, e in reg.items():
        if any(c.get("status") == "active" and c.get("type") in TREND_TYPES
               or (c.get("status") == "active"
                   and c.get("type") in ("price_below", "price_above") and c.get("value"))
               for c in e.get("conditions", [])):
            covered.add(norm_ticker(tk))

    seen, gap = {}, []
    for raw in held_universe():
        n = norm_ticker(raw)
        if n in seen:
            continue                    # 同一檔的第二種寫法，不重複算
        seen[n] = raw
        if n not in covered:
            gap.append((n, raw))
    return sorted(gap), len([n for n in seen if n in covered])


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

    # 🔴 2026-09-04：同一檔曾同時以 2454 與 2454.TW 兩個 key 存在（投資長那邊
    # key 沒正規化 → 新判斷沒覆蓋掉舊判斷），我們這裡是逐筆走 reg.items()，
    # 等於**拿投資長已經換掉的舊條件**去報失效。讀取端也收斂一次，這樣就算
    # 登錄簿還是舊的（例如從備份還原），今天的日檢也不會用到過期的論點。
    n_before = len(reg)
    from investment_chief import normalize_registry
    reg = normalize_registry(reg)
    if len(reg) != n_before:
        print(f"  登錄簿收斂重複代號：{n_before} → {len(reg)} 檔"
              f"（同一檔的舊論點已被較新的那份取代）")

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
        _trend_needed = any(c.get("type") in TREND_TYPES
                            and c.get("status") == "active"
                            for c in entry.get("conditions", []))
        _born = entry.get("source_date")
        inval = _st_state(tk) if _trend_needed else None
        for c in entry.get("conditions", []):
            if c.get("status") == "triggered":
                continue                      # 已觸發過的不重複報
            ctype, val = c.get("type"), c.get("value")
            ang = c.get("angle", "value")
            desc = c.get("desc", "")

            # ── 趨勢型（每日算得出來，不必等財報）
            if ctype in TREND_TYPES:
                if not inval:
                    # 算不出來就誠實掛「待檢」，不要因為抓不到資料就當健康——
                    # 那正是 8 月連踩多次的「綠燈但沒做事」模式
                    pending_metric.append((tk, f"{desc}（趨勢資料不足，今日未檢）", _h, ang))
                    continue
                bear = bool(inval.get("st_bearish"))
                rsdn = bool(inval.get("rs60_broken"))
                hit, label = TREND_TYPES[ctype](bear, rsdn), TREND_LABEL[ctype]
                if hit:
                    # 2026-09-01：登錄當天就成立的不算「新觸發」——那代表條件被寫成
                    # **現況描述**而不是未來事件（實例 2618 的「RS 持續低於均線未收復」，
                    # 一登錄就 triggered）。這種不是失效，是條件本身沒寫好，
                    # 混進 🚫 會稀釋真正的訊號。標成待處理讓它看得見但不佔警示版面。
                    if _born == date:
                        pending_metric.append(
                            (tk, f"{desc}（⚠️登錄當天即成立，條件寫成現況描述非未來事件）",
                             _h, ang))
                        continue
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"{label}｜{desc}", _h, ang, ctype))
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
                    triggered.append((tk, f"跌破失效線 {val}（現價 {px:.2f}）｜{desc}", _h, ang, ctype))
                elif (px - val) / val <= NEAR_PCT:
                    near.append((tk, f"距失效線 {val} 僅 {(px-val)/val*100:.1f}%（現價 {px:.2f}）", _h, ang))
                else:
                    healthy["held" if _h else "watch"] += 1
            elif ctype == "price_above":
                if px >= val:
                    c["status"], c["triggered_date"] = "triggered", date
                    triggered.append((tk, f"升破失效線 {val}（現價 {px:.2f}）｜{desc}", _h, ang, ctype))
                elif (val - px) / val <= NEAR_PCT:
                    near.append((tk, f"距失效線 {val} 僅 {(val-px)/val*100:.1f}%（現價 {px:.2f}）", _h, ang))
                else:
                    healthy["held" if _h else "watch"] += 1

    # ── 存量視角：持股「現在」的兩條出場訊號狀態 ──────────────────
    # 🔴 2026-09-05 Leo 問「現在美股持股有哪些 SuperTrend 翻空？」——當時系統
    # **沒有任何地方看得到這個**，只能一天一天從觸發事件裡拼回來。
    # 因為上面的 triggered 是「今天剛發生的事件」，而多數翻空的持股是更早就翻的、
    # 甚至**登錄條件時就已經是空方**（那種會被歸到 pending_metric，不算新觸發），
    # 所以它們永遠不會再出現在事件流裡。
    # ⭐ 事件（今天變了什麼）跟存量（現在是什麼）是兩個問題，只做事件會漏掉存量。
    exit_state = []
    for tk, entry in reg.items():
        if not entry.get("held"):
            continue
        s = _st_state(tk)
        exit_state.append([tk, None, None] if not s
                          else [tk, bool(s.get("st_bearish")), bool(s.get("rs60_broken"))])
    exit_state.sort(key=lambda r: (-(r[1] is True) - (r[2] is True), r[0]))

    json.dump(reg, open(REG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    gap, n_cov = coverage_gap(reg)
    out = {"date": date, "triggered": [list(x) for x in triggered],
           "near": [list(x) for x in near],
           "pending_metric": [list(x) for x in pending_metric], "healthy": healthy,
           # 2026-09-03：沒有任何條件在被檢查的持股。**「沒檢查」不能長得像「沒事」**。
           "uncovered": [g[0] for g in gap], "covered_count": n_cov,
           # 2026-09-05：持股現在的出場訊號存量 [代號, ST翻空, RS跌破]，
           # None 代表算不出來（**不等於沒事**）。
           "exit_state": exit_state}
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n_tr = sum(1 for v in reg.values() for c in v.get("conditions", [])
               if c.get("angle") == "trend")
    n_va = sum(1 for v in reg.values() for c in v.get("conditions", [])
               if c.get("angle", "value") == "value")
    print(f"失效條件日檢：🚫新觸發 {len(triggered)}｜⚠️逼近 {len(near)}｜"
          f"✅健康 {healthy}｜📋待檢 {len(pending_metric)}")
    if gap:
        print(f"　🔕 持股涵蓋率 {n_cov}/{n_cov + len(gap)}——"
              f"{len(gap)} 檔持股沒有任何條件在被檢查：{', '.join(g[0] for g in gap[:12])}"
              + ("…" if len(gap) > 12 else ""))
    print(f"　登錄簿角度分佈：趨勢 {n_tr} 條｜價值 {n_va} 條")
    _b2 = sum(1 for _, b, r in exit_state if b and r)
    _b1 = sum(1 for _, b, r in exit_state if b and not r)
    _r1 = sum(1 for _, b, r in exit_state if r and not b)
    _un = sum(1 for _, b, r in exit_state if b is None)
    print(f"　🔻 持股出場訊號現況（存量，不是今天才發生）："
          f"ST翻空+RS跌破 {_b2}｜只有ST翻空 {_b1}｜只有RS跌破 {_r1}"
          f"｜沒事 {len(exit_state) - _b2 - _b1 - _r1 - _un}｜算不出來 {_un}")
    # 原本寫 `for tk, msg in triggered`——8/31 加 held 後 tuple 變 3 元素，
    # 這行只要有任何一條真的觸發就會 ValueError。沒炸過只是因為一直沒觸發。
    for r in triggered:
        tk, msg, _h, ang = r[0], r[1], r[2], r[3]
        ctype = r[4] if len(r) > 4 else None
        # 持股 + 方向不會歧義的兩型 → 單獨標紅（Leo 9/5）
        mark = "🔴 出場訊號" if (_h and ctype in EXIT_TYPES) else "🚫"
        print(f"  {mark} [{ang}] {tk}：{msg}")
    for tk, msg, _h, ang in near:
        print(f"  ⚠️ [{ang}] {tk}：{msg}")
    return out


if __name__ == "__main__":
    run()
