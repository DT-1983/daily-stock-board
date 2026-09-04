# -*- coding: utf-8 -*-
"""個股整合報告（2026-09-04，Leo：「調用研究員、投資長幫我解讀報告，跟我們現有的資訊產出一份報告」）。

把**券商報告怎麼說**跟**我們自己的系統怎麼算**擺在同一頁，重點是那些
「報告裡沒有、只有我們算得出來」的交叉檢驗：

| 層 | 來源 | 回答什麼問題 |
|---|---|---|
| 券商報告 | `advisor_reports` | 憑什麼給這個目標價（倍數 × 哪一年的 EPS）|
| 估值前提 | `advisor_reports.implied_multiple` | 市場現在給幾倍、離報告假設多遠 |
| 預估前提檢查 | `state/base_rate.json` | 分析師共識隱含的要求，對照這檔**自己的歷史分布** |
| 毛利率位階 | `state/margin_profile.json` | 獲利能力在自身 24 季裡的位階 |
| 燈號 | `state/combo_result.json` | 技術面四燈與風報比 |
| 投資長 | `state/advisor_verdicts.jsonl` | 兩個獨立角度的判斷與失效條件 |

⚠️ 全部讀既有 state 檔，**不重算、不呼叫 AI、不花錢**。要更新內容請先跑對應的
產生器（`advisor_reports.py parse`／`investment_chief.py`／每日排程）。

⚠️ 樣式走 `board_theme`：header() + BASE_CSS、不寫死中性色碼、跨網域用 nav_abs()
（2026-09-03 Leo 連兩次指出風格不一致後定的四條硬規則）。

用法:
    python stock_brief.py 2454
    python stock_brief.py 2454 -o out.html
    python stock_brief.py --all       # 重產所有有券商報告的個股（每日 08:45 排程）
"""
import io
import os
import re
import sys
import json
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2026-09-05 資料夾整理：路徑一律走 obis_paths，不再各自寫死。
from obis_paths import BRIEFS as OBIS


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _norm(tk):
    return re.sub(r"\.(TW|TWO)$", "", str(tk).upper()).replace(".", "-")


