# -*- coding: utf-8 -*-
"""產業輪動雷達 RRG（Relative Rotation Graph）

2026-08-25 建立。緣由：老墨的 XQ 官方工具「PROJECT RX 產業輪動雷達」
（mophyfei/MOFI_XQ repo）示範了這張圖的價值——資金輪動到哪個產業一眼看穿，
比在單一個股上猜方向踏實。他的版本吃 XQ 自己維護的台股族群/細產業指數，
我們沒有那份資料，改用可行的替代籃子：

  美股：11 檔 SPDR 類股 ETF（XLK/XLF/...）——業界標準做法，
        StockCharts 自己的美股 Sector RRG 用的也是這組，免另外聚合。
  台股：沒有現成的類股指數 ticker 可抓（yfinance 查無 ^TW 開頭的官方分類指數），
        改成自己聚合：TradingView sector 分類下，市值前 N 大成分股等權組成籃子指數。

RS-Ratio / RS-Momentum 公式：JdK 原始方法論不公開精確公式（連 RRG 官網自己都不公布），
這裡採業界廣泛引用的開源版本（BennyThadikaran/RRG-Lite wiki 記載的公式）：

    RS          = 籃子指數 ÷ 基準指數 × 100
    RS-Ratio    = 100 + (RS − MA_N(RS)) ÷ StdDev_N(RS)
    RS-Momentum = 100 + z-score(ROC_N(RS))            ← 對 RS 的漲跌幅做同一套正規化

N 是可調期數（20/60/120/240 日，跟老墨的「計算週期」對齊）；他只曝露一個參數，
這裡比照解讀成「z-score 視窗」與「ROC 回看窗」共用同一個 N。

⚠️ 這是照公開文獻重建的方法論，跟老墨官方版數字不會逐點對上——
他的商品池、確切平滑方式都是他的（.DSTX 是編譯格式讀不到），這裡求的是「同一套邏輯」
不是「數字一致」。象限走向、100 中心值、輪動方向這些概念性的東西才是核心。
"""
import io
import json
import os
import sys
import time

import numpy as np
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from tradingview_screener import Query, col

PERIODS = [20, 60, 120, 240]
HIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "industry_rotation_history.json")
HIST_KEEP_WEEKS = 26          # 軌跡尾巴最多留半年份，太長圖會糊成一團

# 美股：SPDR 11 大類股 ETF。免聚合、免猜產業分類，直接抓歷史價格。
SPDR_SECTORS = {
    "XLK": "科技", "XLF": "金融", "XLV": "醫療保健", "XLY": "非必需消費",
    "XLP": "必需消費", "XLE": "能源", "XLI": "工業", "XLB": "原物料",
    "XLU": "公用事業", "XLRE": "房地產", "XLC": "通訊服務",
}
US_BENCHMARK = "^GSPC"          # 跟 technical_indicators._benchmark 美股基準一致
TW_BENCHMARK = "^TWII"
TW_BASKET_SIZE = 8              # 每個台股產業取市值前 8 大聚合成籃子（等權）
TW_MIN_MEMBERS = 3              # 成分股不足 3 檔的產業籃子雜訊太大，跳過


# ── 資料：抓籃子的歷史價格序列 ──────────────────────────────────────────

def _fetch_closes(ticker, period="3y"):
    """單檔歷史收盤價。3年緩衝是為了 N=240 的 z-score 還要再疊 ROC 回看窗，
    不留夠緩衝前面一大段會算不出東西（跟財報卡 RS 視窗那次踩過的暖機不足是同一種坑）。"""
    try:
        h = yf.Ticker(ticker).history(period=period)
        if h.empty:
            return None, None
        return h.index.tolist(), h["Close"].tolist()
    except Exception as e:
        print(f"  [industry_rotation] {ticker} 抓取失敗：{e}")
        return None, None


