# -*- coding: utf-8 -*-
"""剛轉進 RRG 領先象限的類股，以及它們底下我們母體內的個股（2026-09-05，Leo 指定）。

Leo：「可以多加一組清單，rrg 轉到領先（2-3天以上）的台美股？」

## 為什麼是「2-3 天以上」而不是「今天剛轉」

象限是連續值（RS-Ratio／RS-Momentum）過 100 這條線切出來的，**貼著線的時候會
來回跳**——今天 100.02、明天 99.98 就換一個象限。要求連續站穩 N 天是在濾掉那種
一日行情。⚠️ 這個 N **是 Leo 指定的，不是我們回測出來的**。

## 為什麼還要標「轉進來幾天」而不是只列「現在在領先」

「剛轉進來」跟「已經領先三個月」是兩件事。前者是機會、後者可能已經走完。
所以預設只列 **streak ≤ MAX_STREAK** 的（剛轉不久），並把天數印出來讓人自己判斷。

## 這支的定位

⚠️ **只列清單不下判斷**。2026-09-05 的回測（`backtest_mofi_rrg.py`）只證明
「產業處於領先象限」當**過濾條件**時，12 格全部改善（幅度不大、最好 +1.39pp）；
**沒有測過「剛轉進領先」本身是不是進場訊號**。這兩件事不一樣，不要混。

用法:
    python rrg_turns.py                 # 台美股，連續 ≥2 天、轉進 ≤20 天
    python rrg_turns.py --min-days 3 --max-days 10
    python rrg_turns.py --period 20     # 用 20 日 RRG（預設 60，跟燈號頁一致）
    python rrg_turns.py --with-stocks   # 順便列出母體內屬於這些類股的個股
"""
import argparse
import io
import json
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HIST = "industry_rotation_history.json"
MKT_LABEL = {"us": "🇺🇸 美股", "tw": "🇹🇼 台股"}


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def turns(period="60", min_days=2, max_days=20):
    """回 {market: [ {sector, name, days, since, ratio, momentum}, ... ]}。

    days＝**連續**在領先象限幾個快照日（含今天）。
    since＝轉進領先的那一天。
    """
    h = _load(HIST, {}) or {}
    out = {}
    for m in ("us", "tw"):
        hist = (h.get(m) or {}).get("index") or []
        if not hist:
            continue
        rows = []
        last = hist[-1]
        for sec, v in (last.get("snapshot") or {}).items():
            per = (v.get("periods") or {}).get(period) or {}
            if per.get("quadrant") != "leading":
                continue
            # 往回數連續在領先的天數
            #
            # 🔴 2026-09-05 首測抓到的假訊號：美股 **9/3 的快照壞掉，20 個籃子只記到 4 個**
            # （Energy Minerals / Finance / Miscellaneous / Utilities）。原本的寫法把
            # 「這天沒有這個籃子」當成「這天不在領先」→ 於是 9/4 那天有 **8 個類股**
            # 同時被算成「剛轉進領先」，看起來像一個市場級的大事件，其實是資料缺漏。
            # ⭐ **「沒有資料」不等於「條件不成立」**——這是同一個專案踩過很多次的形狀
            #    （「沒被檢查」長得像「檢查過沒事」）。
            # 修法：籃子不在那天的快照裡就**跳過**（不中斷也不計入），另外記 gaps，
            # 有跳過的在輸出上標 ⚠️，不要假裝那段是連續的。
            days, since, gaps = 0, last.get("date"), 0
            for snap in reversed(hist):
                snapshot = snap.get("snapshot") or {}
                if sec not in snapshot:
                    gaps += 1
                    continue
                q = ((snapshot[sec].get("periods") or {})
                     .get(period, {}) or {}).get("quadrant")
                if q != "leading":
                    break
                days += 1
                since = snap.get("date")
            if days < min_days or (max_days and days > max_days):
                continue
            rows.append({"sector": sec, "name": v.get("name") or sec,
                         "days": days, "since": since, "gaps": gaps,
                         "ratio": per.get("ratio"), "momentum": per.get("momentum")})
        rows.sort(key=lambda r: r["days"])          # 剛轉進來的排前面
        out[m] = rows
    return out


