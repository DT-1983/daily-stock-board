# -*- coding: utf-8 -*-
"""ARK ETF（ARKK/ARKW/ARKG）追蹤報告 → docs/ark.html

用戶 2026-08-17 指示：不追逐日持股異動，只追「產業方向」；同時要 10 年回測
（vs SPY/QQQ，含 Sharpe/Sortino）；報告要包含重倉個股法說會重點跟 ARK 自己的
Big Ideas 觀點，最後做交叉解讀。ark-funds.com 的每日持股 CSV 被 Cloudflare
擋掉（403），改用 yfinance funds_data（top_holdings + sector_weightings +
fund_overview）當結構化資料源；「產業方向」沒有歷史快照可比對，改用 WebSearch
查最近的持股異動報導做質化研判，不臆測沒查證的百分比變化。

用法：python ark_report.py [-o docs/ark.html]
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from board_theme import BASE_CSS, header, NAV, esc
import earnings_call as EC
import chain_positioning as CP
import fundamentals_reality as FR
import technical_indicators as TI

FUNDS = ["ARKK", "ARKW", "ARKG"]
FUND_LABEL = {"ARKK": "ARKK · ARK 創新旗艦 ETF", "ARKW": "ARKW · ARK Next Generation Internet ETF",
              "ARKG": "ARKG · ARK 基因體革命 ETF"}
BENCH = ["SPY", "QQQ"]
BENCH_LABEL = {"SPY": "SPY（大盤代表）", "QQQ": "QQQ（那斯達克100）"}
TOP_N = 10

# 私募/未上市部位，沒有公開財報可查，排除在「前N大持股」的法說會查證名單外
EXCLUDE_PRIVATE = {"SPCX"}

SECTOR_ZH = {
    "realestate": "房地產", "consumer_cyclical": "非必需消費", "basic_materials": "原物料",
    "consumer_defensive": "必需消費", "technology": "科技", "communication_services": "通訊服務",
    "financial_services": "金融服務", "utilities": "公用事業", "industrials": "工業",
    "energy": "能源", "healthcare": "醫療保健",
}


def _fund_snapshot(tk):
    fd = yf.Ticker(tk).funds_data
    holdings = fd.top_holdings
    rows = [{"symbol": sym, "name": holdings.loc[sym].get("Name", sym),
             "weight": float(holdings.loc[sym]["Holding Percent"])}
            for sym in holdings.index]
    sectors = {SECTOR_ZH.get(k, k): v for k, v in (fd.sector_weightings or {}).items() if v}
    ov = fd.fund_overview or {}
    try:
        aum = float(fd.fund_operations.loc["Total Net Assets", tk])
    except Exception:
        aum = None
    try:
        expense = float(fd.fund_operations.loc["Annual Report Expense Ratio", tk])
    except Exception:
        expense = None
    return {"symbol": tk, "holdings": rows, "sectors": sectors,
            "category": ov.get("categoryName", ""), "aum": aum, "expense": expense}


def _backtest_all(periods=(3, 5, 10), rf_annual=0.0):
    """一次抓最長區間(max(periods))的資料，各期間用同一份資料切片算——
    不用每個期間各自打一次 yfinance，省網路來回（用戶要求同時加 3年/5年，跟原本10年一起比）。"""
    tickers = FUNDS + BENCH
    end = datetime.now()
    start = end - timedelta(days=365 * max(periods) + 10)
    data = {}
    for tk in tickers:
        h = yf.Ticker(tk).history(start=start.strftime("%Y-%m-%d"), auto_adjust=True)
        data[tk] = h["Close"]
    common = data[tickers[0]].index
    for tk in tickers[1:]:
        common = common.intersection(data[tk].index)
    for tk in tickers:
        data[tk] = data[tk].reindex(common)

    out = {}
    for years in periods:
        cutoff = end - timedelta(days=365 * years)
        cutoff_ts = pd.Timestamp(cutoff)
        if common.tz is not None:
            cutoff_ts = cutoff_ts.tz_localize(common.tz) if cutoff_ts.tz is None else cutoff_ts.tz_convert(common.tz)
        idx = common[common >= cutoff_ts]
        n = len(idx)
        period = {"start": str(idx[0].date()), "end": str(idx[-1].date()),
                  "years": round(n / 252, 1), "rows": {}}
        for tk in tickers:
            px = data[tk].reindex(idx).values
            rets = px[1:] / px[:-1] - 1
            cagr = (px[-1] / px[0]) ** (252 / (n - 1)) - 1
            vol = rets.std(ddof=1) * np.sqrt(252)
            rf_daily = rf_annual / 252
            excess = rets - rf_daily
            sharpe = excess.mean() / rets.std(ddof=1) * np.sqrt(252) if rets.std(ddof=1) else None
            downside = rets[rets < rf_daily] - rf_daily
            dd_dev = np.sqrt((downside ** 2).mean()) * np.sqrt(252) if len(downside) else None
            sortino = (excess.mean() * 252) / dd_dev if dd_dev else None
            cum = px / px[0]
            peak = np.maximum.accumulate(cum)
            mdd = ((cum - peak) / peak).min()
            period["rows"][tk] = {"total_ret": px[-1] / px[0] - 1, "cagr": cagr, "vol": vol,
                                  "sharpe": sharpe, "sortino": sortino, "mdd": mdd}
        out[years] = period
    return out


def _top_combined(snaps):
    """跨 N 檔基金合併排名：不限「至少兩檔持有」，單一基金的重倉股也算，
    依合計權重排序給「前N大持股」表跟法說會查證名單共用同一份排名。"""
    weights = {tk: {r["symbol"]: r["weight"] for r in snaps[tk]["holdings"]} for tk in FUNDS}
    names = {}
    for tk in FUNDS:
        names.update({r["symbol"]: r["name"] for r in snaps[tk]["holdings"]})
    all_syms = set().union(*[set(w) for w in weights.values()])
    rows = []
    for s in all_syms:
        held_by = [tk for tk in FUNDS if s in weights[tk]]
        total = sum(weights[tk].get(s, 0) for tk in FUNDS)
        rows.append({"symbol": s, "name": names.get(s, s), "total": total,
                     "held_by": held_by, "w": {tk: weights[tk].get(s) for tk in FUNDS}})
    return sorted(rows, key=lambda r: -r["total"])


# ── ARK 自己的觀點／近期持股異動：2026-08-17 WebSearch 查證，來源見文末 ──
ARK_OWN_VIEW = {
    "big_ideas": [
        ("大加速時代（The Great Acceleration）",
         "Big Ideas 2026 是 ARK 第 10 份年度旗艦報告，核心主張是 AI 的進展已經從軟體"
         "擴散到實體系統、科學發現、資本形成與整體生產力，13 個大主題涵蓋 AI 基礎設施、"
         "自駕、機器人、多組學生技、太空與去中心化金融。"),
        ("創新資產佔比預估大幅提升",
         "ARK 預估「創新導向資產」的市值佔比會從 2025 年約 20% 成長到 2030 年約 50%，"
         "市值規模從約 5 兆美元擴大到約 28 兆美元——這是 ARK 所有選股邏輯的總前提，"
         "解讀 ARK 持股時要知道這是它的核心世界觀，不是中立預測。"),
        ("資料中心資本支出估計",
         "ARK 預估資料中心系統支出會從 2025 年約 5000 億美元成長到 2030 年約 1.4 兆美元，"
         "年複合成長率約 30%，是 ARK 持續加碼 AI 基礎設施相關持股的量化依據。"),
    ],
    "recent_moves": [
        ("減碼串流／串流以外的內容平台",
         "近期單日減碼近 9900 萬美元的 Roku 持股，同時加碼特斯拉，訊號解讀為從「串流"
         "內容」轉向「自駕/AI驅動的移動」敘事。"),
        ("加碼特斯拉，逢弱加碼",
         "特斯拉股價走弱期間 ARK 反手加碼（單筆約 1430 萬美元），目前 ARK Invest 合計"
         "持有的特斯拉部位市值約 8.7 億美元，顯示這是 ARK 現階段最核心的信念持股之一。"),
        ("加碼加密貨幣／新興金融科技",
         "近期持續加碼 Coinbase、Robinhood，顯示對數位資產與新興金融科技的信念沒有減弱，"
         "反而在加碼。"),
        ("加碼電商、減碼部分傳統科技",
         "近期加碼 Amazon、Alibaba，同時賣出台積電、百度，訊號解讀為從「傳統科技龍頭」"
         "轉向「電商+新興市場數位化」敘事——賣台積電比較值得注意，因為那等於減少對"
         "半導體製造龍頭的直接曝險，轉而透過下游應用（AI消費/電商）間接參與。"),
    ],
}
SOURCES = [
    ("What's Driving Cathie Wood's Latest Portfolio Moves", "https://www.kavout.com/market-lens/what-s-driving-cathie-wood-s-latest-portfolio-moves"),
    ("ARK Invest Dumps $99M Roku, Huge Bets on Tesla in 2026 - Memeburn", "https://memeburn.com/cathie-wood-tesla-roku-ark-invest/"),
    ("Cathie Wood's Ark Invest Has Built an $870 Million Tesla Position - Motley Fool", "https://www.fool.com/investing/2026/08/05/cathie-woods-ark-has-built-an-870-million-tesla-po/"),
    ("Cathie Wood buys another $72M of mega-cap tech stock - TheStreet", "https://www.thestreet.com/investing/cathie-wood-buys-another-72m-of-mega-cap-amazon-stock"),
    ("BIG IDEAS 2026 - ARK Invest", "https://www.ark-invest.com/big-ideas-2026"),
    ("ARK Invest releases Big Ideas 2026 report - ETF Express", "https://etfexpress.com/2026/01/22/ark-invest-releases-big-ideas-2026-report/"),
    ("BIG IDEAS 2026 - The Investment Opportunity Report (PDF)", "https://etfs.ark-funds.com/hubfs/1_Download_Files_ETF_Website/Reports/ARKInvest-InvestmentOpportunityReport2026.pdf"),
]


def _pct(x, digits=1):
    return f"{x*100:+.{digits}f}%" if x is not None else "—"


def _pct_w(x, digits=1):
    """權重用，不加正負號前綴（權重不是漲跌）。"""
    return f"{x*100:.{digits}f}%" if x is not None else "—"


def _num(x, digits=2):
    return f"{x:.{digits}f}" if x is not None else "—"


def _fmt_usd_m(x):
    if x is None:
        return "—"
    return f"${x/1000:.1f}B" if x >= 1000 else f"${x:.0f}M"


def _bt_note(bt):
    """動態總結：用最長區間的數字講重點，不寫死具體數字（回測資料每次跑會變）。"""
    longest = max(bt.keys())
    r = bt[longest]["rows"]
    ark_sharpe = max((r[tk]["sharpe"] or 0) for tk in FUNDS)
    bench_sharpe = max((r[tk]["sharpe"] or 0) for tk in BENCH)
    ark_mdd = min(r[tk]["mdd"] for tk in FUNDS)
    bench_mdd = max(r[tk]["mdd"] for tk in BENCH)
    verdict = ("風險調整後報酬（Sharpe/Sortino）都輸給大盤/QQQ" if ark_sharpe < bench_sharpe
               else "風險調整後報酬（Sharpe/Sortino）優於大盤/QQQ")
    return (f'<p class="note">拉長到 {longest} 年看，三檔 ARK 基金{verdict}，'
            f'且最大回撤達 {_pct(ark_mdd)}（大盤/QQQ 約 {_pct(bench_mdd)}），'
            f'代表同樣的報酬用了遠高於大盤的風險去換。短天期（3年/5年）的排序可能不同，'
            f'請往上對照各期間表格自行比較。</p>')


def _overview_html(snaps, bt, top10):
    cards = "".join(f"""<div class="fcard" data-fund="{tk}">
  <div class="fname">{FUND_LABEL[tk]}</div>
  <div class="fmeta">類別 {esc(snaps[tk]['category']) or '—'}　規模 {_fmt_usd_m(snaps[tk]['aum'])}
    費用率 {_pct_w(snaps[tk]['expense'], 2) if snaps[tk]['expense'] else '—'}</div>