def gather(ticker):
    """把所有既有資料湊成一份 dict。缺的就是 None——**不補、不猜**。"""
    t = _norm(ticker)
    out = {"ticker": t}

    cr = _load("state/combo_result.json", {}) or {}
    rows = cr.get("rows") or cr.get("items") or []
    out["lamp"] = next((r for r in rows if _norm(r.get("ticker", "")) == t), None)

    mp = _load("state/margin_profile.json", {}) or {}
    out["margin"] = next((v.get("data") for k, v in mp.items()
                          if _norm(k) == t and isinstance(v, dict)), None)

    br = _load("state/base_rate.json", {}) or {}
    out["base_rate"] = next((c for c in (br.get("checks") or [])
                             if _norm(c.get("ticker", "")) == t), None)

    reg = _load("state/thesis_conditions.json", {}) or {}
    out["thesis"] = next((v for k, v in reg.items() if _norm(k) == t), None)

    st = _load("state/advisor_reports.json", {}) or {}
    out["reports"] = sorted(
        [r for r in st.values()
         if not r.get("_notreport") and _norm(r.get("ticker", "")) == t],
        key=lambda r: str(r.get("date")), reverse=True)

    tc = _load("state/target_changes.json", {}) or {}
    ch = []
    for v in tc.values():
        ch += [r for r in v.get("rows", []) if _norm(r.get("ticker", "")) == t]
    out["changes"] = sorted(ch, key=lambda r: str(r.get("date")), reverse=True)

    v = None
    p = "state/advisor_verdicts.jsonl"
    if os.path.exists(p):
        for ln in io.open(p, encoding="utf-8"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if _norm(d.get("ticker", "")) == t:
                v = d
    out["verdict"] = v
    return out


def _price(d):
    lamp = d.get("lamp") or {}
    if lamp.get("price"):
        return float(lamp["price"])
    try:
        import price_store, tw_symbol
        sym = (tw_symbol.resolve(d["ticker"])
               if re.match(r"^\d{4,6}[A-Z]?$", d["ticker"]) else d["ticker"])
        s = price_store.get_closes([sym], period="1y").get(sym)
        if s is not None and not s.empty:
            return float(s.dropna().iloc[-1])
    except Exception:                                       # noqa: BLE001
        pass
    return None



# 投資長 reasoning 的分段標記。它寫的時候本來就有分「事實／推論／資料缺口」，
# 但原樣輸出會變成一整片文字牆（2026-09-04 Leo：「段落不清楚，幫我重排一下」）。
# 兩種寫法都會出現：`【事實】` 與 `事實：`。
_MARKS = [("事實", "f"), ("推論/假設", "i"), ("推論", "i"), ("假設", "i"),
          ("提醒", "w"), ("資料缺口", "w"), ("綜合以上", "s"), ("結論", "s")]
_MARK_LABEL = {"f": "事實", "i": "推論", "w": "注意", "s": "結論"}


def fmt_reasoning(txt, esc):
    """把一整段 reasoning 拆成有標籤的段落。

    做法：找出所有標記出現的位置切段，每段前面掛一個彩色標籤。
    找不到任何標記就退回「照句號斷行」——**不硬套格式**，
    寧可維持原樣也不要切錯句子。
    """
    import re as _re
    t = (txt or "").strip()
    if not t:
        return ""
    pat = "|".join(_re.escape(m) for m, _ in _MARKS)
    hits = list(_re.finditer(rf"(?:【({pat})】|({pat})[：:])", t))
    if not hits:
        # 沒有標記：每 2 句斷一段，至少讓它不是一整片
        sents = [x for x in _re.split(r"(?<=。)", t) if x.strip()]
        return "".join(f'<p class="rz">{esc(x.strip())}</p>' for x in sents)
    out = []
    if hits[0].start() > 0:
        out.append(f'<p class="rz">{esc(t[:hits[0].start()].strip())}</p>')
    for i, m in enumerate(hits):
        name = m.group(1) or m.group(2)
        kind = next(k for lbl, k in _MARKS if lbl == name)
        end = hits[i + 1].start() if i + 1 < len(hits) else len(t)
        seg = t[m.end():end].strip().lstrip("：:").strip()
        if not seg:
            continue
        out.append(f'<p class="rz {kind}"><span class="rzl">{_MARK_LABEL[kind]}</span>'
                   f'{esc(seg)}</p>')
    return "".join(out)


CSS = """
.sb{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px;margin:12px 0}
.sb h2{font-size:15px;font-weight:700;color:#F5B841;margin-bottom:4px}
.sb .sub{font-size:11.5px;color:var(--dim);margin-bottom:9px;line-height:1.6}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:8px;margin:8px 0}
.kv .c{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 10px}
.kv .k{font-size:10px;color:var(--dim);letter-spacing:.3px}
.kv .v{font-size:15px;font-weight:700;margin-top:3px;
 font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums}
.kv .v.zh{font-family:inherit;font-size:14px}
.kv .s{font-size:10.5px;color:var(--muted);margin-top:2px;line-height:1.5}
.txt{font-size:13px;color:var(--muted);line-height:1.85;margin-top:8px}
/* 投資長 reasoning 分段（2026-09-04）：原本一整片牆，改成每個「事實/推論/注意」
   各自一段、左邊一條色帶。色帶顏色只表示**段落性質**不是多空訊號。 */
.rz{font-size:13px;line-height:1.9;color:var(--muted);margin:7px 0 0;
 padding:7px 0 7px 11px;border-left:2px solid var(--line2)}
.rz .rzl{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.5px;
 padding:1px 7px;border-radius:5px;margin-right:8px;vertical-align:1px;
 background:var(--line);color:var(--muted)}
.rz.f{border-left-color:#475569}
.rz.f .rzl{background:#334155;color:#CBD5E1}
.rz.i{border-left-color:var(--accent)}
.rz.i .rzl{background:#1E3A5F;color:#BFDBFE}
.rz.w{border-left-color:var(--warn)}
.rz.w .rzl{background:#3A2E10;color:#FCD34D}
.rz.s{border-left-color:var(--up)}
.rz.s .rzl{background:#14311F;color:#86EFAC}
.txt b{color:#CBD5E1}
.ang{border-left:3px solid var(--line);padding-left:12px;margin:12px 0}
.ang.buy{border-left-color:var(--up)}
.ang.sell{border-left-color:var(--down)}
.ang .t{font-size:14px;font-weight:700}
.ang .b{font-size:12.5px;color:#93C5FD;margin:3px 0 6px}
.rp{border-top:1px solid var(--line);padding:9px 0;font-size:12.5px;color:var(--muted);line-height:1.7}
.rp b{color:var(--ink)}
.warn{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--warn);
 border-radius:10px;padding:12px 15px;margin:12px 0;font-size:13px;line-height:1.85;color:var(--muted)}
.warn b{color:#FCD34D}
.pos{color:var(--up)}.neg{color:var(--down)}
/* 摘要層 */
.sm{font-size:13.5px;line-height:1.95;color:#CBD5E1;margin:2px 0 0;padding-left:18px}
.sm li{margin:5px 0}
.kp{font-size:12.5px;line-height:1.8;color:var(--muted);padding:7px 0;
 border-top:1px solid var(--line2)}
.kp .tag{display:inline-block;font-size:10px;font-weight:700;padding:1px 7px;
 border-radius:5px;margin-right:8px;vertical-align:1px}
.kp .tag.nc{background:#1E3A5F;color:#BFDBFE}
.kp .tag.cl{background:#334155;color:#CBD5E1}
.kp .tag.cv{background:#3A2E10;color:#FCD34D}
/* 查核表 */
.fc{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.fc th{text-align:left;padding:7px 8px;color:var(--dim);font-weight:600;font-size:11.5px;
 border-bottom:1px solid var(--line);white-space:nowrap}
.fc td{padding:9px 8px;border-bottom:1px solid var(--line2);vertical-align:top;
 line-height:1.75;color:var(--muted)}
.fc td.k{white-space:nowrap;color:var(--ink);font-weight:600}
.fc td.v{white-space:nowrap;font-weight:700}
.fc .ok{color:var(--up)}.fc .warn{color:var(--warn)}.fc .wait{color:var(--dim)}
.fc .note{display:block;margin-top:4px;color:var(--dim);font-size:11.5px;line-height:1.7}
@media(max-width:700px){.fc td.k,.fc td.v{white-space:normal}}
"""


def render(d, extra_notes=None):
    from board_theme import BASE_CSS, esc, header, nav_abs
    import advisor_reports as ar
    px = _price(d)
    name = (d.get("lamp") or {}).get("name") or (d["reports"][0].get("name")
                                                 if d["reports"] else d["ticker"])
    body = []

    # ── 燈號 ───────────────────────────────────────────────
    L = d.get("lamp")
    if L:
        # 2026-09-04 Leo：「這幾個字卡可以像燈號那樣顏色呈現嗎」
        # → 用**跟查股頁/燈號頁完全同一套符號**，不另外發明一套：
        #   🔴 多方 / 🟢 空方（老墨的用法，跟一般紅綠相反，但站上早就統一了）
        #   🟢/⚫ 四顆燈、⭐ 打點成立
        # ⚠️ board_theme 的規則是「顏色只給訊號用，數字類不上色」，
        #   所以現價、風報比這種純數字維持白色；只有 RS 是有方向語意的百分比，
        #   跟 technical_indicators 的 RS 卡一致上綠/紅。
        lam = L.get("lamps") or {}
        lamp_str = "".join("🟢" if v else "⚫" for v in lam.values()) or "—"
        bull = L.get("bull")
        st_v = ("🔴 多方" if bull else "🟢 空方") if bull is not None else "—"
        st_s = ((f"停損參考線 {L['st_line']:,.1f}"
                 + (f"（現價高於 {L['gap_pct']:+.1f}%）" if L.get("gap_pct") is not None else ""))
                if bull and L.get("st_line") else
                (f"站上 {L['st_line']:,.1f} 才翻多" if L.get("st_line") else ""))
        rr = L.get("rr")
        rr_s = ("⭐ 打點成立（≥3燈且風報比≥1）" if L.get("combo") and rr and rr >= 1
                else ("空方不計風報比" if bull is False else "無目標價則不計"))
        rs_h = "—"
        if L.get("rs_short") is not None:
            def _c(x):
                return f'<span class="{"pos" if x > 0 else "neg"}">{x:+.1f}%</span>'
            rs_h = f'{_c(L["rs_short"])} / {_c(L.get("rs_long") or 0)}'
        cells = [("現價", f"{L['price']:,.2f}" if L.get("price") else "—",
                  f"資料日 {L.get('asof','—')}", False),
                 ("四燈", f'<span style="font-size:19px;letter-spacing:2px">{lamp_str}</span>',
                  f"{L.get('lit')}/4　{'COMBO 成立' if L.get('combo') else '未成立'}", True),
                 ("SuperTrend", st_v, st_s, True),
                 ("風報比", f"{rr:.2f}" if rr else "—", rr_s, False),
                 ("RS 短/長", rs_h, "對自身 60 日均線", True)]
        body.append('<div class="sb"><h2>技術面（進出燈號）</h2>'
                    '<div class="sub">來源：每日掃描 combo_result；'
                    '符號跟查股頁／進出燈號頁同一套</div><div class="kv">'
                    + "".join(f'<div class="c"><div class="k">{esc(k)}</div>'
                              f'<div class="v{" zh" if zh else ""}">{v}</div>'
                              f'<div class="s">{esc(sub_)}</div></div>'
                              for k, v, sub_, zh in cells) + "</div></div>")

    # ── 券商報告 ────────────────────────────────────────────
    if d["reports"]:
        # ── 多家對照表（2026-09-04 Leo：「同一隻股票的報告請整合在一起」）──
        # 同一檔有多份時，最有資訊量的不是逐份讀，是**把假設並排看差在哪**。
        # 7750 新代實測：5 家在 10 天內出報告、目標價差 35%，而差異幾乎全來自
        # 「倍數」與「用哪一年的 EPS」，不是基本面分歧。
        cmp_ = ""
        if len(d["reports"]) > 1:
            tgs = [r["target"] for r in d["reports"] if r.get("target")]
            def _row(r):
                tg = f'{r["target"]:,.0f}' if r.get("target") else "—"
                mu = (f'{r["valuation_multiple"]:g} 倍'
                      if r.get("valuation_multiple") else "—")
                return (f'<tr><td class="k">{esc(r.get("broker"))}</td>'
                        f'<td>{esc(r.get("date"))}</td>'
                        f'<td>{esc(r.get("rating") or "—")}</td>'
                        f'<td class="v">{tg}</td><td class="v">{mu}</td>'
                        f'<td>{esc(r.get("valuation_eps_label") or "—")}</td></tr>')
            trs = "".join(_row(r) for r in d["reports"])
            spread = ""
            if len(tgs) >= 2:
                spread = (f'目標價 {min(tgs):,.0f}～{max(tgs):,.0f}'
                          f'（差 {(max(tgs) / min(tgs) - 1) * 100:.0f}%）')
            cmp_ = ('<table class="fc"><tr><th>券商</th><th>日期</th><th>評等</th>'
                    '<th>目標價</th><th>倍數</th><th>乘在哪一期</th></tr>'
                    + trs + '</table>'
                    + (f'<div class="txt">⚠️ <b>{spread}</b>——差異多半來自'
                       f'<b>倍數與用哪一年 EPS</b>，不是基本面分歧。'
                       f'多家同時出報告代表這個看法已經擁擠。</div>' if spread else ""))
        rp = []
        for r in d["reports"]:
            tg = r.get("target")
            up = f"（距現價 {(tg / px - 1) * 100:+.1f}%）" if tg and px else ""
            im = ar.implied_multiple(r, px)
            vm = ""
            if im:
                now, want, how = im
                cls = "neg" if now >= want else "pos"
                vm = (f'<br>估值前提：市場現在給 <span class="{cls}">{now:.1f} 倍'
                      f'{esc((r.get("valuation_kind") or "").upper())}</span>、'
                      f'報告假設 {want:.1f} 倍'
                      + ("——<b>前提已用完</b>" if now >= want
                         else f"（還差 {(want / now - 1) * 100:.0f}%）")
                      + f'　<span style="color:var(--dim);font-size:11px">{esc(how)}</span>')
            rp.append(
                f'<div class="rp"><b>{esc(r.get("broker"))}</b>　{esc(r.get("date"))}　'
                f'{esc(r.get("rating") or "無評等")}　'
                + (f'目標 <b>{tg:,.0f}</b>{esc(up)}' if tg else "無目標價（Note 類）")
                + (f'<br>依據：{esc(r["valuation_basis"])}' if r.get("valuation_basis") else "")
                + vm
                + (f'<br>論點：{esc(r["thesis"])}' if r.get("thesis") else "")
                + (f'<br>報告自列風險：{esc("、".join(r["risks"]))}' if r.get("risks") else "")
                + "</div>")
        body.append('<div class="sb"><h2>券商研究報告</h2>'
                    f'<div class="sub">{len(d["reports"])} 份，各家自己的推導，'
                    f'不是市場共識平均</div>' + cmp_ + "".join(rp) + "</div>")

    # ── 摘要層（2026-09-04 Leo：「我希望可以等於是一份摘要」）─────────
    top = d["reports"][0] if d["reports"] else None
    if top and (top.get("summary") or top.get("key_points")):
        li = "".join(f"<li>{esc(x)}</li>" for x in (top.get("summary") or []))
        TAG = {"nonconsensus": ("nc", "非共識"), "claim": ("cl", "可查核宣稱"),
               "caveat": ("cv", "報告自己的保留")}
        kps = "".join(
            f'<div class="kp"><span class="tag {TAG.get(k.get("type"), ("cl", "重點"))[0]}">'
            f'{TAG.get(k.get("type"), ("cl", "重點"))[1]}</span>{esc(k.get("text"))}</div>'
            for k in (top.get("key_points") or []))
        body.append('<div class="sb"><h2>這份報告在講什麼</h2>'
                    f'<div class="sub">{esc(top.get("broker"))}　{esc(top.get("date"))}'
                    '　摘要由本機 claude 從原文抽出，不是我的評論</div>'
                    + (f'<ul class="sm">{li}</ul>' if li else "")
                    + kps + "</div>")

    # ── 查核層（Leo：「像老墨的 html 檢查報告商寫的是不是事實」）──────
    if top:
        try:
            import report_factcheck as fcm
            rows = fcm.check(top, px, d.get("base_rate"), d.get("margin"))
        except Exception as e:                              # noqa: BLE001
            rows = []
            print(f"  查核層失敗：{str(e)[:80]}")
        if rows:
            V = {"ok": ("ok", "✅ 對得上"), "warn": ("warn", "⚠️ 有落差"),
                 "wait": ("wait", "⏳ 還不能驗")}
            trs = "".join(
                f'<tr><td class="k">{esc(r["kind"])}</td>'
                f'<td>{esc(r["claim"])}</td>'
                f'<td>{esc(r["ours"])}<span class="note">{esc(r["note"])}</span></td>'
                f'<td class="v {V[r["verdict"]][0]}">{V[r["verdict"]][1]}</td></tr>'
                for r in rows)
            body.append('<div class="sb"><h2>查核：報告的假設 vs 我們算的</h2>'
                        f'<div class="sub">{esc(fcm.summary(rows))}　'
                        '⭐ 重點不是抓券商說謊——他們寫的多半是預估。'
                        '是把「他假設什麼」跟「這檔自己的歷史做得到什麼」擺在一起，'
                        '讓落差自己現形</div>'
                        '<table class="fc"><tr><th>查核項</th><th>報告說</th>'
                        '<th>我們算的</th><th>判定</th></tr>'
                        + trs + "</table></div>")

    # ── 我們算的、報告沒有的 ─────────────────────────────────
    cross = []
    b = d.get("base_rate")
    if b and b.get("requirement"):
        q, tr = b["requirement"], (b.get("track_record") or {})
        tier = {"unprecedented": "要求超出這檔自身歷史紀錄一大截",
                "rare": "要求剛好貼在自身歷史紀錄上",
                "normal": "要求落在這檔過去做得到的範圍內",
                "low_coverage": "分析師覆蓋太少，不列入判斷"}.get(q.get("tier"), q.get("tier"))
        cross.append(
            f'<div class="txt"><b>預估前提檢查（{q.get("year")}）</b>：{esc(tier)}。'
            f'剩 {q.get("months_left")} 個月要月營收 YoY '
            f'<b>{q.get("need_yoy", 0) * 100:+.1f}%</b>，'
            f'而這檔歷史中位 {q.get("yoy_med", 0) * 100:+.1f}%、'
            f'最大 {q.get("yoy_max", 0) * 100:+.1f}%（n={q.get("yoy_n")}）。'
            + (f'分析師準頭：{tr.get("n")} 次猜中 {tr.get("beats")} 次、'
               f'中位驚喜 {tr.get("median_surprise"):+.1f}%（{esc(tr.get("bias",""))}）。'
               if tr else "")
            + '<br><span style="color:var(--dim)">這一層量的是「市場對它的期待被堆多高」，'
              '不是「公司好不好」——是容錯空間的刻度。</span></div>')
    m = d.get("margin")
    if m:
        cross.append(
            f'<div class="txt"><b>毛利率位階</b>：現值 {m.get("cur")}%，'
            f'在自身 {m.get("n")} 季裡第 <b>{m.get("pct"):.0f} 百分位</b>'
            f'（區間 {m.get("lo")}~{m.get("hi")}、中位 {m.get("med")}）。'
            f'{esc(m.get("note") or "")}</div>')
    if cross:
        body.append('<div class="sb"><h2>我們算的：報告裡沒有的那幾層</h2>'
                    '<div class="sub">這些是對照「這檔自己的歷史分布」算出來的，'
                    '不是跟同業比、也不是券商的預估</div>' + "".join(cross) + "</div>")

    # ── 投資長 ─────────────────────────────────────────────
    v = d.get("verdict")
    if v:
        angs = []
        for key, nm in (("trend_angle", "趨勢角度（SuperTrend＋RS＋產業輪動）"),
                        ("value_angle", "價值角度（洪瑞泰）")):
            a = v.get(key) or {}
            j = a.get("judgment") or "—"
            cls = "buy" if j.startswith("續抱") else ("sell" if "出場" in j else "")
            angs.append(
                f'<div class="ang {cls}"><div class="t">{esc(nm)}：{esc(j)}</div>'
                f'<div class="b">{esc(a.get("brief") or "")}</div>'
                + fmt_reasoning(a.get("reasoning"), esc) + '</div>')
        conds = []
        for key, nm in (("trend_conditions", "趨勢"), ("value_conditions", "價值")):
            for c in v.get(key) or []:
                conds.append(f'<div class="txt">· [{nm}] {esc(c.get("desc"))}</div>')
        body.append('<div class="sb"><h2>投資長判斷</h2>'
                    '<div class="sub">兩個角度獨立判斷，**不強迫湊成一個結論**；'
                    '相反的建議照實列出，最終決定是你的</div>'
                    + "".join(angs)
                    + ('<div class="txt" style="margin-top:12px"><b>失效條件（每天自動檢查）</b></div>'
                       + "".join(conds) if conds else "") + "</div>")

    # ── 券商異動 ────────────────────────────────────────────
    if d["changes"]:
        rows = "".join(
            f'<div class="rp">{esc(c.get("date"))}｜<b>{esc(c.get("broker"))}</b>｜'
            f'{esc(c.get("rating"))}｜'
            f'{"▲ 調升" if c.get("direction") == "up" else ("▼ 調降" if c.get("direction") == "down" else "－")}'
            f'　{esc(str(c.get("tp_old")))} → {esc(str(c.get("tp_new")))}</div>'
            for c in d["changes"])
        body.append('<div class="sb"><h2>近期券商目標價異動</h2>'
                    '<div class="sub">來自每日異動表；⚠️ 數字未經覆核，'
                    '只看方向不建判斷條件</div>' + rows + "</div>")

    for n in (extra_notes or []):
        body.append(f'<div class="warn">{n}</div>')

    sub = (f'{esc(name)}（{esc(d["ticker"])}）'
           + (f'　現價 {px:,.2f}' if px else "")
           + '<br>券商報告怎麼說 vs 我們自己算什麼——全部讀既有資料，沒有重算也沒有花錢')
    return ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(name)} 整合報告</title><style>" + BASE_CSS + CSS
            + "</style></head><body><div class=\"wrap\">"
            + header("earnings", f"{name} 整合報告", sub, nav_abs())
            + "".join(body) + "</div></body></html>")


