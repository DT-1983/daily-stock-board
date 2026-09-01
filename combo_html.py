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
Q = chr(39)

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
.cbfilter{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:14px 0 4px;
  background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 14px}
.fgrp{display:flex;gap:6px;align-items:center}
.fgrp>span{font-size:12px;color:var(--dim);margin-right:2px}
.fbtn{background:var(--line);border:1px solid transparent;border-radius:7px;color:var(--ink);
  cursor:pointer;font-family:inherit;font-size:12px;padding:5px 12px}
.fbtn[aria-pressed=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.fcount{font-size:12px;color:var(--dim);margin-left:auto}
.expbtn{background:none;border:1px solid var(--line);border-radius:6px;color:var(--dim);
  cursor:pointer;font-family:inherit;font-size:11px;padding:2px 7px}
.expbtn:hover{border-color:#4a9eff;color:#93C5FD}
tr.detail>td{padding:0 6px 14px;background:rgba(255,255,255,.02)}
@media(max-width:760px){table.cb th:nth-child(n+8),table.cb td:nth-child(n+8){display:none}}
"""


FILTER_HTML = """<div class="cbfilter">
<div class="fgrp"><span>市場</span>
<button class="fbtn" data-f="mkt" data-v="all" aria-pressed="true">全部</button>
<button class="fbtn" data-f="mkt" data-v="tw">台股</button>
<button class="fbtn" data-f="mkt" data-v="us">美股</button></div>
<div class="fgrp"><span>燈號</span>
<button class="fbtn" data-f="lit" data-v="all" aria-pressed="true">全部</button>
<button class="fbtn" data-f="lit" data-v="3">3 燈以上</button>
<button class="fbtn" data-f="lit" data-v="4">4 燈</button>
<button class="fbtn" data-f="lit" data-v="hit">3 燈 + 風報比≥1</button></div>
<div class="fgrp"><span>來源</span>
<button class="fbtn" data-f="src" data-v="all" aria-pressed="true">全部</button>
<button class="fbtn" data-f="src" data-v="守備清單">守備清單</button>
<button class="fbtn" data-f="src" data-v="持股">持股</button>
<button class="fbtn" data-f="src" data-v="自訂">自訂</button></div>
<span class="fcount" id="fcount"></span></div>"""

FILTER_JS = """<script>
// 三組篩選（市場／燈號／來源）互相 AND。展開的圖表列跟著它的主列一起顯示或隱藏，
// 否則篩掉主列後圖表會孤零零留在畫面上。
var F = {mkt:"all", lit:"all", src:"all"};
function applyFilter(){
  var n = 0;
  document.querySelectorAll("table.cb tr[data-tid]").forEach(function(tr){
    var okM = F.mkt === "all" || tr.dataset.mkt === F.mkt;
    var lit = parseInt(tr.dataset.lit, 10);
    var okL = F.lit === "all"
      || (F.lit === "3" && lit >= 3)
      || (F.lit === "4" && lit >= 4)
      || (F.lit === "hit" && lit >= 3 && tr.dataset.rr === "1");
    var okS = F.src === "all" || (tr.dataset.src || "").split("|").indexOf(F.src) >= 0;
    var show = okM && okL && okS;
    tr.style.display = show ? "" : "none";
    if (show) n++;
    var d = document.getElementById(tr.dataset.tid);
    if (d && !show) d.style.display = "none";
  });
  document.querySelectorAll(".cbsec").forEach(function(sec){
    var t = sec.nextElementSibling;
    if (!t || t.tagName !== "TABLE") return;
    var any = Array.prototype.some.call(t.querySelectorAll("tr[data-tid]"),
                                        function(r){ return r.style.display !== "none"; });
    sec.style.display = any ? "" : "none";
    t.style.display = any ? "" : "none";
  });
  document.getElementById("fcount").textContent = "符合 " + n + " 檔";
}
document.querySelectorAll(".fbtn").forEach(function(b){
  b.addEventListener("click", function(){
    var f = b.dataset.f;
    F[f] = b.dataset.v;
    document.querySelectorAll('.fbtn[data-f="' + f + '"]').forEach(function(x){
      x.setAttribute("aria-pressed", x === b ? "true" : "false");
    });
    applyFilter();
  });
});
applyFilter();
</script>"""


def _ti_css():
    """technical_indicators 的樣式——圖表片段依賴它，不帶進來會整區沒樣式。"""
    try:
        import technical_indicators as ti
        return ti.CSS
    except Exception:                                   # noqa: BLE001
        return ""


def _fmt(v, n=1, suffix=""):
    return "—" if v is None else f"{v:,.{n}f}{suffix}"


def _row_html(r):
    lamps = "".join(f'<span class="lamp {"on" if v else "off"}" title="{esc(k)}"></span>'
                    for k, v in r["lamps"].items())
    rr = r.get("rr")
    if rr is None:
        rrh = '<span class="dimv">無目標價</span>'
    else:
        cls = "pos" if rr >= 1 else ("neg" if rr < 0 else "")
        rrh = f'<span class="{cls}">{rr:,.1f}</span>'
    # 空方時這條線是壓力不是停損：顯示「站上才翻多」而不是「距停損」，
    # 兩者方向相反、意義不同，混在同一欄會讓人誤讀（老墨的版本就分開講）。
    gap = r.get("gap_pct")
    if gap is None:
        gaph = "—"
    elif r.get("bull"):
        gaph = f'<span class="pos">{gap:+.1f}%</span>'
    else:
        gaph = (f'<span class="dimv" title="SuperTrend 空方，這條線是壓力不是停損">'
                f'站上 {r["st_line"]:,.1f} 才翻多（還要 {abs(gap):.1f}%）</span>')
    tid = "d_" + esc(r["ticker"]).replace(".", "_").replace("-", "_")
    btn = ("<button class=" + chr(34) + "expbtn" + chr(34) +
           " onclick=" + chr(34) +
           "var e=document.getElementById(" + Q + tid + Q + ");" +
           "e.style.display=e.style.display==" + Q + "table-row" + Q +
           "?" + Q + "none" + Q + ":" + Q + "table-row" + Q + ";" + chr(34) +
           ">圖</button> ") if r.get("chart") else ""
    import re as _re
    mkt = "tw" if _re.match(r"^[0-9]{4,6}[A-Z]?(\.TWO?)?$", str(r["ticker"])) else "us"
    srcs = "|".join(r.get("src") or [])
    rrok = "1" if (r.get("rr") is not None and r["rr"] >= 1) else "0"
    return (f'<tr data-mkt="{mkt}" data-lit="{r["lit"]}" data-rr="{rrok}" '
            f'data-src="{esc(srcs)}" data-tid="{tid}">'
            f'<td>{btn}<b>{esc(r["ticker"])}</b></td>'
            f'<td>{esc((r.get("name") or "")[:16])}</td>'
            f'<td style="text-align:left">{lamps}</td>'
            f'<td>{r["lit"]}/4</td>'
            f'<td>{_fmt(r["price"])}</td>'
            f'<td>{_fmt(r.get("target"))}</td>'
            f'<td>{rrh}</td><td>{gaph}</td>'
            f'<td>{_fmt(r.get("rs_short"),1,"%")}</td>'
            f'<td class="srcs">{esc("/".join(r.get("src") or []))}</td></tr>'
            + (f'<tr class="detail" id="{tid}" data-mkt="{mkt}" style="display:none">'
               f'<td colspan="10">{r["chart"]}</td></tr>' if r.get("chart") else ""))


def _table(rows):
    if not rows:
        return '<div class="cbnote">這一組目前沒有標的。</div>'
    head = ("<tr><th>代號</th><th>名稱</th><th>燈號</th><th>燈</th><th>現價</th>"
            "<th>市場共識目標</th><th>風報比</th><th>距停損／翻多門檻</th><th>RS60</th><th>來源</th></tr>")
    return ('<table class="cb">' + head
            + "".join(_row_html(r) for r in rows) + "</table>")


def attach_charts(rows, limit=None):
    """把技術面圖表（technical_indicators 那三張，財報卡用的同一套）掛進 COMBO 成立的列。

    ⚠️ 只對 COMBO 成立的產：build() 內部自己打 yfinance，179 檔全產既慢又浪費，
    而沒亮燈的股票本來就不會想點開看。單檔約 23KB，80 檔約 1.8MB——
    跟 rotation.html(5.7MB) 比還好。
    """
    import technical_indicators as ti
    todo = [r for r in rows if r["combo"]]
    if limit:
        todo = todo[:limit]
    print(f"  產技術面圖表 {len(todo)} 檔…")
    ok = 0
    for i, r in enumerate(todo, 1):
        try:
            h = ti.build_html(r.get("symbol") or r["ticker"])
            if h:
                r["chart"] = h
                ok += 1
        except Exception as e:                          # noqa: BLE001
            print(f"    [warn] {r['ticker']} 產圖失敗：{str(e)[:50]}")
        if i % 20 == 0:
            print(f"    …{i}/{len(todo)}")
    print(f"  圖表完成 {ok}/{len(todo)}")
    return rows


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
    body.append(FILTER_HTML)
    body.append(f'<div class="cbsec">⭐ 打點成立<small>亮 ≥{d["combo_min"]} 燈且風報比 ≥ 1，'
                f'共 {len(hit)} 檔</small></div>' + _table(hit))
    body.append(f'<div class="cbsec">COMBO 成立但風報比 &lt; 1<small>技術面共振了，'
                f'但這個價位進場賠率不划算，共 {len(weak)} 檔</small></div>' + _table(weak))
    body.append(f'<div class="cbsec">COMBO 成立但查無目標價<small>只能看距停損，'
                f'共 {len(notgt)} 檔</small></div>' + _table(notgt))
    body.append(FILTER_JS)
    body.append("</div>")
    return (header("activity", "COMBO 打點",
                   f'四燈共振 × 風報比　·　資料日 {esc(d.get("date",""))}', NAV, "combo")
            + NL.join(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/combo.html")
    ap.add_argument("--no-charts", action="store_true", help="不產技術面圖表（快速預覽用）")
    ap.add_argument("--chart-limit", type=int, default=None, help="最多產幾檔圖（測試用）")
    a = ap.parse_args()
    if not os.path.exists(RESULT_PATH):
        print(f"找不到 {RESULT_PATH}——先跑 python combo_scan.py")
        return 1
    d = json.load(io.open(RESULT_PATH, encoding="utf-8"))
    if not a.no_charts:
        attach_charts(d["rows"], limit=a.chart_limit)
    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>COMBO 打點</title><style>" + BASE_CSS + CSS + _ti_css() + "</style></head><body>"
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