</div>""" for tk in FUNDS)

    ov_head = "".join(f"<th>{esc(tk)} 權重</th>" for tk in FUNDS)
    ov_rows = "".join(
        f'<tr><td>{esc(r["symbol"])}</td><td>{esc(r["name"])}</td>'
        + "".join(f'<td class="num">{_pct_w(r["w"][tk])}</td>' for tk in FUNDS) + '</tr>'
        for r in top10)

    def _bt_table(period):
        rows = "".join(
            f'<tr data-fund="{"bench" if tk in BENCH else tk}">'
            f'<td>{FUND_LABEL.get(tk, BENCH_LABEL.get(tk, tk)).split(" · ")[0].split("（")[0]}</td>'
            f'<td class="num">{_pct(r["total_ret"])}</td><td class="num">{_pct(r["cagr"])}</td>'
            f'<td class="num">{_pct(r["vol"])}</td><td class="num">{_num(r["sharpe"])}</td>'
            f'<td class="num">{_num(r["sortino"])}</td><td class="num">{_pct(r["mdd"])}</td></tr>'
            for tk, r in period["rows"].items())
        return f"""<table class="dt bttable"><tr><th>標的</th><th>總報酬</th><th>年化報酬</th><th>年化波動</th>
    <th>Sharpe</th><th>Sortino</th><th>最大回撤</th></tr>{rows}</table>"""

    bt_sections = "".join(f"""
  <div class="sub2" style="margin-top:20px">{years} 年回測（{bt[years]['start']} ~ {bt[years]['end']}，約 {bt[years]['years']} 年）
    <span class="note">無風險利率簡化用 0%</span></div>
  {_bt_table(bt[years])}""" for years in sorted(bt.keys()))

    return f"""