def briefed_tickers():
    """有券商報告的代號集合——`--all` 的母體。

    ⚠️ 母體刻意只取「有券商報告的」，不取全部持股：沒有報告的話這一頁的
    上半部（券商怎麼說、估值前提）整段是空的，產出來只會是一頁我們自己
    系統的數字，跟燈號頁重複。
    """
    st = _load("state/advisor_reports.json", {}) or {}
    out = []
    for v in st.values():
        if v.get("_notreport"):
            continue
        tk = v.get("ticker")
        if tk and str(tk) not in out:
            out.append(str(tk))
    return sorted(out)


def build_one(ticker, output=""):
    """產一檔，回 (輸出路徑, gather 結果)。"""
    d = gather(ticker)
    html = render(d)
    out = output or os.path.join(OBIS, f"{d['ticker']}_整合報告.html")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    return out, d, len(html)


def _stat(d):
    return (f"燈號 {'有' if d['lamp'] else '無'}｜券商報告 {len(d['reports'])} 份"
            f"｜異動 {len(d['changes'])} 筆｜投資長判斷 {'有' if d['verdict'] else '無'}"
            f"｜毛利率位階 {'有' if d['margin'] else '無'}"
            f"｜預估前提 {'有' if d['base_rate'] else '無'}")


INDEX_NAME = "整合報告索引.html"

