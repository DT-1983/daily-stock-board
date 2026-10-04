# -*- coding: utf-8 -*-
"""DCF 區間試算（2026-10-04，Leo：「DCF 應該是可以做，然後給區間我覺得不錯，你先跑試試看」）。

只做一件事：**你給假設，我給「假設一變價格差多少」的區間**——不替你決定該用哪個成長率或折現率，
也不輸出「合理價」單點。假設全部由呼叫者明確提供（JSON），沒有隱藏預設。
輸入欄位（單位自洽即可，例如十億美元；股數同單位的十億股）：
  fcff        明確預測期每年自由現金流（FCFF）清單
  wacc        折現率（小數）
  g           永續成長率（小數），終值 = 最後一年現金流 ×(1+g)/(wacc−g)
  fade_years  （選用，預設 0）終值前的「成長淡出期」：FCFF 成長率從 fade_from 線性降到 g，共 N 年（三階段）
  fade_from   （選用）淡出起點成長率
  shares      股數
  net_debt    淨負債（負債−現金；淨現金給負數）
  price       （選用）現價；有給就反推「市價隱含的永續成長率」
簡化（誠實標明）：年底折現、t=1..N；不處理期中現金流、股票薪酬稀釋、選擇權／權證、少數股權。
⚠️ 這是檢查工具不是估值結論：終值占比通常很高，區間寬正是它要你看見的事。
用法：python dcf_range.py inputs.json"""
import json
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def ev_of(fcff, wacc, g, fade_years=0, fade_from=None):
    """回 (企業價值, 終值占比)。"""
    if wacc <= g:
        return float("inf"), 1.0
    pv = sum(x / (1 + wacc) ** (i + 1) for i, x in enumerate(fcff))
    t, c = len(fcff), fcff[-1]
    for k in range(1, fade_years + 1):
        gr = fade_from + (g - fade_from) * k / fade_years
        c *= 1 + gr
        t += 1
        pv += c / (1 + wacc) ** t
    tv = c * (1 + g) / (wacc - g) / (1 + wacc) ** t
    return pv + tv, tv / (pv + tv)


def per_share(a, wacc=None, g=None):
    e, share = ev_of(a["fcff"], a["wacc"] if wacc is None else wacc, a["g"] if g is None else g,
                     a.get("fade_years", 0), a.get("fade_from"))
    return (e - a["net_debt"]) / a["shares"], share


def implied_g(a, price):
    """市價隱含的永續成長率（二分法）；回 None 代表連 g 逼近 wacc 都到不了現價。"""
    lo, hi = -0.05, a["wacc"] - 1e-4
    if per_share(a, g=hi)[0] < price:
        return None
    for _ in range(80):
        m = (lo + hi) / 2
        if per_share(a, g=m)[0] < price:
            lo = m
        else:
            hi = m
    return lo


def report(a):
    b, share = per_share(a)
    print(f"基準：WACC {a['wacc']*100:.1f}%、永續成長 {a['g']*100:.1f}%"
          + (f"、淡出 {a['fade_years']} 年（從 {a['fade_from']*100:.0f}%）" if a.get("fade_years") else "")
          + f" → 每股 {b:,.0f}（終值占企業價值 {share*100:.0f}%）")
    ws = [a["wacc"] - 0.01, a["wacc"] - 0.005, a["wacc"], a["wacc"] + 0.005, a["wacc"] + 0.01]
    gs = [a["g"] - 0.01, a["g"] - 0.005, a["g"], a["g"] + 0.005, a["g"] + 0.01]
    print("\n每股價值（列＝WACC，欄＝永續成長率）")
    print("WACC＼g  " + "".join(f"{g*100:>8.1f}%" for g in gs))
    vals = []
    for w in ws:
        row = []
        for g in gs:
            v = per_share(a, w, g)[0] if w > g + 0.005 else float("nan")
            row.append(v)
            if v == v:
                vals.append(v)
        print(f"{w*100:>5.1f}%  " + "".join(f"{v:>9,.0f}" if v == v else f"{'—':>9}" for v in row))
    print(f"\n區間（WACC±1 點、g±1 點內）：{min(vals):,.0f} ～ {max(vals):,.0f}；基準 {b:,.0f}；"
          f"最高／最低 ＝ {max(vals)/min(vals):.1f} 倍")
    if a.get("price"):
        ig = implied_g(a, a["price"])
        print(f"現價 {a['price']:,.0f}：" + (f"要永續成長 {ig*100:.1f}% 才撐得起（基準假設 {a['g']*100:.1f}%）" if ig is not None
                                          else "即使成長逼近折現率也撐不起現價"))


if __name__ == "__main__":
    report(json.load(open(sys.argv[1], encoding="utf-8")))
