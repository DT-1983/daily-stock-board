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
.gstrip{display:flex;gap:6px;margin-top:12px;overflow-x:auto;padding-bottom:4px;
 scrollbar-width:thin}
.gcell{flex:1;min-width:76px;background:var(--card);border:1px solid var(--line);
 border-radius:9px;padding:8px 6px;text-align:center}
.gcell.fc{border-style:dashed;border-color:#EAB30866}
.gcell .gq{color:var(--dim);font-size:10.5px;letter-spacing:.2px;white-space:nowrap}
.gcell .gvv{font-size:14.5px;font-weight:700;margin-top:3px}
.gcell.fc .gvv{color:#EAB308}
.gcell .gt{font-size:9px;color:#EAB308;margin-top:2px}
"""


def light(flag, name, pk, dd):
    # flag 用純文字（🇺🇸/🇹🇼 emoji 在 Windows 會退化成小寫字母 us/tw）
    col, why = STATUS_STYLE.get(pk["status"], STATUS_STYLE["無資料"])
    # 數字鏈：高點 xx% → 最新 xx%（· 下季預測 xx%）——用戶要求看得到具體數字
    act, fc = dd.get("actual") or [], dd.get("forecast") or []
    vals = {a["period"]: a["value"] for a in act}
    vals.update({f["period"]: f["value"] for f in fc if f["period"] not in vals})
    parts = []
    pp = pk.get("peak_period")
    if pp and pp in vals:
        parts.append(f'高點 {pp} <b>{vals[pp]:+.2f}%</b>')
    if act:
        a = act[-1]
        tag = "概估 " if a.get("est") else ""
        if a["period"] != pp or tag:
            parts.append(f'最新 {a["period"]} {tag}<b>{a["value"]:+.2f}%</b>')
        nxt = next((f for f in fc if f["period"] > a["period"]), None)
        if nxt:
            parts.append(f'{nxt["period"]} 預測 <b>{nxt["value"]:+.2f}%</b>')
    chain = " → ".join(parts) if parts else "—"
    return (f'<div class="glight"><div class="flag"><b>{esc(flag)}</b> {esc(name)}</div>'
            f'<div class="st"><i style="background:{col}"></i>'
            f'<span style="color:{col}">{esc(pk["status"])}</span></div>'
            f'<div class="why">{esc(why)}</div>'
            f'<div class="pk">{chain}<br>（近 8 季實際＋預測合併判定）</div></div>')


def chart_block(key, title, unit_note, d, extra_meta=""):
    # 「還沒有正式實際值」的（概估、預測）一律走黃色虛線組（用戶 2026-08-04 指示）
    act, fc = d["actual"], d["forecast"]
    conf = [a for a in act if not a.get("est")]          # 正式實際值（藍實線）
    last_any = act[-1]["period"] if act else ""
    pending = ([{**a, "tag": "概估"} for a in act if a.get("est")] +
               [{**f, "tag": "預測"} for f in fc if f["period"] > last_any])
    labels = [a["period"] for a in conf] + [p["period"] for p in pending]
    a_vals = [a["value"] for a in conf] + [None] * len(pending)
    # 黃虛線從最後一個正式實際點接出去，視覺上連續
    f_vals = [None] * (len(conf) - 1) + ([conf[-1]["value"]] if conf else []) + \
             [p["value"] for p in pending]

    def _short(p):  # 2026-Q1 → 26Q1，橫排時省寬度
        return p[2:4] + p[5:]

    cells = "".join(
        f'<div class="gcell"><div class="gq">{esc(_short(a["period"]))}</div>'
        f'<div class="gvv num">{a["value"]:+.2f}</div></div>'
        for a in conf[-6:]) + "".join(
        f'<div class="gcell fc"><div class="gq">{esc(_short(p["period"]))}</div>'
        f'<div class="gvv num">{p["value"]:+.2f}</div><div class="gt">{p["tag"]}</div></div>'
        for p in pending)
    cfg = {"labels": labels, "actual": a_vals, "forecast": f_vals}
    return (f'<div class="gchart"><h2>{title}</h2>'
            f'<div class="meta">{unit_note}{extra_meta}</div>'
            f'<div class="gcbox"><canvas id="c_{key}"></canvas></div>'
            f'<div class="gstrip">{cells}</div></div>'), cfg


def build(d):
    us_light = light("US", "美國", d["peak"]["us"], d["us"])
    tw_light = light("TW", "台灣", d["peak"]["tw"], d["tw"])

    asof = d["tw"].get("forecast_asof")
    annual = d["tw"].get("annual") or {}
    tw_meta = ""
    if asof:
        tw_meta = f' · 預測＝主計總處 {esc(asof)} 新聞稿'
    if annual:
        tw_meta += "".join(f' · {y} 全年預測 {v:+.2f}%' for y, v in sorted(annual.items()))

    us_html, us_cfg = chart_block(
        "us", "US 美國實質 GDP", "季增年率 SAAR（美國慣例口徑）· 實際＝FRED · 預測＝Philly Fed SPF 中位數", d["us"])
    tw_html, tw_cfg = chart_block(
        "tw", "TW 台灣實質 GDP", "年增率 YoY（台灣慣例口徑）· 實際＝主計總處", d["tw"], tw_meta)

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