INDEX_CSS = """
.ix{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.ix th{text-align:left;padding:8px 9px;color:var(--dim);font-weight:600;font-size:11.5px;
 border-bottom:1px solid var(--line);white-space:nowrap}
.ix td{padding:11px 9px;border-bottom:1px solid var(--line2);vertical-align:top;
 color:var(--muted);line-height:1.7}
.ix tr.hot td{background:rgba(248,113,113,.06)}
.ix a{color:var(--ink);font-weight:700;text-decoration:none;border-bottom:1px dotted var(--line2)}
.ix a:hover{color:#93C5FD}
.ix .code{font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums;font-size:13.5px}
.ix .nm{display:block;font-size:11.5px;color:var(--dim);font-weight:400;margin-top:2px}
.ix .num{font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
.ix .sub{display:block;font-size:11px;color:var(--dim);margin-top:2px;line-height:1.6}
.ix .pos{color:var(--up)}.ix .neg{color:var(--down)}
.ix .fire{color:var(--down);font-weight:700}
.ix .quiet{color:var(--dim)}
.pill{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;
 border-radius:5px;margin-right:5px;vertical-align:1px}
.pill.ok{background:#14311F;color:#86EFAC}
.pill.warn{background:#3A2E10;color:#FCD34D}
.pill.wait{background:var(--line);color:var(--muted)}
@media(max-width:700px){
 .ix,.ix tbody,.ix tr,.ix td{display:block;width:100%}
 .ix thead{display:none}
 .ix tr{border:1px solid var(--line);border-radius:10px;padding:4px 2px;margin:9px 0;
  background:var(--surface)}
 .ix td{border-bottom:1px solid var(--line2);padding:8px 12px}
 .ix tr td:last-child{border-bottom:none}
 .ix td::before{content:attr(data-h);display:block;font-size:10px;color:var(--dim);
  letter-spacing:.3px;margin-bottom:3px}
 .ix td.main::before{content:none}
}
"""


