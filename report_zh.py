# -*- coding: utf-8 -*-
"""券商報告中文重點頁（2026-09-05，Leo：「做成通用的」）。

## 這支跟 stock_brief 的差別

| | `stock_brief.py` | 這支 |
|---|---|---|
| 主體 | **我們自己的系統**（燈號/投資長/毛利率/base_rate），券商報告是其中一層 | **單一份券商報告**，我們的數字是對照組 |
| 一檔多份報告 | 併成對照表 | 一份一頁（要看哪一份自己選）|
| 回答 | 「這檔現在怎麼看」 | 「**這份報告在說什麼、哪裡站不住腳**」|

## 🔴 這頁刻意不叫 AI 寫「判讀」

第一版（高盛 2454 那份）的「我讀完發現的三件事」是我手寫的。回頭看，
**那三條全部都是算術**：CAGR 對帳、逐年拆 EPS 找空白年、把上檔拆成
「盈餘 × 倍數」。所以做法不是叫模型寫感想，而是**把那三條變成 report_factcheck
的規則**（9/5 已加），這頁只負責把查核層抓到的落差**排在最前面、講成人話**。

⭐ **能算的就不要讓 AI 用講的。** 模型寫的判讀每次都不一樣、而且不會自己去驗算；
規則寫一次，16 份既有報告和之後每一份都適用，還能被回頭檢查。

⚠️ 這是**重點整理不是全文翻譯**——原文是券商的付費研究，整份翻譯等於重製它。
本頁放的是可查證的數字與表格、查核層算出來的落差、以及我們系統的獨立對照。

⚠️ 全部讀既有 state 檔，**不呼叫 AI、不花錢**（摘要那幾點是解析時就抽好的）。

用法:
    python report_zh.py 2454                    # 該檔最新一份報告
    python report_zh.py 2454 --broker 高盛       # 指定券商
    python report_zh.py --all                   # 每檔最新一份，全部重產
    python report_zh.py --list                  # 有哪些報告可以產
"""
import argparse
import io
import json
import os
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                      # noqa: E402
import report_factcheck as fcm                               # noqa: E402
import stock_brief                                           # noqa: E402

STORE = "state/advisor_reports.json"


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def reports(ticker=None, broker=None):
    """符合條件的報告，最新的排前面。回 [(檔名, 內容), ...]。"""
    st = stock_brief._load(STORE, {}) or {}
    out = []
    for k, r in st.items():
        if r.get("_notreport"):
            continue
        if ticker and stock_brief._norm(r.get("ticker", "")) != stock_brief._norm(ticker):
            continue
        if broker and broker.lower() not in str(r.get("broker", "")).lower():
            continue
        out.append((k, r))
    out.sort(key=lambda kv: str(kv[1].get("date")), reverse=True)
    return out


def cagr(a, b, n):
    return (b / a) ** (1.0 / n) - 1


# ── 版面 ────────────────────────────────────────────────────
CSS = """
.lead{background:var(--surface);border:1px solid var(--line);border-left:3px solid #F5B841;
 border-radius:10px;padding:14px 17px;margin:12px 0;font-size:14.5px;line-height:1.95;color:#E2E8F0}
.lead b{color:#FCD34D}
.lead .h{font-size:12px;color:var(--dim);font-weight:700;letter-spacing:.5px;
 display:block;margin-bottom:6px}
.ft{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.ft th{text-align:right;padding:7px 9px;color:var(--dim);font-weight:600;font-size:11.5px;
 border-bottom:1px solid var(--line);white-space:nowrap}
.ft th:first-child{text-align:left}
.ft td{padding:8px 9px;border-bottom:1px solid var(--line2);text-align:right;
 font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums;color:var(--muted);
 white-space:nowrap}
.ft td:first-child{text-align:left;font-family:inherit;color:var(--ink);font-weight:600}
.ft tr.hl td{color:#FCD34D}
.fnd{border-left:3px solid var(--down);padding:2px 0 2px 13px;margin:14px 0}
.fnd .t{font-size:14px;font-weight:700;color:#FCA5A5;margin-bottom:5px}
.fnd .b{font-size:13px;line-height:1.95;color:var(--muted)}
.fnd .b b{color:#E2E8F0}
.src{font-size:11.5px;color:var(--dim);line-height:1.8;margin-top:16px;
 border-top:1px solid var(--line);padding-top:11px}
.src code{font-size:11px;color:var(--muted)}
"""