<section class="sec">
  <div class="sechd"><h2>總覽</h2></div>
  <div class="fgrid">{cards}</div>

  <div class="sub2" style="margin-top:16px">前 {len(top10)} 大持股（跨三檔基金合計權重排序，橫槓代表該基金未持有）</div>
  <table class="dt"><tr><th>代號</th><th>名稱</th>{ov_head}</tr>{ov_rows}</table>
  {bt_sections}
  {_bt_note(bt)}
</section>"""


def _sector_html(snaps):
    def bars(tk):
        secs = sorted(snaps[tk]["sectors"].items(), key=lambda x: -x[1])
        return "".join(
            f'<div class="sbar"><span class="sn">{esc(k)}</span>'
            f'<div class="sbg"><div class="sfg" style="width:{v*100:.1f}%"></div></div>'
            f'<span class="sv num">{v*100:.1f}%</span></div>' for k, v in secs if v > 0)

    return f"""
<section class="sec">
  <div class="sechd"><h2>產業方向</h2></div>
  <p class="note">ark-funds.com 的每日持股 CSV 被 Cloudflare 擋掉，抓不到歷史快照做「這個月 vs 上個月」
    的精確比對；下面是<b>現在的產業曝險快照</b>，配合下方 ARK 官方近期公開的持股異動報導（有查證來源），
    交叉解讀「錢正在往哪個方向移動」——不是我自己猜的百分比。</p>
  <div class="fgrid2">{"".join(f'<div data-fund="{tk}"><div class="sub2">{FUND_LABEL[tk]}</div>{bars(tk)}</div>' for tk in FUNDS)}</div>

  <div class="sub2" style="margin-top:20px">近期公開持股異動（查證來源見文末）</div>
  <div class="movegrid">{"".join(f'''<div class="movecard">
    <div class="mvt">{esc(t)}</div><div class="mvd">{esc(d)}</div></div>'''
    for t, d in ARK_OWN_VIEW["recent_moves"])}</div>
