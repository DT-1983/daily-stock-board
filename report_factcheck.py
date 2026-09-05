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
| **複合成長率** | 內文寫的 CAGR | 拿它**自己的預估表**開 n 次方重算，對不對得上 | ✅ 自己對帳 |
| **有沒有空白年** | 只給 CAGR，看不到單一年 | 逐年拆 EPS YoY，找出「營收長、盈餘不長」那一年 | ✅ 自己對帳 |
| **上檔來源** | 「上檔 +59%」 | 拆成「盈餘成長 × 倍數變化」兩項各貢獻多少 | ✅ 自己對帳 |
| 季度 EPS | eps_quarterly | 下次財報公布時比對 | ⏳ 等財報 |

⭐ 後面三條（2026-09-05 加，起因是高盛 2454 那份）**完全不需要外部資料**——
只拿報告的兩個地方互相對帳就能抓出不一致，跟「倍數 × 基數 ≈ 目標價」同一招。
高盛那份的實例：內文寫 CAGR 43%/59%，但它自己的表算出來是 60.9%/86.2%
（差別在把三年當成四期複利）；2026E 營收 +14.5% 而 EPS 只有 +0.8%。
**這兩件事讀內文都看不出來，要拿計算機重算才會現形。**

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


_CAGR_NEAR = re.compile(
    r"(?:CAGR|複合成長|年複合|複合年增)[^。\n]{0,40}?"
    r"((?:\d{1,3}(?:\.\d)?%[／/、與和及~-]?\s*){1,3})"
    r"|((?:\d{1,3}(?:\.\d)?%[／/]){1,2}\d{1,3}(?:\.\d)?%)[^。\n]{0,20}?(?:CAGR|複合成長)",
    re.I)


