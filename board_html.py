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


import html as _html


def esc_tw(s):
    return _html.escape(str(s if s is not None else ""))


def ma_series(closes, n):
    return [round(sum(closes[i + 1 - n:i + 1]) / n, 2) if i + 1 >= n else None
            for i in range(len(closes))]


def supertrend(highs, lows, closes, period=10, mult=3.0):
    """標準 SuperTrend（ATR 基礎，Wilder 平滑）。回傳 {st:[值], dir:[1多/-1空]}。"""
    n = len(closes)
    if n < period + 1 or not highs or not lows:
        return None
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(n)]
    st = [None] * n
    dr = [None] * n
    up = [None] * n
    lo = [None] * n
    for i in range(period - 1, n):
        if atr[i] is None:
            continue
        bu, bl = hl2[i] + mult * atr[i], hl2[i] - mult * atr[i]
        if i == period - 1 or up[i - 1] is None:
            up[i], lo[i] = bu, bl
            dr[i] = 1 if closes[i] >= hl2[i] else -1
        else:
            up[i] = bu if (bu < up[i - 1] or closes[i - 1] > up[i - 1]) else up[i - 1]
            lo[i] = bl if (bl > lo[i - 1] or closes[i - 1] < lo[i - 1]) else lo[i - 1]
            if closes[i] > up[i - 1]:
                dr[i] = 1
            elif closes[i] < lo[i - 1]:
                dr[i] = -1
            else:
                dr[i] = dr[i - 1]
        st[i] = lo[i] if dr[i] == 1 else up[i]
    return {"st": [round(x, 2) if x is not None else None for x in st], "dir": dr}


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
            highs = h["High"].round(2).tolist()
            lows = h["Low"].round(2).tolist()
            charts[t] = {"dates": [d.strftime("%m/%d") for d in h.index], "close": closes,
                         "ma5": ma_series(closes, 5), "ma10": ma_series(closes, 10),
                         "ma20": ma_series(closes, 20), "last": closes[-1],
                         "supertrend": supertrend(highs, lows, closes)}
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
.pill{font-size:13px;padding:3px 10px;border-radius:12px;background:#262b33;cursor:pointer;user-select:none}
.pill.act{background:#4a9eff;color:#fff}.pill:hover{background:#333a44}
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
.cbar{display:flex;gap:6px;margin-bottom:6px}
.cbtn{font-size:12.5px;padding:3px 10px;border-radius:8px;border:1px solid #2a2e35;background:#1c2128;color:#8a8f98;cursor:pointer}
.cbtn.on{background:#4a9eff;color:#fff;border-color:#4a9eff}
.rail{position:fixed;right:6px;top:80px;display:flex;flex-direction:column;gap:5px;z-index:20}
.rail a,.rail button{font-size:11px;width:40px;height:40px;border-radius:50%;border:1px solid #2a2e35;
 background:#1c2128cc;color:#cfd3d8;text-decoration:none;display:flex;align-items:center;justify-content:center;cursor:pointer}
.hidden{display:none!important}
"""

JS = """
let curMkt='US',curSig='all';
function setMkt(m){curMkt=m;document.querySelectorAll('.toggle button').forEach(b=>b.classList.toggle('on',b.dataset.m===m));curSig='all';apply();}
function setSig(s){curSig=(curSig===s?'all':s);apply();}
function mkt(m){setMkt(m);}
function apply(){
 document.querySelectorAll('.cnt[data-mkt],.ovrow[data-mkt]').forEach(e=>e.classList.toggle('hidden',e.dataset.mkt!==curMkt));
 document.querySelectorAll('details.card').forEach(c=>{
  const ok=c.dataset.mkt===curMkt&&(curSig==='all'||c.classList.contains(curSig));
  c.classList.toggle('hidden',!ok);});
 document.querySelectorAll('.ovrow:not(.hidden) .pill[data-sig]').forEach(p=>p.classList.toggle('act',p.dataset.sig===curSig));
 document.querySelectorAll('.chain').forEach(h=>{
  let n=h.nextElementSibling,any=false;
  while(n&&!n.classList.contains('chain')){if(n.classList.contains('card')&&!n.classList.contains('hidden'))any=true;n=n.nextElementSibling;}
  h.classList.toggle('hidden',!any);});
}
function expandAll(x){document.querySelectorAll('details.card:not(.hidden)').forEach(d=>d.open=x);}
function showChart(btn,tk){
 const box=btn.nextElementSibling;
 if(box.style.display==='block'){box.style.display='none';return;}
 box.style.display='block'; if(box.dataset.done)return; box.dataset.done=1;
 const d=CHARTS[tk]; if(!d){box.innerHTML='<span class=sub>無走勢資料</span>';return;}
 // 切換鈕：均線 / SuperTrend 各自開關
 const bar=document.createElement('div');bar.className='cbar';
 const hasST=d.supertrend&&d.supertrend.st;
 bar.innerHTML='<button class="cbtn" data-g="ma">📊 均線 MA</button>'+
   (hasST?'<button class="cbtn on" data-g="st">📈 SuperTrend</button>':'');
 box.appendChild(bar);
 const c=document.createElement('canvas');box.appendChild(c);
 const ds=[
   {label:'收盤',data:d.close,borderColor:'#4a9eff',borderWidth:2,pointRadius:0,_g:'price'},
   {label:'MA5',data:d.ma5,borderColor:'#3ddc84',borderWidth:1,pointRadius:0,_g:'ma',hidden:true},
   {label:'MA10',data:d.ma10,borderColor:'#f0b429',borderWidth:1,pointRadius:0,_g:'ma',hidden:true},
   {label:'MA20',data:d.ma20,borderColor:'#888',borderWidth:1,pointRadius:0,_g:'ma',hidden:true}];
 if(hasST){ds.push({label:'SuperTrend',data:d.supertrend.st,borderWidth:2.6,pointRadius:0,spanGaps:false,_g:'st',
   segment:{borderColor:ctx=>{const dir=d.supertrend.dir[ctx.p1DataIndex];return dir===1?'#3ddc84':(dir===-1?'#ff5c5c':'#8a8f98');}}});}
 const chart=new Chart(c,{type:'line',data:{labels:d.dates,datasets:ds},
  options:{responsive:true,plugins:{legend:{display:false}},
   scales:{x:{ticks:{color:'#6b7280',maxTicksLimit:6,font:{size:10}}},y:{ticks:{color:'#6b7280',font:{size:10}}}}}});
 bar.querySelectorAll('.cbtn').forEach(b=>b.onclick=()=>{
   const on=b.classList.toggle('on');
   chart.data.datasets.forEach((dd,i)=>{if(dd._g===b.dataset.g)chart.setDatasetVisibility(i,on);});
   chart.update();});
}
"""


def card_us(sig, tk, nm, block, has_chart, mdc, score_val="—"):
    cls = SIG_CLASS.get(sig, "watch")
    detail = mdc.convert(re.sub(r"(?s)^##.*?\n", "", block, count=1)); mdc.reset()
    chart = (f'<button class="chartbtn" onclick="showChart(this,\'{tk}\')">📈 走勢圖</button>'
             f'<div class="chartbox"></div>') if has_chart else ""
    return (f'<details class="card {cls}" data-mkt="US"><summary>'
            f'<span class="tk">{sig} {tk}</span><span class="nm">{nm}</span>'
            f'<span class="badge">評分 {score_val}</span>'
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
    g = lambda k: r.get(k, "—")
    chg = r.get("chg")
    chgs = f'{chg:+.2f}%' if isinstance(chg, (int, float)) else "—"
    quote = ('<h3>📈 當日行情</h3><table>'
             '<tr><th>收盤</th><th>開</th><th>高</th><th>低</th><th>漲跌</th><th>量(張)</th></tr>'
             f'<tr><td>{g("last")}</td><td>{g("open")}</td><td>{g("high")}</td>'
             f'<td>{g("low")}</td><td>{chgs}</td><td>{g("vol")}</td></tr></table>')
    plan = ('<h3>🎯 作戰計劃</h3><table>'
            f'<tr><th>理想買點</th><td>{g("buy_point")}</td></tr>'
            f'<tr><th>停損</th><td>{g("stop_loss")}</td></tr>'
            f'<tr><th>目標</th><td>{g("target")}</td></tr></table>') if r.get("buy_point") else ""
    fin = ('<h3>💼 財務摘要</h3><table>'
           '<tr><th>EPS</th><th>毛利率</th><th>PER</th><th>PBR</th><th>殖利率</th></tr>'
           f'<tr><td>{g("eps")}</td><td>{g("gross_margin")}%</td><td>{g("pe")}</td>'
           f'<td>{g("pb")}</td><td>{g("yield")}%</td></tr></table>')
    chk = ""
    if r.get("checklist"):
        items = "".join(f"<li>{esc_tw(x)}</li>" for x in r["checklist"])
        chk = f'<h3>✅ 檢查清單</h3><ul>{items}</ul>'
    detail = (f'{quote}{chart}'
              f'<p><b>理由</b>：{esc_tw(r.get("reason",""))}</p>'
              f'<p class="sub"><b>風險</b>：{esc_tw(r.get("risk",""))}</p>'
              f'{plan}{fin}{chk}')
    nm = TW_NAME.get(r["code"], r.get("name", r["code"]))
    return (f'<details class="card {cls}" data-mkt="TW"><summary>'
            f'<span class="tk">{sig} {r["code"]}</span><span class="nm">{nm}</span>'
            f'<span class="badge">評分 {r.get("score","—")}</span>'
            f'<span class="oneliner">{esc_tw(r.get("oneliner",""))}</span></summary>'
            f'<div class="detail">{chips}{detail}</div></details>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    raw = convert(open(args.input, encoding="utf-8").read())
    summary, stocks = parse_report(raw)
    # 美股評分在摘要區（代號): action | 評分 X），抓出來對照
    us_score = dict(re.findall(r"\(([A-Z\.]+)\)\*\*[:：][^|]*\|\s*評分\s*(\d+)", summary))
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
            st = supertrend(r.get("highs"), r.get("lows"), cl) if r.get("highs") and r.get("lows") else None
            charts[r["code"]] = {"dates": r.get("dates", []), "close": cl,
                                 "ma5": ma_series(cl, 5), "ma10": ma_series(cl, 10),
                                 "ma20": ma_series(cl, 20), "last": cl[-1], "supertrend": st}

    date = datetime.now().strftime("%Y-%m-%d")
    mdc = md.Markdown(extensions=["tables", "sane_lists", "nl2br"])

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
            body.append(card_us(sig, tk, nm, block, tk in charts, mdc, us_score.get(tk, "—")))
        for r in tw:
            body.append(card_tw(r, r["code"] in charts))

    summary_html = mdc.convert(summary) if summary else ""; mdc.reset()
    charts_json = json.dumps(charts, ensure_ascii=False)

    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{date} 美台股看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>{CSS}</style></head><body><div class="wrap" id="top">
<h1>🎯 {date} 產業鏈看板</h1>
<div class="sub">7 條產業鏈 · 美股(AI決策)＋台股(籌碼+AI決策) · 點卡片展開、點走勢圖載入<br>
🏛️ <a href="buffett.html" style="color:#6db3ff">巴菲特價值清單（俗貴價+龍頭排名）→</a></div>
<div class="toggle">
 <button data-m="US" class="on" onclick="mkt('US')">🇺🇸 美股</button>
 <button data-m="TW" onclick="mkt('TW')">🇹🇼 台股</button>
</div>
<div class="legend"><span><b>燈號</b></span>
 <span>🟢 買進</span><span>🔴 賣出</span><span>🔵 持有</span><span>⚪/🟡 觀望（同義）</span>
 <span>　外資/投信為近 12 日買賣超(張)</span></div>
<div class="overview"><b>📊 今日摘要（點選可篩選）</b>
 <div class="ovrow" data-mkt="US">
  <span class="pill act" data-sig="all" onclick="setSig('all')">美股 {len(stocks)} 檔</span>
  <span class="pill" data-sig="buy" onclick="setSig('buy')">🟢買進 {sig_cnt['🟢']}</span>
  <span class="pill" data-sig="sell" onclick="setSig('sell')">🔴賣出 {sig_cnt['🔴']}</span>
  <span class="pill" data-sig="hold" onclick="setSig('hold')">🔵持有 {sig_cnt['🔵']}</span>
  <span class="pill" data-sig="watch" onclick="setSig('watch')">⚪🟡觀望 {sig_cnt['🟡']+sig_cnt['⚪']}</span></div>
 <div class="ovrow hidden" data-mkt="TW">
  <span class="pill act" data-sig="all" onclick="setSig('all')">台股 {len(tw_data)} 檔</span>
  <span class="pill" data-sig="buy" onclick="setSig('buy')">🟢買進 {tw_cnt['🟢']}</span>
  <span class="pill" data-sig="sell" onclick="setSig('sell')">🔴賣出 {tw_cnt['🔴']}</span>
  <span class="pill" data-sig="watch" onclick="setSig('watch')">⚪觀望 {tw_cnt['⚪']}</span></div>
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
  ③ <b>進場（資金流向）</b>：美股用 <b>OBV 能量潮</b>（量價同步看資金淨流入）；台股用 <b>法人 20 日買超÷均量</b>（相對值）。</p>
 <p class="sub" style="margin:8px 0 4px"><b>什麼是「進場因子」？為什麼不用「漲幅」？</b><br>
  「漲多」≠「資金真的在買」——股價可能量縮虛漲（沒人接、隨時回落）。進場因子改看「<b>量價是否同步</b>」：<br>
  ‧ <b>美股 OBV（能量潮）</b>：上漲日把成交量加進去、下跌日減掉，累積出「<b>淨買盤量</b>」。再除以自身均量正規化（−1～+1），<br>
  　<b>＋＝放量上攻（資金真的在進）、−＝出貨</b>。size-neutral：小股不會因量小被大股輾壓。<br>
  ‧ <b>台股法人籌碼</b>：外資＋投信（聰明錢）近 20 日<b>淨買超股數 ÷ 近 20 日均量</b>。除以均量是關鍵——<br>
  　看「<b>買超佔成交比重</b>」而非絕對張數，<b>10 萬張流通的股票買 1 萬張，比 100 萬張買 2 萬張更猛</b>。<br>
  例：台積電市值最大、營收也成長，但外資近期<b>大賣</b>、量價背離，進場因子扣分，這次就沒進前 6——<b>看真實資金，不看名氣</b>。</p>
 <p class="sub" style="margin:8px 0 0"><b>多久掃一次？會變嗎？</b><br>
  建議<b>每週掃一次</b>（如每週一）。市值與成長變化慢（大型股穩定在榜），但<b>籌碼面天天變</b>，<br>
  所以<b>核心大型股會固定、邊緣名單隨資金流向輪動</b>。掃太頻繁（每天）過度換股；每月一次又錯過法人輪動。</p>
 <hr style="border-color:#2a2e35;margin:14px 0">
 <p style="margin:4px 0;font-size:13.5px"><b>🚦 燈號（AI 操作建議）</b><br>
  🟢 買進　🔴 賣出　🔵 持有　⚪／🟡 觀望<br>
  <span class="sub">註：⚪ 和 🟡 是<b>同一個意思（觀望）</b>，工具在「摘要統計」用 🟡、「個股卡片」用 ⚪，無差別。</span></p>
 <p style="margin:8px 0 0;font-size:13.5px"><b>💯 評分高低是什麼？</b><br>
  AI 綜合技術面（均線/量能）＋ 基本面 ＋ 籌碼/消息，給 <b>0～100 分</b>：<br>
  <b>分數越高＝越偏多（買進傾向）</b>；<b>越低＝越偏空（賣出傾向）</b>；<b>50 左右＝中性觀望</b>。<br>
  <span class="sub">參考級距：80+ 強勢看多｜60-79 偏多｜40-59 中性｜20-39 偏空｜20 以下 強勢看空。評分是「相對強弱」參考，非保證。</span></p>
 <hr style="border-color:#2a2e35;margin:14px 0">
 <p style="margin:4px 0;font-size:13.5px"><b>📈 走勢圖的 SuperTrend 是什麼？</b><br>
  SuperTrend 是<b>趨勢方向指標</b>（跟 TradingView 內建版同款，參數 ATR 10、倍數 3）。原理：<br>
  ① 先算 <b>ATR</b>（平均真實波動，衡量近期震盪幅度）。<br>
  ② 在價格上下各畫一條「軌道」＝ 中價 ± 倍數×ATR。<br>
  ③ 收盤<b>站上</b>軌道→翻<b style="color:#3ddc84">多頭（線轉綠、走在價格下方當支撐）</b>；<b>跌破</b>→翻<b style="color:#ff5c5c">空頭（線轉紅、走在價格上方當壓力）</b>。<br>
  <b>怎麼看</b>：線<span style="color:#3ddc84">綠</span>＝順勢偏多、線<span style="color:#ff5c5c">紅</span>＝偏空；<b>顏色一翻就是趨勢反轉訊號</b>。比單看均線更快抓到轉折。<br>
  <span class="sub">圖例可點：預設顯示 收盤＋MA20＋SuperTrend，想看 MA5/MA10 點圖例打開即可。SuperTrend 為趨勢輔助，非買賣建議。</span></p>
</div>
<div class="sub" style="margin-top:20px">產生時間 {datetime.now():%Y-%m-%d %H:%M} · 美股 yfinance+Gemini / 台股 FinMind+Gemini · 守備清單客觀篩選(市值+成長+進場資金流)</div>
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