</section>"""


def _bigideas_html():
    items = "".join(f'''<div class="bicard">
    <div class="bit">{esc(t)}</div><div class="bid">{esc(d)}</div></div>'''
    for t, d in ARK_OWN_VIEW["big_ideas"])
    return f"""
<section class="sec">
  <div class="sechd"><h2>ARK 自己的觀點——Big Ideas 2026</h2></div>
  {items}
</section>"""


def _holdings_earnings_html(top10):
    tickers = [r for r in top10 if r["symbol"] not in EXCLUDE_PRIVATE]
    print(f"重倉個股法說會重點（{len(tickers)} 檔）…")
    blocks = []
    for r in tickers:
        tk = r["symbol"]
        print(f"  {tk} …", end=" ", flush=True)
        try:
            html, _ = EC.build(tk, "", "")
        except Exception as e:
            html = ""
            print(f"失敗：{e}")
        fund_attr = esc(" ".join(r["held_by"]))
        if html:
            print("完成")
            blocks.append(f'<div class="ecard2" data-fund="{fund_attr}"><div class="ecard2hd">{esc(tk)}'
                          f'<span class="ecard2fund">{esc("/".join(r["held_by"]))}</span></div>{html}</div>')
        else:
            print("（無資料，跳過）")
            blocks.append(f'<div class="ecard2" data-fund="{fund_attr}"><div class="ecard2hd">{esc(tk)}'
                          f'<span class="ecard2fund">{esc("/".join(r["held_by"]))}</span></div>'
                          f'<p class="note">查無最新法說會逐字稿摘要。</p></div>')
    return f"""
