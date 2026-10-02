# -*- coding: utf-8 -*-
"""持股出場訊號：資料＋網頁（2026-10-02，Leo：「太長了，每日新變化獨立一段，這樣不好讀…或是我可以直接開持股變化網頁？」）

兩個出口共用同一份計算（`overview()`），數字不可能兩邊不一樣：
  · Discord 持股密報 ② 今日新變化（daily_warroom.sec_exit）——只放今天變了什麼＋存量一行計數
  · 出場檢視表頂端區塊（assets.talentxtrend.com/exit-review，要密碼）——exit_review.render 插入 block()

存量＝每檔持股現在處在哪一階段（thesis_check 的 exit_state：[代號, ST 翻空?, RS60 跌破?]）。
事件＝今天剛翻面（st_alert 的 flips_hold＋thesis_check 的出場型觸發）。
🔴 存量跟今天的翻面事件打架時**以事件為準**並註明（2026-10-02 實測有兩檔：事件是 RS60 站回、
   存量還寫跌破）。原因沒查明。
系統註記照 trade_plan.supertrend_invalidation 原文：ST 翻空＝建議先賣一半（若尚未賣）；
RS(60日) 跌破自身 60 日均線＝建議剩餘部位全出。這裡只呈現現況，不改規則。
"""
import datetime as dt
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BUCKET_LABEL = {"both": "ST空＋RS破", "st_only": "只 ST 空", "rs_only": "只 RS 破", "clear": "沒事", "unk": "無法判定"}
ORDER = ["both", "st_only", "rs_only", "clear", "unk"]


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return d


def _nk(tk):
    return re.sub(r"\.(TW|TWO)$", "", str(tk or "").strip().upper())


def bucket(st, rs):
    if st is None:
        return "unk"
    if st and rs:
        return "both"
    if st:
        return "st_only"
    if rs:
        return "rs_only"
    return "clear"


def holder_marks():
    """👦 小孩｜🏠 Leo 的長期持有台股（監控但不參與風控）。"""
    try:
        from trade_plan import kids_tickers, legacy_tickers
        m = {_nk(t): "🏠" for t in legacy_tickers()}
        m.update({_nk(t): "👦" for t in kids_tickers()})
        return m
    except Exception:                                        # noqa: BLE001
        return {}


def overview(date=None):
    """回 dict：state{nk:[st,rs]}、disp{nk:原代號}、events{nk:{kind,dir,word,before,after}}、
    buckets{桶:[nk…]}、corrected[nk…]、date。沒有存量資料回 None。"""
    d = _load("state/thesis_check_today.json", {}) or {}
    es = d.get("exit_state") or []
    if not es:
        return None
    state = {_nk(r[0]): [r[1], r[2]] for r in es}
    disp = {_nk(r[0]): r[0] for r in es}
    # 🔴 只算「實際還持有」的：失效條件登錄的 held 旗標會過期（2026-10-02 實測有兩檔已不在
    # 持股資料裡、登錄卻還標持有，讓密報多算兩檔）。持股母體以 investment_chief.held_universe() 為準，
    # 它是出場檢視表原本用的同一份；取不到就不過濾（寧可多列也不靜默少列），並在 stale 留下被排除的。
    stale = []
    try:
        import investment_chief as _ic
        _held = {_nk(_ic.norm_ticker(x)) for x in _ic.held_universe()}
        if _held:
            stale = sorted(k for k in state if k not in _held)
            for k in stale:
                state.pop(k)
                disp.pop(k, None)
    except Exception:                                        # noqa: BLE001
        pass
    events = {}
    flips = (_load("state/st_flips_today.json", {}) or {}).get("flips_hold", [])
    for f in flips:
        nk = _nk(f.get("code"))
        if nk not in state:
            continue
        w = str(f.get("word") or "").replace("→", "").strip()
        kind = "RS" if (f.get("sig") == "rs60" or w.startswith("RS")) else "ST"
        events[nk] = {"kind": kind, "dir": int(f.get("dir") or 0), "word": w if kind == "RS" else f"SuperTrend {w}"}
    try:
        from thesis_check import EXIT_TYPES as _ET
    except Exception:                                        # noqa: BLE001
        _ET = ("supertrend_bear", "supertrend_flip", "rs_below")
    for r in d.get("triggered", []):
        if len(r) > 4 and r[2] and r[4] in _ET:
            nk = _nk(r[0])
            if nk in events or nk not in state:
                continue
            kind = "RS" if r[4] in ("rs_below", "rs_above") else "ST"
            events[nk] = {"kind": kind, "dir": -1, "word": str(r[1]).split("｜")[0].strip()}
    corrected = []
    for nk, e in events.items():
        s = state[nk]
        if s[0] is None:
            continue
        idx = 0 if e["kind"] == "ST" else 1
        new = e["dir"] < 0
        if s[idx] != new:
            s[idx] = new
            corrected.append(nk)
        before = list(s)
        before[idx] = not new
        e["after"], e["before"] = bucket(*s), bucket(*before)
    buckets = {b: [] for b in ORDER}
    for nk, s in state.items():
        buckets[bucket(*s)].append(nk)
    return {"date": date or time.strftime("%Y-%m-%d"), "state": state, "disp": disp, "events": events,
            "buckets": buckets, "corrected": corrected, "stale": stale}


