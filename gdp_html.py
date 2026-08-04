"""GDP 觀察頁 → docs/gdp.html

洪瑞泰的 GDP 用法：GDP 高點賣股票、不買股票（低點反之）。
本頁只做「提醒燈」——已定案不接任何買賣訊號、不做自動擇時。

讀 gdp_data.json（gdp_fetch.py 產出），實際值實線、預測值虛線，
自動標高點狀態：尚未到頂（綠）／接近高點（黃）／已過高點（紅）。

用法：python gdp_html.py [-o docs/gdp.html]
"""
import os
import sys
import json
import argparse
from datetime import datetime

from board_theme import BASE_CSS, header, esc, NAV

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_STYLE = {
    "尚未到頂": ("#22C55E", "高點還在前面，依洪瑞泰邏輯尚可持股"),
    "接近高點": ("#EAB308", "最新一季就是高點——警戒區：不買股票、考慮分批賣"),
    "已過高點": ("#EF4444", "高點已過、成長下坡——洪瑞泰：GDP 高點賣股票"),
    "無資料": ("#64748B", "資料不足"),
}

CSS_EXTRA = """
.glights{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.glight{flex:1;min-width:250px;background:var(--surface);border:1px solid var(--line);
 border-radius:12px;padding:15px 16px}
.glight .flag{font-size:13px;font-weight:700;color:var(--muted)}
.glight .st{font-size:21px;font-weight:800;margin:6px 0 3px;display:flex;align-items:center;gap:8px}
.glight .st i{width:11px;height:11px;border-radius:50%;display:inline-block;flex-shrink:0}
.glight .why{font-size:12.5px;color:var(--muted);line-height:1.6}
.glight .pk{font-size:12px;color:var(--dim);margin-top:6px}
.gchart{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px;margin:12px 0}
.gchart h2{font-size:14.5px;font-weight:700;margin-bottom:4px}
.gchart .meta{font-size:11.5px;color:var(--dim);margin-bottom:8px}
.gcbox{height:220px}
.gtable{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:10px}
.gtable th{color:var(--dim);font-weight:600;text-align:right;padding:6px 8px;
 border-bottom:1px solid var(--line);font-size:11px}
.gtable th:first-child,.gtable td:first-child{text-align:left}
.gtable td{padding:6px 8px;border-bottom:1px solid var(--line2);text-align:right}
.gtable tr:last-child td{border-bottom:0}
.ftag{font-size:10px;color:#93C5FD;background:#1E3A5F;padding:1px 6px;border-radius:4px;margin-left:5px}
"""


def light(flag, name, pk):
    col, why = STATUS_STYLE.get(pk["status"], STATUS_STYLE["無資料"])
    peak = f'高點：{esc(pk.get("peak_period") or "—")}' if pk.get("peak_period") else ""
    return (f'<div class="glight"><div class="flag">{flag} {esc(name)}</div>'
            f'<div class="st"><i style="background:{col}"></i>'
            f'<span style="color:{col}">{esc(pk["status"])}</span></div>'
            f'<div class="why">{esc(why)}</div>'
            f'<div class="pk">{peak}（近 8 季實際＋預測合併判定）</div></div>')


def chart_block(key, title, unit_note, d, extra_meta=""):
    act, fc = d["actual"], d["forecast"]
    last = act[-1]["period"] if act else ""
    fut = [f for f in fc if f["period"] > last]
    labels = [a["period"] for a in act] + [f["period"] for f in fut]
    a_vals = [a["value"] for a in act] + [None] * len(fut)
    # 預測線從最後一個實際點接出去，視覺上連續
    f_vals = [None] * (len(act) - 1) + ([act[-1]["value"]] if act else []) + [f["value"] for f in fut]
    rows = "".join(
        f'<tr><td>{esc(a["period"])}</td><td class="num">{a["value"]:+.2f}%</td></tr>'
        for a in act[-6:]) + "".join(
        f'<tr><td>{esc(f["period"])}<span class="ftag">預測</span></td>'
        f'<td class="num">{f["value"]:+.2f}%</td></tr>' for f in fut)
    cfg = {"labels": labels, "actual": a_vals, "forecast": f_vals}
    return (f'<div class="gchart"><h2>{title}</h2>'
            f'<div class="meta">{unit_note}{extra_meta}</div>'
            f'<div class="gcbox"><canvas id="c_{key}"></canvas></div>'
            f'<table class="gtable"><tr><th>季度</th><th>成長率</th></tr>{rows}</table></div>'), cfg