def stocks_in(sectors_by_mkt):
    """我們母體（combo_result）裡屬於這些類股的個股。回 {market: {sector: [row,…]}}。"""
    cr = _load("state/combo_result.json", {}) or {}
    rows = cr.get("rows") or cr.get("items") or []
    import re
    out = {}
    for r in rows:
        m = "tw" if re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(r.get("ticker"))) else "us"
        want = {x["sector"] for x in sectors_by_mkt.get(m, [])}
        if r.get("sector") in want:
            out.setdefault(m, {}).setdefault(r["sector"], []).append(r)
    for m in out:
        for sec in out[m]:
            # 亮燈多的、風報比高的排前面
            out[m][sec].sort(key=lambda r: (-(r.get("lit") or 0), -(r.get("rr") or -99)))
    return out


def lines(period="60", min_days=2, max_days=20, top_stocks=4, held=None):
    """給日報用的行。held 給定時，個股後面標 💼。"""
    t = turns(period, min_days, max_days)
    if not any(t.values()):
        return []
    st = stocks_in(t)
    out = []
    for m in ("tw", "us"):
        rows = t.get(m) or []
        if not rows:
            continue
        out.append(f"{MKT_LABEL[m]}")
        for r in rows:
            gw = f"　⚠️ 中間有 {r['gaps']} 天快照缺這個籃子" if r.get("gaps") else ""
            out.append(f"　🔵 **{r['name']}**　連續 {r['days']} 天（{r['since']} 轉進）{gw}")
            ss = (st.get(m) or {}).get(r["sector"]) or []
            if ss:
                names = []
                for x in ss[:top_stocks]:
                    mark = "💼" if held and _norm(x.get("ticker")) in held else ""
                    names.append(f"{mark}{x.get('ticker')}"
                                 f"（{x.get('lit')}燈"
                                 + (f"・風報比 {x['rr']:.1f}" if x.get("rr") else "")
                                 + "）")
                more = f" …另 {len(ss)-top_stocks} 檔" if len(ss) > top_stocks else ""
                out.append(f"　　母體內：{'、'.join(names)}{more}")
            else:
                out.append("　　母體內：沒有這一類的股票")
    return out


def _norm(tk):
    import re
    return re.sub(r"\.(TW|TWO)$", "", str(tk).upper()).replace(".", "-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="60", choices=["20", "60", "120"])
    ap.add_argument("--min-days", type=int, default=2)
    ap.add_argument("--max-days", type=int, default=20,
                    help="轉進超過這麼多天就不算「剛轉」；0＝不限")
    ap.add_argument("--with-stocks", action="store_true")
    a = ap.parse_args()

    t = turns(a.period, a.min_days, a.max_days or 0)
    hist = _load(HIST, {}) or {}
    asof = ((hist.get("us") or {}).get("index") or [{}])[-1].get("date")
    print(f"RRG {a.period} 日｜快照 {asof}｜連續 ≥{a.min_days} 天"
          + (f"、≤{a.max_days} 天" if a.max_days else "") + "在領先象限\n")

    st = stocks_in(t) if a.with_stocks else {}
    for m in ("tw", "us"):
        rows = t.get(m) or []
        print(f"{MKT_LABEL[m]}：{len(rows)} 個類股")
        if not rows:
            print("   （沒有符合的）")
        for r in rows:
            gw = f"　⚠️缺 {r['gaps']} 天快照" if r.get("gaps") else ""
            print(f"   🔵 {r['name']:12} 連續 {r['days']:2} 天"
                  f"（{r['since']} 轉進）　RS-Ratio {r['ratio']}　動能 {r['momentum']}{gw}")
            if a.with_stocks:
                ss = (st.get(m) or {}).get(r["sector"]) or []
                if ss:
                    for x in ss[:8]:
                        rr = f"風報比 {x['rr']:.1f}" if x.get("rr") else "無目標價"
                        print(f"        {str(x.get('ticker')):8}{str(x.get('name') or '')[:10]:12}"
                              f" {x.get('lit')}燈  {rr}")
                    if len(ss) > 8:
                        print(f"        …另 {len(ss)-8} 檔")
                else:
                    print("        （母體內沒有這一類的股票）")
        print()
    print("⚠️ 「連續 N 天」的 N 是 Leo 指定的門檻，不是我們回測出來的。")
    print("⚠️ 9/5 回測只證明「產業在領先象限」當**過濾條件**有幫助（12 格全改善、"
          "幅度不大）；**沒測過「剛轉進領先」本身是不是進場訊號**，兩件事不一樣。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
