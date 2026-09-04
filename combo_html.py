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

from board_theme import BASE_CSS, header, NAV, esc, LOOKUP_BOX, LOOKUP_CSS  # noqa: E402

RESULT_PATH = "state/combo_result.json"
# 2026-09-05 資料夾整理：路徑一律走 obis_paths，不再各自寫死。
from obis_paths import DAILY as OBIS
NL = chr(10)
Q = chr(39)

CSS = """
.cbwrap{padding:0}   /* 外層已經有 .wrap 限寬置中，這裡不要再限一次 */
/* 2026-09-03 Leo：統計卡縮小 + 跟搜尋框做在同一排（.cbtop 併排,窄螢幕自動換行）*/
.cbtop{display:flex;gap:10px;align-items:stretch;flex-wrap:wrap;margin:12px 0 6px}
.cbtop .lkbox{margin:0;flex:1 1 300px}
.cbstat{display:flex;gap:6px;flex-wrap:wrap;margin:0}
.cbstat div{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:5px 10px;min-width:auto}
.cbstat b{display:block;font-size:15px;line-height:1.15}
.cbstat span{font-size:10px;color:var(--dim)}
.flab2{margin-left:14px}
.cbnote{background:var(--card);border:1px solid var(--line);border-left:3px solid #EAB308;
  border-radius:8px;padding:11px 14px;margin:12px 0;font-size:13px;line-height:1.75;color:var(--dim)}
.cbsec{margin:26px 0 8px;font-size:15px;font-weight:700}
.cbsec small{font-weight:400;color:var(--dim);margin-left:8px}
table.cb{width:100%;border-collapse:collapse;font-size:13px}
table.cb th{text-align:right;padding:8px 6px;color:var(--dim);font-weight:600;
  border-bottom:1px solid var(--line);white-space:nowrap;font-size:12px}
table.cb th:nth-child(-n+4){text-align:left}
table.cb td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
table.cb td:nth-child(-n+4){text-align:left}
table.cb tr:hover td{background:rgba(255,255,255,.03)}
.lamp{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:3px}
.on{background:#22C55E}.off{background:#374151}
.pos{color:#22C55E}.neg{color:#EF4444}.dimv{color:var(--dim)}
.srcs{font-size:11px;color:var(--dim)}
/* 篩選列：沿用 board_theme 的 .ctrl（置頂）+ .seg（市場）+ .sc（圓角籤，帶色點與計數）——
   2026-09-02 Leo：「同步投資網站的設計風格跟按鈕方式」。看板頁就是這一套，這頁原本自己另寫了一組。 */
.cbctrl{display:flex;flex-direction:column;gap:7px}
.frow{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.flab{font-size:11.5px;color:var(--dim);min-width:30px}
.fcount{font-size:12px;color:var(--dim);margin-left:auto}
.sc .fn{color:var(--dim);font-weight:500}
.sc[aria-pressed=true] .fn{color:var(--muted)}
/* 類股象限標籤：四色跟產業輪動頁 QUADRANT_COLOR 完全一致，看兩頁不用重新記顏色 */
.qb{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:5px;
  color:#fff;margin-right:6px;letter-spacing:.3px}
.qsec{font-size:11.5px;color:var(--muted)}
.expbtn{background:none;border:1px solid var(--line);border-radius:6px;color:var(--dim);
  cursor:pointer;font-family:inherit;font-size:11px;padding:2px 7px}
.expbtn:hover{border-color:#4a9eff;color:#93C5FD}
tr.detail>td{padding:0 6px 14px;background:rgba(255,255,255,.02)}
@media(max-width:760px){table.cb th:nth-child(n+9),table.cb td:nth-child(n+9){display:none}
  .qsec{display:none}}
/* 2026-09-03 Leo：工具欄太寬擋住圖 → 本頁專屬縮窄（不動 board_theme 全站標準）。
   主因是 .seg button min-height:38px、.sc 34px，四列疊起來很高。*/
.ctrl{padding:6px 0 5px;margin-bottom:2px}
.cbctrl{gap:4px}
.frow{gap:5px}
.flab{min-width:26px}
.seg{padding:2px}
.seg button{padding:3px 11px;min-height:26px;font-size:12px}
.sc{padding:2px 10px;min-height:24px;font-size:11.5px}
"""