def index_rows():
    """每一檔一行摘要。**只讀既有 state 檔＋跑查核，不呼叫 AI、不重算行情。**

    ⚠️ 這裡刻意重跑一次 `gather()`／`report_factcheck.check()`，跟 `--all` 有重複
    計算。換來的是「索引不依賴 --all 的內部狀態」——`--index` 單獨跑得起來，
    而且改 render() 不會連帶弄壞索引。12 檔的成本是幾秒，不值得為此耦合。
    """
    today = _load("state/advisor_reports_today.json", {}) or {}
    fired_by = {}
    for r in today.get("rows", []):
        tk = _norm(str(r.get("ticker") or ""))
        for f in (r.get("fired") or []):
            fired_by.setdefault(tk, []).append(f)

    out = []
    for tk in briefed_tickers():
        d = gather(tk)
        px = _price(d)
        top = d["reports"][0] if d["reports"] else None
        fc = []
        if top:
            try:
                import report_factcheck as fcm
                fc = fcm.check(top, px, d.get("base_rate"), d.get("margin"))
            except Exception:                               # noqa: BLE001
                fc = []
        cnt = {"ok": 0, "warn": 0, "wait": 0}
        for r in fc:
            cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1

        # 目標價取最新一份「有給目標價」的報告——不是最高的那一份，也不平均。
        tgt = tgt_src = None
        for r in d["reports"]:
            if r.get("target"):
                tgt, tgt_src = float(r["target"]), r
                break

        lamp = d.get("lamp") or {}
        out.append({
            "ticker": d["ticker"],
            "name": (top or {}).get("name") or lamp.get("name") or d["ticker"],
            "n_reports": len(d["reports"]),
            "brokers": sorted({str(r.get("broker") or "?") for r in d["reports"]}),
            "last_date": (top or {}).get("date"),
            "rating": (top or {}).get("rating"),
            "price": px,
            "target": tgt,
            "target_broker": (tgt_src or {}).get("broker"),
            "upside": (round((tgt / px - 1) * 100, 1)
                       if tgt and px else None),
            "fc": cnt,
            "n_fc": len(fc),
            "fired": fired_by.get(_norm(tk), []),
            "lit": lamp.get("lit"),
            "has_lamp": bool(lamp),
            "verdict": bool(d.get("verdict")),
            "n_changes": len(d.get("changes") or []),
        })

    # 要看的排前面：先失效線觸發、再落差條數、再報告份數。
    out.sort(key=lambda r: (-len(r["fired"]), -r["fc"]["warn"],
                            -r["n_reports"], r["ticker"]))
    return out


