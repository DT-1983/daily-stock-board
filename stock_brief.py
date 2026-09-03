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

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"


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
                    f'不是市場共識平均</div>' + "".join(rp) + "</div>")

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
                f'<div class="txt">{esc(a.get("reasoning") or "")}</div></div>')
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("-o", "--output", default="")
    a = ap.parse_args()
    d = gather(a.ticker)
    html = render(d)
    out = a.output or os.path.join(OBIS, f"{d['ticker']}_整合報告.html")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    print(f"✅ 已存 {out}（{len(html):,} bytes）")
    print(f"   燈號 {'有' if d['lamp'] else '無'}｜券商報告 {len(d['reports'])} 份"
          f"｜異動 {len(d['changes'])} 筆｜投資長判斷 {'有' if d['verdict'] else '無'}"
          f"｜毛利率位階 {'有' if d['margin'] else '無'}｜預估前提 {'有' if d['base_rate'] else '無'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