def _tw_sector_members(min_market_cap=3e9):
    """台股各 sector 市值前 TW_BASKET_SIZE 大成分股。用 TradingView 一次性快照，
    不逐檔查——這一步快（幾秒），真正貴的是後面逐檔抓歷史價格。"""
    base = Query().set_markets("taiwan")
    q = base.select("name", "sector", "market_cap_basic", "exchange", "close").where(
        col("market_cap_basic") >= min_market_cap,
        col("close") >= 5.0,
        col("exchange").isin(["TWSE", "TPEX"]),
    )
    count, df = q.limit(3000).get_scanner_data()
    if df is None or df.empty:
        return {}
    df["ticker"] = df["name"].astype(str) + df["exchange"].map({"TWSE": ".TW", "TPEX": ".TWO"}).fillna(".TW")
    out = {}
    for sector, grp in df.groupby("sector"):
        if not sector or str(sector).lower() == "nan":
            continue
        top = grp.sort_values("market_cap_basic", ascending=False).head(TW_BASKET_SIZE)
        if len(top) >= TW_MIN_MEMBERS:
            out[sector] = top["ticker"].tolist()
    return out


def _basket_index(member_closes_list):
    """多檔收盤價序列（各自日期可能不完全對齊）→ 等權聚合成一條籃子指數（基期=100）。
    用「每日報酬率等權平均」而非「價格直接平均」——避免高價股的絕對價格量級蓋過其他成分股，
    這是編制指數的標準做法（跟直接平均價格是兩回事，後者會被股價位數不同的成分股扭曲）。
    """
    # 先把每檔轉成 pandas Series 對齊日期（外部已用同市場、同期間抓，索引通常一致；
    # 用 reindex + ffill 處理個別股票偶爾缺一天的情形，不要整檔因為一天缺值就丟掉）
    import pandas as pd
    series_list = [s for s in member_closes_list if s is not None and len(s) > 60]
    if len(series_list) < TW_MIN_MEMBERS:
        return None
    all_idx = sorted(set().union(*[set(s.index) for s in series_list]))
    aligned = [s.reindex(all_idx).ffill() for s in series_list]
    rets = pd.concat([a.pct_change() for a in aligned], axis=1).mean(axis=1, skipna=True)
    idx = (1 + rets.fillna(0)).cumprod() * 100
    idx.iloc[0] = 100.0
    return idx


# ── RS-Ratio / RS-Momentum（查證公式，見檔頭）───────────────────────────

def _zscore_plus100(series, window):
    ma = series.rolling(window).mean()
    sd = series.rolling(window).std(ddof=0)
    return 100 + (series - ma) / sd


def rs_ratio_momentum(basket, bench, periods=PERIODS):
    """回 {period: {"ratio": pd.Series, "momentum": pd.Series}}，索引為日期。
    整段序列都回傳（不是只取最新值）——要畫軌跡尾巴一定要有歷史。"""
    import pandas as pd
    common = basket.index.intersection(bench.index)
    if len(common) < max(periods) + 20:
        return None
    b, k = basket.reindex(common), bench.reindex(common)
    rs = (b / k) * 100
    out = {}
    for n in periods:
        ratio = _zscore_plus100(rs, n)
        roc = rs.pct_change(n) * 100
        momentum = _zscore_plus100(roc, n)
        out[n] = {"ratio": ratio, "momentum": momentum}
    return out


def quadrant(ratio, momentum):
    """RRG 四象限，順時針：改善→領先→弱化→落後→(回改善)。"""
    if ratio is None or momentum is None or np.isnan(ratio) or np.isnan(momentum):
        return None
    if ratio >= 100 and momentum >= 100:
        return "leading"      # 領先
    if ratio < 100 and momentum >= 100:
        return "improving"    # 改善
    if ratio < 100 and momentum < 100:
        return "lagging"      # 落後
    return "weakening"        # 弱化


QUADRANT_LABEL = {"leading": "領先", "improving": "改善", "lagging": "落後", "weakening": "弱化"}
QUADRANT_COLOR = {"leading": "#ff5277", "improving": "#25e6ff", "lagging": "#8fb0d6", "weakening": "#ffb020"}


# ── 快照組裝：算出每個籃子在 4 個週期下的最新座標 ─────────────────────────