<section class="sec">
  <div class="sechd"><h2>重倉個股法說會重點</h2>
    <span class="cnt">三檔基金合計權重前 {len(tickers)} 大（不含私募的 SPCX）</span></div>
  <div class="ecard2grid">{"".join(blocks)}</div>
</section>"""


def _synthesis_html():
    return """
<section class="sec">
  <div class="sechd"><h2>綜合解讀</h2></div>
  <div class="card">
  <p><b>方向是否一致：大致一致，但要拆開看。</b> ARK 近期的加碼動作（特斯拉、Coinbase、
  Robinhood、Amazon）跟 Big Ideas 2026 講的「AI+自駕+加密+電商」敘事對得上；賣出台積電跟
  百度則是「從半導體製造龍頭/中國曝險撤出、轉向下游應用」的具體動作，不是單純故事。</p>
  <p><b>但回測數據給了一個必要的提醒</b>：過去長期來看三檔 ARK 基金的風險調整後報酬（Sharpe/Sortino）
  都不如大盤跟 QQQ，最大回撤是大盤的兩倍以上。也就是說「ARK 說的故事」跟「ARK 過去的績效效率」
  是兩件事——故事聽起來對，不代表用 ARK 的方式參與這個故事是效率最好的做法。</p>
  <p><b>怎麼用這份報告</b>：與其直接買 ARK 系列基金跟著它的高波動度一起承受，不如把這份報告
  當「主題雷達」——ARK 在加碼什麼方向，可以自己去該方向裡挑風險調整後報酬更好的標的
  （例如直接持有 TSLA/COIN 本身，而不是透過基金承擔額外一層基金層級的波動）。</p>
  </div>
</section>"""


def build():
    print(f"抓 {'/'.join(FUNDS)} 持股快照 …")
    snaps = {tk: _fund_snapshot(tk) for tk in FUNDS}
    print("3/5/10 年回測 …")
    bt = _backtest_all()
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    src_html = "".join(f'<li><a href="{u}" target="_blank" rel="noopener">{esc(t)}</a></li>'
                       for t, u in SOURCES)

    top10 = _top_combined(snaps)[:TOP_N]

    body = "".join([
        _overview_html(snaps, bt, top10),
        _sector_html(snaps),
        _bigideas_html(),
        _holdings_earnings_html(top10),
        _synthesis_html(),
    ])

    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>ARK ETF 追蹤</title>
<style>{BASE_CSS}{CP.CSS}{FR.CSS}{TI.CSS}{EC.CSS}{CSS_EXTRA}</style></head><body><div class="wrap">
{header("ark", "ARK ETF 追蹤", f"{' + '.join(FUNDS)} · 產業方向／重倉法說會／3·5·10年回測 · 更新 {date}", NAV, "ark")}
<div class="ctrl" style="position:static;border:0;padding:0 0 12px;margin-bottom:0">
  <div class="seg" role="group" aria-label="切換 ARK 基金" id="fundSeg">
    <button data-f="ALL" aria-pressed="true">全部</button>
    {"".join(f'<button data-f="{tk}" aria-pressed="false">{tk}</button>' for tk in FUNDS)}
  </div>
  <p class="note" style="margin-top:8px">總覽卡片、產業曝險、每期回測表格、重倉個股法說會（依該股是否被選中基金持有）
    會依你選的基金篩選；前N大持股表跟 Big Ideas 觀點是跨基金整合內容，不受此篩選影響。</p>
</div>
{body}
<section class="sec"><div class="sechd"><h2>資料來源</h2></div>
<ul class="srclist">{src_html}</ul>
<p class="disc">本頁非投資建議，僅供研究參考。持股/產業曝險為 Yahoo Finance 即時快照，
會隨基金每日調倉變動；法說會摘要由本機 Claude 上網查證 Motley Fool 逐字稿彙整，
可能有遺漏或延遲，正式決策前請自行查核最新公開資訊。</p></section>
</div>
<script>
(function(){{
  var $=function(s){{return document.querySelector(s);}},$$=function(s){{return [].slice.call(document.querySelectorAll(s));}};
  function apply(f){{
    $$('[data-fund]').forEach(function(el){{
      var vs=el.dataset.fund.split(' ');
      var show=(f==='ALL'||vs.indexOf(f)!==-1||vs.indexOf('bench')!==-1);
      el.style.display=show?'':'none';
    }});
  }}
  $$('#fundSeg button').forEach(function(b){{
    b.onclick=function(){{
      $$('#fundSeg button').forEach(function(x){{x.setAttribute('aria-pressed',x===b);}});
      apply(b.dataset.f);
    }};
  }});
}})();
</script>
</body></html>"""
    return html


