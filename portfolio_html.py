"""策略賽馬看板：產業鏈 vs 巴菲特（真實買股模擬，絕對金額）。

頂部總損益 + 賽馬圖；點開每倉看買了哪幾隻、進場價/現價/損益。
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
    "產業鏈精選": "🏭", "產業鏈+趨勢": "📈", "巴菲特價值": "🏛️",
    "AI 伺服器": "🖥️", "矽光子/光通訊": "🔆", "低軌衛星": "🛰️", "太陽能": "☀️",
    "Bitcoin→AI 機房": "₿", "AI 電力/核能": "⚡", "機器人": "🤖",
}
COLORS = ["#4a9eff", "#3ddc84", "#ff9b5c", "#c98bff", "#ffd479",
          "#5ce0d8", "#ff7676", "#9aa0a6", "#8ab4f8"]


def esc(s):
    return _html.escape(str(s if s is not None else ""))


def usd(v, sign=False):
    s = f"{'+' if (sign and v >= 0) else ''}${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"
    return s


CSS = """
*{box-sizing:border-box}
body{font-family:"Microsoft JhengHei","PingFang TC",-apple-system,sans-serif;margin:0;
 background:#0f1115;color:#e6e6e6;line-height:1.5;font-size:15px}
.wrap{max-width:940px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:6px 0}h2{font-size:16px;margin:18px 0 6px}.sub{color:#9aa0a6;font-size:13px}a{color:#6db3ff}
.tot{background:#1a1d23;border:1px solid #2a2e35;border-radius:12px;padding:14px;margin:10px 0;text-align:center}
.tot .big{font-size:30px;font-weight:800}.tot .sub2{font-size:13px;color:#9aa0a6}
.vs{display:flex;gap:10px;margin:10px 0;flex-wrap:wrap}
.vs .box{flex:1;min-width:150px;background:#1a1d23;border:1px solid #2a2e35;border-radius:12px;padding:12px;text-align:center}
.vs .nm{font-size:14px;font-weight:700}.vs .val{font-size:22px;font-weight:800;margin:4px 0}
.vs .pnl{font-size:14px;font-weight:700}.vs .sub2{font-size:12px;color:#9aa0a6}
.win{border-color:#3ddc84;box-shadow:0 0 0 1px #3ddc84}
.card{background:#1a1d23;border:1px solid #2a2e35;border-radius:10px;padding:12px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-bottom:1px solid #2a2e35;padding:7px 6px;text-align:right}
th{color:#9aa0a6;font-weight:600}td.l,th.l{text-align:left}
.pos{color:#3ddc84;font-weight:700}.neg{color:#ff7676;font-weight:700}.flat{color:#9aa0a6}
.medal{font-size:15px}
details{margin:2px 0}summary{cursor:pointer;color:#bcd2ff;font-size:13px;padding:4px 0}
.hlist{margin:6px 0 10px}
.hrow{padding:7px 2px;border-bottom:1px solid #23272e}
.htop{display:flex;align-items:baseline;gap:10px;font-size:14.5px}
.htop .htk{font-weight:700;flex:1}
.htop span{font-weight:700}
.hsub{font-size:11.5px;color:#9aa0a6;margin-top:3px}
.legend{font-size:12px;color:#9aa0a6;margin:8px 0;display:flex;flex-wrap:wrap;gap:12px}
.chl{display:flex;gap:6px;margin:2px 0 10px}
.cb{font-size:12.5px;padding:4px 12px;border-radius:14px;border:1px solid #2a2e35;background:#1c2128;color:#bcd2ff;cursor:pointer}
.cb.on{background:#4a9eff;color:#fff;border-color:#4a9eff}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
"""


def cls(r):
    return "pos" if r > 0 else ("neg" if r < 0 else "flat")


def holding_rows(pf):
    """每隻股票一張小卡（手機友善）：第一行 代號／報酬％／損益；第二行 進場→現價·股數·市值。"""
    items = []
    for tk, h in pf["holdings"].items():
        eu, sh = h["eu"], h["sh"]
        cu = h.get("cu", eu)
        en, cur = h.get("en", eu), h.get("cur", h.get("en", eu))
        val = sh * cu
        pnl = sh * (cu - eu)
        ret = (cu / eu - 1) * 100 if eu else 0
        items.append((tk, sh, en, cur, ret, val, pnl, tk.endswith(".TW")))
    items.sort(key=lambda x: -x[6])   # 損益大→小
    rows = []
    for tk, sh, en, cur, ret, val, pnl, tw in items:
        u = "NT$" if tw else "$"
        rows.append(
            f'<div class="hrow"><div class="htop">'
            f'<span class="htk">{esc(tk)}</span>'
            f'<span class="{cls(ret)}">{ret:+.1f}%</span>'
            f'<span class="{cls(pnl)}">{usd(pnl,1)}</span></div>'
            f'<div class="hsub">{u}{en:,.1f} → {u}{cur:,.1f}　{sh:.2f} 股　市值 ${val:,.0f}</div>'
            f'</div>')
    return '<div class="hlist">' + "".join(rows) + '</div>'


def build(state):
    pfs = state["portfolios"]
    base = state.get("base", 10000)
    main = state.get("main", [])
    fx = state.get("fx", 32)
    inception = state.get("inception", "?")
    updated = state.get("updated", "?")
    try:
        days = (datetime.strptime(updated, "%Y-%m-%d") -
                datetime.strptime(inception, "%Y-%m-%d")).days
    except Exception:
        days = 0

    # 賽馬圖
    all_dates = sorted({d for pf in pfs.values() for d, _ in pf["history"]})
    order = list(main) + [n for n in pfs if n not in main]
    color_map = {n: COLORS[i % len(COLORS)] for i, n in enumerate(order)}
    datasets = []
    for n in order:
        hmap = {d: v for d, v in pfs[n]["history"]}
        last, filled = base, []
        for d in all_dates:
            if hmap.get(d) is not None:
                last = hmap[d]
            filled.append(round(last, 2))
        mn = n in main
        datasets.append({"label": f"{ICON.get(n,'')} {n}", "data": filled,
                         "borderColor": color_map[n], "fill": False, "tension": 0.2,
                         "borderWidth": 3 if mn else 1.5,
                         "borderDash": [] if mn else [4, 3], "pointRadius": 0,
                         "grp": "main" if mn else "chain",
                         "hidden": not mn})   # 預設只顯示 3 主倉

    # 頂部總損益（2 主倉合計）
    invested = base * len(main)
    cur_total = sum(pfs[n]["value"] for n in main)
    pnl_total = cur_total - invested
    ret_total = (cur_total / invested - 1) * 100 if invested else 0
    tot = (f'<div class="tot"><div class="sub2">{len(main)} 套方法總投入 {usd(invested)}（各 {usd(base)}）</div>'
           f'<div class="big {cls(pnl_total)}">{usd(cur_total)}　<span style="font-size:18px">'
           f'{usd(pnl_total,1)}（{ret_total:+.2f}%）</span></div></div>')

    # 主倉對決卡（N 個方法並排，報酬最高者綠框）
    vs = ""
    if main:
        best = max(pfs[n]["ret"] for n in main)

        def box(name):
            pf = pfs[name]
            w = "win" if pf["ret"] == best else ""
            return (f'<div class="box {w}"><div class="nm">{ICON.get(name,"")} {esc(name)}</div>'
                    f'<div class="val">{usd(pf["value"])}</div>'
                    f'<div class="pnl {cls(pf["pnl"])}">{usd(pf["pnl"],1)}（{pf["ret"]:+.2f}%）</div>'
                    f'<div class="sub2">{len(pf["holdings"])} 檔</div>'
                    f'<details><summary>看持股</summary>{holding_rows(pf)}</details></div>')
        vs = '<div class="vs">' + "".join(box(n) for n in main) + '</div>'

    # 7 鏈明細
    chains = sorted([(n, pf) for n, pf in pfs.items() if n not in main],
                    key=lambda kv: -kv[1]["ret"])
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    rows = []
    for i, (n, pf) in enumerate(chains):
        m = medals.get(i, f"{i+1}")
        rows.append(
            f'<tr><td class="l"><span class="medal">{m}</span> {ICON.get(n,"")} <b>{esc(n)}</b></td>'
            f'<td>{usd(pf["value"])}</td><td class="{cls(pf["pnl"])}">{usd(pf["pnl"],1)}</td>'
            f'<td class="{cls(pf["ret"])}">{pf["ret"]:+.2f}%</td></tr>'
            f'<tr><td colspan="4" class="l"><details><summary>看 {len(pf["holdings"])} 檔持股</summary>'
            f'{holding_rows(pf)}</details></td></tr>')

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
<div class="sub">起始 {esc(inception)}（第 {days} 天）· 更新 {date} · 每倉 {usd(base)} · 匯率 1美元={fx}台幣 ·
 <a href="{PAGES_URL}">← 看板</a></div>

{tot}
<div class="card">
<div class="chl"><button class="cb on" onclick="chl(this,'main')">3 主策略</button>
<button class="cb" onclick="chl(this,'chain')">7 產業鏈</button>
<button class="cb" onclick="chl(this,'all')">全部</button></div>
<canvas id="race" height="150"></canvas>
<div class="legend">{legend}</div></div>

<h2>⚔️ 三套方法對決（點「看持股」展開）</h2>{vs}

<h2>🏭 7 條產業鏈明細</h2>
<div class="card"><table><tr><th class="l">產業鏈</th><th>市值</th><th>損益</th><th>報酬</th></tr>
{''.join(rows)}</table></div>

<h2>📖 兩套買股方法怎麼決定的</h2>
<div class="card" style="font-size:13.5px;line-height:1.65">
<p style="margin:4px 0"><b>🏭 產業鏈精選（動能／成長派）</b><br>
鎖定 7 條 AI 題材產業鏈，每條鏈用<b>三因子客觀篩選</b>選最強標的（非人工挑）：<br>
　① <b>市值</b>：規模越大越穩、流動性好<br>
　② <b>成長</b>：美股看營收年增率、台股看月營收 YoY<br>
　③ <b>進場（資金流）</b>：美股看 <b>OBV 能量潮</b>（量價是否同步、資金真的在買）、台股看 <b>法人20日買超÷均量</b><br>
三因子各自排名正規化加總 → <b>守備清單</b>。「產業鏈精選」＝<b>每鏈取分數最高前 2</b>（重點壓 ~14 檔）；
下方「7 鏈明細」＝各鏈完整清單分開比。<b>每週日重篩</b>，量沒進來的會被換掉。</p>
<hr style="border-color:#2a2e35;margin:10px 0">
<p style="margin:4px 0"><b>⚡ 產業鏈+趨勢（選股＋擇時）</b><br>
拿「產業鏈精選」同一批股，再用 <b>SuperTrend</b>（TradingView 同款趨勢線）過濾：
<b>只抱「多頭（綠燈）」的，翻空（紅燈）就先不持有</b>。測「選股好之後，加上趨勢擇時會不會更賺、回檔少」。</p>
<hr style="border-color:#2a2e35;margin:10px 0">
<p style="margin:4px 0"><b>🏛️ 巴菲特價值（價值派 · 洪瑞泰選股法）</b><br>
洪瑞泰精髓：先挑「<b>好公司</b>」，再等「<b>便宜</b>」才買。三道關卡：<br>
　① <b>產業龍頭</b>：同產業市值前 3（護城河、寡占）<b>優先選</b><br>
　② <b>ROE ≥ 15%</b>：賺錢能力強且穩定<br>
　③ <b>盈再率 &lt; 80%</b>（越低越好）：不用一直砸大錢買設備就能賺＝<b>印鈔機生意</b>（洪瑞泰最看重，權重最高）<br>
通過品質三關後，<b>現價 ≤ 俗價（EPS×12）</b>＝便宜才買，取品質分前 30。<br>
排除照妖鏡（EPS估降/高負債）。<b>每季</b>隨財報更新。
<span class="sub">※ 不再用「折價最大」選 —— 那會選到 CHTR/MKC 這種衰退爛股（虛高俗價）；改用洪瑞泰品質優先。</span></p>
<hr style="border-color:#2a2e35;margin:10px 0">
<p style="margin:4px 0"><b>⚙️ 各買多少？（等金額，不是等股數）</b><br>
每個倉都是獨立 <b>{usd(base)}</b>，平均分給該倉持股：<br>
　<b>每檔配額 ＝ {usd(base)} ÷ 檔數　｜　股數 ＝ 配額 ÷ 股價（美金）</b><br>
所以是「<b>每檔投一樣多錢</b>」，股數隨股價變 —— 貴的買少股、便宜的買多股。<br>
例：巴菲特30 → 每檔 $333（ALL $240 買 1.39 股、BCE $22 買 14.9 股）。<br>
<b>7 鏈各自也是獨立 {usd(base)}</b>，檔數少的每檔配額更大（如 Bitcoin 鏈 6 檔 → 每檔 $1,667；AI 伺服器 12 檔 → 每檔 $833）。
同一檔在「產業鏈全」(68檔均分)和「個別鏈」買的金額不同，因為是不同的 {usd(base)} 倉。</p>
<hr style="border-color:#2a2e35;margin:10px 0">
<p style="margin:4px 0"><b>⚙️ 其它</b>：台股以<b>即時匯率</b>（現 1美元={fx}台幣）換美金，全部美金加總才能比。
<b>市值 ＝ Σ 股數×現價，損益 ＝ 市值 − 本金</b>。每週跟新清單調倉（賣退榜、買新進，把當下總市值重新均分），淨值接續累計。</p>
<p class="sub" style="margin:8px 0 0">一句話：<b>產業鏈精選＝追「現在強、資金在進」；產業鏈+趨勢＝同股再加趨勢擇時；巴菲特＝撿「便宜的好公司」</b>。
跑一段時間看哪套在這個市場賺得多、回檔少。</p>
</div>
</div>
<script>
const chart=new Chart(document.getElementById('race'),{{type:'line',
 data:{{labels:{json.dumps(all_dates)},datasets:{json.dumps(datasets, ensure_ascii=False)}}},
 options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
  plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{}}}}}},
  scales:{{y:{{grid:{{color:'#2a2e35'}},ticks:{{color:'#9aa0a6',
    callback:function(v){{return '$'+v.toLocaleString();}}}}}},
           x:{{grid:{{display:false}},ticks:{{color:'#9aa0a6',maxTicksLimit:8}}}}}}}}}});
function chl(b,mode){{
 document.querySelectorAll('.cb').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 chart.data.datasets.forEach(d=>{{d.hidden=(mode=='all')?false:(d.grp!=mode);}});
 chart.update();}}
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
