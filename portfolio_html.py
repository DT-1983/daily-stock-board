"""策略賽馬 v2（統一風格版）

資料邏輯與文字說明完全沿用 portfolio_html.py（usd/cls/holding_rows 直接 import），
只換頁首/配色/圖示為 board_theme 統一設計系統。

用法：python portfolio_html_v2.py [-o docs/portfolios.html]
"""
import os
import json
import argparse
from datetime import datetime

from portfolio_html_legacy import usd, cls, holding_rows, OBIS
from board_theme import BASE_CSS, header, icon, esc, NAV

# 2026-09-03（Leo：「電腦版圖版占太多地方，空白太多」）：桌機版緊湊化。
#
# **只在這一頁蓋、不改 board_theme**——.row/.wrap/.vsgrid 是全站共用的，改主題會
# 動到看板、燈號、財報等每一頁，風險跟收益不成比例。這頁的問題是它自己的資訊密度
# （四張大卡片各只有 4 行字、產業鏈列中間一大片空白），頁面層級處理就夠。
#
# 三個改動：① 寬螢幕放寬到 1280（1100 在 1440 螢幕上兩側留白過多）
# ② 卡片與列的內距、字級縮一階 ③ 產業鏈列改三欄，把市值/損益移到中間補空白。
DESKTOP_CSS = """
@media(min-width:1080px){
  .wrap{max-width:1280px}
  .stat{padding:12px;margin:8px 0}
  .stat .big{font-size:25px}
  .vsgrid{gap:9px;margin:8px 0}
  .vsgrid .box{padding:11px 12px}
  .vsgrid .val{font-size:19px;margin:3px 0}
  .vsgrid .pnl{font-size:12.5px}
  .vsgrid details{margin-top:6px}
  .row{min-height:44px;padding:9px 12px;align-items:center}
  .row .info{display:flex;align-items:center;gap:18px;flex:1;min-width:0}
  .row .t1{flex:0 0 250px}
  .row .one{margin-top:0;flex:1;text-align:left}
  #race{max-height:250px}
}
"""

import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 印 emoji 會炸

