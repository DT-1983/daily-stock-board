# -*- coding: utf-8 -*-
"""本益比百分位回測（單檔試做，2026-10-04，Leo：「先做一隻試試看，也包括本益比百分位回測」）。

問題：這檔股票「買在自己過去 N 年本益比的哪個位置」，之後 12 個月的報酬有沒有差別？報酬又是靠獲利成長還是倍數變化？
規則（先固定、再跑，不看結果調整）：
  · 本益比＝證交所每日落後本益比（FinMind TaiwanStockPER，只用「當時已公布」的獲利，沒有前視偏差）。
  · 每個月底取樣；百分位只用「該月底以前、過去 5 年」的資料（滾動，不偷看未來）；EPS≤0 的日子不算。
  · 分五組（固定切點 0–20／20–40／40–60／60–80／80–100 百分位，不用資料決定切點）。
  · 之後 12 個月報酬＝未調整收盤價的價格報酬（不含股利）。拆解：(1+價格報酬)＝(1+EPS 成長)×(1+本益比變化)，
    其中「EPS」＝收盤價÷本益比（證交所落後 EPS），成長是事後實績，不是預測。
限制（誠實標明）：單一股票、12 個月窗口互相重疊（獨立樣本遠少於月數）、不含股利、只有存活至今的這一檔（存活者偏差）、
  落後 EPS 看不到成長預期。這個結果只能說「這檔過去的樣子」，不能推廣到別檔、也不是買賣訊號。
用法：python pe_pctile_backtest.py 2454"""
import datetime as dt
import statistics as st
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

WIN_YEARS = 5
BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]


def load(code):
    from fundamentals_reality import _fm
    start = "2008-01-01"
    per = _fm("TaiwanStockPER", code, start) or []
    px = _fm("TaiwanStockPrice", code, start) or []
    per = {x["date"]: float(x["PER"]) for x in per if x.get("PER") not in (None, "") and float(x["PER"]) > 0}
    cl = {x["date"]: float(x["close"]) for x in px if x.get("close") not in (None, "") and float(x["close"]) > 0}
    days = sorted(set(per) & set(cl))
    return days, per, cl


def pctile(sample, v):
    return 100.0 * sum(1 for x in sample if x <= v) / len(sample)


def run(code):
    days, per, cl = load(code)
    if len(days) < 800:
        print(f"{code} 資料太少（{len(days)} 天），不做")
        return
    d0 = dt.date.fromisoformat(days[0])
    print(f"{code}：共 {len(days)} 個交易日 {days[0]} ～ {days[-1]}")
    dd = [dt.date.fromisoformat(d) for d in days]

    def idx_on_or_before(date):
        lo, hi = 0, len(dd) - 1
        ans = None
        while lo <= hi:
            m = (lo + hi) // 2
            if dd[m] <= date:
                ans, lo = m, m + 1
            else:
                hi = m - 1
        return ans

    # 每月最後一個交易日
    me = {}
    for i, d in enumerate(dd):
        me[(d.year, d.month)] = i
    rows = []
    for (y, m), i in sorted(me.items()):
        t = dd[i]
        if t < d0 + dt.timedelta(days=365 * WIN_YEARS):
            continue
        j = idx_on_or_before(dt.date(t.year + 1, t.month, min(t.day, 28)))
        if j is None or dd[j] <= t + dt.timedelta(days=330):
            continue                                            # 未來 12 個月還沒走完，不算
        lo = idx_on_or_before(t - dt.timedelta(days=365 * WIN_YEARS))
        sample = [per[days[k]] for k in range(lo, i + 1)]
        pc = pctile(sample, per[days[i]])
        ret = cl[days[j]] / cl[days[i]] - 1
        eps0 = cl[days[i]] / per[days[i]]
        eps1 = cl[days[j]] / per[days[j]]
        rows.append({"date": days[i], "pc": pc, "per": per[days[i]], "ret": ret,
                     "eps_g": eps1 / eps0 - 1, "pe_chg": per[days[j]] / per[days[i]] - 1})
    print(f"可用月底樣本 {len(rows)} 個（{rows[0]['date']} ～ {rows[-1]['date']}）；12 個月窗口重疊，獨立樣本約 {len(rows) // 12} 個\n")
    print("百分位組　 月數  報酬中位  報酬平均  賺錢比例  EPS成長中位  本益比變化中位")
    for lo_, hi_ in BUCKETS:
        g = [r for r in rows if lo_ <= r["pc"] < hi_]
        if not g:
            print(f"{lo_:>3}–{min(hi_, 100):<3}      0  —")
            continue
        print(f"{lo_:>3}–{min(hi_, 100):<3}   {len(g):>5}  {st.median(r['ret'] for r in g)*100:>+7.0f}%  "
              f"{st.mean(r['ret'] for r in g)*100:>+7.0f}%  {sum(1 for r in g if r['ret'] > 0)/len(g)*100:>6.0f}%  "
              f"{st.median(r['eps_g'] for r in g)*100:>+9.0f}%  {st.median(r['pe_chg'] for r in g)*100:>+11.0f}%")
    # 分年
    print("\n分年（各年 12 個月前進報酬的中位，看結果是不是只靠某幾年）")
    by = {}
    for r in rows:
        by.setdefault(r["date"][:4], []).append(r)
    for y, g in sorted(by.items()):
        print(f"  {y}  月數 {len(g):>2}  百分位中位 {st.median(r['pc'] for r in g):>3.0f}  報酬中位 {st.median(r['ret'] for r in g)*100:>+5.0f}%  "
              f"EPS成長 {st.median(r['eps_g'] for r in g)*100:>+5.0f}%  本益比變化 {st.median(r['pe_chg'] for r in g)*100:>+5.0f}%")
    # 現在的位置
    i = len(days) - 1
    lo = idx_on_or_before(dd[i] - dt.timedelta(days=365 * WIN_YEARS))
    sample = [per[days[k]] for k in range(lo, i + 1)]
    print(f"\n現在（{days[i]}）：本益比 {per[days[i]]:.1f}，在過去 5 年的第 {pctile(sample, per[days[i]]):.0f} 百分位；"
          f"5 年區間 {min(sample):.1f}～{max(sample):.1f}、中位 {st.median(sample):.1f}")
    ttm = cl[days[i]] / per[days[i]]
    print(f"落後 12 個月 EPS ≈ {ttm:.2f}（收盤價÷本益比）。若目標價為 T，目標價隱含的落後本益比＝T÷{ttm:.2f}；"
          f"該倍數在過去 5 年的百分位：")
    for T in (5552, 7000):
        m = T / ttm
        print(f"  T={T:,}：{m:.1f} 倍 → 第 {pctile(sample, m):.0f} 百分位（超過歷史最高 {max(sample):.1f} 倍就是 100）")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "2454")
