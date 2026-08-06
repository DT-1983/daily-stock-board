"""產業鏈定位：同鏈股票的毛利率／60日報酬比較（BEST MATCH 報告拆解功能 #1）

只涵蓋現有 8 條鏈（chain_reports_src/reports_data/*.json 的 valuechain）裡的股票，
不在鏈上的持股（傳產/金融股等）會被跳過，不硬湊。

架構：
  build_cache()  ── 一天跑一次（本機排程/skill），算好全部 107 檔的毛利率+60日報酬，
                     寫 chain_positioning_cache.json。避免財報卡每次產出都重打 API
                     （FinMind 一天限流的教訓，2026-08-05 已踩過一次）。
  build_html(t)  ── 財報卡引用，純讀快取，不打任何 API。查不到鏈就回空字串。

用法：
  python chain_positioning.py                 # 建快取
  python chain_positioning.py --ticker 3037   # 快取讀出後印 debug 用
"""
import os
import sys
import json
import glob
import re
import argparse
import time
from datetime import datetime, timedelta

import requests
import yfinance as yf

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "chain_positioning_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")


# ── 1. 鏈與環節結構（讀 valuechain，不重造資料） ────────────────────────

_TICKER_RE = re.compile(r"^\d{4,5}$|^[A-Z][A-Z.]{0,5}$")


def _extract_tickers(raw):
    """研究 Agent 寫的 stocks 欄位格式不統一：'2330'／'3105 穩懋'／'TE（T1 Energy）'／
    '3055（代理）' 都出現過。先砍掉全形/半形括號內容（附註、公司全名），
    再拆詞，只留下真的長得像代號的 token（中文公司名會被這個 regex 篩掉）。"""
    raw = re.sub(r"[（(][^）)]*[）)]", "", raw)
    toks = re.split(r"[、,\s]+", raw.strip())
    return [t for t in (x.strip() for x in toks) if t and _TICKER_RE.match(t)]


