# -*- coding: utf-8 -*-
"""券商目標價拆解（2026-10-02，Leo：「目標價我們可以拆解嗎？建立自己的評價系統」）

老墨的阿福會把「目標價」拆成：前提 → 獲利預估 → 估值倍數 → 目標價，再看兩家券商差在哪一年的 EPS、
還是倍數不同。我們的報告庫（advisor_reports.json）已經有解析好的欄位：目標價、倍數、EPS／每股淨值、
估值基準年。這支把它們拆開，**只做描述，不訂任何新的買賣門檻**（門檻要 Leo 拍板或有回測依據）。

每份報告拆成：
  ① 目標價 ＝ 倍數 × 基準（EPS 或每股淨值）；核對乘起來對不對得上（對不上＝解析或原報告有問題）
  ② 市場現在給這個基準幾倍（現價 ÷ 基準）→ 目標價要的是「重新評價多少」
  ③ 基準 EPS 比近四季實際 EPS 要成長多少（報告要你相信的獲利）
  ④ 目標價換算成「現在可見獲利的本益比」，落在這檔自己過去的本益比分布的哪個位置
     （TWSE 每日 PER，同口徑——不拿預估本益比比歷史落後本益比）
  ⑤ 跟洪瑞泰貴價倍數（30）的距離（只標示，不下結論）
多家券商同一檔：把目標價差拆成「倍數差」跟「EPS 差」。

🔴 倍數／基準若是「依目標價÷倍數回推」的（valuation_eps_label 含「回推」），①自然對得上，標明不是報告自己寫的。
🔴 TTM EPS 與 PER 都用 FinMind／證交所已公布的實績；沒有就留空，不用預估湊。

用法:
    python target_decompose.py                 # 全部可拆解的報告
    python target_decompose.py --ticker 7750   # 一檔，含多券商差異拆解
    python target_decompose.py --html          # 另存 HTML 到 obis（私人）
"""
import argparse
import datetime as dt
import io
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

HONG_EXPENSIVE_MULT = 30            # 洪瑞泰貴價＝預期常利 EPS × 30（hongruitai_method）


def load_reports(ticker=None):
    d = json.load(io.open("state/advisor_reports.json", encoding="utf-8"))
    rows = [r for r in (d.values() if isinstance(d, dict) else d) if isinstance(r, dict)]
    out = []
    for r in rows:
        if r.get("_notreport") or r.get("_superseded_by"):
            continue
        if ticker and str(r.get("ticker")) != str(ticker):
            continue
        base = r.get("valuation_eps") or r.get("bps")
        if r.get("target") and r.get("valuation_multiple") and base:
            out.append(r)
    out.sort(key=lambda r: (str(r["ticker"]), str(r.get("date"))))
    return out


_CACHE = {}


def market_data(code):
    """現價、TWSE 每日 PER／PBR 歷史、近四季實際 EPS。同一檔只抓一次。"""
    if code in _CACHE:
        return _CACHE[code]
    from fundamentals_reality import _fm, _tw_quarterly
    res = {"price": None, "per_now": None, "pbr_now": None, "per_hist": [], "pbr_hist": [], "ttm_eps": None, "asof": None}
    try:
        rows = _fm("TaiwanStockPER", code, (dt.date.today() - dt.timedelta(days=365 * 5)).isoformat()) or []
        rows = [x for x in rows if x.get("PER") is not None]
        if rows:
            res["per_now"], res["pbr_now"], res["asof"] = float(rows[-1]["PER"]), float(rows[-1]["PBR"]), rows[-1]["date"]
            res["per_hist"] = [float(x["PER"]) for x in rows if float(x["PER"]) > 0]
            res["pbr_hist"] = [float(x["PBR"]) for x in rows if float(x["PBR"]) > 0]
    except Exception as e:                                    # noqa: BLE001
        print(f"  [{code}] PER 歷史失敗：{str(e)[:60]}")
    try:
        q = _tw_quarterly(code) or []
        eps4 = [x["eps"] for x in q[-4:] if x.get("eps") is not None]
        if len(eps4) == 4:
            res["ttm_eps_fm"] = sum(eps4)
            res["ttm_end"] = q[-1].get("period")            # 例 2026-06
    except Exception as e:                                    # noqa: BLE001
        print(f"  [{code}] 季 EPS 失敗：{str(e)[:60]}")
    try:
        import yfinance as yf
        import tw_symbol
        sym = tw_symbol.resolve(code)
        h = yf.Ticker(sym).history(period="5d")["Close"].dropna()
        if len(h):
            res["price"] = float(h.iloc[-1])
    except Exception as e:                                    # noqa: BLE001
        print(f"  [{code}] 現價失敗：{str(e)[:60]}")
    # 近四季 EPS：**以證交所 PER 反推為主**（現價÷PER，官方已公布的落後 EPS），FinMind 季 EPS 加總只當對照。
    # 2026-10-02 寶雅（5904）：FinMind 季 EPS 加總 34.02、證交所 PER 反推 3.40——差 10 倍，
    # 報告自己的 EPS（2025=2.95）跟 PER 這邊一致，FinMind 那邊是錯的。兩邊差超過 ±25% 就標出來。
    if res["price"] and res["per_now"]:
        res["ttm_eps"] = res["price"] / res["per_now"]
        fm = res.get("ttm_eps_fm")
        if fm and not (0.75 <= fm / res["ttm_eps"] <= 1.33):
            res["ttm_mismatch"] = f"FinMind 季 EPS 加總 {fm:.2f} 與證交所 PER 反推 {res['ttm_eps']:.2f} 差 {fm / res['ttm_eps']:.1f} 倍"
    elif res.get("ttm_eps_fm"):
        res["ttm_eps"] = res["ttm_eps_fm"]                    # 沒有 PER（虧損股）才退回 FinMind
    _CACHE[code] = res
    return res


