"""美股/台股看板 HTML（v3）：7 鏈分區 + 燈號 + 走勢圖 + 台美切換 + 跳轉導覽

美股：daily_stock_analysis 報告 + yfinance 走勢
台股：tw_analysis.json（FinMind 籌碼 + Gemini 決策）+ FinMind 走勢

用法:python board_html.py reports/report_YYYYMMDD.md [-o out.html]
"""
import sys
import os
import re
import json
import argparse
from datetime import datetime
import markdown as md
import yfinance as yf
from tw_report import convert

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"
TW_JSON = "tw_analysis.json"

def _load_chain_map():
    """US ticker→chain：優先讀客觀篩選 screen_result.json，無則 fallback。"""
    fb = {"NVDA": "AI 伺服器", "AVGO": "AI 伺服器", "ALAB": "矽光子/光通訊",
          "CRDO": "矽光子/光通訊", "RKLB": "低軌衛星", "ASTS": "低軌衛星",
          "FSLR": "太陽能", "CORZ": "Bitcoin→AI 機房", "IREN": "Bitcoin→AI 機房",
          "CEG": "AI 電力/核能", "VST": "AI 電力/核能", "TSLA": "機器人"}
    try:
        d = json.load(open("screen_result.json", encoding="utf-8"))
        m = {}
        for chain, lst in d["us"].items():
            for x in lst:
                m.setdefault(x["code"], chain)   # 同股跨鏈時取第一個鏈
        return m or fb
    except Exception:
        return fb


CHAIN_MAP = _load_chain_map()
CHAIN_ORDER = ["AI 伺服器", "矽光子/光通訊", "機器人", "低軌衛星",
               "AI 電力/核能", "太陽能", "Bitcoin→AI 機房"]
CHAIN_ICON = {"AI 伺服器": "🖥️", "矽光子/光通訊": "🔦", "機器人": "🤖",
              "低軌衛星": "🛰️", "AI 電力/核能": "⚡", "太陽能": "☀️",
              "Bitcoin→AI 機房": "⛏️"}
SIG_CLASS = {"🔴": "sell", "🟢": "buy", "🔵": "hold", "🟡": "watch", "⚪": "watch"}

# 台股中文名（yfinance 給英文，這裡覆蓋）
TW_NAME = {
    "1503": "士電", "1504": "東元", "1513": "中興電", "1519": "華城", "1597": "直得",
    "1605": "華新", "2049": "上銀", "2308": "台達電", "2314": "台揚", "2317": "鴻海",
    "2345": "智邦", "2359": "所羅門", "2368": "金像電", "2454": "聯發科", "3017": "奇鋐",
    "3023": "信邦", "3081": "聯亞", "3105": "穩懋", "3163": "波若威", "3324": "雙鴻",
    "3363": "上詮", "3450": "聯鈞", "3491": "昇達科", "3576": "聯合再生", "4576": "大銀微",
    "4908": "前鼎", "5483": "中美晶", "6182": "合晶", "6271": "同欣電", "6285": "啟碁",
    "6443": "元晶", "8046": "南電",
}


def ma_series(closes, n):
    return [round(sum(closes[i + 1 - n:i + 1]) / n, 2) if i + 1 >= n else None
            for i in range(len(closes))]


def fetch_us_charts(tickers):
    """yf.download 批次抓美股走勢（比逐檔 Ticker.history 穩、不易限流）"""
    charts = {}
    if not tickers:
        return charts
    try:
        data = yf.download(tickers, period="3mo", group_by="ticker",
                           progress=False, threads=False, auto_adjust=True)
    except Exception:
        return charts
    for t in tickers:
        try:
            h = data[t].dropna() if len(tickers) > 1 else data.dropna()
            closes = h["Close"].round(2).tolist()
            if not closes:
                continue
            charts[t] = {"dates": [d.strftime("%m/%d") for d in h.index], "close": closes,
                         "ma5": ma_series(closes, 5), "ma10": ma_series(closes, 10),
                         "ma20": ma_series(closes, 20), "last": closes[-1]}
        except Exception:
            pass
    return charts


