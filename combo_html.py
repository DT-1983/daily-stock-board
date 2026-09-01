# -*- coding: utf-8 -*-
"""COMBO 打點頁 → docs/combo.html（2026-09-01，Leo 指定抄老墨 XQ 的判定）

判定規則見 combo_scan.py。這支只負責呈現，**不重算任何指標**——
兩邊各算一次遲早會漂移，頁面直接讀 state/combo_result.json。

⚠️ 風報比的目標價用的是 **yfinance 市場共識**，不是投顧報告的目標價。
   老墨 8996 那份用投顧目標 1500 算出 1.95；我們用市場共識 1758.57 算出 3.25。
   **同一檔、同一天、差 1.7 倍** —— 兩者不能互相比較，頁面上必須寫清楚。

用法：python combo_html.py [-o docs/combo.html]
"""
import argparse
import io
import json
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from board_theme import BASE_CSS, header, NAV, esc  # noqa: E402

RESULT_PATH = "state/combo_result.json"
OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"
NL = chr(10)

CSS = """
.cbwrap{max-width:1180px;margin:0 auto;padding:0 14px 60px}
.cbstat{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 6px}
.cbstat div{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:10px 14px;min-width:120px}
.cbstat b{display:block;font-size:22px;line-height:1.2}
.cbstat span{font-size:12px;color:var(--dim)}
.cbnote{background:var(--card);border:1px solid var(--line);border-left:3px solid #EAB308;
  border-radius:8px;padding:11px 14px;margin:12px 0;font-size:13px;line-height:1.75;color:var(--dim)}
.cbsec{margin:26px 0 8px;font-size:15px;font-weight:700}
.cbsec small{font-weight:400;color:var(--dim);margin-left:8px}
table.cb{width:100%;border-collapse:collapse;font-size:13px}
table.cb th{text-align:right;padding:8px 6px;color:var(--dim);font-weight:600;
  border-bottom:1px solid var(--line);white-space:nowrap;font-size:12px}
table.cb th:nth-child(1),table.cb th:nth-child(2){text-align:left}
table.cb td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
table.cb td:nth-child(1),table.cb td:nth-child(2){text-align:left}
table.cb tr:hover td{background:rgba(255,255,255,.03)}
.lamp{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:3px}
.on{background:#22C55E}.off{background:#374151}
.pos{color:#22C55E}.neg{color:#EF4444}.dimv{color:var(--dim)}
.srcs{font-size:11px;color:var(--dim)}
@media(max-width:760px){table.cb th:nth-child(n+8),table.cb td:nth-child(n+8){display:none}}
"""


def _fmt(v, n=2, suffix=""):
    return "—" if v is None else f"{v:,.{n}f}{suffix}"


def _row_html(r):
    lamps = "".join(f'<span class="lamp {"on" if v else "off"}" title="{esc(k)}"></span>'
                    for k, v in r["lamps"].items())
    rr = r.get("rr")
    if rr is None:
        rrh = '<span class="dimv">無目標價</span>'
    else:
        cls = "pos" if rr >= 1 else ("neg" if rr < 0 else "")
        rrh = f'<span class="{cls}">{rr:,.2f}</span>'
    gap = r.get("gap_pct")
    gaph = "—" if gap is None else f'<span class="{"pos" if gap>0 else "neg"}">{gap:+.1f}%</span>'
    return (f'<tr><td><b>{esc(r["ticker"])}</b></td>'
            f'<td>{esc((r.get("name") or "")[:16])}</td>'
            f'<td style="text-align:left">{lamps}</td>'
            f'<td>{r["lit"]}/4</td>'
            f'<td>{_fmt(r["price"])}</td>'
            f'<td>{_fmt(r.get("target"))}</td>'
            f'<td>{rrh}</td><td>{gaph}</td>'
            f'<td>{_fmt(r.get("rs_short"),1,"%")}</td>'
            f'<td class="srcs">{esc("/".join(r.get("src") or []))}</td></tr>')


def _table(rows):
    if not rows:
        return '<div class="cbnote">這一組目前沒有標的。</div>'
    head = ("<tr><th>代號</th><th>名稱</th><th>燈號</th><th>燈</th><th>現價</th>"
            "<th>市場共識目標</th><th>風報比</th><th>距停損</th><th>RS60</th><th>來源</th></tr>")
    return ('<table class="cb">' + head
            + "".join(_row_html(r) for r in rows) + "</table>")