def render_index(rows):
    from board_theme import BASE_CSS, esc, header, nav_abs

    def cell_target(r):
        if not r["target"]:
            return '<span class="quiet">報告未給</span>'
        s = f'<span class="num">{r["target"]:,.0f}</span>'
        if r["upside"] is not None:
            k = "pos" if r["upside"] >= 0 else "neg"
            s += f' <span class="num {k}">{r["upside"]:+.1f}%</span>'
        if r["target_broker"]:
            s += f'<span class="sub">{esc(r["target_broker"])}</span>'
        return s

    def cell_fc(r):
        if not r["n_fc"]:
            return '<span class="quiet">未查核</span>'
        c, p = r["fc"], []
        if c["ok"]:
            p.append(f'<span class="pill ok">{c["ok"]} 對得上</span>')
        if c["warn"]:
            p.append(f'<span class="pill warn">{c["warn"]} 有落差</span>')
        if c["wait"]:
            p.append(f'<span class="pill wait">{c["wait"]} 等財報</span>')
        return "".join(p)

    def cell_fired(r):
        if not r["fired"]:
            return '<span class="quiet">未觸發</span>'
        first = str(r["fired"][0])[:60]
        extra = (f'<span class="sub">另有 {len(r["fired"]) - 1} 條</span>'
                 if len(r["fired"]) > 1 else "")
        return f'<span class="fire">🔴 {esc(first)}</span>{extra}'

    def cell_ours(r):
        p = []
        if r["has_lamp"]:
            p.append(f'燈號 {r["lit"]}/4')
        else:
            p.append('<span class="quiet">不在燈號母體</span>')
        if r["verdict"]:
            p.append("有投資長判斷")
        if r["n_changes"]:
            p.append(f'異動 {r["n_changes"]} 筆')
        return "　".join(p)

    trs = []
    for r in rows:
        cls = ' class="hot"' if r["fired"] else ""
        trs.append(
            f"<tr{cls}>"
            f'<td class="main" data-h="個股"><a class="code" '
            f'href="{esc(r["ticker"])}_整合報告.html">{esc(r["ticker"])}</a>'
            f'<span class="nm">{esc(r["name"])}</span></td>'
            f'<td data-h="券商報告"><span class="num">{r["n_reports"]}</span> 份'
            f'<span class="sub">{esc("、".join(r["brokers"][:3]))}'
            f'{"…" if len(r["brokers"]) > 3 else ""}　最新 {esc(r["last_date"] or "-")}</span></td>'
            f'<td data-h="報告目標價">{cell_target(r)}</td>'
            f'<td data-h="查核">{cell_fc(r)}</td>'
            f'<td data-h="失效線">{cell_fired(r)}</td>'
            f'<td data-h="我們自己的資料">{cell_ours(r)}</td>'
            "</tr>")

    n_fire = sum(1 for r in rows if r["fired"])
    n_warn = sum(r["fc"]["warn"] for r in rows)
    sub = (f"{len(rows)} 檔有券商研究報告　"
           f"{n_fire} 檔的失效線被觸發　共 {n_warn} 條假設與我們算的有落差")

    head = ('<div class="sb"><h2>這頁是什麼</h2><div class="sub">'
            '每一列是一檔**有券商研究報告**的個股，點代號進去看整合報告。'
            '排序＝失效線被觸發的排最前，其次是查核落差多的。<br>'
            '⚠️ 目標價是「最新一份報告」的數字，不是共識也不是最高的那份；'
            '風報比用的仍然是共識目標價，兩者不同源，不要互相對照。<br>'
            '⚠️ 沒有券商報告的持股不會出現在這裡——那些看燈號頁就好，'
            '這一頁的價值在「報告說的 vs 我們算的」。'
            '</div></div>')
    head = head.replace("**有券商研究報告**", "<b>有券商研究報告</b>")

    tbl = ('<div class="sb"><h2>個股一覽</h2>'
           '<table class="ix"><thead><tr>'
           "<th>個股</th><th>券商報告</th><th>報告目標價</th>"
           "<th>查核</th><th>失效線</th><th>我們自己的資料</th>"
           "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>")

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>整合報告索引</title><style>" + BASE_CSS + CSS + INDEX_CSS
            + '</style></head><body><div class="wrap">'
            + header("earnings", "整合報告索引", sub, nav_abs())
            + head + tbl + "</div></body></html>")