def build_market_snapshot(market):
    """market: "us" 或 "tw"。回 {sector_key: {"name":.., "periods": {20:{ratio,momentum,quadrant},...},
    "size": 市值代理值}}，算不出來的籃子直接跳過（不用 0 硬湊）。"""
    if market == "us":
        bench_h = yf.Ticker(US_BENCHMARK).history(period="3y")
        if bench_h.empty:
            print("  [industry_rotation] 美股基準抓取失敗，跳過整個美股快照")
            return {}
        bench = bench_h["Close"]
        out = {}
        for tk, name in SPDR_SECTORS.items():
            h = yf.Ticker(tk).history(period="3y")
            if h.empty:
                print(f"  [industry_rotation] {tk} 抓取失敗，跳過")
                continue
            rm = rs_ratio_momentum(h["Close"], bench)
            if rm is None:
                continue
            periods = {}
            for n in PERIODS:
                r, m = rm[n]["ratio"].iloc[-1], rm[n]["momentum"].iloc[-1]
                if np.isnan(r) or np.isnan(m):
                    continue
                periods[n] = {"ratio": round(float(r), 2), "momentum": round(float(m), 2),
                              "quadrant": quadrant(r, m)}
            if periods:
                out[tk] = {"name": name, "periods": periods, "size": 1.0}
        return out

    if market == "tw":
        bench_h = yf.Ticker(TW_BENCHMARK).history(period="3y")
        if bench_h.empty:
            print("  [industry_rotation] 台股基準抓取失敗，跳過整個台股快照")
            return {}
        bench = bench_h["Close"]
        members = _tw_sector_members()
        out = {}
        for sector, tks in members.items():
            closes, mcaps = [], []
            for tk in tks:
                h = yf.Ticker(tk).history(period="3y")
                if h.empty:
                    continue
                closes.append(h["Close"])
            basket = _basket_index(closes)
            if basket is None:
                print(f"  [industry_rotation] {sector} 成分股資料不足（<{TW_MIN_MEMBERS}檔），跳過")
                continue
            rm = rs_ratio_momentum(basket, bench)
            if rm is None:
                continue
            periods = {}
            for n in PERIODS:
                r, m = rm[n]["ratio"].iloc[-1], rm[n]["momentum"].iloc[-1]
                if np.isnan(r) or np.isnan(m):
                    continue
                periods[n] = {"ratio": round(float(r), 2), "momentum": round(float(m), 2),
                              "quadrant": quadrant(r, m)}
            if periods:
                out[sector] = {"name": SECTOR_TW_LABEL.get(sector, sector),
                               "periods": periods, "size": len(closes)}
        return out

    raise ValueError(f"未知市場：{market}")


SECTOR_TW_LABEL = {   # TradingView sector 英文 → 繁中（跟 buffett_html_legacy.SECTOR_TW 同一套語彙，這裡是TV自己的20分類不是GICS，名字對不上不能直接共用那份）
    "Commercial Services": "商業服務", "Communications": "通訊", "Consumer Durables": "耐久消費品",
    "Consumer Non-Durables": "非耐久消費品", "Consumer Services": "消費服務",
    "Distribution Services": "流通服務", "Electronic Technology": "電子科技",
    "Energy Minerals": "能源礦業", "Finance": "金融", "Health Services": "健康服務",
    "Health Technology": "健康科技", "Industrial Services": "工業服務",
    "Miscellaneous": "其他", "Non-Energy Minerals": "非能源礦業",
    "Process Industries": "製程工業", "Producer Manufacturing": "生產製造",
    "Retail Trade": "零售貿易", "Technology Services": "科技服務",
    "Transportation": "運輸", "Utilities": "公用事業",
}


# ── 歷史存檔：給軌跡尾巴用 ────────────────────────────────────────────

def load_history():
    if not os.path.exists(HIST_PATH):
        return {"us": [], "tw": []}
    try:
        with open(HIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"us": [], "tw": []}


def append_history(hist, market, snapshot, date_str):
    """把這次快照疊進歷史，並裁掉太舊的（軌跡尾巴不用留太長，留了也看不清）。"""
    hist.setdefault(market, [])
    # 同一天重跑會產生重複點——先移除同一天的舊紀錄再疊新的，不是每次都無限累加
    hist[market] = [row for row in hist[market] if row.get("date") != date_str]
    hist[market].append({"date": date_str, "snapshot": snapshot})
    hist[market].sort(key=lambda r: r["date"])
    if len(hist[market]) > HIST_KEEP_WEEKS:
        hist[market] = hist[market][-HIST_KEEP_WEEKS:]
    return hist


