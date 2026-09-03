# -*- coding: utf-8 -*-
"""券商報告查核層（2026-09-04，Leo：「也有像老墨的 html 檢查報告商寫的是不是事實」）。

## 這支在做什麼

拿券商報告裡**可以被證偽的宣稱**，一條一條對照我們自己算出來的數字，給三態：

    ✅ 對得上   ⚠️ 有落差（附我們的數字）   ⏳ 還不能驗（要等財報/時間）

⭐ **重點不是抓券商說謊**——他們寫的多半是預估，不是事實。重點是把
「他假設什麼」跟「這檔自己的歷史做得到什麼」擺在一起，讓落差自己現形。

## 每一條查什麼、拿什麼比

| 查核項 | 報告的宣稱 | 我們拿什麼比 | 零成本？ |
|---|---|---|---|
| 估值倍數 | 目標價 = N 倍 × 某年 EPS | 現價 ÷ 同一個基數＝市場現在給幾倍 | ✅ 既有 |
| 成長率 | 預估表的營收/EPS 年增 | 這檔**自己**的歷史 YoY 中位與最大（base_rate）| ✅ 既有 |
| 今年營收 | 預估的全年營收 | base_rate 的「剩下幾個月要 YoY 多少」 | ✅ 既有 |
| 毛利率風險 | 報告自列「成本上升侵蝕毛利」 | margin_profile 的位階（已經在哪裡了）| ✅ 既有 |
| **目標價軌跡** | 報告自己的 target_history | 同期**實際股價**漲幅——目標價是領先還是追著跑 | ✅ price_store |
| 季度 EPS | eps_quarterly | 下次財報公布時比對 | ⏳ 等財報 |

⚠️ **不做的**：不上網查新聞、不驗「NVIDIA 是不是真的認購 35 億」這種事件真偽——
那要花錢，而且報告引用的是公開重訊，造假機率極低。我們查的是**推論與假設**，
不是事實陳述。

全部讀既有 state 檔 ＋ price_store，**不呼叫 AI、不花錢**。
"""
import io
import re
import sys
import json
import os

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, WARN, WAIT = "ok", "warn", "wait"


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _num(x):
    try:
        v = float(x)
        return v if v == v else None                        # NaN 擋掉
    except (TypeError, ValueError):
        return None


def _price_on(sym, date_str):
    """某一天（或之前最近一個交易日）的收盤。查不到回 None。"""
    try:
        import price_store
        s = price_store.get_closes([sym], period="3y").get(sym)
        if s is None or s.empty:
            return None
        s = s.dropna()
        s = s[s.index <= date_str]
        return float(s.iloc[-1]) if len(s) else None
    except Exception:                                       # noqa: BLE001
        return None


def _sym(ticker):
    t = str(ticker).upper()
    if re.match(r"^\d{4,6}[A-Z]?$", t):
        try:
            import tw_symbol
            return tw_symbol.resolve(t)
        except Exception:                                   # noqa: BLE001
            return t + ".TW"
    return t.replace(".", "-")