def _claimed_cagr(report):
    """報告**自己宣稱**的複合成長率，回 [百分比數字, ...]。

    優先吃結構化欄位 `cagr_claim`（解析層 2026-09-05 起會抓）；沒有的話退回
    從 summary／thesis 的文字裡找「CAGR」「複合成長率」附近的百分比。

    ⚠️ 文字比對只是**過渡用的退路**——它讀的是本機模型寫的摘要不是原文，
    抓不到就回空陣列，讓查核項顯示「還不能比對」。**寧可說不知道，
    不要從不可靠的來源湊一個數字出來當事實。**
    """
    v = report.get("cagr_claim")
    if isinstance(v, dict):
        # 解析層 2026-09-05 起的格式：{"revenue": 43, "eps": 59, "period": "2025-28E"}
        # ⚠️ 順序必須是 (營收, EPS)——下游是照順序配到欄位上的。
        got = [_num(v.get("revenue")), _num(v.get("eps"))]
        return got if all(got) else [x for x in got if x]
    if isinstance(v, (list, tuple)):
        got = [_num(x) for x in v]
        return [x for x in got if x]
    if _num(v):
        return [_num(v)]

    txt = " ".join(str(x) for x in ((report.get("summary") or [])
                                    + [report.get("thesis") or ""]))
    out = []
    for m in _CAGR_NEAR.finditer(txt):
        seg = m.group(1) or m.group(2) or ""
        for p in re.findall(r"\d{1,3}(?:\.\d)?(?=%)", seg):
            f = _num(p)
            if f and 0 < f < 300 and f not in out:
                out.append(f)
    return out


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

    # ── 6. 宣稱的 CAGR vs 從它自己的表算出來的 ──────────────
    #
    # 🔴 2026-09-05 加（起因：高盛 2454 那份）。報告內文寫「2025-28E 營收/獲利
    # CAGR 43%/59%」，但拿它**自己表格**的 595,966 → 2,483,426 開三次方是 60.9%。
    # 對得起來的算法是把三年當成**四期**複利（42.9%）——券商常見的期數寫法差異，
    # 不是造假，但影響是：**只讀那句話沒看表的人會低估這份報告押了多大。**
    # ⭐ 這條跟「倍數 × 基數 ≈ 目標價」是同一招：**拿報告的兩個地方互相對帳**，
    # 不需要任何外部資料就能抓出不一致。
    fcs = [f for f in (report.get("forecast") or [])
           if _num(f.get("revenue")) or _num(f.get("eps"))]
    if len(fcs) >= 2:
        claimed = _claimed_cagr(report)
        # 🔴 首測抓到的 bug：宣稱值是一組（[43, 59]），原本每個欄位都拿**整組**去比，
        # 於是「營收 3 年複利 60.9%」被組裡的 59（那是 EPS 的）比中，變成假的 ✅對得上。
        # ⭐ 一組數字要對應到多個欄位時，**必須先決定誰對誰**，不能讓它們互相亂配——
        # 「有一個對得上」跟「對的那個對得上」是兩回事。
        # 券商寫法一律是「營收/獲利 CAGR X%/Y%」，數量吻合時照順序配。
        FIELDS = (("revenue", "營收"), ("eps", "EPS"))
        pos = len(claimed) == len(FIELDS)
        for idx, (field, label) in enumerate(FIELDS):
            mine = [claimed[idx]] if pos else claimed
            vals = [(f.get("year"), _num(f.get(field))) for f in fcs]
            vals = [(y, v) for y, v in vals if v and v > 0]
            if len(vals) < 2:
                continue
            (y0, v0), (y1, v1) = vals[0], vals[-1]
            n = len(vals) - 1                       # 年數＝資料點數 − 1
            c_n = ((v1 / v0) ** (1.0 / n) - 1) * 100
            c_n1 = ((v1 / v0) ** (1.0 / (n + 1)) - 1) * 100
            ours = (f"用表格 {y0} {v0:,.0f} → {y1} {v1:,.0f} 算："
                    f"{n} 年複利 **{c_n:.1f}%**（{n+1} 期複利 {c_n1:.1f}%）")
            hit = [c for c in mine if abs(c - c_n) <= 3]
            hit1 = [c for c in mine if abs(c - c_n1) <= 3]
            if not mine:
                out.append({
                    "kind": f"{label}複合成長率",
                    "claim": "報告內文沒有結構化的 CAGR 可比對",
                    "ours": ours,
                    "verdict": WAIT,
                    "note": "這是從預估表反推的，**先記著**；等解析層抓到報告自己宣稱的"
                            "CAGR 就會自動比對兩者一不一致",
                })
            elif hit:
                out.append({
                    "kind": f"{label}複合成長率",
                    "claim": f"報告宣稱 {hit[0]:.0f}%",
                    "ours": ours,
                    "verdict": OK,
                    "note": "宣稱值與表格算出來的一致",
                })
            elif hit1:
                out.append({
                    "kind": f"{label}複合成長率",
                    "claim": f"報告宣稱 {hit1[0]:.0f}%",
                    "ours": ours,
                    "verdict": WARN,
                    "note": f"宣稱值對得上的是 **{n+1} 期**複利，但 {y0}→{y1} 只有 "
                            f"**{n} 年**。真正的年複合成長率是 {c_n:.1f}%——"
                            "**只讀內文那句話、沒看表，會低估這份報告押了多大**",
                })
            else:
                out.append({
                    "kind": f"{label}複合成長率",
                    "claim": f"報告宣稱 {'／'.join(f'{c:.0f}%' for c in mine)}",
                    "ours": ours,
                    "verdict": WARN,
                    "note": "宣稱值跟表格算出來的**兩種算法都對不上**——"
                            "可能是期間不同（例如從前一年起算），也可能有一邊抄錯，"
                            "引用前先回原文確認",
                })

    # ── 7. 有沒有「空白年」：營收成長但盈餘沒成長的那一年 ─────
    #
    # 🔴 2026-09-05 加。高盛 2454 的表：2026E 營收 +14.5%，EPS 只有 **+0.8%**，
    # 爆發全押在 2027（EPS +177.6%）。
    # ⭐ 這件事**看 CAGR 完全看不到**——平均會把空白年抹平。
    # 對持有人的意義：那一年沒有盈餘成長可以撐股價，等於「先付錢、兩年後才拿貨」。
    eps_rows = [(f.get("year"), _num(f.get("eps")), _num(f.get("revenue")))
                for f in (report.get("forecast") or [])]
    eps_rows = [(y, e, rv) for y, e, rv in eps_rows if e and e > 0]
    flats = []
    for i in range(1, len(eps_rows)):
        (_, e0, r0), (y1_, e1, r1) = eps_rows[i - 1], eps_rows[i]
        ge = e1 / e0 - 1
        gr = (r1 / r0 - 1) if (r0 and r1 and r0 > 0) else None
        if ge < 0.05:
            flats.append((y1_, ge, gr))
    if eps_rows and len(eps_rows) >= 2:
        if flats:
            y1_, ge, gr = flats[0]
            rv = f"、營收卻 {gr:+.1%}" if gr is not None else ""
            nxt = ""
            j = [i for i, (y, _e, _r) in enumerate(eps_rows) if y == y1_]
            if j and j[0] + 1 < len(eps_rows):
                y2, e2, _ = eps_rows[j[0] + 1]
                nxt = f"；隔年 {y2} 才跳 {e2/eps_rows[j[0]][1]-1:+.0%}"
            out.append({
                "kind": "有沒有空白年",
                "claim": f"{y1_} EPS 年增 {ge:+.1%}{rv}{nxt}",
                "ours": "逐年拆開預估表算出來的（報告只給複合成長率，看不到這一格）",
                "verdict": WARN,
                "note": f"**{y1_} 是空白年**——那一年沒有盈餘成長可以撐股價。"
                        "買進理由不是「明年會賺更多」，而是**「以後會賺很多，"
                        "而且現在就要先付這個價」**",
            })
        else:
            out.append({
                "kind": "有沒有空白年",
                "claim": "每一年 EPS 年增都 ≥ 5%",
                "ours": "逐年拆開預估表算出來的",
                "verdict": OK,
                "note": "成長是逐年遞進的，不是集中押在某一年之後",
            })

    # ── 8. 上檔空間拆解：多少來自盈餘成長、多少來自倍數變化 ────
    #
    # 🔴 2026-09-05 加。恆等式：目標價/現價 ＝ (目標倍數/現在倍數) × (目標年EPS/今年EPS)。
    # ⭐ 「上檔 +59%」這個數字本身不告訴你**要相信什麼才會實現**。拆開之後才知道
    # 是在賭盈餘、還是在賭市場願意付更高的倍數——這兩件事的失敗方式完全不同。
    veps = _num(report.get("valuation_eps"))
    # 「現在」的基數用**今年**那一列，不是表上第一列——第一列常常是去年的實際數。
    # （首測就吃到這個：表是 2025/2026E/2027E/2028E，取第一列會拿 2025 的實際 EPS。）
    import time as _time
    _yr = _time.strftime("%Y")
    cur_eps = cur_y = None
    for f in (report.get("forecast") or []):
        e = _num(f.get("eps"))
        y = str(f.get("year", ""))
        if not (e and e > 0):
            continue
        if y.rstrip("EAF") == _yr:
            cur_eps, cur_y = e, y
            break
        if cur_eps is None:
            cur_eps, cur_y = e, y                   # 退路：表上第一個有 EPS 的年度
    if price and veps and veps > 0 and cur_eps and cur_eps > 0 and _num(report.get("target")):
        tgt = _num(report["target"])
        up = tgt / price - 1
        g_eps = veps / cur_eps - 1                  # 盈餘成長貢獻
        m_now, m_tgt = price / cur_eps, tgt / veps
        g_mult = m_tgt / m_now - 1                  # 倍數變化貢獻
        y0 = cur_y or "當年"
        out.append({
            "kind": "上檔空間的來源",
            "claim": f"目標價 {tgt:,.0f} vs 現價 {price:,.0f}＝上檔 {up:+.1%}",
            "ours": f"盈餘成長貢獻 {g_eps:+.0%}（{y0} EPS {cur_eps:g} → "
                    f"{report.get('valuation_eps_label') or '目標年'} {veps:g}）"
                    f"× 倍數變化貢獻 {g_mult:+.0%}"
                    f"（現在 {m_now:.1f} 倍 → 目標 {m_tgt:.1f} 倍）",
            "verdict": WARN if g_mult < -0.3 or g_mult > 0.3 else OK,
            "note": ("⚠️ 這條跟上面「估值倍數」不衝突：那條是**同一個 EPS 基數**下"
                     "還差幾倍，這條是**相對今年盈餘**拆成兩項。兩項相乘就是上檔。"
                     "**倍數要壓縮這麼多還能有上檔，代表整段故事靠的是盈餘跳升**"
                     "——盈餘沒跳，倍數壓縮就會變成下檔"
                     if g_mult < -0.3 else
                     "兩項相乘就是上檔。**上檔主要來自倍數擴張而不是盈餘**——"
                     "這代表就算財報照預估走，市場不給那個倍數，股價也到不了目標價"
                     if g_mult > 0.3 else
                     "盈餘與倍數兩項的貢獻沒有偏向任何一邊"),
        })

    # ── 9. 季度 EPS：等財報才驗 ──────────────────────────
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