def render(key, r, d=None, px=None, fc=None):
    from board_theme import BASE_CSS, esc, esc_b, header, nav_abs

    d = d if d is not None else stock_brief.gather(str(r.get("ticker")))
    px = px if px is not None else stock_brief._price(d)
    fc = fc if fc is not None else fcm.check(r, px, d.get("base_rate"), d.get("margin"))
    lamp = d.get("lamp") or {}
    name = r.get("name") or lamp.get("name") or r.get("ticker")
    tgt = _num(r.get("target"))
    veps = _num(r.get("valuation_eps"))
    rep_px = _num(r.get("close_at_report"))
    fcs = [f for f in (r.get("forecast") or []) if _num(f.get("revenue")) or _num(f.get("eps"))]

    def kv(items):
        cs = "".join(f'<div class="c"><div class="k">{esc(k)}</div>'
                     f'<div class="v{" zh" if zh else ""}">{v}</div>'
                     + (f'<div class="s">{esc(s)}</div>' if s else "") + "</div>"
                     for k, v, s, zh in items)
        return f'<div class="kv">{cs}</div>'

    def sb(title, sub, body):
        return (f'<div class="sb"><h2>{esc(title)}</h2>'
                + (f'<div class="sub">{sub}</div>' if sub else "") + body + "</div>")

    B = []

    # ── 開頭：查核層抓到最嚴重的那一條，講成一句話 ─────────────
    #
    # 🔴 這裡刻意**不叫 AI 下結論**。第一版是我手寫的，但回頭看那些「發現」
    # 全是算術，已經變成 report_factcheck 的規則。這裡只是把規則抓到的東西
    # 排序後放到最上面——**同一份報告跑十次會得到同一句話**，AI 寫的不會。
    warns = [x for x in fc if x["verdict"] == "warn"]
    if warns:
        # ⚠️ **所有落差各給一行，不排名、不截斷。**
        # 一度只列前三條，結果 2454 那份把「CAGR 內文與自家表格對不上」擠掉了——
        # 而那正是 Leo 覺得有價值的一條。查核項的既有順序是「重要性」沒錯，但那個
        # 順序是為表格排的，拿來當「只給你看前三名」的依據就不夠。
        # ⭐ 我沒有一套有依據的嚴重度排序，**所以就不排**——全列出來讓他自己掃，
        # 細節留在下面的表。寧可多一行，不要替他決定哪條不用看。
        head = "".join(
            f'<div style="margin-top:7px">・<b>{esc(x["kind"])}</b>　{esc_b(x["note"])}</div>'
            for x in warns)
        B.append(f'<div class="lead"><span class="h">查核抓到 {len(warns)} 條落差'
                 '（每條的數字在下面的查核表）</span>' + head + '</div>')
    else:
        B.append('<div class="lead"><span class="h">查核結果</span>'
                 f'{esc(fcm.summary(fc))}　'
                 '<b>沒有查到假設與我們算的有落差。</b>'
                 '⚠️ 沒查到落差不等於這份報告是對的——只代表我們<b>現有的九項規則</b>'
                 '沒抓到問題。</div>')

    # ── 關鍵數字 ─────────────────────────────────────────────
    items = [("評等", esc(r.get("rating") or "—"),
              f"前次 {esc(r['rating_prev'])}" if r.get("rating_prev") else "", True)]
    if tgt:
        items.append(("目標價", f"{tgt:,.0f}",
                      f"前次 {_num(r['target_prev']):,.0f}" if _num(r.get("target_prev")) else "",
                      False))
    if rep_px and tgt:
        items.append(("報告日收盤", f"{rep_px:,.0f}", f"當時上檔 {tgt/rep_px-1:+.1%}", False))
    if px:
        s = f"報告後 {px/rep_px-1:+.1%}" if rep_px else ""
        if tgt:
            s += ("｜" if s else "") + f"現在上檔 {tgt/px-1:+.1%}"
        items.append(("現價", f"{px:,.0f}", s, False))
    if veps and tgt:
        m = tgt / veps
        items.append(("估值方法", f"{m:.4g}x {(r.get('valuation_kind') or '').upper()}",
                      f"{esc(r.get('valuation_eps_label') or '')} 基數 {veps:g}", False))
        if px:
            items.append(("現價隱含倍數", f"{px/veps:.1f}x",
                          f"距報告假設 {m/(px/veps)-1:+.0%}", False))
    B.append(sb("關鍵數字", f"報告日 {esc(r.get('date'))}　{esc(r.get('broker'))}"
                            "　數字取自原文，未經改寫", kv(items)))

    # ── 報告在說什麼 ──────────────────────────────────────────
    if r.get("summary"):
        li = "".join(f"<li>{esc(x)}</li>" for x in r["summary"])
        B.append(sb("這份報告在說什麼",
                    "解析時由本機模型從原文抽出——這是<b>報告的主張</b>，不是我們的判斷",
                    f'<ul class="sm">{li}</ul>'))

    # ── 財務預估表（含我們算的 YoY 與 CAGR）────────────────────
    if len(fcs) >= 2:
        hdr = "".join(f"<th>{esc(x.get('year'))}</th>" for x in fcs)

        def row(label, vals, fmt, cls=""):
            return (f'<tr class="{cls}"><td>{esc(label)}</td>'
                    + "".join(f"<td>{fmt(v)}</td>" for v in vals) + "</tr>")

        def yoy(vals):
            out_ = [None]
            for i in range(1, len(vals)):
                a, b = vals[i - 1], vals[i]
                out_.append(b / a - 1 if (a and b and a > 0) else None)
            return out_

        pct = lambda v: "—" if v is None else f"{v:+.1%}"                    # noqa: E731
        body = f'<table class="ft"><tr><th>單位 {esc(r.get("revenue_unit") or "")}</th>{hdr}</tr>'
        rev = [_num(x.get("revenue")) for x in fcs]
        eps = [_num(x.get("eps")) for x in fcs]
        if any(rev):
            body += row("營收", rev, lambda v: "—" if v is None else f"{v:,.0f}")
            body += row("　YoY", yoy(rev), pct, "hl")
        if any(eps):
            body += row("EPS", eps, lambda v: "—" if v is None else f"{v:,.2f}")
            body += row("　YoY", yoy(eps), pct, "hl")
        pes = [_num(x.get("pe")) for x in fcs]
        if any(pes):
            body += row("本益比", pes, lambda v: "—" if v is None else f"{v:.1f}")
        body += "</table>"
        B.append(sb("券商的財務預估",
                    "表格數字照抄原文；<b>YoY 那幾列是我們算的</b>，原文沒有——"
                    "報告通常只給複合成長率，<b>平均會把「某一年原地踏步」抹平</b>", body))

    # ── 查核表（本頁的重點）───────────────────────────────────
    if fc:
        V = {"ok": ("ok", "✅ 對得上"), "warn": ("warn", "⚠️ 有落差"),
             "wait": ("wait", "⏳ 還不能驗")}
        order = {"warn": 0, "ok": 1, "wait": 2}
        rows = sorted(fc, key=lambda x: order.get(x["verdict"], 9))
        trs = "".join(
            f'<tr><td class="k">{esc(x["kind"])}</td><td>{esc_b(x["claim"])}</td>'
            f'<td>{esc_b(x["ours"])}<span class="note">{esc_b(x["note"])}</span></td>'
            f'<td class="v {V[x["verdict"]][0]}">{V[x["verdict"]][1]}</td></tr>'
            for x in rows)
        B.append(sb("查核：報告的假設 vs 我們自己算的",
                    esc(fcm.summary(fc))
                    + "　有落差的排最前面。⭐ 重點不是抓券商說謊——他們寫的多半是預估。"
                      "是把「他假設什麼」跟「這檔自己的歷史做得到什麼」擺在一起，"
                      "讓落差自己現形",
                    '<table class="fc"><tr><th>查核項</th><th>報告說</th>'
                    f'<th>我們算的</th><th>判定</th></tr>{trs}</table>'))

    # ── 報告自己的保留與風險 ───────────────────────────────────
    kp = r.get("key_points") or []
    cav = [k for k in kp if k.get("type") == "caveat"]
    non = [k for k in kp if k.get("type") == "nonconsensus"]
    if cav or non or r.get("risks"):
        body = ""
        if cav:
            body += ('<div class="sub" style="margin-top:0">⭐ <b>這幾條是券商自己寫的保留</b>'
                     '，通常被讀者略過，但它們是這個故事最脆弱的地方</div>')
            body += "".join(f'<div class="kp"><span class="tag cv">保留</span>{esc(k["text"])}'
                            "</div>" for k in cav)
        if non:
            body += "".join(f'<div class="kp"><span class="tag nc">非共識</span>{esc(k["text"])}'
                            "</div>" for k in non)
        if r.get("risks"):
            body += '<div class="sub" style="margin:11px 0 4px">報告自列的風險</div>'
            body += "".join(f'<div class="kp">・{esc(x)}</div>' for x in r["risks"])
        B.append(sb("報告自己的保留與風險", "", body))

    # ── 我們自己的訊號（獨立來源）──────────────────────────────
    if lamp:
        ct = _num(lamp.get("target"))
        B.append(sb("我們自己的訊號（跟這份報告無關的獨立來源）",
                    "取自每日燈號掃描——<b>風報比用的是市場共識目標價，不是這家券商的</b>；"
                    "兩者不同源，不要互相對照",
                    kv([("四燈", f"{lamp.get('lit')}／4", "", True),
                        ("SuperTrend", "多方" if lamp.get("bull") else "空方",
                         f"支撐線 {_num(lamp.get('st_line')):,.1f}"
                         if _num(lamp.get("st_line")) else "", True),
                        ("風報比", f"{lamp.get('rr')}" if lamp.get("rr") else "—",
                         "空方不計算" if not lamp.get("rr") else "用共識目標價算", False),
                        ("共識目標價", f"{ct:,.0f}" if ct else "—",
                         f"這家券商 {tgt:,.0f}，高出 {tgt/ct-1:+.0%}"
                         if (ct and tgt) else "", False)])))

    # ── 失效條件 ─────────────────────────────────────────────
    cond = r.get("conditions") or []
    if cond:
        B.append(sb("這份報告什麼時候算失效",
                    "解析時登錄的，每天自動檢查——<b>不需要你自己記</b>",
                    "".join(f'<div class="kp">・{esc(c.get("desc"))}</div>' for c in cond)))

    B.append('<div class="src">'
             f'📄 來源：{esc(r.get("broker"))} {esc(name)}（{esc(r.get("ticker"))}）'
             f'研究報告，{esc(r.get("date"))}。<br>'
             '⚠️ <b>這是重點整理，不是全文翻譯</b>——原文是券商的付費研究，'
             '整份翻譯等於重製它。本頁放的是可查證的數字與表格、查核層算出來的落差，'
             '以及我們系統獨立算出來的對照。要看完整論述請讀原始 PDF。<br>'
             '🔢 所有數字皆由程式從解析後的資料讀出，非手動輸入；'
             '查核那幾條是規則算的，<b>不是 AI 寫的感想</b>。<br>'
             f'📁 原始 PDF：<code>Documents\\Investment\\…\\{esc(key)}</code>'
             '</div>')

    sub = (f"{esc(r.get('date'))} {esc(r.get('broker'))}"
           + (f"　評等 {esc(r.get('rating'))}" if r.get("rating") else "")
           + (f"　目標價 {tgt:,.0f}" if tgt else "")
           + (f"　現價 {px:,.0f}" if px else "")
           + (f"　上檔 {tgt/px-1:+.0%}" if (tgt and px) else ""))
    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(name)} {esc(r.get('broker'))}報告中文重點</title><style>"
            + BASE_CSS + stock_brief.CSS + CSS
            + '</style></head><body><div class="wrap">'
            + header("earnings", f"{esc(name)} {esc(r.get('ticker'))}　"
                                 f"{esc(r.get('broker'))}報告中文重點", sub, nav_abs())
            + "".join(B) + "</div></body></html>")


