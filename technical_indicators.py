"""技術面四指標（BEST MATCH 拆解功能 #4）→ 財報卡新增區塊

四個指標全部只需要 OHLCV 價量資料，yfinance 對美股/台股皆可直接抓，
不需要額外資料源。公式依報告「方法說明」逐一對照移植：

  SuperTrend      ATR(10, Wilder's RMA)×3 —— 直接復用 board_html_legacy.supertrend()
  雙重颱風K線     跟 SuperTrend 同構，只差 ATR 用 SMA(TrueRange,10) 而非 Wilder 平滑
  EXCEED CHARGE   TTM Squeeze／擠壓動能：布林帶(樣本標準差) vs 凱特納通道(SMA of TR)，
                   擠壓＝布林帶縮進凱特納通道內；動能＝對 value 序列做線性迴歸取末端值
  RS 相對強弱     Weinstein/Mansfield：(股價/大盤 比值) 對其自身均線的乖離%，
                   短線(25日)＋長線(200日)兩組

用法：
    python technical_indicators.py 3037.TW
    python technical_indicators.py NVDA
"""
import sys
import re
import argparse

import numpy as np
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from board_html_legacy import supertrend  # 復用既有 SuperTrend，不重造


def _is_tw(ticker):
    return bool(re.match(r"^\d{4,5}(\.TWO?)?$", ticker.upper())) or ticker.upper().endswith((".TW", ".TWO"))


def _benchmark(ticker):
    return "^TWII" if _is_tw(ticker) else "^GSPC"


# ── 雙重颱風K線：SuperTrend 的 SMA-ATR 變體 ──────────────────────────

def double_typhoon(highs, lows, closes, period=10, mult=3.0):
    n = len(closes)
    if n < period + 1:
        return None
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = [None] * n
    for i in range(period - 1, n):
        atr[i] = sum(tr[i - period + 1:i + 1]) / period  # SMA，不是 Wilder RMA
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(n)]
    st, dr, up, lo = [None] * n, [None] * n, [None] * n, [None] * n
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
            dr[i] = 1 if closes[i] > up[i - 1] else (-1 if closes[i] < lo[i - 1] else dr[i - 1])
        st[i] = lo[i] if dr[i] == 1 else up[i]
    return {"st": st, "dir": dr}


# ── EXCEED CHARGE：擠壓動能（TTM Squeeze） ───────────────────────────

def squeeze_momentum(highs, lows, closes, length=20, bb_mult=2.0, kc_mult=1.5):
    n = len(closes)
    if n < length + 1:
        return None
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)

    def sma(a, w):
        out = np.full(len(a), np.nan)
        for i in range(w - 1, len(a)):
            out[i] = a[i - w + 1:i + 1].mean()
        return out

    bb_mid = sma(c, length)
    bb_std = np.full(n, np.nan)
    for i in range(length - 1, n):
        bb_std[i] = c[i - length + 1:i + 1].std(ddof=1)  # 樣本標準差
    bb_up, bb_lo = bb_mid + bb_mult * bb_std, bb_mid - bb_mult * bb_std

    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    kc_range = sma(tr, length)  # 凱特納：SMA of TR，非 ATR
    kc_up, kc_lo = bb_mid + kc_mult * kc_range, bb_mid - kc_mult * kc_range

    squeeze_on = (bb_lo > kc_lo) & (bb_up < kc_up)

    donchian_mid = np.full(n, np.nan)
    for i in range(length - 1, n):
        donchian_mid[i] = (h[i - length + 1:i + 1].max() + l[i - length + 1:i + 1].min()) / 2
    value = c - (donchian_mid + bb_mid) / 2

    # 線性迴歸取視窗末端投影值（標準 TTM Squeeze 動能柱算法）
    mom = np.full(n, np.nan)
    x = np.arange(length)
    for i in range(length - 1, n):
        y = value[i - length + 1:i + 1]
        if np.isnan(y).any():
            continue
        b, a = np.polyfit(x, y, 1)
        mom[i] = a + b * (length - 1)

    return {"squeeze_on": squeeze_on, "momentum": mom}


# ── RS 相對強弱（Mansfield） ──────────────────────────────────────────

def mansfield_rs(closes, bench_closes, short=25, long=200):
    n = min(len(closes), len(bench_closes))
    c = np.array(closes[-n:], dtype=float)
    b = np.array(bench_closes[-n:], dtype=float)
    rs_raw = c / b
    out = {}
    for label, win in (("short", short), ("long", long)):
        if n < win + 1:
            out[label] = None
            continue
        rs_avg = rs_raw[-win:].mean()
        out[label] = (rs_raw[-1] / rs_avg - 1) * 100
    return out


# ── 綜合：抓資料＋算四指標＋渲染 ──────────────────────────────────────