def build(d):
    us_light = light("🇺🇸", "美國", d["peak"]["us"])
    tw_light = light("🇹🇼", "台灣", d["peak"]["tw"])

    asof = d["tw"].get("forecast_asof")
    annual = d["tw"].get("annual") or {}
    tw_meta = ""
    if asof:
        tw_meta = f' · 預測＝主計總處 {esc(asof)} 新聞稿'
    if annual:
        tw_meta += "".join(f' · {y} 全年預測 {v:+.2f}%' for y, v in sorted(annual.items()))

    us_html, us_cfg = chart_block(
        "us", "🇺🇸 美國實質 GDP", "季增年率 SAAR（美國慣例口徑）· 實際＝FRED · 預測＝Philly Fed SPF 中位數", d["us"])
    tw_html, tw_cfg = chart_block(
        "tw", "🇹🇼 台灣實質 GDP", "年增率 YoY（台灣慣例口徑）· 實際＝主計總處", d["tw"], tw_meta)

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>GDP 觀察</title>
<style>{BASE_CSS}{CSS_EXTRA}</style></head><body><div class="wrap">
{header("gdp", "GDP 觀察", f"洪瑞泰：GDP 高點賣股票、不買股票 · 更新 {esc(d['updated'])}", NAV, "gdp")}
<div class="glights">{us_light}{tw_light}</div>
<div class="note">
<b>怎麼用</b>：洪瑞泰把 GDP 成長率當「大盤溫度計」——成長率衝到高點時市場最熱，該賣不該買；
高點過後成長下坡，更不是進場時機。本頁只做提醒燈，<b>不接任何自動買賣</b>（已定案不用 GDP 擇時）。<br>
<b>口徑注意</b>：美國用季增年率（SAAR）、台灣用年增率（YoY），是各自的官方慣例，兩張圖數字不能互比。<br>
<b>高點判定</b>：近 8 季實際值＋未來預測合併取最大值——在未來＝尚未到頂、是最新季＝接近高點、在過去＝已過高點。
</div>
{us_html}{tw_html}
<p class="sub" style="margin-top:20px">產生於 {datetime.now():%Y-%m-%d %H:%M} ·
資料源 FRED / Philly Fed SPF / 主計總處 nstatdb ·
台灣預測為手動維護（主計總處每季新聞稿），過期會自動推 Telegram 提醒</p>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
const CFG={{us:{json.dumps(us_cfg)},tw:{json.dumps(tw_cfg)}}};
for(const k of ['us','tw']){{
 const c=CFG[k];
 new Chart(document.getElementById('c_'+k),{{type:'line',
  data:{{labels:c.labels,datasets:[
   {{label:'實際',data:c.actual,borderColor:'#3B82F6',backgroundColor:'#3B82F620',
    borderWidth:2,pointRadius:2.5,fill:true,tension:.25}},
   {{label:'預測',data:c.forecast,borderColor:'#EAB308',borderDash:[6,4],
    borderWidth:2,pointRadius:2.5,pointStyle:'rectRot',tension:.25}}]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
   plugins:{{legend:{{labels:{{color:'#94A3B8',boxWidth:18,font:{{size:11}}}}}},
    tooltip:{{callbacks:{{label:x=>x.dataset.label+' '+(x.parsed.y==null?'—':x.parsed.y.toFixed(2)+'%')}}}}}},
   scales:{{x:{{ticks:{{color:'#64748B',font:{{size:10}},maxRotation:45}},grid:{{color:'#1E293B'}}}},
    y:{{ticks:{{color:'#64748B',font:{{size:10}},callback:v=>v+'%'}},grid:{{color:'#1E293B'}}}}}}}}}});
}}
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/gdp.html")
    args = ap.parse_args()
    src = os.path.join(HERE, "gdp_data.json")
    if not os.path.exists(src):
        print("無 gdp_data.json，先跑 python gdp_fetch.py")
        return
    d = json.load(open(src, encoding="utf-8"))
    html = build(d)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    open(args.output, "w", encoding="utf-8").write(html)
    print(f"✅ 已存 {args.output}")


if __name__ == "__main__":
    main()