def save_history(hist):
    tmp = HIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
    os.replace(tmp, HIST_PATH)


# ── HTML 渲染（跟 ark_report.py 同款：BASE_CSS + header + click-selector）────

def _bubble_data(snapshot, period):
    pts = []
    for key, d in snapshot.items():
        p = d["periods"].get(period)
        if not p:
            continue
        pts.append({"key": key, "name": d["name"], "ratio": p["ratio"], "momentum": p["momentum"],
                    "quadrant": p["quadrant"], "size": d.get("size", 1.0)})
    return pts


def _trail_data(hist_rows, market_key, period, max_points=8):
    """某一籃子過去幾週的座標序列，給軌跡尾巴用。歷史累積不足時就是短尾巴或沒有，
    不是 bug——這功能本來就要跑幾週才有東西可畫。"""
    out = []
    for row in hist_rows[-max_points:]:
        d = row.get("snapshot", {}).get(market_key)
        if not d:
            continue
        p = d.get("periods", {}).get(str(period)) or d.get("periods", {}).get(period)
        if p:
            out.append({"date": row["date"], "ratio": p["ratio"], "momentum": p["momentum"]})
    return out


def render_html(snap_us, snap_tw, hist):
    import json as _json
    from board_theme import BASE_CSS, header, NAV, esc

    payload = {
        "us": {str(n): _bubble_data(snap_us, n) for n in PERIODS},
        "tw": {str(n): _bubble_data(snap_tw, n) for n in PERIODS},
        "trail_us": {str(n): {k: _trail_data(hist.get("us", []), k, n) for k in snap_us} for n in PERIODS},
        "trail_tw": {str(n): {k: _trail_data(hist.get("tw", []), k, n) for k in snap_tw} for n in PERIODS},
    }
    date = time.strftime("%Y-%m-%d %H:%M")

    quad_note = (
        'X軸 <b>RS-Ratio 相對強弱</b>、Y軸 <b>RS-Momentum 強弱變化率</b>，兩軸中心值皆為 100。'
        '四象限順時針輪動：'
        f'<b style="color:{QUADRANT_COLOR["improving"]}">改善</b> → '
        f'<b style="color:{QUADRANT_COLOR["leading"]}">領先</b> → '
        f'<b style="color:{QUADRANT_COLOR["weakening"]}">弱化</b> → '
        f'<b style="color:{QUADRANT_COLOR["lagging"]}">落後</b> → 回到改善。'
        '<b>「改善→領先」的轉折是資金剛轉強的甜蜜點</b>，值得優先注意。'
    )
    period_btns = "".join(
        f'<button data-p="{n}" aria-pressed="{"true" if n == 20 else "false"}">{n}日</button>'
        for n in PERIODS)

    head_html = ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 '<meta name="robots" content="noindex"><title>產業輪動雷達</title>'
                 '<style>' + BASE_CSS + CSS_EXTRA + '</style></head><body><div class="wrap">')
    hdr = header("rotation", "產業輪動雷達",
                 f"RRG（Relative Rotation Graph）· 美股11大類股(SPDR ETF) + 台股{len(snap_tw)}個TradingView產業籃子"
                 f" · 更新 {esc(date)}（每週六隨全市場重掃）", NAV, "rotation")
    note_html = (
        '<div class="note">' + quad_note + '<br>'
        '資料源：美股用 11 檔 SPDR 類股 ETF（業界標準籃子）；台股沒有官方類股指數可直接抓，'
        f'改成 TradingView 產業分類下市值前 {TW_BASKET_SIZE} 大成分股等權聚合。'
        '公式為業界公開重建版（非老墨官方精確值），數字不會跟他的工具逐點對上，方法論一致。<br>'
        '<span style="color:var(--muted)">軌跡尾巴需要累積幾週資料才看得出來，剛上線時多半只有一個點是正常的。</span>'
        '</div>'
    )
    ctrl_html = (
        '<div class="ctrl">'
        '<div class="seg" role="group" aria-label="切換市場" id="mktSeg">'
        '<button data-m="us" aria-pressed="true">美股</button>'
        '<button data-m="tw" aria-pressed="false">台股</button></div>'
        f'<div class="seg" role="group" aria-label="切換週期" id="perSeg">{period_btns}</div>'
        '</div>'
        '<div class="rrgwrap"><div class="rrgbox"><canvas id="rrgChart"></canvas></div>'
        '<div class="rrgrank" id="rrgRank"></div></div>'
        '<p class="disc">RRG 是產業/籃子層級的相對強弱統計工具，不是個股買賣訊號，'
        '不構成投資建議。台股籃子由少數大型股等權聚合，會被成分股個別異動放大，'
        '僅供研究參考，正式決策前請自行查核。</p></div>'
    )

    script_html = _rrg_script(payload)
    return head_html + hdr + note_html + ctrl_html + script_html + "</body></html>"