def transitions(ov):
    """今天的變化依「去哪一桶」分組，回 [(圖示, 標題, [(nk, 備註)])]。
    新達成 ST空＋RS破／新轉弱／解除——這三件是 Leo 要的「今天該看哪幾檔」。"""
    rank = {"both": 3, "st_only": 2, "rs_only": 2, "unk": 0, "clear": 0}
    worse_both, worse, better = [], [], []
    for nk, e in ov["events"].items():
        a, b = e.get("after"), e.get("before")
        if a is None:
            continue
        if a == "both" and b != "both":
            worse_both.append((nk, "RS 跌破" if e["kind"] == "RS" else "ST 翻空"))
        elif rank[a] > rank[b]:
            worse.append((nk, "RS 跌破" if e["kind"] == "RS" else "ST 翻空"))
        elif rank[a] < rank[b] or (a != b and rank[a] == rank[b]):
            note = "RS 站回" if e["kind"] == "RS" else "ST 翻多"
            if b == "both":
                note += f"，兩條→{BUCKET_LABEL.get(a, a)}"
            elif a == "clear":
                note += "，回到沒事"
            better.append((nk, note))
    out = []
    if worse_both:
        out.append(("🔴", "新達成「ST空＋RS破」", worse_both))
    if worse:
        out.append(("🟠", "新轉弱", worse))
    if better:
        out.append(("🟢", "解除", better))
    return out


# ───────────────────── 區塊（嵌進出場檢視表） ─────────────────────
# 2026-10-02 Leo 要把這份跟 assets.talentxtrend.com/exit-review 整合成一頁：
# 出場檢視表本來就有成本／損益／距停損，缺的是「今天變了什麼」＋全部持股的階段計數，
# 所以這裡只產一個頂端區塊（exit_review.render 插進去），不另做網頁。
# 區塊裡不放金額；金額在下面逐檔卡片，同一頁、同一道密碼。
URL = "https://assets.talentxtrend.com/exit-review"
CSS = """
.hx{margin:14px 0 6px}
.hx h2{font-size:17px;margin:0 0 8px;padding-left:10px;border-left:3px solid var(--accent)}
.hx-chips{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.hx-chip{padding:7px 11px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:14px}
.hx-chip b{font-family:'IBM Plex Mono',monospace;font-size:18px;margin-right:6px}
.hx-chip.b0{border-color:#EF4444}.hx-chip.b0 b{color:#fca5a5}
.hx-chip.b1,.hx-chip.b2{border-color:#F97316}.hx-chip.b1 b,.hx-chip.b2 b{color:#fdba74}
.hx-chip.b3 b{color:#86efac}
.hx-new{background:var(--card);border:1px solid var(--line);margin:8px 0;padding:10px 12px}
.hx-new h3{margin:0 0 6px;font-size:15px}
.hx-row{display:flex;justify-content:space-between;gap:10px;padding:8px 2px;border-top:1px solid var(--line2);align-items:baseline}
.hx-row:first-of-type{border-top:0}
.hx-nm{font-size:15.5px}
.hx-mt{font-size:12.5px;color:var(--muted);text-align:right}
.hx-note{background:var(--card);border:1px solid var(--line);padding:10px 12px;margin:8px 0;color:var(--muted);font-size:13.5px;line-height:1.75}
"""


def _esc(s):
    from board_theme import esc
    return esc(str(s))


def block(date=None):
    """回 HTML 字串（要搭配 CSS 一起放進 <style>）；沒存量資料回空字串。"""
    from daily_warroom import tkname
    ov = overview(date)
    if not ov:
        return ""
    marks = holder_marks()
    chips = "".join(
        f'<span class="hx-chip b{i}"><b>{len(ov["buckets"][b])}</b>{BUCKET_LABEL[b]}</span>'
        for i, b in enumerate(["both", "st_only", "rs_only", "clear"]))
    unk = len(ov["buckets"]["unk"])
    tr = transitions(ov)
    body = ""
    if tr:
        for ic, title, items in tr:
            body += f'<div class="hx-new"><h3>{ic} {title}　{len(items)} 檔</h3>' + "".join(
                f'<div class="hx-row"><div class="hx-nm">{marks.get(nk, "")}{_esc(tkname(ov["disp"][nk]))}</div>'
                f'<div class="hx-mt">{_esc(note)}</div></div>' for nk, note in items) + "</div>"
    else:
        body = '<div class="hx-note">今天持股沒有新的出場訊號變化。</div>'
    corr = ""
    if ov["corrected"]:
        corr = ('<div class="hx-note">已依今日翻面事件校正存量：'
                + _esc("、".join(tkname(ov["disp"][n]) for n in ov["corrected"])) + "</div>")
    total = sum(len(v) for v in ov["buckets"].values())
    return (f'<div class="hx"><h2>今日新變化　<small style="font-weight:400;color:var(--muted)">'
            f'全部 {total} 檔持股</small></h2>{body}'
            f'<div class="hx-chips">{chips}'
            + (f'<span class="hx-chip"><b>{unk}</b>無法判定</span>' if unk else "") + "</div>"
            + corr + "</div>")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    o = overview()
    if not o:
        print("沒有存量資料")
    else:
        print({b: len(v) for b, v in o["buckets"].items()}, "校正", o["corrected"])
        for ic, t, items in transitions(o):
            print(ic, t, items)
