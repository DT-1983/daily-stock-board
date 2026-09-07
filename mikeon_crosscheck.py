# -*- coding: utf-8 -*-
"""跟 MIKEON 官方盈再表的俗貴價對帳（2026-09-08 Leo 從討論區抓下自己的持股清單）。

Leo：「請看 CHEAP 跟 PRICY 那兩欄，想要核對一下我們的俗貴價計算方式」

## 為什麼要做這件事

我們的俗貴價是**自己算的**（`buffett_screener.evaluate`），
2026-08-27 對照官方 5 檔調校過一次（見那支的註解）。但 5 檔是小樣本，
而且調校那次只看台股／少數美股。Leo 這份是他自己 65 檔持股的官方值，
是目前能拿到**最大的一份對照組**。

⭐ 這支的用途是**量測差距**，不是改公式。
   看完之後要不要調參數是 Leo 的決定（見記憶 feedback_no_self_change_criteria）。

## 對帳邏輯

我們：貴價 = EPS × 30、俗價 = 貴價 ÷ 1.15^8（≈EPS×9.81），
      EPS 優先用常利（近2年平均×0.7 ＋ 近5年中位數×0.3）。
官方：Pricey / Cheap 兩欄直接給。

⚠️ **先驗一件事**：官方的 Pricey/Cheap 比值是不是也是 1.15^8＝3.059。
   如果不是，代表兩邊連折現年數或報酬率假設都不同，那比「數字差多少」更根本。

用法：
    python mikeon_crosscheck.py "C:/path/myFavorite.xlsx"
    python mikeon_crosscheck.py xxx.xlsx --limit 10      # 先看幾檔
"""
import argparse
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "state", "mikeon_crosscheck.json")


def load_sheet(path):
    import pandas as pd
    df = pd.read_excel(path)
    need = {"Equity", "Pricey", "Cheap"}
    miss = need - set(df.columns)
    if miss:
        raise SystemExit(f"Excel 少了欄位：{miss}")
    rows = []
    for _, r in df.iterrows():
        tk = str(r["Equity"]).strip()
        if not tk or tk.lower() == "nan":
            continue
        try:
            pricey = float(r["Pricey"])
            cheap = float(r["Cheap"])
        except (TypeError, ValueError):
            continue
        rows.append({"ticker": tk,
                     "name": str(r.get("COMPANY", "")).strip()[:40],
                     "exchange": str(r.get("Exchange", "")).strip(),
                     "price": (float(r["Last Price"])
                               if str(r.get("Last Price", "")).replace(".", "").isdigit()
                               else None),
                     "off_pricey": pricey, "off_cheap": cheap})
    return rows


def to_yf(ticker, exchange):
    """MIKEON 的代號 → yfinance。台股在 Exchange 欄是 TWSE/TPEX。"""
    t = str(ticker).strip().upper()
    ex = str(exchange or "").upper()
    if t.isdigit() or (t[:-1].isdigit() and t[-1].isalpha()):
        if "TPEX" in ex or "OTC" in ex:
            return t + ".TWO"
        return t + ".TW"
    return t


def main():
    ap = argparse.ArgumentParser(description="跟 MIKEON 官方俗貴價對帳")
    ap.add_argument("xlsx")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows = load_sheet(a.xlsx)
    if a.limit:
        rows = rows[:a.limit]
    print(f"讀到 {len(rows)} 檔\n")

    # ── 先驗官方自己的比值 ────────────────────────────────
    import statistics
    ratios = [r["off_pricey"] / r["off_cheap"]
              for r in rows if r["off_cheap"] and r["off_cheap"] > 0]
    if ratios:
        print("【官方 Pricey ÷ Cheap 的比值】"
              f"中位 {statistics.median(ratios):.4f}"
              f"　最小 {min(ratios):.4f}　最大 {max(ratios):.4f}")
        print(f"  我們用的 1.15^8 = {1.15 ** 8:.4f}"
              "　← 一樣代表折現年數與報酬率假設相同\n")

    import buffett_screener as bs
    out = []
    for i, r in enumerate(rows, 1):
        sym = to_yf(r["ticker"], r["exchange"])
        try:
            d = bs.fetch_fundamentals(sym)
            ev = bs.evaluate(d) if d else {}
        except Exception as e:                              # noqa: BLE001
            print(f"[{i:3}/{len(rows)}] {r['ticker']:8} ❌ {str(e)[:60]}")
            out.append(dict(r, yf=sym, our_cheap=None, our_pricey=None,
                            err=str(e)[:80]))
            continue
        oc, op = ev.get("cheap_price"), ev.get("expensive_price") or ev.get("exp_price")
        rec = dict(r, yf=sym, our_cheap=oc, our_pricey=op,
                   eps_used=ev.get("eps_used"), eps_basis=ev.get("eps_basis"))
        if oc and r["off_cheap"]:
            rec["cheap_diff_pct"] = (oc / r["off_cheap"] - 1) * 100
        if op and r["off_pricey"]:
            rec["pricey_diff_pct"] = (op / r["off_pricey"] - 1) * 100
        out.append(rec)
        dc = rec.get("cheap_diff_pct")
        print(f"[{i:3}/{len(rows)}] {r['ticker']:8} 官方俗 {r['off_cheap']:>9.1f} / "
              f"我們 {(oc if oc else 0):>9.1f}"
              + (f"　差 {dc:+7.1f}%" if dc is not None else "　（我們算不出）")
              + f"　EPS基準 {rec.get('eps_basis') or '—'}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n✅ 明細已存 {OUT}")

    have = [r for r in out if r.get("cheap_diff_pct") is not None]
    if have:
        ds = sorted(r["cheap_diff_pct"] for r in have)
        import statistics as st
        print(f"\n【俗價差距】{len(have)}/{len(out)} 檔算得出來")
        print(f"  中位 {st.median(ds):+.1f}%　平均 {st.mean(ds):+.1f}%"
              f"　最小 {ds[0]:+.1f}%　最大 {ds[-1]:+.1f}%")
        within = lambda p: sum(1 for x in ds if abs(x) <= p)   # noqa: E731
        for p in (10, 20, 30, 50):
            print(f"  差距 ≤{p:>2}% 的：{within(p):>3} 檔（{within(p)/len(ds)*100:.0f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
