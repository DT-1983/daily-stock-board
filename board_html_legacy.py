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
               "AI 電力/核能", "太陽能", "Bitcoin→AI 機房", "玻璃基板/TGV"]
CHAIN_ICON = {"AI 伺服器": "🖥️", "矽光子/光通訊": "🔦", "機器人": "🤖",
              "低軌衛星": "🛰️", "AI 電力/核能": "⚡", "太陽能": "☀️",
              "Bitcoin→AI 機房": "⛏️", "玻璃基板/TGV": "🧊"}
SIG_CLASS = {"🔴": "sell", "🟢": "buy", "🔵": "hold", "🟡": "watch", "⚪": "watch"}


def _load_chain_themes():
    """讀 chain_themes.py 產的 {chain: 一句題材}；沒有就回空 dict（題材層可選）。"""
    try:
        d = json.load(open("chain_themes.json", encoding="utf-8"))
        return d.get("themes", {}), d.get("generated", "")
    except Exception:
        return {}, ""


CHAIN_THEMES, CHAIN_THEMES_TS = _load_chain_themes()


def _load_chain_reports():
    """讀每鏈深度解讀 HTML 片段 {chain: fragment}；手動維護、非必要。"""
    try:
        return json.load(open("chain_reports.json", encoding="utf-8"))
    except Exception:
        return {}


CHAIN_REPORTS = _load_chain_reports()


def _theme_html(theme):
    """題材層 render：新版 dict(catalyst/risk/watch) 做成可展開；舊版字串相容。"""
    if isinstance(theme, dict):
        cat = esc_tw(theme.get("catalyst", ""))
        extra = []
        if theme.get("risk"):
            extra.append(f'<span class="trisk">⚠️ 風險：{esc_tw(theme["risk"])}</span>')
        if theme.get("watch"):
            extra.append(f'<span class="twatch">👀 本週觀察：{esc_tw(theme["watch"])}</span>')
        if extra:
            return (f'<details class="theme"><summary>💡 {cat}</summary>'
                    f'{"".join(extra)}</details>')
        return f'<div class="theme">💡 {cat}</div>'
    return f'<div class="theme">💡 {esc_tw(theme)}</div>'