def _flip_bars(dr):
    """SuperTrend/雙重颱風目前方向已經走了幾根 K。"""
    valid = [d for d in dr if d is not None]
    if not valid:
        return None, None
    cur = valid[-1]
    n = 0
    for d in reversed(valid):
        if d != cur:
            break
        n += 1
    return cur, n


def build(ticker):
    """算一次，回 (html, summary_text)。理由同 fundamentals_reality.build()：
    避免財報卡渲染跟 narrative() 的 LLM prompt 各自重抓一次價量資料。"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty or len(hist) < 60:
            return "", ""
        highs, lows, closes = hist["High"].tolist(), hist["Low"].tolist(), hist["Close"].tolist()

        bench = yf.Ticker(_benchmark(ticker)).history(period="1y")
        bench_closes = bench["Close"].tolist() if not bench.empty else []
    except Exception as e:
        print(f"  [technical_indicators] {ticker} 抓取失敗：{e}")
        return "", ""

    st = supertrend(highs, lows, closes)
    dt = double_typhoon(highs, lows, closes)
    sq = squeeze_momentum(highs, lows, closes)
    rs = mansfield_rs(closes, bench_closes) if bench_closes else {"short": None, "long": None}

    st_dir, st_bars = _flip_bars(st["dir"]) if st else (None, None)
    dt_dir, dt_bars = _flip_bars(dt["dir"]) if dt else (None, None)

    def trend_tile(name, dir_, bars):
        if dir_ is None:
            return _tile(name, "—", "無資料")
        label = "多頭" if dir_ == 1 else "空頭"
        col = "#4ade80" if dir_ == 1 else "#ff8a8a"
        return _tile(name, f'<span style="color:{col}">{label}</span>', f"第 {bars} 根")

    sq_on = bool(sq["squeeze_on"][-1]) if sq and not np.isnan(sq["squeeze_on"][-1:].astype(float)).any() else None
    sq_mom = sq["momentum"][-1] if sq is not None else None
    sq_mom_s = f"{sq_mom:+.2f}" if sq_mom is not None and not np.isnan(sq_mom) else "—"
    sq_label = ("擠壓中" if sq_on else "無擠壓") if sq_on is not None else "—"
    sq_col = "#EAB308" if sq_on else ("#4ade80" if (sq_mom or 0) > 0 else "#ff8a8a")

    rs_s = rs.get("short")
    rs_l = rs.get("long")
    rs_html = (f'短線 <b class="num" style="color:{"#4ade80" if (rs_s or 0)>0 else "#ff8a8a"}">'
               f'{f"{rs_s:+.1f}%" if rs_s is not None else "—"}</b>　'
               f'長線 <b class="num" style="color:{"#4ade80" if (rs_l or 0)>0 else "#ff8a8a"}">'
               f'{f"{rs_l:+.1f}%" if rs_l is not None else "—"}</b>')

    tiles = "".join([
        trend_tile("SUPER TREND", st_dir, st_bars),
        trend_tile("雙重颱風K線", dt_dir, dt_bars),
        _tile("EXCEED CHARGE", f'<span style="color:{sq_col}">{sq_label}</span>', f"動能 {sq_mom_s}"),
        _tile("RS 相對強弱", rs_html, ""),
    ])

    html = f"""<div class="technical"><h3>技術面四指標</h3>
<div class="posnote">近一年日線計算，基準指數：{_benchmark(ticker)}</div>
<div class="techgrid">{tiles}</div>
</div>"""

    def _lbl(dir_, bars):
        return f'{"多頭" if dir_==1 else "空頭"}第{bars}根' if dir_ is not None else "無資料"

    summary = (f"SuperTrend {_lbl(st_dir, st_bars)}　雙重颱風K線 {_lbl(dt_dir, dt_bars)}　"
               f"EXCEED CHARGE {sq_label}(動能{sq_mom_s})　"
               f"RS相對強弱 短線{f'{rs_s:+.1f}%' if rs_s is not None else '—'}"
               f"/長線{f'{rs_l:+.1f}%' if rs_l is not None else '—'}")
    return html, summary


def build_html(ticker):
    """CLI／向下相容用：只要 HTML。"""
    return build(ticker)[0]


def _tile(name, main, sub):
    return (f'<div class="ttile"><div class="tn">{name}</div>'
            f'<div class="tv">{main}</div><div class="ts">{sub}</div></div>')


CSS = """
.technical{margin-top:16px;padding-top:14px;border-top:1px solid #16223A}
.technical h3{font-size:14px;font-weight:700;color:#F5B841;margin-bottom:4px}
.techgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:10px}
.ttile{background:#1a1d23;border:1px solid #2a2e35;border-radius:9px;padding:9px 11px}
.tn{font-size:10px;color:#6b7280;letter-spacing:.3px;font-weight:600}
.tv{font-size:14px;font-weight:700;margin-top:4px;color:#e8eaed}
.ts{font-size:11px;color:#9aa0a6;margin-top:2px}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    print(build_html(args.ticker) or "（無資料）")


if __name__ == "__main__":
    main()