# 象限四色與中文——優先從輪動頁 import，兩頁永遠同色；import 不到（缺套件）才用這份副本
try:
    from industry_rotation import QUADRANT_COLOR as QCOL, QUADRANT_LABEL as QLAB  # noqa: E402
except Exception:                                       # noqa: BLE001
    QCOL = {"leading": "#3987e5", "improving": "#2fbf71", "lagging": "#e5484d", "weakening": "#eda100"}
    QLAB = {"leading": "領先", "improving": "改善", "lagging": "落後", "weakening": "弱化"}
QORDER = ["leading", "improving", "weakening", "lagging"]


def _sc(f, v, label, dot=None, pressed=False):
    """站內標準圓角籤（board_theme .sc）：可帶色點，<b class="fn"> 由 JS 填「選它會剩幾檔」。"""
    d = f'<span class="d2" style="background:{dot}"></span>' if dot else ""
    return (f'<button class="sc" data-f="{f}" data-v="{esc(v)}" aria-pressed="{"true" if pressed else "false"}">'
            f'{d}{esc(label)} <b class="fn"></b></button>')


def filter_html():
    quad = "".join(_sc("quad", q, QLAB[q], QCOL[q]) for q in QORDER)
    # 2026-09-03 Leo：篩選列做成兩排——第一排 市場+燈號、第二排 象限+來源。
    return ('<div class="ctrl cbctrl">'
            '<div class="frow"><span class="flab">市場</span>'
            '<div class="seg" role="group" aria-label="切換市場">'
            '<button data-f="mkt" data-v="all" aria-pressed="true">全部</button>'
            '<button data-f="mkt" data-v="tw" aria-pressed="false">台股</button>'
            '<button data-f="mkt" data-v="us" aria-pressed="false">美股</button></div>'
            '<span class="flab flab2">燈號</span>'
            + _sc("lit", "all", "全部", pressed=True) + _sc("lit", "3", "3 燈以上")
            + _sc("lit", "4", "4 燈") + _sc("lit", "hit", "⭐ 打點（3 燈 + 風報比 ≥ 1）")
            + '<span class="fcount" id="fcount"></span></div>'
            '<div class="frow"><span class="flab">象限</span>'
            + _sc("quad", "all", "全部", pressed=True) + quad + _sc("quad", "none", "無分類")
            + '<span class="flab flab2">來源</span>'
            + _sc("src", "all", "全部", pressed=True) + _sc("src", "守備清單", "守備清單")
            + _sc("src", "持股", "持股") + _sc("src", "自訂", "自訂")
            + '</div></div>')