def parse_report(text):
    parts = re.split(r"(?m)^## ", text)
    summary, stocks = "", []
    for p in parts:
        if "分析結果摘要" in p[:20] or "分析结果摘要" in p[:20] or p.startswith("📊"):
            summary = p
        else:
            m = re.match(r"\s*([🔴🟢🔵🟡⚪])?\s*(.+?)\s*\(([A-Z\.]+)\)", p)
            if m:
                # (sig, ticker, name, block) — ticker 在前，對齊下游解包
                stocks.append((m.group(1) or "⚪", m.group(3).split(".")[0],
                               m.group(2).strip(), "## " + p))
    return summary, stocks


def oneliner(b):
    m = re.search(r"一句話決策\*\*[:：]\s*(.+)", b)
    return m.group(1).strip() if m else ""


def score(b):
    m = re.search(r"評分\s*(\d+)", b)
    return m.group(1) if m else "—"


CSS = """
*{box-sizing:border-box}
body{font-family:"Microsoft JhengHei","PingFang TC",-apple-system,sans-serif;margin:0;
 background:#0f1115;color:#e6e6e6;line-height:1.6;font-size:15px}
.wrap{max-width:980px;margin:0 auto;padding:16px 56px 16px 16px}
h1{font-size:20px;margin:6px 0}.sub{color:#9aa0a6;font-size:13px}
.toggle{display:inline-flex;background:#1c2128;border-radius:18px;padding:3px;margin:12px 0}
.toggle button{border:0;background:transparent;color:#9aa0a6;padding:6px 18px;border-radius:15px;
 font-size:14px;cursor:pointer;font-weight:600}.toggle button.on{background:#4a9eff;color:#fff}
.legend{background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;padding:8px 12px;margin:8px 0;
 font-size:13px;display:flex;flex-wrap:wrap;gap:14px}.legend b{color:#fff}
.overview{background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;padding:10px 12px;margin:10px 0}
.ovrow{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.pill{font-size:13px;padding:3px 10px;border-radius:12px;background:#262b33}
.chain{margin:20px 0 6px;font-size:17px;border-left:4px solid #4a9eff;padding-left:10px;
 display:flex;align-items:center;gap:8px}
.cnt{font-size:12px;color:#9aa0a6;background:#1c2128;padding:1px 8px;border-radius:10px}
.card{background:#1a1d23;border:1px solid #2a2e35;border-radius:10px;margin:8px 0;overflow:hidden}
.card.sell{border-left:4px solid #ff5c5c}.card.buy{border-left:4px solid #3ddc84}
.card.hold,.card.watch{border-left:4px solid #8a8f98}
summary{cursor:pointer;padding:11px 13px;list-style:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
summary::-webkit-details-marker{display:none}
.tk{font-weight:700;font-size:16px}.nm{color:#9aa0a6;font-size:13px}
.px{margin-left:auto;font-size:13px;color:#cfd3d8}
.badge{font-size:13px;padding:2px 8px;border-radius:10px;background:#262b33}
.oneliner{flex-basis:100%;color:#cfd3d8;font-size:13.5px;margin-top:2px}
.detail{padding:0 13px 13px;border-top:1px solid #2a2e35}
.detail h3{font-size:14px;margin:12px 0 4px;color:#bcd2ff}
.detail table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}
.detail th,.detail td{border:1px solid #2a2e35;padding:5px 8px;text-align:left}.detail th{background:#222831}
.detail blockquote{border-left:3px solid #4a9eff;margin:6px 0;padding:2px 10px;color:#cfd3d8}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{font-size:12.5px;padding:2px 9px;border-radius:10px;background:#222831}
.chip.pos{color:#3ddc84}.chip.neg{color:#ff7676}
.chartbtn{margin:8px 0;font-size:13px;background:#262b33;border:0;color:#bcd2ff;padding:5px 12px;border-radius:8px;cursor:pointer}
.chartbox{display:none;margin:6px 0}
.rail{position:fixed;right:6px;top:80px;display:flex;flex-direction:column;gap:5px;z-index:20}
.rail a,.rail button{font-size:11px;width:40px;height:40px;border-radius:50%;border:1px solid #2a2e35;
 background:#1c2128cc;color:#cfd3d8;text-decoration:none;display:flex;align-items:center;justify-content:center;cursor:pointer}
.hidden{display:none!important}
"""

