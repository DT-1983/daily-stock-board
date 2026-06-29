"""策略賽馬看板：8 模擬倉（7 鏈 + 巴菲特）淨值走勢 + 報酬排行。

讀 portfolios.json → 出 docs/portfolios.html（Chart.js 賽馬線圖 + 排行表 + 持股展開）。
用法:python portfolio_html.py [-o docs/portfolios.html]
"""
import os
import json
import html as _html
import argparse
from datetime import datetime

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"
PAGES_URL = "https://dt-1983.github.io/daily-stock-board/"
ICON = {
    "AI 伺服器": "🖥️", "矽光子/光通訊": "🔆", "低軌衛星": "🛰️", "太陽能": "☀️",
    "Bitcoin→AI 機房": "₿", "AI 電力/核能": "⚡", "機器人": "🤖", "巴菲特價值": "🏛️",
}
COLORS = ["#4a9eff", "#3ddc84", "#ff9b5c", "#c98bff", "#ffd479",
          "#5ce0d8", "#ff7676", "#9aa0a6"]


def esc(s):
    return _html.escape(str(s if s is not None else ""))


CSS = """
*{box-sizing:border-box}
body{font-family:"Microsoft JhengHei","PingFang TC",-apple-system,sans-serif;margin:0;
 background:#0f1115;color:#e6e6e6;line-height:1.55;font-size:15px}
.wrap{max-width:920px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:6px 0}.sub{color:#9aa0a6;font-size:13px}a{color:#6db3ff}
.card{background:#1a1d23;border:1px solid #2a2e35;border-radius:10px;padding:12px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #2a2e35;padding:8px 6px;text-align:right}
th{color:#9aa0a6;font-weight:600}td.l,th.l{text-align:left}
.pos{color:#3ddc84;font-weight:700}.neg{color:#ff7676;font-weight:700}.flat{color:#9aa0a6}
.medal{font-size:16px}
details{margin:2px 0}summary{cursor:pointer;color:#bcd2ff;font-size:13px}
.hold{font-size:12px;color:#9aa0a6;padding:4px 0 4px 18px;word-break:break-all}
.legend{font-size:12px;color:#9aa0a6;margin:8px 0;display:flex;flex-wrap:wrap;gap:12px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
"""


def cls(ret):
    return "pos" if ret > 0 else ("neg" if ret < 0 else "flat")


def build(state):
    pfs = state["portfolios"]
    rank = sorted(pfs.items(), key=lambda kv: -kv[1]["ret"])
    inception = state.get("inception", "?")
    updated = state.get("updated", "?")
    days = 0
    try:
        days = (datetime.strptime(updated, "%Y-%m-%d") -
                datetime.strptime(inception, "%Y-%m-%d")).days
    except Exception:
        pass

    # Chart.js 資料：用聯集日期軸
    all_dates = sorted({d for pf in pfs.values() for d, _ in pf["history"]})
    datasets = []
    color_map = {}
    for i, (name, _) in enumerate(rank):
        color_map[name] = COLORS[i % len(COLORS)]
    for name, pf in pfs.items():
        hmap = {d: v for d, v in pf["history"]}
        series = [hmap.get(d) for d in all_dates]
        # 補洞（前值填充）
        last = 100
        filled = []
        for v in series:
            if v is not None:
                last = v
            filled.append(last)
        datasets.append({"label": f"{ICON.get(name,'')} {name}",
                         "data": filled, "borderColor": color_map[name],
                         "fill": False, "tension": 0.2, "borderWidth": 2,
                         "pointRadius": 0})

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    rows = []
    for i, (name, pf) in enumerate(rank):
        m = medals.get(i, f"{i+1}")
        ic = ICON.get(name, "")
        holds = "、".join(pf["holdings"][:30]) + ("…" if len(pf["holdings"]) > 30 else "")
        rows.append(
            f'<tr><td class="l"><span class="medal">{m}</span> {ic} <b>{esc(name)}</b></td>'
            f'<td>{pf["nav"]:.2f}</td>'
            f'<td class="{cls(pf["ret"])}">{pf["ret"]:+.2f}%</td>'
            f'<td>{len(pf["holdings"])}</td></tr>'
            f'<tr><td colspan="4" class="l"><details><summary>持股 {len(pf["holdings"])} 檔</summary>'
            f'<div class="hold">{esc(holds)}</div></details></td></tr>'
        )

    legend = "".join(
        f'<span><span class="dot" style="background:{color_map[n]}"></span>{ICON.get(n,"")} {esc(n)}</span>'
        for n, _ in rank)

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>策略賽馬 · 模擬倉</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script><style>{CSS}</style></head>
<body><div class="wrap">
<h1>🏇 策略賽馬 — 7 產業鏈 vs 巴菲特價值</h1>
<div class="sub">起始 {esc(inception)}（第 {days} 天）· 更新 {date} · 等權重報酬指數（起始 100，免換匯）·
 每週調倉 · <a href="{PAGES_URL}">← 看板</a></div>

<div class="card"><canvas id="race" height="150"></canvas>
<div class="legend">{legend}</div></div>

<div class="card">
<table><tr><th class="l">模擬倉</th><th>淨值</th><th>報酬</th><th>持股</th></tr>
{''.join(rows)}
</table>
</div>
<p class="sub">玩法：每條產業鏈、巴菲特法各開一個紙上倉，等權重買、每週跟清單調倉。
跑一段時間看誰賺最多 → 驗證哪套篩選邏輯真的有效。報酬用各股本地幣別%算（美股美元、台股台幣），不受匯率干擾。</p>
</div>
<script>
new Chart(document.getElementById('race'),{{type:'line',
 data:{{labels:{json.dumps(all_dates)},datasets:{json.dumps(datasets, ensure_ascii=False)}}},
 options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
  plugins:{{legend:{{display:false}}}},
  scales:{{y:{{grid:{{color:'#2a2e35'}},ticks:{{color:'#9aa0a6'}}}},
           x:{{grid:{{display:false}},ticks:{{color:'#9aa0a6',maxTicksLimit:8}}}}}}}}}});
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/portfolios.html")
    args = ap.parse_args()
    if not os.path.exists("portfolios.json"):
        print("無 portfolios.json，先跑 paper_portfolio.py init")
        return
    state = json.load(open("portfolios.json", encoding="utf-8"))
    html = build(state)
    for out in [args.output, os.path.join(OBIS, "策略賽馬模擬倉.html")]:
        try:
            if os.path.dirname(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "w", encoding="utf-8").write(html)
            print(f"✅ 已存:{out}")
        except Exception as e:
            print(f"⚠️ 寫 {out} 失敗:{e}")


if __name__ == "__main__":
    main()