ICON_NAME = {  # 中文 emoji 圖示 → Lucide SVG（不用 emoji 當結構圖示）
    "產業鏈全": "portfolio", "產業鏈+趨勢": "portfolio", "巴菲特價值": "buffett",
}
COLORS = ["#3B82F6", "#22C55E", "#F97316", "#A78BFA", "#EAB308",
         "#22D3EE", "#EF4444", "#94A3B8", "#60A5FA"]


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
        datasets.append({"label": n, "data": filled, "borderColor": color_map[n],
                         "fill": False, "tension": 0.2, "borderWidth": 3 if mn else 1.5,
                         "borderDash": [] if mn else [4, 3], "pointRadius": 0,
                         "grp": "main" if mn else "chain", "hidden": not mn})

    invested = base * len(main)
    cur_total = sum(pfs[n]["value"] for n in main)
    pnl_total = cur_total - invested
    ret_total = (cur_total / invested - 1) * 100 if invested else 0
    stat = (f'<div class="stat"><div class="sub2">{len(main)} 套方法總投入 {usd(invested)}'
            f'（各 {usd(base)}）</div><div class="big {cls(pnl_total)}">{usd(cur_total)}　'
            f'<span style="font-size:17px">{usd(pnl_total,1)}（{ret_total:+.2f}%）</span></div></div>')

    vs = ""
    if main:
        best = max(pfs[n]["ret"] for n in main)

        def box(name):
            pf = pfs[name]
            w = "win" if pf["ret"] == best else ""
            return (f'<div class="box {w}"><div class="nm">{esc(name)}</div>'
                    f'<div class="val">{usd(pf["value"])}</div>'
                    f'<div class="pnl {cls(pf["pnl"])}">{usd(pf["pnl"],1)}（{pf["ret"]:+.2f}%）</div>'
                    f'<div class="sub2" style="color:var(--dim)">{len(pf["holdings"])} 檔</div>'
                    f'<details><summary>看持股</summary>{holding_rows(pf)}</details></div>')
        vs = '<div class="vsgrid">' + "".join(box(n) for n in main) + '</div>'

    chains = sorted([(n, pf) for n, pf in pfs.items() if n not in main],
                    key=lambda kv: -kv[1]["ret"])
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    rows = []
    for i, (n, pf) in enumerate(chains):
        m = medals.get(i, f"{i+1}")
        detail = f'<div class="mdbody">{holding_rows(pf)}</div>'
        # 中途加入的鏈起跑日跟大盤不同，報酬率不能跟從頭跑的鏈直接比大小 → 明確標出來
        late = pf.get("inception") and pf["inception"] != inception
        late_tag = (f'<span class="nm" style="color:#EAB308">⚠ {esc(pf["inception"])} 才加入</span>'
                    if late else "")
        rows.append(
            f'<button class="row" data-id="c{i}" aria-expanded="false">'
            f'<span style="width:22px;text-align:center;flex-shrink:0">{m}</span>'
            f'<span class="info"><span class="t1"><span class="tk">{esc(n)}</span>'
            f'<span class="nm">{len(pf["holdings"])} 檔</span>{late_tag}</span>'
            f'<span class="one">{usd(pf["value"])}　'
            f'<span class="{cls(pf["pnl"])}">{usd(pf["pnl"],1)}</span></span></span>'
            f'<span class="rt"><span class="sv num {cls(pf["ret"])}">{pf["ret"]:+.1f}%</span></span>'
            f'{icon("chevron",15,"currentColor",2.5)}</button>'
            f'<div class="detail" data-for="c{i}">{detail}</div>')

    legend = "".join(
        f'<span><i style="width:9px;height:9px;border-radius:50%;display:inline-block;'
        f'background:{color_map[n]}"></i>{esc(n)}</span>' for n in order)
    # 2026-08-19：這裡原本用 datetime.now()（畫圖當下的時間），資料沒更新時
    # 頁面照樣寫著今天 → 「今天的日期＋昨天的數字」，看不出來。
    # 改成顯示 portfolios.json 自己的 updated（資料的時間），並在資料落後時明講。
    render_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.now().strftime("%Y-%m-%d")
    stale = updated != today
    stale_note = ""
    if stale:
        stale_note = (f'<div class="stalewarn">⚠️ 資料停在 <b>{esc(updated)}</b>，'
                      f'今天（{today}）的調倉／淨值更新沒有成功。'
                      f'下面的數字是上次成功更新時的結果，不是今天的。</div>')

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>策略賽馬 · 模擬倉</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>{BASE_CSS}{DESKTOP_CSS}</style></head><body><div class="wrap">
{header("portfolio", "策略賽馬模擬倉",
  f"起始 {esc(inception)}（第 {days} 天）· <b>資料日期 {esc(updated)}</b>"
  f" · 每倉 {usd(base)} · 匯率 1美元={fx}台幣"
  f" · 淨值每日 09:00 更新，清單每週六重篩"
  f"<br><span style='color:var(--dim);font-size:11px'>頁面產生於 {render_time}"
  f"（產生時間≠資料時間，以上面的資料日期為準）</span>", NAV, "portfolio")}
{stale_note}
{stat}
<div class="card">
  <div class="ctrl" style="position:static;border:0;padding:0 0 10px">
    <div class="seg" role="group" aria-label="切換圖表範圍">
      <button data-c="main" aria-pressed="true">{len(main)} 主策略</button>
      <button data-c="chain" aria-pressed="false">{len(chains)} 產業鏈</button>
      <button data-c="all" aria-pressed="false">全部</button></div>
  </div>
  <canvas id="race" height="150"></canvas>
  <div class="chartlegend">{legend}</div>
</div>

<section class="sec"><div class="sechd"><h2>{len(main)} 套方法對決</h2></div>{vs}</section>

<section class="sec"><div class="sechd"><h2>{len(chains)} 條產業鏈明細</h2>
  <span class="cnt">點列展開持股</span></div>
  <div class="rows">{"".join(rows)}</div>
</section>