def _rrg_script(payload):
    import json as _json
    lines = []
    lines.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>')
    lines.append("<script>")
    lines.append("window.RRG_DATA = " + _json.dumps(payload, ensure_ascii=False) + ";")
    lines.append("var rrgChart = null, curM = 'us', curP = '20';")
    lines.append("var QCOLOR = " + _json.dumps(QUADRANT_COLOR, ensure_ascii=False) + ";")
    lines.append("var QLABEL = " + _json.dumps(QUADRANT_LABEL, ensure_ascii=False) + ";")
    lines.append("""
function quadrantBgPlugin() {
  return {
    id: 'quadrantBg',
    beforeDraw: function(chart) {
      var ctx = chart.ctx, area = chart.chartArea;
      var xScale = chart.scales.x, yScale = chart.scales.y;
      var midX = xScale.getPixelForValue(100), midY = yScale.getPixelForValue(100);
      ctx.save();
      ctx.fillStyle = 'rgba(37,230,255,.05)'; ctx.fillRect(area.left, area.top, midX-area.left, midY-area.top);
      ctx.fillStyle = 'rgba(255,82,119,.06)'; ctx.fillRect(midX, area.top, area.right-midX, midY-area.top);
      ctx.fillStyle = 'rgba(143,176,214,.05)'; ctx.fillRect(area.left, midY, midX-area.left, area.bottom-midY);
      ctx.fillStyle = 'rgba(255,176,32,.06)'; ctx.fillRect(midX, midY, area.right-midX, area.bottom-midY);
      ctx.strokeStyle = '#2a3550'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(midX, area.top); ctx.lineTo(midX, area.bottom);
      ctx.moveTo(area.left, midY); ctx.lineTo(area.right, midY); ctx.stroke();
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#5f80a6';
      ctx.fillText('改善 ▲', area.left+6, area.top+14);
      ctx.fillText('領先 ▲', midX+6, area.top+14);
      ctx.fillText('落後 ▼', area.left+6, area.bottom-6);
      ctx.fillText('弱化 ▼', midX+6, area.bottom-6);
      ctx.restore();
    }
  };
}

function draw() {
  var pts = (window.RRG_DATA[curM] || {})[curP] || [];
  var trailKey = 'trail_' + curM;
  var trails = (window.RRG_DATA[trailKey] || {})[curP] || {};
  if (rrgChart) rrgChart.destroy();

  var bubbleDs = {
    label: '目前位置',
    data: pts.map(function(p) { return {x: p.ratio, y: p.momentum, r: 6 + Math.min(p.size, 10)}; }),
    backgroundColor: pts.map(function(p) { return (QCOLOR[p.quadrant] || '#8fb0d6') + 'cc'; }),
    borderColor: '#0a1222', borderWidth: 1.5
  };
  var trailDs = Object.keys(trails).map(function(k) {
    var seq = trails[k];
    if (!seq || seq.length < 2) return null;
    var cur = pts.find(function(p){ return p.key === k; });
    var line = seq.map(function(s) { return {x: s.ratio, y: s.momentum}; });
    if (cur) line.push({x: cur.ratio, y: cur.momentum});
    return {
      type: 'line', data: line,
      borderColor: 'rgba(139,160,200,.35)', borderWidth: 1.2, pointRadius: 1.5,
      pointBackgroundColor: 'rgba(139,160,200,.5)', showLine: true, fill: false, order: 5
    };
  }).filter(Boolean);

  rrgChart = new Chart(document.getElementById('rrgChart'), {
    type: 'bubble',
    data: {datasets: [bubbleDs].concat(trailDs)},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {callbacks: {label: function(ctx) {
          var p = pts[ctx.dataIndex];
          return p ? (p.name + '：RS-Ratio ' + p.ratio + '／RS-Momentum ' + p.momentum + '（' + QLABEL[p.quadrant] + '）') : '';
        }}}
      },
      scales: {
        x: {title: {display:true, text:'RS-Ratio 相對強弱', color:'#8fb0d6'}, ticks:{color:'#5f80a6'}, grid:{color:'#16223A'}},
        y: {title: {display:true, text:'RS-Momentum 強弱變化率', color:'#8fb0d6'}, ticks:{color:'#5f80a6'}, grid:{color:'#16223A'}}
      }
    },
    plugins: [quadrantBgPlugin()]
  });

  var rank = pts.slice().sort(function(a,b){ return (b.ratio+b.momentum)-(a.ratio+a.momentum); });
  document.getElementById('rrgRank').innerHTML = rank.map(function(p) {
    return '<div class="rrgrow"><span class="dot" style="background:'+(QCOLOR[p.quadrant]||'#8fb0d6')+'"></span>'+
      '<span class="nm">'+p.name+'</span>'+
      '<span class="qv">'+QLABEL[p.quadrant]+'</span>'+
      '<span class="num">'+p.ratio.toFixed(1)+' / '+p.momentum.toFixed(1)+'</span></div>';
  }).join('') || '<div class="rrgrow">（本次無資料）</div>';
}

document.getElementById('mktSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#mktSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curM = b.dataset.m; draw();
});
document.getElementById('perSeg').addEventListener('click', function(e) {
  var b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#perSeg button').forEach(function(x){x.setAttribute('aria-pressed', x===b);});
  curP = b.dataset.p; draw();
});
draw();
</script>""")
    return "\n".join(lines)