FILTER_JS = """<script>
// 四組篩選（市場／燈號／象限／來源）互相 AND。展開的圖表列跟著它的主列一起顯示或隱藏，
// 否則篩掉主列後圖表會孤零零留在畫面上。
// 每顆籤上的計數＝「在其他三組目前選擇下，改選這顆會剩幾檔」——跟看板頁的計數同一種語意。
var F = {mkt:"all", lit:"all", quad:"all", src:"all"};
var ROWS = Array.prototype.slice.call(document.querySelectorAll("table.cb tr[data-tid]"));
function match(tr, f, v){
  if (v === "all") return true;
  if (f === "mkt")  return tr.dataset.mkt === v;
  if (f === "quad") return (tr.dataset.quad || "none") === v;
  if (f === "src")  return (tr.dataset.src || "").split("|").indexOf(v) >= 0;
  if (f === "lit"){
    var lit = parseInt(tr.dataset.lit, 10);
    if (v === "3") return lit >= 3;
    if (v === "4") return lit >= 4;
    if (v === "hit") return lit >= 3 && tr.dataset.rr === "1";
  }
  return true;
}
function rowOk(tr, over){
  for (var f in F){
    var v = (over && over.f === f) ? over.v : F[f];
    if (!match(tr, f, v)) return false;
  }
  return true;
}
function applyFilter(){
  var n = 0;
  ROWS.forEach(function(tr){
    var show = rowOk(tr, null);
    tr.style.display = show ? "" : "none";
    if (show) n++;
    var d = document.getElementById(tr.dataset.tid);
    if (d && !show) d.style.display = "none";
  });
  document.querySelectorAll(".cbsec").forEach(function(sec){
    var t = sec.nextElementSibling;
    if (!t || t.tagName !== "TABLE") return;
    var any = t.querySelectorAll("tr[data-tid]").length &&
      Array.prototype.some.call(t.querySelectorAll("tr[data-tid]"),
                                function(r){ return r.style.display !== "none"; });
    sec.style.display = any ? "" : "none";
    t.style.display = any ? "" : "none";
  });
  document.getElementById("fcount").textContent = "符合 " + n + " 檔";
  document.querySelectorAll("[data-f]").forEach(function(b){
    var el = b.querySelector(".fn");
    if (!el) return;
    var c = 0;
    ROWS.forEach(function(tr){ if (rowOk(tr, {f: b.dataset.f, v: b.dataset.v})) c++; });
    el.textContent = c;
  });
}
document.querySelectorAll("[data-f]").forEach(function(b){
  b.addEventListener("click", function(){
    var f = b.dataset.f;
    F[f] = b.dataset.v;
    document.querySelectorAll('[data-f="' + f + '"]').forEach(function(x){
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
    # ⚠️ 一次點擊到位：原本點「圖」只展開這一列，裡面的圖表還是收合的
    #    （technical_indicators 自帶「展開圖表 ▾」），等於要點兩次才看得到圖。
    #    Leo 回報「無法點進去看細項的圖表」就是卡在這一層。
    #    展開時順便把內層 toggle 也按下去，只在它還沒展開時按（避免又收起來）。
    _js = ("var e=document.getElementById(" + Q + tid + Q + ");"
           "var open=e.style.display!=" + Q + "table-row" + Q + ";"
           "e.style.display=open?" + Q + "table-row" + Q + ":" + Q + "none" + Q + ";"
           "if(open){var t=e.querySelector(" + Q + ".techtoggle" + Q + ");"
           "var c=e.querySelector(" + Q + ".techcharts" + Q + ");"
           "if(t&&c&&c.style.display==" + Q + "none" + Q + "){t.click();}}"
           "this.textContent=open?" + Q + "▾ 收合" + Q + ":" + Q + "▸ 圖表" + Q + ";")
    btn = ("<button class=" + chr(34) + "expbtn" + chr(34) +
           " onclick=" + chr(34) + _js + chr(34) +
           ">▸ 圖表</button> ") if r.get("chart") else ""
    import re as _re
    mkt = "tw" if _re.match(r"^[0-9]{4,6}[A-Z]?(\.TWO?)?$", str(r["ticker"])) else "us"
    srcs = "|".join(r.get("src") or [])
    rrok = "1" if (r.get("rr") is not None and r["rr"] >= 1) else "0"
    # 類股象限（純顯示）：標籤顯示 60 日象限，滑鼠停上去看 20/60/120 三週期＋細分類
    q = r.get("quad") or {}
    q60 = q.get("60")
    if q60 in QLAB:
        tip = "　".join(f"{n}日 {QLAB.get(q.get(n), '—')}" for n in ("20", "60", "120"))
        tip += f"｜{r.get('industry') or ''}｜輪動快照 {r.get('quad_date') or ''}"
        qh = (f'<span class="qb" style="background:{QCOL[q60]}" title="{esc(tip)}">{QLAB[q60]}</span>'
              f'<span class="qsec">{esc(r.get("sector_zh") or "")}</span>')
        qv = q60
    else:
        qh = '<span class="dimv" title="ETF 或查無類股分類">—</span>'
        qv = "none"
    return (f'<tr data-mkt="{mkt}" data-lit="{r["lit"]}" data-rr="{rrok}" data-quad="{qv}" '
            f'data-src="{esc(srcs)}" data-tid="{tid}">'
            f'<td>{btn}<b>{esc(r["ticker"])}</b></td>'
            f'<td>{esc((r.get("name") or "")[:16])}</td>'
            f'<td>{qh}</td>'
            f'<td>{lamps}</td>'
            f'<td>{r["lit"]}/4</td>'
            f'<td>{_fmt(r["price"])}</td>'
            f'<td>{_fmt(r.get("target"))}</td>'
            f'<td>{rrh}</td><td>{gaph}</td>'
            f'<td>{_fmt(r.get("rs_short"),1,"%")}</td>'
            f'<td class="srcs">{esc("/".join(r.get("src") or []))}</td></tr>'
            + (f'<tr class="detail" id="{tid}" data-mkt="{mkt}" style="display:none">'
               f'<td colspan="11">{r["chart"]}</td></tr>' if r.get("chart") else ""))


def _table(rows):
    if not rows:
        return '<div class="cbnote">這一組目前沒有標的。</div>'
    head = ("<tr><th>代號</th><th>名稱</th><th>類股象限</th><th>燈號</th><th>燈</th><th>現價</th>"
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
    body.append('<div class="cbtop"><div class="cbstat">'
                f'<div><b>{len(rows)}</b><span>掃描母體</span></div>'
                f'<div><b>{len(ok)}</b><span>COMBO 成立（≥{d["combo_min"]} 燈）</span></div>'
                f'<div><b style="color:#22C55E">{len(hit)}</b><span>⭐ 打點成立（且風報比 ≥ 1）</span></div>'
                f'<div><b style="color:#EF4444">{sum(1 for r in ok if (r.get("rr") or 0) < 0)}</b>'
                '<span>現價已超過共識目標</span></div></div>'
                + LOOKUP_BOX + '</div>')
    body.append(filter_html())
    body.append(f'<div class="cbsec">⭐ 打點成立<small>亮 ≥{d["combo_min"]} 燈且風報比 ≥ 1，'
                f'共 {len(hit)} 檔</small></div>' + _table(hit))
    body.append(f'<div class="cbsec">COMBO 成立但風報比 &lt; 1<small>技術面共振了，'
                f'但這個價位進場賠率不划算，共 {len(weak)} 檔</small></div>' + _table(weak))
    body.append(f'<div class="cbsec">COMBO 成立但查無目標價<small>只能看距停損，'
                f'共 {len(notgt)} 檔</small></div>' + _table(notgt))
    body.append(FILTER_JS)
    # 2026-09-01 Leo：說明移到最下面——一進頁面應該先看到訊號，
    #                 不是先讀一大段規則。
    body.append('<div class="cbsec" style="margin-top:34px">📖 這頁怎麼看</div>')
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
                '<b>類股象限</b>＝這檔所屬類股（TradingView 分類）在<a href="rotation.html">產業輪動圖</a>'
                '的位置，顯示 <b>60 日</b>：'
                + "　".join(f'<span class="qb" style="background:{QCOL[q]}">{QLAB[q]}</span>' for q in QORDER)
                + '（滑鼠停在標籤上看 20／60／120 三週期）。'
                '<b>只是參考欄位，不是第五個燈</b>——燈四已經是個股層級的相對強度，'
                '而且三個週期常常互相打架（9/1 美股 20 個類股只有 3 個三週期一致），拿它當門檻等於在賭週期。'
                '要不要升級成門檻，等進出燈號倉跑出「落後象限的部位特別虧」這種證據再說。'
                '資料來源：個股所屬類股用 TradingView 篩選器按代號查（跟產業輪動頁同一個來源，'
                '所以類股名稱兩頁一定對得上），每 30 天重查一次；象限取自輪動頁最新快照。'
                'ETF 查無類股分類，顯示「—」。<br>'
                '⚠️ 出場仍依原規則（SuperTrend 翻空賣一半／RS 跌破 60MA 全出），'
                '這頁只管進場時機，不是停利建議。</div>')
    body.append("</div>")
    return (header("lamp", "進出燈號",
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
            "<title>進出燈號</title>"
            # 🔴 一定要載 Chart.js：technical_indicators 產的是「畫圖的程式碼」，
            #    不是圖片。少了這行整頁 240 個 Chart() 全部 ReferenceError，
            #    版面看起來正常但圖表區永遠空白（財報卡有載，這頁原本漏了）。
            "<script src=" + chr(34) + "https://cdn.jsdelivr.net/npm/chart.js@4"
            + chr(34) + "></script>"
            # 2026-09-02：雙重颱風改真的蠟燭圖，要靠這個外掛（Chart.js 官方組織維護，MIT）
            "<script src=" + chr(34)
            + "https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js"
            + chr(34) + "></script>"
            "<script src=" + chr(34) + "https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js" + chr(34) + "></script>"
            "<script src=" + chr(34)
            + "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js"
            + chr(34) + "></script>"
            "<style>" + BASE_CSS + CSS + LOOKUP_CSS + _ti_css() + "</style></head><body>"
            # header 必須包在 .wrap 裡（首頁就是這樣做的），否則標題會貼齊視窗
            # 左緣、跟下面的內容對不齊——.wrap 才有 max-width:1100px + 置中。
            "<div class=" + chr(34) + "wrap" + chr(34) + ">"
            + build(d) + "</div></body></html>")
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
