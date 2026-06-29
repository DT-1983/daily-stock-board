"""策略賽馬看板：產業鏈全 vs 巴菲特30（2 主倉對決）+ 7 鏈明細。

讀 portfolios.json → docs/portfolios.html（Chart.js 賽馬線圖 + $ 排行 + 持股展開）。
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
    "產業鏈全": "🏭", "巴菲特價值": "🏛️",
    "AI 伺服器": "🖥️", "矽光子/光通訊": "🔆", "低軌衛星": "🛰️", "太陽能": "☀️",
    "Bitcoin→AI 機房": "₿", "AI 電力/核能": "⚡", "機器人": "🤖",
}
COLORS = ["#4a9eff", "#3ddc84", "#ff9b5c", "#c98bff", "#ffd479",
          "#5ce0d8", "#ff7676", "#9aa0a6", "#8ab4f8"]


def esc(s):
    return _html.escape(str(s if s is not None else ""))


CSS = """
*{box-sizing:border-box}
body{font-family:"Microsoft JhengHei","PingFang TC",-apple-system,sans-serif;margin:0;
 background:#0f1115;color:#e6e6e6;line-height:1.55;font-size:15px}
.wrap{max-width:920px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:6px 0}h2{font-size:16px;margin:18px 0 6px}.sub{color:#9aa0a6;font-size:13px}a{color:#6db3ff}
.card{background:#1a1d23;border:1px solid #2a2e35;border-radius:10px;padding:12px;margin:12px 0}
.vs{display:flex;gap:12px;margin:12px 0}
.vs .box{flex:1;background:#1a1d23;border:1px solid #2a2e35;border-radius:12px;padding:14px;text-align:center}
.vs .nm{font-size:15px;font-weight:700}.vs .val{font-size:26px;font-weight:800;margin:6px 0}
.vs .ret{font-size:15px;font-weight:700}.vs .sub2{font-size:12px;color:#9aa0a6}
.win{border-color:#3ddc84;box-shadow:0 0 0 1px #3ddc84}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #2a2e35;padding:8px 6px;text-align:right}
th{color:#9aa0a6;font-weight:600}td.l,th.l{text-align:left}
.pos{color:#3ddc84;font-weight:700}.neg{color:#ff7676;font-weight:700}.flat{color:#9aa0a6}
.medal{font-size:15px}
details{margin:2px 0}summary{cursor:pointer;color:#bcd2ff;font-size:13px}
.hold{font-size:12px;color:#9aa0a6;padding:4px 0 4px 18px;word-break:break-all}
.legend{font-size:12px;color:#9aa0a6;margin:8px 0;display:flex;flex-wrap:wrap;gap:12px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
"""


def cls(r):
    return "pos" if r > 0 else ("neg" if r < 0 else "flat")


def usd(v):
    return f"${v:,.0f}"


def build(state):
    pfs = state["portfolios"]
    base = state.get("base", 10000)
    main = state.get("main", [])
    inception = state.get("inception", "?")
    updated = state.get("updated", "?")
    try:
        days = (datetime.strptime(updated, "%Y-%m-%d") -
                datetime.strptime(inception, "%Y-%m-%d")).days
    except Exception:
        days = 0

    # 賽馬線圖：聯集日期，前值填充
    all_dates = sorted({d for pf in pfs.values() for d, _ in pf["history"]})
    order = list(main) + [n for n in pfs if n not in main]
    color_map = {n: COLORS[i % len(COLORS)] for i, n in enumerate(order)}
    datasets = []
    for n in order:
        pf = pfs[n]
        hmap = {d: v for d, v in pf["history"]}
        last, filled = base, []
        for d in all_dates:
            if hmap.get(d) is not None:
                last = hmap[d]
            filled.append(last)
        is_main = n in main
        datasets.append({"label": f"{ICON.get(n,'')} {n}", "data": filled,
                         "borderColor": color_map[n], "fill": False, "tension": 0.2,
                         "borderWidth": 3 if is_main else 1.5,
                         "borderDash": [] if is_main else [4, 3], "pointRadius": 0})

    # 2 主倉對決卡
    vs_html = ""
    if len(main) >= 2:
        a, b = pfs[main[0]], pfs[main[1]]
        wa = "win" if a["ret"] >= b["ret"] else ""
        wb = "win" if b["ret"] > a["ret"] else ""
        def box(name, pf, w):
            return (f'<div class="box {w}"><div class="nm">{ICON.get(name,"")} {esc(name)}</div>'
                    f'<div class="val">{usd(pf["nav"])}</div>'
                    f'<div class="ret {cls(pf["ret"])}">{pf["ret"]:+.2f}%</div>'
                    f'<div class="sub2">{len(pf["holdings"])} 檔 · 起始 {usd(base)}</div></div>')
        vs_html = f'<div class="vs">{box(main[0],a,wa)}<div style="align-self:center;font-weight:800;color:#9aa0a6">VS</div>{box(main[1],b,wb)}</div>'

    # 7 鏈明細排行
    chains = [(n, pf) for n, pf in pfs.items() if n not in main]
    chains.sort(key=lambda kv: -kv[1]["ret"])
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    rows = []
    for i, (n, pf) in enumerate(chains):
        m = medals.get(i, f"{i+1}")
        holds = "、".join(pf["holdings"][:30]) + ("…" if len(pf["holdings"]) > 30 else "")
        rows.append(
            f'<tr><td class="l"><span class="medal">{m}</span> {ICON.get(n,"")} <b>{esc(n)}</b></td>'
            f'<td>{usd(pf["nav"])}</td><td class="{cls(pf["ret"])}">{pf["ret"]:+.2f}%</td>'
            f'<td>{len(pf["holdings"])}</td></tr>'
            f'<tr><td colspan="4" class="l"><details><summary>持股 {len(pf["holdings"])} 檔</summary>'
            f'<div class="hold">{esc(holds)}</div></details></td></tr>')

    legend = "".join(
        f'<span><span class="dot" style="background:{color_map[n]}"></span>{ICON.get(n,"")} {esc(n)}</span>'
        for n in order)
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>策略賽馬 · 模擬倉</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script><style>{CSS}</style></head>
<body><div class="wrap">
<h1>🏇 策略賽馬 — 產業鏈 vs 巴菲特</h1>
<div class="sub">起始 {esc(inception)}（第 {days} 天）· 更新 {date} · 每倉本金 {usd(base)} · 等權重 · 每週調倉 ·
 <a href="{PAGES_URL}">← 看板</a></div>

<h2>⚔️ 兩大方法對決</h2>{vs_html}

<div class="card"><canvas id="race" height="160"></canvas>
<div class="legend">{legend}</div></div>

<h2>🏭 7 條產業鏈明細</h2>
<div class="card"><table><tr><th class="l">產業鏈</th><th>淨值</th><th>報酬</th><th>持股</th></tr>
{''.join(rows)}</table></div>

<p class="sub">玩法：產業鏈全（七鏈守備清單全買）與巴菲特30（最被低估前30）各投 {usd(base)}，等權重、每週跟清單調倉。
報酬用各股本地幣別%算（美股美元、台股台幣），免匯率干擾。跑一段時間看「動能 vs 價值」哪邊賺。</p>
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