def base_midyear(label, today=None):
    """估值基準的「中點時間」（小數年）。2027F→2027.5、2027-28 年平均→2028.0、2H27E-1H28E→2028.0、
    26H2-27H1→2027.0、未來四季／FWD 12M→今天起半年後。解析不到回 None（寧可不算年化，不猜）。"""
    import re
    t = today or dt.date.today()
    now = t.year + (t.month - 1) / 12
    s = str(label or "")
    pts = []
    for m in re.finditer(r"([12])H(\d\d)", s):                 # 2H27E → 2027.75
        pts.append(2000 + int(m.group(2)) + (0.25 if m.group(1) == "1" else 0.75))
    for m in re.finditer(r"(\d\d)H([12])", s):                 # 26H2 → 2026.75
        pts.append(2000 + int(m.group(1)) + (0.25 if m.group(2) == "1" else 0.75))
    if not pts:
        ys = [int(y) for y in re.findall(r"20\d\d", s)]
        if not ys and re.search(r"(\d\d)[-~](\d\d)", s):
            ys = [2000 + int(y) for y in re.findall(r"(\d\d)", s)][:2]
        if ys:
            pts = [y + 0.5 for y in ys]
    if pts:
        return sum(pts) / len(pts)
    if "未來四季" in s or "12M" in s.upper() or "FWD" in s.upper():
        return now + 0.5
    return None


def pctile(hist, v):
    if not hist or v is None:
        return None
    return sum(1 for x in hist if x <= v) / len(hist)


def decompose(r):
    """一份報告 → 拆解結果 dict（沒有的欄位是 None，不補）。"""
    code = str(r["ticker"])
    T, M = float(r["target"]), float(r["valuation_multiple"])
    B = float(r.get("valuation_eps") or r.get("bps"))
    kind = r.get("valuation_kind") or "PE"
    derived = "回推" in str(r.get("valuation_eps_label") or "")
    md = market_data(code) if code.isdigit() else {}
    nm_flag = None
    try:
        import combo_scan
        off = (combo_scan._tw_names() or {}).get(code)
        nm = str(r.get("name") or "")
        if off and nm and not (nm in off or off in nm or nm.replace("-KY", "") in off or off.replace("-KY", "") in nm):
            nm_flag = f"🔴 代號 {code} 官方名稱是「{off}」，報告寫「{nm}」——代號可能填錯"
    except Exception:                                         # noqa: BLE001
        pass
    P = md.get("price")
    out = {"ticker": code, "name": r.get("name"), "broker": r.get("broker"), "date": r.get("date"),
           "rating": r.get("rating"), "target": T, "kind": kind, "mult": M, "base": B,
           "base_label": r.get("valuation_eps_label"), "derived": derived, "price": P,
           "mult_x_base_gap": (M * B) / T - 1, "flags": [nm_flag] if nm_flag else []}
    if abs(out["mult_x_base_gap"]) > 0.03 and not derived:
        out["flags"].append(f"🔴 倍數×基準={M * B:,.1f} 跟目標價 {T:,.1f} 差 {out['mult_x_base_gap']:+.1%}，解析或報告有問題")
    if P:
        out["upside"] = T / P - 1
        out["mult_now"] = P / B                            # 市場現在在這個基準上給幾倍
        out["rerate"] = M / out["mult_now"] - 1            # 目標價要的重新評價（＝upside，同一件事的另一個名字）
    if kind == "PE" and md.get("ttm_eps"):
        out["ttm_eps"] = md["ttm_eps"]
        out["eps_growth_needed"] = B / md["ttm_eps"] - 1 if md["ttm_eps"] > 0 else None
        # 年化：基準時間點 − 近四季中點（近四季最後一季結束日往回 6 個月）。時間點解析不到就不算，不猜。
        bm = base_midyear(r.get("valuation_eps_label") or r.get("valuation_basis"))
        te = md.get("ttm_end")
        if bm and te and out["eps_growth_needed"] is not None:
            y, m = int(te[:4]), int(te[5:7])
            ttm_mid = y + m / 12 - 0.5
            yrs = bm - ttm_mid
            out["eps_years"] = yrs
            if yrs >= 0.3 and md["ttm_eps"] > 0 and B > 0:
                out["eps_cagr"] = (B / md["ttm_eps"]) ** (1 / yrs) - 1
    if md.get("ttm_mismatch"):
        out["flags"].append("🟠 " + md["ttm_mismatch"] + "（近四季 EPS 以證交所為準）")
    car = r.get("close_at_report")
    if P and car and not (0.6 <= P / float(car) <= 1.7):
        out["flags"].append(f"🔴 現價 {P:,.1f} 跟報告當時收盤 {float(car):,.1f} 差 {P / float(car):.1f} 倍，檢查代號或單位")
    # 目標價對應「現在可見獲利」的本益比，放進自己的歷史分布（同口徑：都是落後本益比）
    hist = md.get("per_hist") if kind == "PE" else md.get("pbr_hist")
    now = md.get("per_now") if kind == "PE" else md.get("pbr_now")
    if P and hist and now:
        implied = now * (T / P)
        out["trail_now"], out["trail_target"] = now, implied
        out["trail_now_pct"], out["trail_target_pct"] = pctile(hist, now), pctile(hist, implied)
        out["hist_n"] = len(hist)
        out["hist_median"] = st.median(hist)
    if kind == "PE":
        out["vs_hong30"] = M - HONG_EXPENSIVE_MULT
    return out