# 台股中文名（yfinance 給英文，這裡覆蓋）
TW_NAME = {
    "1503": "士電", "1504": "東元", "1513": "中興電", "1519": "華城", "1597": "直得",
    "1605": "華新", "2049": "上銀", "2308": "台達電", "2314": "台揚", "2317": "鴻海",
    "2345": "智邦", "2359": "所羅門", "2368": "金像電", "2454": "聯發科", "3017": "奇鋐",
    "3023": "信邦", "3081": "聯亞", "3105": "穩懋", "3163": "波若威", "3324": "雙鴻",
    "3363": "上詮", "3450": "聯鈞", "3491": "昇達科", "3576": "聯合再生", "4576": "大銀微",
    "4908": "前鼎", "5483": "中美晶", "6182": "合晶", "6271": "同欣電", "6285": "啟碁",
    "6443": "元晶", "8046": "南電",
    # 玻璃基板/TGV 鏈（2026-08-05 第 8 鏈）
    "3037": "欣興", "3189": "景碩", "3149": "正達", "8027": "鈦昇",
    "6664": "群翊", "1595": "川寶", "3055": "蔚華科", "4768": "晶呈科技",
    "3481": "群創", "3580": "友威科", "8064": "東捷",
    # 產業鏈定位快取補漏（2026-08-06）
    "1536": "和大", "2330": "台積電", "2356": "英業達", "2382": "廣達",
    "3231": "緯創", "4979": "華星光", "6188": "廣明", "6669": "緯穎",
    # 財報卡新增追蹤股補漏（2026-08-10）
    # 2026-08-13 修正：佳必琪代號當初打錯成6134——6134其實是萬旭電子(上櫃，跟佳必琪無關)，
    # FinMind TaiwanStockInfo 查證佳必琪真正代號是6197(上市)。
    "2313": "華通", "6197": "佳必琪",
    # 小孩持股台股財報卡補漏（2026-08-13）
    "2303": "聯電", "2850": "新產", "2881": "富邦金",
    "2882": "國泰金", "2884": "玉山金", "2891": "中信金",
    # TW_POOL全量補漏（2026-08-11，看板台股卡片顯示英文名）
    "2376": "技嘉", "3533": "嘉澤", "4540": "全球傳動",
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


def _align_rs(rs, n):
    """mansfield_rs_series 內部右對齊、長度可能比 closes 短，補 None 到長度一致
    （跟 backtest_position_sim.py 同一個坑同一個修法，2026-08-11）。"""
    if rs is None:
        return []
    pad = n - len(rs)
    vals = [None] * pad + list(rs) if pad > 0 else list(rs)
    return [None if (v is None or v != v) else round(float(v), 2) for v in vals]


def fetch_us_charts(tickers, bench="^GSPC", disp_days=252):
    """yf.download 批次抓美股走勢（比逐檔 Ticker.history 穩、不易限流）
    2026-08-11：期間 3mo→2y，附帶算 EXCEED CHARGE(squeeze) + RS(相對強弱，短線30日/長線1年)，
    供看板產業鏈明細跟財報卡一樣多兩張圖（用戶要求）。
    多抓一年當「暖機」：長線RS要250個交易日的均線，只抓1年的話前面一整年都算不出值、
    圖幾乎是空的——抓2年、算完指標後只裁回近1年(disp_days)顯示，圖表時間範圍不變，
    但長線RS從顯示範圍第一天就有值。"""
    from technical_indicators import squeeze_momentum, mansfield_rs_series
    charts = {}
    if not tickers:
        return charts
    try:
        data = yf.download(tickers, period="2y", group_by="ticker",
                           progress=False, threads=False, auto_adjust=True)
    except Exception:
        return charts
    try:
        bench_closes = yf.Ticker(bench).history(period="2y")["Close"].tolist()
    except Exception:
        bench_closes = []
    for t in tickers:
        try:
            h = data[t].dropna() if len(tickers) > 1 else data.dropna()
            closes = h["Close"].round(2).tolist()
            if not closes:
                continue
            highs = h["High"].round(2).tolist()
            lows = h["Low"].round(2).tolist()
            dates = [d.strftime("%m/%d") for d in h.index]
            n = len(closes)
            sq = squeeze_momentum(highs, lows, closes)
            rs_s = mansfield_rs_series(closes, bench_closes, 30) if bench_closes else None
            rs_l = mansfield_rs_series(closes, bench_closes, 250) if bench_closes else None
            st = supertrend(highs, lows, closes)
            mom = [None if (v is None or v != v) else round(float(v), 2) for v in sq["momentum"]] if sq else [None] * n
            sq_on = [None if (isinstance(v, float) and v != v) else bool(v) for v in sq["squeeze_on"]] if sq else [None] * n
            rs_s_a, rs_l_a = _align_rs(rs_s, n), _align_rs(rs_l, n)
            cut = max(0, n - disp_days)
            charts[t] = {"dates": dates[cut:], "close": closes[cut:],
                         "ma5": ma_series(closes, 5)[cut:], "ma10": ma_series(closes, 10)[cut:],
                         "ma20": ma_series(closes, 20)[cut:], "last": closes[-1],
                         "supertrend": {"st": st["st"][cut:], "dir": st["dir"][cut:]} if st else None,
                         "mom": mom[cut:], "sq_on": sq_on[cut:],
                         "rs_s": rs_s_a[cut:], "rs_l": rs_l_a[cut:]}
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
.theme{font-size:13px;color:#c9a86a;margin:2px 0 8px 14px;line-height:1.5}
details.theme>summary{cursor:pointer;list-style:none;color:#c9a86a}
details.theme>summary::-webkit-details-marker{display:none}
details.theme>summary::after{content:" ▾";color:#7a6a45;font-size:11px}
details.theme[open]>summary::after{content:" ▴"}
.theme .trisk,.theme .twatch{display:block;margin:4px 0 0 18px;font-size:12.5px;color:#9aa0a6}
.theme .trisk{color:#d99}
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
/* 產業深度解讀（按鈕開全螢幕彈窗） */
.rptbtn{display:block;width:calc(100% - 14px);text-align:left;margin:2px 0 10px 14px;background:#14171d;
 border:1px solid #2a2e35;border-radius:9px;color:#c9a86a;font-size:13.5px;font-weight:700;padding:10px 12px;cursor:pointer}
.rptbtn:hover{background:#1a1f27}
.rptbtn::after{content:" ⤢";color:#7a6a45}
.rptmodal{display:none;position:fixed;inset:0;background:#000d;z-index:100}
.rptmodal.on{display:block}
.rptbox{position:absolute;inset:0;background:#0f1115;display:flex;flex-direction:column}
.rpthead{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 16px;
 border-bottom:1px solid #2a2e35;background:#161b22;flex:0 0 auto}
.rpthead span{font-size:15px;font-weight:700}
.rptx{background:#262b33;border:0;color:#cfd3d8;font-size:15px;width:34px;height:34px;border-radius:8px;cursor:pointer;flex:0 0 auto}
.rptbody{flex:1 1 auto;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:8px 16px 40px}
.rpt{font-size:14px}
.rpt h2{font-size:15.5px;margin:18px 0 6px;border-left:3px solid #4a9eff;padding-left:9px}
.rpt p{margin:7px 0}
.rpt .note{background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;padding:8px 11px;font-size:13px;color:#cfd3d8;margin:9px 0}
.rpt .tldr{background:#12151b;border:1px solid #2a2e35;border-radius:10px;padding:12px 14px;margin:6px 0 16px}
.rpt .tldr .lab{font-size:11.5px;font-weight:700;letter-spacing:.5px;color:#8a8f98;margin-bottom:9px}
.rpt .tldr .row{display:flex;gap:8px;margin:8px 0;font-size:13.5px;align-items:flex-start}
.rpt .tldr .ic{flex:0 0 auto}
.rpt .tldr .r1{border-left:3px solid #4a9eff;padding-left:10px}
.rpt .tldr .r2{border-left:3px solid #3ddc84;padding-left:10px}
.rpt .tldr .r3{border-left:3px solid #ff5c5c;padding-left:10px}
.rpt .tldr b,.rpt td b,.rpt p b{color:#fff}
.rpt .tw{margin:9px 0}
.rpt table{border-collapse:collapse;width:100%;font-size:13px}
.rpt th,.rpt td{border-bottom:1px solid #2a2e35;padding:7px 9px;text-align:left;vertical-align:top}
.rpt th{background:#222831;color:#bcd2ff;font-weight:700}
.rpt .tag{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:9px;background:#262b33;color:#cfd3d8;margin-right:4px}
.rpt ol,.rpt ul{margin:7px 0;padding-left:20px}.rpt li{margin:5px 0}
.rpt .risk li b{color:#ffb4b4}
.rpt .watch li{list-style:none;margin-left:-14px}.rpt .watch li::before{content:"🎯 "}
.rpt .cap{background:#12151b;border:1px solid #2a2e35;border-radius:10px;padding:11px 13px;margin:12px 0 0}
.rpt .stat{display:flex;flex-wrap:wrap;gap:9px;margin:11px 0}
.rpt .stat .box{flex:1 1 150px;background:#1a1d23;border:1px solid #2a2e35;border-radius:9px;padding:10px 12px}
.rpt .stat .n{font-size:17px;font-weight:800;color:#6db3ff}
.rpt .stat .t{font-size:11.5px;color:#9aa0a6;margin-top:3px;line-height:1.4}
.rpt .bb{display:flex;flex-wrap:wrap;gap:11px;margin:9px 0}
.rpt .bb .col{flex:1 1 300px;border-radius:9px;padding:11px 13px}
.rpt .bull{background:#12251a;border:1px solid #295c3c}
.rpt .bear{background:#2a1618;border:1px solid #5c2f33}
.rpt .bb h4{margin:0 0 6px;font-size:13.5px}
.rpt .bull h4{color:#4ade80}.rpt .bear h4{color:#ff8a8a}
.rpt .bb ul{padding-left:17px;margin:4px 0}.rpt .bb li{font-size:13px;margin:5px 0}
.rpt details{margin:10px 0 0;border:1px solid #2a2e35;border-radius:8px;background:#161a20}
.rpt details>summary{cursor:pointer;color:#bcd2ff;font-size:13.5px;font-weight:700;padding:9px 11px;display:block;list-style:none}
.rpt details>summary::-webkit-details-marker{display:none}
.rpt details>summary::after{content:" ▾";color:#6b7280}
.rpt details[open]>summary::after{content:" ▴"}
.rpt .inr{padding:0 11px 11px}
.rpt .disc{color:#6b7280;font-size:11.5px;margin-top:16px;line-height:1.6}
.rpt .ln{margin:3px 0;font-size:12.5px;line-height:1.5}
.rpt .b{display:inline-block;font-size:10px;font-weight:700;padding:1px 8px;border-radius:7px;margin-right:6px}
.rpt .b.up{background:#12351f;color:#4ade80}
.rpt .b.dn{background:#3a1a1d;color:#ff8a8a}
.rpt .k{color:#c9a86a}
@media(max-width:620px){
 .rpt table{border:0}
 .rpt thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
 .rpt tbody tr{display:block;background:#1a1d23;border:1px solid #2a2e35;border-radius:9px;margin:0 0 9px;padding:3px 2px}
 .rpt tbody td{display:block;position:relative;border:0;border-bottom:1px solid #23272e;padding:6px 12px 6px 80px;min-height:31px}
 .rpt tbody tr td:last-child{border-bottom:0}
 .rpt tbody td::before{content:attr(data-label);position:absolute;left:11px;top:6px;width:60px;color:#8a8f98;font-size:11.5px;font-weight:700;line-height:1.55}
}
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

    # 財報懶人包導覽：掃 docs/ 有哪些 earnings_*.html（由 earnings_watch 在財報公布後產），
    # 依檔案修改時間新→舊排，只列最近 8 份。沒有就整段不顯示。
    earn_nav = ""
    try:
        import glob
        files = sorted(glob.glob("docs/earnings_*.html"), key=os.path.getmtime, reverse=True)[:8]
        if files:
            links = " ".join(
                f'<a href="{os.path.basename(f)}" style="color:#6db3ff">'
                f'{os.path.basename(f)[9:-5].replace("_", ".")}</a>' for f in files)
            earn_nav = f'<br>📊 <b>財報懶人包</b>：{links}'
    except Exception:
        pass

    body = []
    for i, c in enumerate(CHAIN_ORDER):
        us, tw = us_by.get(c, []), tw_by.get(c, [])
        if not us and not tw:
            continue
        body.append(f'<div class="chain" id="{i}">{CHAIN_ICON[c]} {c}'
                    f'<span class="cnt" data-mkt="US">美 {len(us)}</span>'
                    f'<span class="cnt hidden" data-mkt="TW">台 {len(tw)}</span></div>')
        theme = CHAIN_THEMES.get(c)
        if theme:
            body.append(_theme_html(theme))
        report = CHAIN_REPORTS.get(c)
        if report:
            body.append(
                f'<button class="rptbtn" onclick="document.getElementById(\'rm{i}\').classList.add(\'on\')">'
                f'📖 產業深度解讀</button>'
                f'<div class="rptmodal" id="rm{i}" onclick="if(event.target===this)this.classList.remove(\'on\')">'
                f'<div class="rptbox"><div class="rpthead"><span>{CHAIN_ICON[c]} {c} · 產業深度解讀</span>'
                f'<button class="rptx" onclick="document.getElementById(\'rm{i}\').classList.remove(\'on\')">✕</button>'
                f'</div><div class="rptbody">{report}</div></div></div>')
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
🏛️ <a href="buffett.html" style="color:#6db3ff">巴菲特價值清單（俗貴價+龍頭排名）</a>
🏇 <a href="portfolios.html" style="color:#6db3ff">策略賽馬模擬倉</a>{earn_nav}</div>
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
 <p class="sub" style="margin:8px 0 4px">守備清單不是人工挑的，是用三個客觀因子，每條產業鏈各取最強 8 檔自動篩出：</p>
 <p style="margin:4px 0;font-size:13.5px">① <b>市值</b>：規模越大越穩、越有流動性。<br>
  ② <b>成長</b>：美股看營收年增率、台股看<b>月營收 YoY</b>。<br>
  ③ <b>進場（資金流向）</b>：美股用 <b>OBV 能量潮</b>（量價同步看資金淨流入）；台股用 <b>法人 20 日買超÷均量</b>（相對值）。</p>
 <p class="sub" style="margin:8px 0 4px"><b>什麼是「進場因子」？為什麼不用「漲幅」？</b><br>
  「漲多」≠「資金真的在買」——股價可能量縮虛漲（沒人接、隨時回落）。進場因子改看「<b>量價是否同步</b>」：<br>
  ‧ <b>美股 OBV（能量潮）</b>：上漲日把成交量加進去、下跌日減掉，累積出「<b>淨買盤量</b>」。再除以自身均量正規化（−1～+1），<br>
  　<b>＋＝放量上攻（資金真的在進）、−＝出貨</b>。size-neutral：小股不會因量小被大股輾壓。<br>
  ‧ <b>台股法人籌碼</b>：外資＋投信（聰明錢）近 20 日<b>淨買超股數 ÷ 近 20 日均量</b>。除以均量是關鍵——<br>
  　看「<b>買超佔成交比重</b>」而非絕對張數，<b>10 萬張流通的股票買 1 萬張，比 100 萬張買 2 萬張更猛</b>。<br>
  例：台積電市值最大、營收也成長，但外資近期<b>大賣</b>、量價背離，進場因子扣分，這次就沒進前 8——<b>看真實資金，不看名氣</b>。</p>
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
<div class="sub" style="margin-top:20px">產生時間 {datetime.now():%Y-%m-%d %H:%M} · 美股 yfinance / 台股 FinMind · 判讀 Claude(本機) · 守備清單客觀篩選(市值+成長+進場資金流)</div>
</div><script>const CHARTS={charts_json};{JS}
mkt('US');  // 初始藏台股卡片
</script></body></html>"""

    # 2026-07-31 修：原本是 `args.output or OBIS路徑`，workflow 一定會帶 -o docs/index.html，
    # 所以 obis 那份「永遠不會產生」（巴菲特頁/賽馬頁都是寫兩份，只有看板漏掉）。
    # 改成兩份都寫：docs/ 給 GitHub Pages、obis 給 Google Drive 手機/外出看。
    # obis 固定檔名（不帶日期），才不會每天長一個新檔、也才有穩定連結。
    targets = [args.output] if args.output else []
    targets.append(os.path.join(OBIS, "美台股看板.html"))
    for out in targets:
        if not out:
            continue
        try:
            if os.path.dirname(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "w", encoding="utf-8").write(html)
            print(f"✅ HTML 看板已存:{out}")
        except Exception as e:
            print(f"⚠️ 寫入 {out} 失敗（跳過）:{e}")   # Actions 上沒有 obis 路徑，正常


if __name__ == "__main__":
    main()