CSS_EXTRA = """
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:12px}
.fgrid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px;margin-top:10px}
.fcard{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.fname{font-weight:700;font-size:14px}
.fmeta{color:var(--muted);font-size:12px;margin-top:5px}
.dt{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
.dt th{text-align:left;color:var(--dim);font-size:11px;padding:6px 8px;border-bottom:1px solid var(--line)}
.dt td{padding:7px 8px;border-bottom:1px solid var(--line2)}
.dt td.num,.dt th:not(:first-child):not(:nth-child(2)){text-align:right}
.sub2{font-size:13px;font-weight:700;color:#93C5FD}
.note{color:var(--dim);font-size:12px;line-height:1.7;margin-top:8px}
.sbar{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:12.5px}
.sn{width:88px;flex-shrink:0;color:var(--muted)}
.sbg{flex:1;height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.sfg{height:100%;background:var(--accent)}
.sv{width:48px;text-align:right;flex-shrink:0}
.movegrid,.bicard{margin-top:10px}
.movecard{background:var(--surface);border:1px solid var(--line);border-radius:10px;
 padding:11px 13px;margin-bottom:8px}
.mvt{font-weight:700;font-size:13.5px;color:#F5B841}
.mvd{color:var(--muted);font-size:12.5px;margin-top:4px;line-height:1.6}
.bicard{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.bit{font-weight:700;font-size:13.5px;color:#F5B841}
.bid{color:var(--muted);font-size:12.5px;margin-top:4px;line-height:1.7}
.ecard2grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));
 gap:14px;margin-top:14px;align-items:start}
.ecard2{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px}
.ecard2hd{font-size:16px;font-weight:800;color:#F5B841;letter-spacing:.3px;
 padding-bottom:9px;margin-bottom:2px;border-bottom:1px solid var(--line2);
 display:flex;align-items:center;gap:8px}
.ecard2fund{font-size:10.5px;font-weight:600;color:var(--dim);background:var(--line);
 padding:2px 8px;border-radius:16px;letter-spacing:.2px}
.ecard2 .reality{border-top:0;margin-top:8px;padding-top:0}
.ecard2 .reality h3{display:none}
.ecard2 .techgrid{grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card p{margin:8px 0;font-size:13.5px;line-height:1.75;color:#C7D8EC}
.srclist{font-size:12.5px;line-height:2;color:var(--muted)}
.srclist a{color:#93C5FD}
.disc{color:var(--dim);font-size:11.5px;margin-top:14px;line-height:1.7}
.cnt{font-size:11.5px;color:var(--dim);background:var(--line);padding:2px 9px;border-radius:16px}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/ark.html")
    args = ap.parse_args()
    html = build()
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    open(args.output, "w", encoding="utf-8").write(html)
    print(f"✅ {args.output}")


if __name__ == "__main__":
    main()