def build_index():
    rows = index_rows()
    if not rows:
        print("沒有任何已解析的券商報告，不產索引。")
        return None, []
    html = render_index(rows)
    out = os.path.join(OBIS, INDEX_NAME)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    return out, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?", default="")
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--all", action="store_true",
                    help="重產所有「有券商報告」的個股＋索引（每日排程用）")
    ap.add_argument("--index", action="store_true",
                    help="只重產索引頁（不重產個股）")
    a = ap.parse_args()

    if a.index and not a.all:
        out, rows = build_index()
        if out:
            print(f"✅ 已存 {out}（{len(rows)} 檔）")
        return 0

    if a.all:
        tks = briefed_tickers()
        if not tks:
            print("沒有任何已解析的券商報告，不產出。")
            return 0
        ok = fail = 0
        for tk in tks:
            try:
                out, d, n = build_one(tk)
                ok += 1
                print(f"  ✅ {d['ticker']:8} {os.path.basename(out)}  ({n:,} bytes)  {_stat(d)}")
            except Exception as e:                          # noqa: BLE001
                fail += 1
                # 一檔壞掉不能讓其餘 N-1 檔跟著不產出（排程裡尤其重要）。
                print(f"  ❌ {tk:8} 失敗：{str(e)[:120]}")
        # 索引一定要在個股全部產完之後才產（它讀的是同一批 state，順序不影響
        # 內容，但先產索引會讓「索引列了某檔、那檔的頁面卻沒更新」變得可能）。
        try:
            ip, irows = build_index()
            if ip:
                n_fire = sum(1 for r in irows if r["fired"])
                print(f"  📇 索引 {os.path.basename(ip)}"
                      f"（{len(irows)} 檔，其中 {n_fire} 檔失效線被觸發）")
        except Exception as e:                              # noqa: BLE001
            fail += 1
            print(f"  ❌ 索引失敗：{str(e)[:120]}")
        print()
        print(f"完成 {ok} 檔，失敗 {fail} 檔｜存放 {OBIS}")
        return 1 if fail and not ok else 0

    if not a.ticker:
        ap.error("要給代號，或用 --all 重產全部")
    out, d, n = build_one(a.ticker, a.output)
    print(f"✅ 已存 {out}（{n:,} bytes）")
    print(f"   {_stat(d)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