JS = """
function mkt(m){
 document.querySelectorAll('[data-mkt]').forEach(e=>e.classList.toggle('hidden',e.dataset.mkt!==m));
 document.querySelectorAll('.toggle button').forEach(b=>b.classList.toggle('on',b.dataset.m===m));
}
function expandAll(x){document.querySelectorAll('details.card:not(.hidden)').forEach(d=>d.open=x);}
function showChart(btn,tk){
 const box=btn.nextElementSibling;
 if(box.style.display==='block'){box.style.display='none';return;}
 box.style.display='block'; if(box.dataset.done)return; box.dataset.done=1;
 const d=CHARTS[tk]; if(!d){box.innerHTML='<span class=sub>無走勢資料</span>';return;}
 const c=document.createElement('canvas');box.appendChild(c);
 new Chart(c,{type:'line',data:{labels:d.dates,datasets:[
   {label:'收盤',data:d.close,borderColor:'#4a9eff',borderWidth:2,pointRadius:0},
   {label:'MA5',data:d.ma5,borderColor:'#3ddc84',borderWidth:1,pointRadius:0},
   {label:'MA10',data:d.ma10,borderColor:'#f0b429',borderWidth:1,pointRadius:0},
   {label:'MA20',data:d.ma20,borderColor:'#ff5c5c',borderWidth:1,pointRadius:0}]},
  options:{responsive:true,plugins:{legend:{labels:{color:'#cfd3d8',boxWidth:12,font:{size:11}}}},
   scales:{x:{ticks:{color:'#6b7280',maxTicksLimit:6,font:{size:10}}},y:{ticks:{color:'#6b7280',font:{size:10}}}}}});
}
"""


def card_us(sig, tk, nm, block, has_chart, mdc):
    cls = SIG_CLASS.get(sig, "watch")
    detail = mdc.convert(re.sub(r"(?s)^##.*?\n", "", block, count=1)); mdc.reset()
    chart = (f'<button class="chartbtn" onclick="showChart(this,\'{tk}\')">📈 走勢圖</button>'
             f'<div class="chartbox"></div>') if has_chart else ""
    return (f'<details class="card {cls}" data-mkt="US"><summary>'
            f'<span class="tk">{sig} {tk}</span><span class="nm">{nm}</span>'
            f'<span class="badge">評分 {score(block)}</span>'
            f'<span class="oneliner">{oneliner(block)}</span></summary>'
            f'<div class="detail">{chart}{detail}</div></details>')