CSS_EXTRA = """
.rrgwrap{display:grid;grid-template-columns:1.6fr 1fr;gap:14px;margin-top:12px}
.rrgbox{height:520px;background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:10px}
.rrgrank{background:#0a1222;border:1px solid #16223A;border-radius:12px;padding:10px;
 max-height:520px;overflow-y:auto}
.rrgrow{display:flex;align-items:center;gap:8px;padding:7px 4px;border-bottom:1px solid #131c30;font-size:12.5px}
.rrgrow .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.rrgrow .nm{flex:1;color:#cfe6ff}
.rrgrow .qv{color:#8fb0d6;font-size:11px;width:36px;text-align:center}
.rrgrow .num{color:#5f80a6;font-variant-numeric:tabular-nums;width:90px;text-align:right}
@media (max-width:820px){.rrgwrap{grid-template-columns:1fr}.rrgbox{height:400px}}
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/rotation.html")
    ap.add_argument("--obis", action="store_true")
    args = ap.parse_args()

    print("算美股 SPDR 11 大類股 …")
    snap_us = build_market_snapshot("us")
    print(f"  {len(snap_us)}/11 檔算出結果")
    print("算台股產業籃子（需逐檔抓歷史價，較慢）…")
    snap_tw = build_market_snapshot("tw")
    print(f"  {len(snap_tw)} 個籃子算出結果")

    hist = load_history()
    date_str = time.strftime("%Y-%m-%d")
    hist = append_history(hist, "us", snap_us, date_str)
    hist = append_history(hist, "tw", snap_tw, date_str)
    save_history(hist)

    html = render_html(snap_us, snap_tw, hist)
    outs = [args.output]
    if args.obis:
        obis = os.path.join(
            r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment",
            "產業輪動雷達.html")
        outs.append(obis)
    for out in outs:
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"已存：{out}")
        except Exception as e:
            print(f"警告 寫入 {out} 失敗（不影響其他輸出）：{e}")


if __name__ == "__main__":
    main()