def build(d):
    rows = d["rows"]
    ok = [r for r in rows if r["combo"]]
    hit = [r for r in ok if r.get("rr") is not None and r["rr"] >= 1]
    weak = [r for r in ok if r.get("rr") is not None and r["rr"] < 1]
    notgt = [r for r in ok if r.get("rr") is None]
    body = [f'<div class="cbwrap">']
    body.append('<div class="cbstat">'
                f'<div><b>{len(rows)}</b><span>掃描母體</span></div>'
                f'<div><b>{len(ok)}</b><span>COMBO 成立（≥{d["combo_min"]} 燈）</span></div>'
                f'<div><b style="color:#22C55E">{len(hit)}</b><span>⭐ 打點成立（且風報比 ≥ 1）</span></div>'
                f'<div><b style="color:#EF4444">{sum(1 for r in ok if (r.get("rr") or 0) < 0)}</b>'
                '<span>現價已超過共識目標</span></div></div>')
    body.append('<div class="cbnote">'
                '<b>四個燈</b>：① SuperTrend 多方　② 動能 &gt; 0　③ 雙重颱風不為綠　'
                f'④ RS{d["rs_short"]}日乖離 &gt; +{d["rs_bias_min"]:g}%。'
                f'亮 {d["combo_min"]} 燈以上＝COMBO 成立；<b>打點成立＝再加上風報比 ≥ 1</b>——'
                '燈號給的是勝率，風報比給的是賠率，只有一半沒有意義。<br>'
                '<b>風報比</b>＝(目標價 − 現價) ÷ (現價 − SuperTrend 線)。'
                '它會自動偏好「剛起漲」、排除「漲過頭」，篩的是<b>進場時機</b>不是標的好壞。'
                '<b>負值＝現價已高於市場共識目標</b>，燈還亮但上檔空間沒了。<br>'
                '⚠️ 目標價用的是 <b>yfinance 市場共識</b>（多家券商平均），'
                '<b>不是單一投顧報告的目標價</b>——兩者數字差很多，不要互相比較。'
                'ETF 與部分上櫃小型股查無目標價，那些只給「距停損」。<br>'
                '⚠️ 出場仍依原規則（SuperTrend 翻空賣一半／RS 跌破 60MA 全出），'
                '這頁只管進場時機，不是停利建議。</div>')
    body.append(f'<div class="cbsec">⭐ 打點成立<small>亮 ≥{d["combo_min"]} 燈且風報比 ≥ 1，'
                f'共 {len(hit)} 檔</small></div>' + _table(hit))
    body.append(f'<div class="cbsec">COMBO 成立但風報比 &lt; 1<small>技術面共振了，'
                f'但這個價位進場賠率不划算，共 {len(weak)} 檔</small></div>' + _table(weak))
    body.append(f'<div class="cbsec">COMBO 成立但查無目標價<small>只能看距停損，'
                f'共 {len(notgt)} 檔</small></div>' + _table(notgt))
    body.append("</div>")
    return (header("activity", "COMBO 打點",
                   f'四燈共振 × 風報比　·　資料日 {esc(d.get("date",""))}', NAV, "combo")
            + NL.join(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/combo.html")
    a = ap.parse_args()
    if not os.path.exists(RESULT_PATH):
        print(f"找不到 {RESULT_PATH}——先跑 python combo_scan.py")
        return 1
    d = json.load(io.open(RESULT_PATH, encoding="utf-8"))
    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>COMBO 打點</title><style>" + BASE_CSS + CSS + "</style></head><body>"
            + build(d) + "</body></html>")
    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    io.open(a.output, "w", encoding="utf-8", newline=NL).write(html)
    print(f"✅ 已存：{a.output}（{len(html):,} bytes）")
    try:
        os.makedirs(OBIS, exist_ok=True)
        io.open(os.path.join(OBIS, "COMBO打點.html"), "w",
                encoding="utf-8", newline=NL).write(html)
        print(f"✅ 已存：{OBIS}")
    except Exception as e:                              # noqa: BLE001
        print(f"  [warn] obis 副本失敗：{str(e)[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