def multi_broker(ds):
    """同一檔多家券商：把相對於最低目標價的差距拆成倍數差與基準差（對數可加）。"""
    ds = [d for d in ds if d["kind"] == ds[0]["kind"]]
    if len(ds) < 2:
        return []
    ref = min(ds, key=lambda d: d["target"])
    rows = []
    for d in ds:
        if d is ref:
            continue
        tot = math.log(d["target"] / ref["target"])
        m = math.log(d["mult"] / ref["mult"])
        b = math.log(d["base"] / ref["base"])
        gap = tot - m - b                                   # 乘不起來的殘差（報告內部不一致）
        rows.append({"vs": ref, "d": d, "total": math.exp(tot) - 1, "mult_share": m, "base_share": b, "resid": gap,
                     "tot_log": tot})
    return rows


def _f(x, nd=1, pct=False):
    if x is None:
        return "—"
    return f"{x:+.{nd}%}" if pct else f"{x:,.{nd}f}"


def line(d):
    s = (f"{d['ticker']} {d['name']} {d['broker']} {str(d['date'])[5:]} {d.get('rating') or ''} 目標 {d['target']:,.1f}"
         f"｜{d['kind']} {d['mult']:g}×{d['base']:,.2f}{'(回推)' if d['derived'] else ''}")
    if d.get("price"):
        s += f"｜現價 {d['price']:,.1f} 距目標 {_f(d.get('upside'), 0, True)} 現在給 {d['mult_now']:.1f}倍"
    if d.get("eps_growth_needed") is not None:
        s += f"｜基準EPS比近四季{_f(d['eps_growth_needed'], 0, True)}"
        if d.get("eps_cagr") is not None:
            s += f"（約{d['eps_years']:.1f}年，年化{_f(d['eps_cagr'], 0, True)}）"
    if d.get("trail_target") is not None:
        s += (f"｜目標價換成落後本益比 {d['trail_target']:.1f}（自己{d['hist_n']}天分布第{d['trail_target_pct'] * 100:.0f}百分位，"
              f"現在第{d['trail_now_pct'] * 100:.0f}）")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--json", help="另存 JSON")
    a = ap.parse_args()
    reps = load_reports(a.ticker)
    print(f"可拆解 {len(reps)} 份報告")
    ds = [decompose(r) for r in reps]
    for d in ds:
        print(line(d))
        for f in d["flags"]:
            print("   ", f)
    by = {}
    for d in ds:
        by.setdefault(d["ticker"], []).append(d)
    for tk, g in by.items():
        mb = multi_broker(g)
        if mb:
            print(f"\n── {tk} {g[0]['name']}：{len(g)} 家券商，以最低目標價 {mb[0]['vs']['broker']} {mb[0]['vs']['target']:,.0f} 為基準")
            for x in mb:
                d = x["d"]
                share_m = x["mult_share"] / x["tot_log"] if x["tot_log"] else 0
                print(f"  {d['broker']} {d['target']:,.0f}（高 {x['total']:+.0%}）＝ 倍數 {d['mult']:g} vs {x['vs']['mult']:g}（貢獻 {share_m:.0%}）"
                      f" ＋ 基準 {d['base']:,.1f}({d.get('base_label') or ''}) vs {x['vs']['base']:,.1f}({x['vs'].get('base_label') or ''})（貢獻 {1 - share_m:.0%}）")
    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps(ds, ensure_ascii=False, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