def check(report, price=None, base_rate=None, margin=None):
    """回 [{"kind","claim","ours","verdict","note"}]，順序＝重要性。"""
    out = []
    tk = report.get("ticker")
    sym = _sym(tk)

    # ── 1. 估值倍數：他假設幾倍 vs 市場現在給幾倍 ──────────────
    try:
        import advisor_reports as ar
        im = ar.implied_multiple(report, price)
    except Exception:                                       # noqa: BLE001
        im = None
    if im:
        now, want, how = im
        gap = (want / now - 1) * 100
        out.append({
            "kind": "估值倍數",
            "claim": f"目標價用 {want:g} 倍{(report.get('valuation_kind') or '').upper()}"
                     f"（{report.get('valuation_eps_label') or '報告的基數'}）",
            "ours": f"市場現在給 {now:.1f} 倍（{how}）",
            "verdict": WARN if now >= want else OK,
            "note": ("市場給的倍數已經追上報告假設——這份報告在估值上的上檔空間用完了"
                     if now >= want else
                     f"還差 {gap:.0f}%。這 {gap:.0f}% 要靠**本益比擴張**來，"
                     f"不是靠盈餘成長——兩者是不同的事"),
        })

    # ── 2. 成長率：他預估的年增 vs 這檔自己的歷史 ───────────────
    fc = [f for f in (report.get("forecast") or []) if _num(f.get("revenue"))]
    fc.sort(key=lambda f: str(f.get("year")))
    if len(fc) >= 2:
        hist_max = hist_med = None
        if base_rate and base_rate.get("requirement"):
            q = base_rate["requirement"]
            hist_max = _num(q.get("yoy_max"))
            hist_med = _num(q.get("yoy_med"))
        rows = []
        worst = OK
        for a, b in zip(fc, fc[1:]):
            ra, rb = _num(a["revenue"]), _num(b["revenue"])
            if not ra or ra <= 0:
                continue
            yoy = (rb / ra - 1) * 100
            tag = ""
            if hist_max is not None:
                hm = hist_max * 100
                if yoy > hm:
                    tag, worst = f"⚠️ 超過歷史最大 {hm:.0f}%", WARN
                elif yoy > hm * 0.8:
                    tag = f"貼近歷史最大 {hm:.0f}%"
                    worst = worst if worst == WARN else WARN
            rows.append(f"{b.get('year')} 營收 YoY {yoy:+.1f}%" + (f"　{tag}" if tag else ""))
        if rows:
            out.append({
                "kind": "成長率假設",
                "claim": "；".join(rows),
                "ours": (f"這檔歷史月營收 YoY 中位 {hist_med * 100:+.1f}%、"
                         f"最大 {hist_max * 100:+.1f}%"
                         if hist_med is not None else "查無歷史 YoY 分布可比"),
                "verdict": worst if hist_max is not None else WAIT,
                "note": ("預估要求連續貼在或超過這檔自己的歷史上限——"
                         "不是說做不到，是說**沒有容錯空間**"
                         if worst == WARN else
                         "預估落在這檔過去做得到的範圍內"),
            })

    # ── 3. 今年營收：他的預估 vs 我們算的「剩下要跑多快」 ──────────
    if base_rate and base_rate.get("requirement"):
        q = base_rate["requirement"]
        tier = {"unprecedented": ("要求超出這檔自身歷史紀錄一大截", WARN),
                "rare": ("要求剛好貼在自身歷史紀錄上", WARN),
                "normal": ("要求落在這檔過去做得到的範圍內", OK),
                "low_coverage": ("分析師覆蓋太少，不列入判斷", WAIT)}.get(
            q.get("tier"), ("", WAIT))
        tr = base_rate.get("track_record") or {}
        out.append({
            "kind": f"{q.get('year')} 全年營收",
            "claim": f"市場共識 {(_num(q.get('fy')) or 0) / 1e8:,.0f} 億",
            "ours": (f"剩 {q.get('months_left')} 個月要月營收 YoY "
                     f"{(_num(q.get('need_yoy')) or 0) * 100:+.1f}%；"
                     f"歷史中位 {(_num(q.get('yoy_med')) or 0) * 100:+.1f}%、"
                     f"最大 {(_num(q.get('yoy_max')) or 0) * 100:+.1f}%"),
            "verdict": tier[1],
            "note": tier[0] + (f"。分析師準頭：{tr.get('n')} 次猜中 {tr.get('beats')} 次、"
                               f"中位驚喜 {tr.get('median_surprise'):+.1f}%（{tr.get('bias','')}）"
                               if tr else ""),
        })

    # ── 4. 報告自列的毛利率風險，現在到哪了 ──────────────────
    rk = "、".join(report.get("risks") or [])
    if margin and ("毛利" in rk or "margin" in rk.lower() or "成本" in rk):
        pct = _num(margin.get("pct"))
        out.append({
            "kind": "毛利率風險",
            "claim": "報告自列風險含「成本上升侵蝕毛利率」",
            "ours": (f"現值 {margin.get('cur')}%，在自身 {margin.get('n')} 季裡"
                     f"第 {pct:.0f} 百分位（區間 {margin.get('lo')}~{margin.get('hi')}）"),
            "verdict": WARN if pct is not None and pct <= 40 else OK,
            "note": ("毛利率位階本來就偏低——報告點的那個風險不是「未來可能發生」，"
                     "是**現在就在偏低的位置**，要往上走才撐得起 EPS 預估"
                     if pct is not None and pct <= 40 else
                     "目前毛利率位階不低，報告點的風險尚未在數字上顯現"),
        })

    # ── 5. 目標價軌跡：領先股價，還是追著股價跑 ─────────────────
    th = [h for h in (report.get("target_history") or [])
          if _num(h.get("target")) and h.get("date")]
    th.sort(key=lambda h: str(h["date"]))
    if len(th) >= 2:
        a, b = th[0], th[-1]
        t0, t1 = _num(a["target"]), _num(b["target"])
        p0 = _num(a.get("close")) or _price_on(sym, a["date"])
        p1 = _num(b.get("close")) or _price_on(sym, b["date"])
        if t0 and t1 and p0 and p1 and t0 > 0 and p0 > 0:
            dt_ = (t1 / t0 - 1) * 100
            dp = (p1 / p0 - 1) * 100
            lead = dt_ - dp
            out.append({
                "kind": "目標價軌跡",
                "claim": f"{a['date']} 目標 {t0:,.0f} → {b['date']} 目標 {t1:,.0f}"
                         f"（{dt_:+.0f}%）",
                "ours": f"同期股價 {p0:,.0f} → {p1:,.0f}（{dp:+.0f}%）",
                "verdict": WARN if lead > 30 else OK,
                "note": ("目標價漲得比股價還多——這是**目標價追著股價跑**的形態，"
                         "上檔空間有多少是「重新評價倍數」給的、有多少是盈餘真的成長，"
                         "值得分開看"
                         if lead > 30 else
                         "目標價與股價漲幅相當，沒有明顯的追價形態"),
            })

    # ── 6. 季度 EPS：等財報才驗 ──────────────────────────
    eq = [e for e in (report.get("eps_quarterly") or []) if _num(e.get("value"))]
    if eq:
        out.append({
            "kind": "季度 EPS 預估",
            "claim": "、".join(f"{e['q']} {_num(e['value']):g}" for e in eq[:5]),
            "ours": "等該季財報公布後自動比對",
            "verdict": WAIT,
            "note": "這幾個數字是這份報告最快會被證偽的地方——下一季財報就見真章",
        })

    return out


def summary(rows):
    """一行總結：幾條對得上、幾條有落差、幾條還不能驗。"""
    n = {OK: 0, WARN: 0, WAIT: 0}
    for r in rows:
        n[r["verdict"]] = n.get(r["verdict"], 0) + 1
    return f"{n[OK]} 條對得上／{n[WARN]} 條有落差／{n[WAIT]} 條還不能驗"