def _slug(s):
    return "".join(c for c in str(s) if c.isalnum() or c in "-_")[:24] or "報告"


def build(key, r, output=""):
    html = render(key, r)
    fn = f"{r.get('ticker')}_{_slug(r.get('broker'))}報告_中文重點.html"
    out = output or op.brief(fn)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    return out, len(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?", default="")
    ap.add_argument("--broker", default="")
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--all", action="store_true", help="每檔最新一份，全部重產")
    ap.add_argument("--list", action="store_true", help="列出可以產的報告")
    a = ap.parse_args()

    if a.list:
        rs = reports(a.ticker or None, a.broker or None)
        print(f"共 {len(rs)} 份：")
        for k, r in rs:
            print(f"  {r.get('date')}  {str(r.get('ticker')):6} {str(r.get('name') or ''):8}"
                  f" {str(r.get('broker') or ''):10} 目標 {r.get('target')}")
        return 0

    if a.all:
        seen, ok, fail = set(), 0, 0
        for k, r in reports():
            t = stock_brief._norm(r.get("ticker", ""))
            if t in seen:
                continue                    # 每檔只產最新那一份
            seen.add(t)
            try:
                out, n = build(k, r)
                ok += 1
                print(f"  ✅ {t:6} {str(r.get('broker')):10} {os.path.basename(out)}"
                      f"  ({n:,} bytes)")
            except Exception as e:          # noqa: BLE001
                fail += 1                   # 一份壞掉不影響其餘
                print(f"  ❌ {t:6} {str(r.get('broker')):10} {type(e).__name__}: {str(e)[:90]}")
        print(f"\n完成 {ok} 份，失敗 {fail} 份｜存放 {op.BRIEFS}")
        return 1 if fail and not ok else 0

    if not a.ticker:
        ap.error("要給代號，或用 --all / --list")
    rs = reports(a.ticker, a.broker or None)
    if not rs:
        print(f"找不到 {a.ticker} " + (f"（券商含「{a.broker}」）" if a.broker else "") + " 的報告")
        return 1
    k, r = rs[0]
    out, n = build(k, r, a.output)
    print(f"✅ 已存 {out}（{n:,} bytes）")
    print(f"   {r.get('date')} {r.get('broker')}　"
          f"{fcm.summary(fcm.check(r, stock_brief._price(stock_brief.gather(r['ticker']))))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