def card_tw(r, has_chart):
    sig = r.get("emoji", "⚪")
    cls = SIG_CLASS.get(sig, "watch")
    fc = "pos" if (r.get("foreign") or 0) >= 0 else "neg"
    tc = "pos" if (r.get("trust") or 0) >= 0 else "neg"
    chips = (f'<div class="chips">'
             f'<span class="chip {fc}">外資 {r.get("foreign","—")} 張</span>'
             f'<span class="chip {tc}">投信 {r.get("trust","—")} 張</span>'
             f'<span class="chip">月營收YoY {r.get("rev_yoy","—")}%</span>'
             f'<span class="chip">MA5 {r.get("ma5","—")} / MA20 {r.get("ma20","—")}</span></div>')
    chart = (f'<button class="chartbtn" onclick="showChart(this,\'{r["code"]}\')">📈 走勢圖</button>'
             f'<div class="chartbox"></div>') if has_chart else ""
    detail = (f'<p><b>理由</b>：{r.get("reason","")}</p>'
              f'<p class="sub"><b>風險</b>：{r.get("risk","")}</p>')
    nm = TW_NAME.get(r["code"], r.get("name", r["code"]))
    return (f'<details class="card {cls}" data-mkt="TW"><summary>'
            f'<span class="tk">{sig} {r["code"]}</span><span class="nm">{nm}</span>'
            f'<span class="badge">評分 {r.get("score","—")}</span>'
            f'<span class="oneliner">{r.get("oneliner","")}</span></summary>'
            f'<div class="detail">{chips}{chart}{detail}</div></details>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    raw = convert(open(args.input, encoding="utf-8").read())
    summary, stocks = parse_report(raw)
    us_by = {c: [] for c in CHAIN_ORDER}
    for sig, tk, nm, block in stocks:
        if CHAIN_MAP.get(tk):
            us_by[CHAIN_MAP[tk]].append((sig, tk, nm, block))

    # 台股:讀 tw_analysis.json
    tw_data = []
    if os.path.exists(TW_JSON):
        tw_data = json.load(open(TW_JSON, encoding="utf-8"))
    tw_by = {c: [] for c in CHAIN_ORDER}
    for r in tw_data:
        tw_by.setdefault(r["chain"], []).append(r)

    # 走勢:美股 yf.download 批次 + 台股用 FinMind closes
    charts = fetch_us_charts([tk for _, tk, _, _ in stocks])
    for r in tw_data:
        cl = r.get("closes")
        if cl:
            charts[r["code"]] = {"dates": r.get("dates", []), "close": cl,
                                 "ma5": ma_series(cl, 5), "ma10": ma_series(cl, 10),
                                 "ma20": ma_series(cl, 20), "last": cl[-1]}

    date = datetime.now().strftime("%Y-%m-%d")
    mdc = md.Markdown(extensions=["tables", "sane_lists"])

    sig_cnt = {"🟢": 0, "🔴": 0, "🔵": 0, "🟡": 0, "⚪": 0}
    for sig, *_ in stocks:
        sig_cnt[sig] = sig_cnt.get(sig, 0) + 1
    tw_cnt = {"🟢": 0, "🔴": 0, "⚪": 0, "🔵": 0}
    for r in tw_data:
        tw_cnt[r.get("emoji", "⚪")] = tw_cnt.get(r.get("emoji", "⚪"), 0) + 1

    nav = "".join(f'<a href="#{i}">{CHAIN_ICON[c]}</a>' for i, c in enumerate(CHAIN_ORDER)
                  if us_by.get(c) or tw_by.get(c))

    body = []
    for i, c in enumerate(CHAIN_ORDER):
        us, tw = us_by.get(c, []), tw_by.get(c, [])
        if not us and not tw:
            continue
        body.append(f'<div class="chain" id="{i}">{CHAIN_ICON[c]} {c}'
                    f'<span class="cnt" data-mkt="US">美 {len(us)}</span>'
                    f'<span class="cnt hidden" data-mkt="TW">台 {len(tw)}</span></div>')
        for sig, tk, nm, block in us:
            body.append(card_us(sig, tk, nm, block, tk in charts, mdc))
        for r in tw:
            body.append(card_tw(r, r["code"] in charts))

    summary_html = mdc.convert(summary) if summary else ""; mdc.reset()
    charts_json = json.dumps(charts, ensure_ascii=False)

    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{date} 美台股看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>{CSS}</style></head><body><div class="wrap" id="top">
<h1>🎯 {date} 產業鏈看板</h1>
<div class="sub">7 條產業鏈 · 美股(AI決策)＋台股(籌碼+AI決策) · 點卡片展開、點走勢圖載入</div>
<div class="toggle">
 <button data-m="US" class="on" onclick="mkt('US')">🇺🇸 美股</button>
 <button data-m="TW" onclick="mkt('TW')">🇹🇼 台股</button>
</div>
<div class="legend"><span><b>燈號</b></span>
 <span>🟢 買進</span><span>🔴 賣出</span><span>🔵 持有</span><span>🟡/⚪ 觀望</span>
 <span>　外資/投信為近 12 日買賣超(張)</span></div>
<div class="overview"><b>📊 今日摘要</b>
 <div class="ovrow" data-mkt="US">
  <span class="pill">美股 {len(stocks)} 檔</span><span class="pill">🟢買進 {sig_cnt['🟢']}</span>
  <span class="pill">🔴賣出 {sig_cnt['🔴']}</span><span class="pill">🔵持有 {sig_cnt['🔵']}</span>
  <span class="pill">🟡⚪觀望 {sig_cnt['🟡']+sig_cnt['⚪']}</span></div>
 <div class="ovrow hidden" data-mkt="TW">
  <span class="pill">台股 {len(tw_data)} 檔</span><span class="pill">🟢買進 {tw_cnt['🟢']}</span>
  <span class="pill">🔴賣出 {tw_cnt['🔴']}</span><span class="pill">⚪觀望 {tw_cnt['⚪']}</span></div>
</div>
<div class="rail">
 <button onclick="expandAll(true)" title="全展開">⤢</button>
 <button onclick="expandAll(false)" title="全收合">⤡</button>
 {nav}<a href="#top" title="回頂">↑</a></div>
<div data-mkt="US"><details><summary class="sub">📋 美股 AI 決策摘要（點展開）</summary>{summary_html}</details></div>
{''.join(body)}
<div class="overview" style="margin-top:24px">
 <b>📖 這份清單怎麼來的（客觀篩選說明）</b>
 <p class="sub" style="margin:8px 0 4px">守備清單不是人工挑的，是用三個客觀因子，每條產業鏈各取最強 6 檔自動篩出：</p>
 <p style="margin:4px 0;font-size:13.5px">① <b>市值</b>：規模越大越穩、越有流動性。<br>
  ② <b>成長</b>：美股看營收年增率、台股看<b>月營收 YoY</b>。<br>
  ③ <b>進場（籌碼面）</b>：美股用 3 個月股價動能代理；台股用 <b>法人近 20 日買超</b>。</p>
 <p class="sub" style="margin:8px 0 4px"><b>什麼是「籌碼面」？</b><br>
  籌碼＝「股票在誰手上、誰在買誰在賣」。台股每天公布外資、投信（基金）等<b>法人大戶</b>的買賣張數。<br>
  法人連續<b>大買</b>＝聰明錢進場、後勢看好；<b>大賣</b>＝資金撤離。這是看價量看不到的「<b>大戶資金流向</b>」。<br>
  例：台積電市值最大、營收也成長，但因外資近期<b>大賣逾 5 萬張</b>，籌碼面扣分，這次就沒進前 6——這正是籌碼面的價值：<b>看真實資金，不看名氣</b>。</p>
 <p class="sub" style="margin:8px 0 0"><b>多久掃一次？會變嗎？</b><br>
  建議<b>每週掃一次</b>（如每週一）。市值與成長變化慢（大型股穩定在榜），但<b>籌碼面天天變</b>，<br>
  所以<b>核心大型股會固定、邊緣名單隨資金流向輪動</b>。掃太頻繁（每天）過度換股；每月一次又錯過法人輪動。</p>
</div>
<div class="sub" style="margin-top:20px">產生時間 {datetime.now():%Y-%m-%d %H:%M} · 美股 yfinance+Gemini / 台股 FinMind+Gemini · 守備清單客觀篩選(市值+成長+籌碼)</div>
</div><script>const CHARTS={charts_json};{JS}
mkt('US');  // 初始藏台股卡片
</script></body></html>"""

    out = args.output or os.path.join(OBIS, f"{date}_美台股看板.html")
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(html)
    print(f"✅ HTML 看板已存:{out}")


if __name__ == "__main__":
    main()
