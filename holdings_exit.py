# -*- coding: utf-8 -*-
"""持股出場訊號：資料＋網頁（2026-10-02，Leo：「太長了，每日新變化獨立一段，這樣不好讀…或是我可以直接開持股變化網頁？」）

兩個出口共用同一份計算（`overview()`），數字不可能兩邊不一樣：
  · Discord 持股密報 ② 今日新變化（daily_warroom.sec_exit）——只放今天變了什麼＋存量一行計數
  · 網頁 /holdings（戰情室服務，同一道 token 門檻）——完整名單、逐檔數字、可點開

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
URL = "https://stock.talentxtrend.com/holdings"


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
            "buckets": buckets, "corrected": corrected}


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


# ───────────────────────────── 網頁 ─────────────────────────────
CSS = """
.hx-wrap{max-width:860px;margin:0 auto;padding:0 14px 60px}
.hx-note{background:var(--card);border:1px solid var(--line);padding:11px 13px;margin:12px 0;color:var(--muted);font-size:14px;line-height:1.75}
.hx-chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.hx-chip{display:block;padding:8px 12px;border:1px solid var(--line);background:var(--card);color:var(--ink);text-decoration:none;font-size:14px}
.hx-chip b{font-family:'IBM Plex Mono',monospace;font-size:18px;margin-right:6px}
.hx-chip.b0{border-color:#EF4444}.hx-chip.b0 b{color:#fca5a5}
.hx-chip.b1,.hx-chip.b2{border-color:#F97316}.hx-chip.b1 b,.hx-chip.b2 b{color:#fdba74}
.hx-chip.b3 b{color:#86efac}
h2{font-size:17px;margin:26px 0 8px;padding-left:10px;border-left:3px solid var(--accent)}
.hx-new{background:var(--card);border:1px solid var(--line);margin:8px 0;padding:10px 12px}
.hx-new h3{margin:0 0 6px;font-size:15px}
.hx-row{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:9px 2px;border-top:1px solid var(--line2);align-items:baseline}
.hx-row:first-child{border-top:0}
.hx-nm{font-size:15.5px}.hx-nm .hx-ev{display:inline-block;margin-left:8px;font-size:12px;padding:1px 7px;border:1px solid var(--line);color:var(--accent)}
.hx-mt{font-size:12.5px;color:var(--muted);font-family:'IBM Plex Mono',monospace;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
details>summary{cursor:pointer;color:var(--muted);font-size:14px;padding:8px 0}
"""


def _esc(s):
    from board_theme import esc
    return esc(str(s))


def render(date=None):
    from board_theme import BASE_CSS, header
    from daily_warroom import tkname
    ov = overview(date)
    if not ov:
        return "<!doctype html><meta charset=utf-8><body style='background:#04070E;color:#DCE7F5;padding:20px'>沒有持股出場存量資料（thesis_check 今天還沒跑）。</body>"
    marks = holder_marks()
    cr = _load("state/combo_result.json", {}) or {}
    crow = {_nk(r.get("ticker")): r for r in (cr.get("rows") or [])}
    asof = max((str(r.get("asof") or "") for r in crow.values()), default="")

    def metrics(nk):
        r = crow.get(nk)
        if not r:
            return "—", ""
        gp = r.get("gap_pct")
        side = "ST線上" if (gp or 0) >= 0 else "ST線下"
        m = f"{r.get('price')}　{side} {abs(gp or 0):.1f}%　RS {r.get('rs_short'):+.1f}%　{r.get('lit')}/4燈" \
            if (r.get("rs_short") is not None and gp is not None) else f"{r.get('price')}"
        return m, ""

    def row(nk):
        e = ov["events"].get(nk)
        ev = f'<span class="hx-ev">⚡今天{"RS破" if e["kind"] == "RS" and e["dir"] < 0 else "RS回" if e["kind"] == "RS" else "ST空" if e["dir"] < 0 else "ST多"}</span>' if e else ""
        m, _ = metrics(nk)
        return (f'<div class="hx-row"><div class="hx-nm">{marks.get(nk, "")}{_esc(tkname(ov["disp"][nk]))}{ev}</div>'
                f'<div class="hx-mt">{_esc(m)}</div></div>')

    chips = "".join(
        f'<a class="hx-chip b{i}" href="#g-{b}"><b>{len(ov["buckets"][b])}</b>{BUCKET_LABEL[b]}</a>'
        for i, b in enumerate(["both", "st_only", "rs_only", "clear"]) if True)
    # 今日新變化
    tr = transitions(ov)
    new_html = ""
    if tr:
        for ic, title, items in tr:
            new_html += f'<div class="hx-new"><h3>{ic} {title}　{len(items)} 檔</h3>' + "".join(
                f'<div class="hx-row"><div class="hx-nm">{marks.get(nk, "")}{_esc(tkname(ov["disp"][nk]))}</div>'
                f'<div class="hx-mt">{_esc(note)}</div></div>' for nk, note in items) + "</div>"
    else:
        new_html = '<div class="hx-note">今天持股沒有新的出場訊號變化。</div>'
    groups = ""
    for b in ORDER:
        names = ov["buckets"][b]
        if not names:
            continue
        # 每組內：今天有事件的排前面，其餘依代號
        names = sorted(names, key=lambda n: (0 if n in ov["events"] else 1, n))
        inner = "".join(row(n) for n in names)
        icon = {"both": "🔴", "st_only": "🟠", "rs_only": "🟠", "clear": "✅", "unk": "⚪"}[b]
        body = (f"<details><summary>{icon} {BUCKET_LABEL[b]}　{len(names)} 檔（點開）</summary>{inner}</details>"
                if b in ("clear", "unk") else f'<h2 id="g-{b}">{icon} {BUCKET_LABEL[b]}　{len(names)} 檔</h2>{inner}')
        groups += body
        if b in ("clear", "unk"):
            groups = groups  # 保持順序
    corr = ""
    if ov["corrected"]:
        corr = f'<div class="hx-note">已依今日翻面事件校正存量：{_esc("、".join(tkname(ov["disp"][n]) for n in ov["corrected"]))}</div>'
    return ("<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>持股出場訊號</title><style>"
            + BASE_CSS + CSS + "</style></head><body>"
            + header("portfolio", "持股出場訊號", f"{ov['date']}　{sum(len(v) for v in ov['buckets'].values())} 檔持股", [], eyebrow="HOLDINGS EXIT")
            + '<div class="hx-wrap">'
            '<div class="hx-note"><b>系統註記：</b>ST 翻空＝建議先賣一半（若尚未賣）；RS(60日) 跌破自身 60 日均線＝建議剩餘部位全出。'
            '這頁只呈現「現在各持股處在哪一階段」，不改規則。⚡＝今天新變化。'
            f'價格、距線、RS、燈號來自每日 07:00 掃描（{_esc(asof)} 收盤）。</div>'
            f'<div class="hx-chips">{chips}</div>{corr}<h2>今日新變化</h2>{new_html}{groups}</div></body></html>')


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