<section class="sec explain"><div class="sechd"><h2>兩套買股方法怎麼決定的</h2></div>
<div class="card">
<h3 style="color:#F5B841">產業鏈全（動能／成長派）</h3>
<p>鎖定 7 條 AI 題材產業鏈，每條鏈用<b>三因子客觀篩選</b>選最強標的（非人工挑）：<br>
① <b>市值</b>：規模越大越穩、流動性好　② <b>成長</b>：美股看營收年增率、台股看月營收 YoY
③ <b>進場（資金流）</b>：美股看 <b>OBV 能量潮</b>、台股看<b>法人20日買超÷均量</b><br>
三因子各自排名正規化加總 → <b>守備清單</b>。「產業鏈全」＝七鏈完整清單全買、等權重（約 80+ 檔）。<b>每週日重篩</b>。<br>
<span style="color:#93C5FD">2026-07-28 由「每鏈取前 2」改回全買：5.5 年回測顯示取前 2 過度集中，回撤 −55.9% 比單一鏈還差。
Bitcoin→AI 機房該鏈合計限重 10%（回測 MDD −94%）。</span></p>
<hr>
<h3 style="color:#F5B841">產業鏈+趨勢（選股＋擇時）</h3>
<p>拿「產業鏈全」同一批股，再用 <b>SuperTrend</b> 過濾：只抱多頭（綠燈）的，翻空（紅燈）先不持有。<br>
<span style="color:#93C5FD">用<b>週線</b> SuperTrend 判斷（公式參數 ATR10×3 不變，只把 K 棒由日改週）。
日線 32 次賣出有 24 次(75%)賣完股價續漲，訊號雜訊過高；週線同期只 10 次訊號。</span></p>
<hr>
<h3 style="color:#F5B841">巴菲特價值（價值派 · 洪瑞泰選股法）</h3>
<p>先挑「好公司」，再等「便宜」才買。依洪瑞泰講稿原文設定初篩母體：
美股 <b>S&amp;P 500</b> 成分股、台股 TWSE+TPEX，兩邊都是 <b>PE≤15、</b>美股 ROE≥10%（他刻意放寬）
／台股 ROE≥15%。<br>
過關候選再過品質關：① 產業龍頭（同產業市值前3）② ROE≥15% 且近4年至少3年達標
③ <b>盈再率</b>&lt;80%（台股 FinMind、美股 SEC EDGAR 官方申報計算，非替代估算）
④ 配息率≥40%。<br>
通過品質關後，<b>現價 ≤ 俗價</b>才買，取品質分前 30，排除照妖鏡（EPS估降/高負債）。
<b>每週六</b>隨全市場重掃更新（財報一公告最慢 7 天內吃進來）。</p>
<p style="color:#F5B841;border-left:3px solid #F5B841;padding-left:10px;margin-top:10px">
<b>⚠️ 2026-08-27 規則改版，此日之後的績效不能直接跟之前比。</b><br>
對照 MIKEON 官方盈再表逐檔驗證後，俗貴價改為官方定義：
<b>EPS 改用「常利」</b>（近2年平均×0.7＋近5年中位數×0.3，平滑一次性損益，原本用近四季實績/預估）、
<b>俗價＝貴價÷1.15<sup>8</sup></b>（＝8年年化15%的折現價，原本用 EPS×12 這個二手簡化值）。<br>
新線比舊線低約 18%，進場門檻變嚴：巴菲特倉持股當天由 <b>21 檔降為 3 檔</b>——
不是公司變差，是原本有不少是靠寬鬆舊線買進的。曲線刻意保留不歸零，但**跨 8/27 的報酬率
等於跨了兩套規則**，看的時候要知道這件事。（產業鏈全／產業鏈+趨勢兩倉不受影響，
它們讀的是守備清單不是巴菲特清單。）</p>
<hr>
<h3 style="color:#F5B841">各買多少？（等金額，不是等股數）</h3>
<p>每個倉獨立 <b>{usd(base)}</b>，平均分給該倉持股：<b>每檔配額 = {usd(base)} ÷ 檔數，股數 = 配額 ÷ 股價</b>。
貴的買少股、便宜的買多股。市值 = Σ股數×現價，損益 = 市值 − 本金。每週跟新清單調倉。</p>
<p class="sub">一句話：<b>產業鏈全＝追「現在強、資金在進」；產業鏈+趨勢＝同股再加週線趨勢擇時；巴菲特＝撿「便宜的好公司」</b>。</p>
</div></section>
</div>
<script>
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const chart=new Chart(document.getElementById('race'),{{type:'line',
 data:{{labels:{json.dumps(all_dates)},datasets:{json.dumps(datasets, ensure_ascii=False)}}},
 options:{{responsive:true,interaction:{{mode:'nearest',intersect:false}},
  plugins:{{legend:{{display:false}},tooltip:{{mode:'nearest',intersect:false}}}},
  scales:{{y:{{grid:{{color:'#1E293B'}},ticks:{{color:'#94A3B8',
    callback:function(v){{return '$'+v.toLocaleString();}}}}}},
           x:{{grid:{{display:false}},ticks:{{color:'#94A3B8',maxTicksLimit:8}}}}}}}}}});
$$('.seg button').forEach(b=>b.onclick=()=>{{
 $$('.seg button').forEach(x=>x.setAttribute('aria-pressed',x===b));
 chart.data.datasets.forEach(d=>{{d.hidden=(b.dataset.c=='all')?false:(d.grp!=b.dataset.c);}});
 chart.update();}});
$$('.row').forEach(r=>r.onclick=()=>{{const d=$(`.detail[data-for="${{r.dataset.id}}"]`),
 open=r.getAttribute('aria-expanded')==='true';
 r.setAttribute('aria-expanded',!open);d.classList.toggle('on',!open);
 d.style.display=!open?'block':'none';}});
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
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            open(out, "w", encoding="utf-8").write(html)
            print(f"✅ 已存:{out}")
        except Exception as e:
            print(f"⚠️ 寫 {out} 失敗:{e}")


if __name__ == "__main__":
    main()