def load_chain_structure():
    """回 {chain_name: {"positioning":..., "segs":[{"seg","do","tickers"}]}}。
    2026-08-06：加 positioning／do——之前只取 stocks 沒取這兩個欄位，
    使用者反應「看不出上下游關係」，其實深度報告資料裡本來就有，只是沒渲染。"""
    out = {}
    for f in sorted(glob.glob(os.path.join(HERE, "chain_reports_src/reports_data/*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        chain = d.get("_chain")
        if not chain:
            continue
        segs = []
        for seg in d.get("valuechain", []):
            segs.append({"seg": seg["seg"], "do": seg.get("do", ""),
                        "tickers": _extract_tickers(seg["stocks"])})
        out[chain] = {"positioning": d.get("positioning", ""), "segs": segs}
    return out


def ticker_lookup(structure):
    """{ticker: (chain, seg)}——同一檔若出現在多鏈/多環節，取第一個。"""
    m = {}
    for chain, info in structure.items():
        for seg in info["segs"]:
            for tk in seg["tickers"]:
                m.setdefault(tk, (chain, seg["seg"]))
    return m


def _is_tw(tk):
    return bool(re.match(r"^\d{4,5}$", tk))


# ── 2. 指標抓取（毛利率＋60日報酬） ──────────────────────────────────

def _fm(dataset, sid, start):
    params = {"dataset": dataset, "data_id": sid, "start_date": start}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
    try:
        r = requests.get(FINMIND, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("data") or []
    except Exception:
        return []


def _metrics_tw(code):
    d200 = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    d70 = (datetime.now() - timedelta(days=95)).strftime("%Y-%m-%d")
    fin = _fm("TaiwanStockFinancialStatements", code, d200)
    price = _fm("TaiwanStockPrice", code, d70)
    gm = None
    if fin:
        last = max(d["date"] for d in fin)
        byt = {d["type"]: d["value"] for d in fin if d["date"] == last}
        rev, gp = byt.get("Revenue"), byt.get("GrossProfit")
        gm = (gp / rev * 100) if (rev and gp is not None) else None
    ret60 = None
    if len(price) >= 2:
        closes = [p["close"] for p in price if p.get("close")]
        if len(closes) >= 2:
            base = closes[max(0, len(closes) - 60)]
            ret60 = (closes[-1] / base - 1) * 100 if base else None
    return gm, ret60


def _metrics_us(tk):
    try:
        t = yf.Ticker(tk)
        info = t.info or {}
        gm = info.get("grossMargins")
        gm = gm * 100 if isinstance(gm, (int, float)) else None
        hist = t.history(period="4mo")
        ret60 = None
        if len(hist) >= 2:
            closes = hist["Close"].dropna()
            if len(closes) >= 2:
                base = closes.iloc[max(0, len(closes) - 60)]
                ret60 = (closes.iloc[-1] / base - 1) * 100 if base else None
        return gm, ret60
    except Exception:
        return None, None


# ── 3. 快取建立 ──────────────────────────────────────────────────────

def build_cache():
    structure = load_chain_structure()
    lookup = ticker_lookup(structure)
    tickers = sorted(lookup)
    print(f"共 {len(tickers)} 檔（{sum(1 for t in tickers if _is_tw(t))} 台股 / "
          f"{sum(1 for t in tickers if not _is_tw(t))} 美股）")

    metrics = {}
    for i, tk in enumerate(tickers):
        gm, ret60 = _metrics_tw(tk) if _is_tw(tk) else _metrics_us(tk)
        metrics[tk] = {"gross_margin": gm, "ret60": ret60}
        print(f"  [{i+1}/{len(tickers)}] {tk}  毛利 {gm}  60日 {ret60}")
        if _is_tw(tk):
            time.sleep(0.3)  # FinMind 客氣一點，別再撞限流

    cache = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
             "structure": structure, "metrics": metrics}
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已存 {CACHE}")


# ── 4. 渲染（財報卡引用，純讀快取） ──────────────────────────────────

def _name(tk):
    if _is_tw(tk):
        try:
            import board_html_legacy as L
            return L.TW_NAME.get(tk, tk)
        except Exception:
            return tk
    return tk


def summary_text(ticker):
    """給 narrative() LLM prompt 用的一行文字摘要。純讀快取，零額外 API 成本。"""
    if not os.path.exists(CACHE):
        return ""
    cache = json.load(open(CACHE, encoding="utf-8"))
    lookup = ticker_lookup(cache["structure"])
    tk = ticker.replace(".TW", "").replace(".TWO", "") if _is_tw_yf(ticker) else ticker.upper()
    hit = lookup.get(tk)
    if not hit:
        return ""
    chain, my_seg = hit
    metrics = cache["metrics"]
    my = metrics.get(tk, {})
    peers = [metrics.get(t, {}) for seg in cache["structure"][chain]["segs"]
             for t in seg["tickers"] if t != tk]
    peer_gm = [p["gross_margin"] for p in peers if p.get("gross_margin") is not None]
    peer_ret = [p["ret60"] for p in peers if p.get("ret60") is not None]
    gm_avg = sum(peer_gm) / len(peer_gm) if peer_gm else None
    ret_avg = sum(peer_ret) / len(peer_ret) if peer_ret else None
    parts = [f"屬於「{chain}」鏈、{my_seg}環節"]
    if my.get("gross_margin") is not None and gm_avg is not None:
        parts.append(f"毛利率{my['gross_margin']:.1f}%（同鏈平均{gm_avg:.1f}%）")
    if my.get("ret60") is not None and ret_avg is not None:
        parts.append(f"近60日{my['ret60']:+.1f}%（同鏈平均{ret_avg:+.1f}%）")
    return "、".join(parts)


def build_html(ticker):
    """回 HTML 片段字串；查不到鏈就回空字串（呼叫端據此決定要不要顯示這個區塊）。"""
    if not os.path.exists(CACHE):
        return ""
    cache = json.load(open(CACHE, encoding="utf-8"))
    lookup = ticker_lookup(cache["structure"])
    tk = ticker.replace(".TW", "").replace(".TWO", "") if _is_tw_yf(ticker) else ticker.upper()
    hit = lookup.get(tk)
    if not hit:
        return ""
    chain, my_seg = hit
    chain_info = cache["structure"][chain]
    segs = chain_info["segs"]
    metrics = cache["metrics"]

    rows = []
    for i, seg in enumerate(segs):
        cells = []
        for t in seg["tickers"]:
            m = metrics.get(t, {})
            gm, ret = m.get("gross_margin"), m.get("ret60")
            gm_s = f"{gm:.1f}%" if gm is not None else "—"
            if ret is not None:
                cls = "pos" if ret > 0 else ("neg" if ret < 0 else "flat")
                ret_s = f'<span class="num {cls}">{ret:+.1f}%</span>'
            else:
                ret_s = '<span class="num flat">—</span>'
            focus = " focus" if t == tk else ""
            cells.append(
                f'<div class="peer{focus}"><div class="pt">{_name(t)}<span class="pc">{t}</span></div>'
                f'<div class="pv">毛利 <b class="num">{gm_s}</b>　60日 {ret_s}</div></div>')
        mark = ' <span class="segmine">· 你的標的在這裡</span>' if seg["seg"] == my_seg else ""
        do = f'<div class="segdo">{seg["do"]}</div>' if seg.get("do") else ""
        arrow = '<div class="segarrow">↓ 往下游</div>' if i > 0 else ""
        rows.append(f'{arrow}<div class="segrow"><div class="segname">{seg["seg"]}{mark}</div>'
                    f'{do}<div class="segcells">{"".join(cells)}</div></div>')

    pos_line = (f'<div class="chainpos">{chain_info["positioning"]}</div>'
               if chain_info.get("positioning") else "")

    return (f'<div class="positioning"><h3>產業鏈定位 · {chain}</h3>'
            f'{pos_line}'
            f'<div class="posnote">依上游→下游排列，同鏈股票毛利率與近60日報酬對照，'
            f'資料 {cache["updated"]}（青框＝本檔所在環節）</div>{"".join(rows)}</div>')


def _is_tw_yf(ticker):
    return ticker.upper().endswith((".TW", ".TWO")) or _is_tw(ticker)


CSS = """
.positioning{margin-top:16px;padding-top:14px;border-top:1px solid #16223A}
.positioning h3{font-size:14px;font-weight:700;color:#F5B841;margin-bottom:4px}
.chainpos{font-size:12.5px;color:#C7D8EC;line-height:1.6;margin-bottom:8px;
 padding:8px 10px;background:#161a20;border-radius:8px}
.posnote{font-size:11.5px;color:#8a8f98;margin-bottom:10px}
.segarrow{text-align:center;font-size:10.5px;color:#4a5568;margin:2px 0}
.segrow{margin:6px 0 10px}
.segname{font-size:12px;color:#93C5FD;font-weight:600}
.segmine{color:#F5B841;font-weight:700;font-size:10.5px}
.segdo{font-size:11px;color:#8a8f98;margin:2px 0 6px}
.segcells{display:flex;flex-wrap:wrap;gap:6px}
.peer{background:#1a1d23;border:1px solid #2a2e35;border-radius:8px;padding:6px 9px;font-size:11.5px;min-width:120px}
.peer.focus{border-color:#4a9eff;box-shadow:0 0 0 1px #4a9eff}
.pt{font-weight:700;color:#e8eaed}
.pc{color:#6b7280;font-weight:400;margin-left:4px;font-size:10.5px}
.pv{color:#9aa0a6;margin-top:2px}
.pv .pos{color:#4ade80}.pv .neg{color:#ff8a8a}.pv .flat{color:#6b7280}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="不建快取，只印某檔的定位 HTML（debug 用）")
    args = ap.parse_args()
    if args.ticker:
        print(build_html(args.ticker) or "（不在任何鏈上）")
        return
    build_cache()


if __name__ == "__main__":
    main()
