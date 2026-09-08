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
OUT = os.path.join(HERE, "state", "mikeon_crosscheck.json")          # 最新一份
HIST = os.path.join(HERE, "state", "mikeon_crosscheck_history")      # 每季一份，只進不出

# 🔴 2026-09-08 Leo：「我們再累積一季的資料再看？」——
#    原本每次跑都**覆寫** OUT，下一季跑完這一季就沒了，**根本累積不到東西**。
#    ⭐ 「之後再比較」的計畫，前提是現在就把這一份留下來。
#       決定可以延後，**保存不行**——錯過的那一期補不回來。
#    所以另外存一份帶日期的到 HIST，只進不出（同 obis 存檔資料夾的原則）。


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


DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
STALE_DAYS = 45          # 檔案超過這麼多天沒更新就當「這一季還沒抓」


def newest_xlsx():
    """找最新的 myFavorite*.xlsx。回 (路徑, 幾天前) 或 (None, None)。"""
    import glob
    import time
    fs = glob.glob(os.path.join(DOWNLOADS, "myFavorite*.xlsx"))
    if not fs:
        return None, None
    f = max(fs, key=os.path.getmtime)
    return f, (time.time() - os.path.getmtime(f)) / 86400


def compare(rows, verbose=False):
    """跑完整份對帳。回 (統計dict, 明細list)。

    ⚠️ **手動跑與排程跑共用這一份**，不寫兩套——兩套遲早給出不一樣的數字。
    """
    import statistics as st
    ratios = [r["off_pricey"] / r["off_cheap"]
              for r in rows if r["off_cheap"] and r["off_cheap"] > 0]
    if verbose and ratios:
        print("【官方 Pricey / Cheap 的比值】"
              f"中位 {st.median(ratios):.4f}"
              f"  最小 {min(ratios):.4f}  最大 {max(ratios):.4f}")
        print(f"  我們用的 1.15^8 = {1.15 ** 8:.4f}"
              "  <- 一樣代表折現年數與報酬率假設相同\n")

    import buffett_screener as bs
    out = []
    for i, r in enumerate(rows, 1):
        sym = to_yf(r["ticker"], r["exchange"])
        try:
            d = bs.fetch_fundamentals(sym)
            ev = bs.evaluate(d) if d else {}
        except Exception as e:                              # noqa: BLE001
            if verbose:
                print(f"[{i:3}/{len(rows)}] {r['ticker']:8} X {str(e)[:60]}")
            out.append(dict(r, yf=sym, our_cheap=None, our_pricey=None,
                            err=str(e)[:80]))
            continue
        oc, op = ev.get("cheap_price"), ev.get("exp_price")
        rec = dict(r, yf=sym, our_cheap=oc, our_pricey=op,
                   eps_used=ev.get("eps_used"), eps_basis=ev.get("eps_basis"))
        if oc and r["off_cheap"]:
            rec["cheap_diff_pct"] = (oc / r["off_cheap"] - 1) * 100
        if op and r["off_pricey"]:
            rec["pricey_diff_pct"] = (op / r["off_pricey"] - 1) * 100
        out.append(rec)
        if verbose:
            dc = rec.get("cheap_diff_pct")
            print(f"[{i:3}/{len(rows)}] {r['ticker']:8} 官方 {r['off_cheap']:>9.1f} / "
                  f"我們 {(oc if oc else 0):>9.1f}"
                  + (f"  差 {dc:+7.1f}%" if dc is not None else "  （算不出）")
                  + f"  {rec.get('eps_basis') or '-'}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False, indent=1)
    io.open(OUT, "w", encoding="utf-8").write(payload)
    # 每季一份，檔名帶日期。⚠️ 同一天重跑會覆蓋同一個檔（那是同一次對帳的重試），
    # 不同日期一律各留一份。
    import datetime as _dt
    os.makedirs(HIST, exist_ok=True)
    io.open(os.path.join(HIST, f"{_dt.date.today().isoformat()}.json"),
            "w", encoding="utf-8").write(payload)

    v = sorted(r["cheap_diff_pct"] for r in out
               if r.get("cheap_diff_pct") is not None
               and r["cheap_diff_pct"] == r["cheap_diff_pct"])

    def w(pct):
        return sum(1 for x in v if abs(x) <= pct)

    return ({"total": len(out), "n": len(v),
             "med": st.median(v) if v else 0.0,
             "lo": v[0] if v else 0.0, "hi": v[-1] if v else 0.0,
             "p10": w(10), "p20": w(20), "p30": w(30), "p50": w(50),
             "ratio": st.median(ratios) if ratios else 0.0}, out)


REPORT_CSS = """
.ck{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}
.ck th,.ck td{padding:7px 9px;border-bottom:1px solid var(--line2);text-align:left}
.ck th{color:var(--dim);font-size:10px;letter-spacing:.12em;text-transform:uppercase;
 font-family:'IBM Plex Mono',ui-monospace,monospace;border-bottom-color:var(--hud)}
.ck .num{text-align:right;font-family:'IBM Plex Mono',ui-monospace,monospace;
 font-variant-numeric:tabular-nums}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
 background:var(--hud);border:1px solid var(--hud);margin:14px 0}
.sum div{background:var(--panel);padding:10px 12px}
.sum b{display:block;font-size:21px;font-family:'IBM Plex Mono',ui-monospace,monospace}
.sum span{font-size:10px;color:var(--dim);letter-spacing:.1em}
"""


def report_html(out_path, stats, rows):
    """給 Leo 看的對帳報告，放 obis（手機開得了）。"""
    from board_theme import BASE_CSS, header, nav_abs, esc

    def cell(r):
        d = r.get("cheap_diff_pct")
        cls = "pos" if abs(d) <= 10 else ("neg" if abs(d) > 30 else "")
        return (f'<tr><td><b>{esc(r["ticker"])}</b></td>'
                f'<td>{esc((r.get("name") or "")[:26])}</td>'
                f'<td class="num">{r["off_cheap"]:,.1f}</td>'
                f'<td class="num">{(r.get("our_cheap") or 0):,.1f}</td>'
                f'<td class="num"><span class="{cls}">{d:+.1f}%</span></td>'
                f'<td class="dimv">{esc(r.get("eps_basis") or "")}</td></tr>')

    ok = [r for r in rows if r.get("cheap_diff_pct") is not None
          and r["cheap_diff_pct"] == r["cheap_diff_pct"]]
    ok.sort(key=lambda r: abs(r["cheap_diff_pct"]))
    aligned = abs(stats["ratio"] - 1.15 ** 8) < 0.05
    body = ('<div class="sum">'
            f'<div><b>{stats["n"]}</b><span>可比對檔數</span></div>'
            f'<div><b>{stats["med"]:+.1f}%</b><span>中位差距</span></div>'
            f'<div><b>{stats["p10"]}</b><span>正負 10% 內</span></div>'
            f'<div><b>{stats["p30"]}</b><span>正負 30% 內</span></div>'
            f'<div><b>{stats["ratio"]:.4f}</b><span>官方 貴/俗 中位</span></div>'
            f'<div><b>{1.15 ** 8:.4f}</b><span>我們的 1.15^8</span></div></div>'
            + ('<div class="note">上面兩個比值一樣，代表兩邊的<b>折現年數（8 年）'
               '與要求報酬率（15%）假設相同</b>——這比數字差多少更根本。<br>'
               '差距集中在「常利 EPS 怎麼算」：官方是人工調整的正常化盈餘，'
               '我們用 yfinance 的 Normalized Income 自動近似。'
               '保險股與大額減損股偏差較大，是已知限制。</div>'
               if aligned else
               '<div class="stalewarn">⚠️ <b>官方的貴÷俗比值跟我們的 1.15^8 對不上</b>'
               '——那代表折現年數或要求報酬率的假設變了。'
               '**先查這個**，個別差距在這之前都沒有意義。</div>')
            + '<table class="ck"><tr><th>代號</th><th>名稱</th><th>官方俗價</th>'
              '<th>我們</th><th>差距</th><th>EPS 基準</th></tr>'
            + "".join(cell(r) for r in ok) + "</table>")
    html = ("<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>俗貴價對帳</title><style>" + BASE_CSS + REPORT_CSS
            + "</style></head><body><div class=\"wrap\">"
            + header("buffett", "俗貴價對帳",
                     f"跟 MIKEON 官方盈再表比對　·　{stats['date']}　·　"
                     f"共 {stats['total']} 檔、{stats['n']} 檔可比對",
                     nav_abs(), eyebrow="VALUATION AUDIT")
            + body + "</div></body></html>")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    io.open(out_path, "w", encoding="utf-8").write(html)
    return out_path


def run_auto():
    """排程用。**有新檔才對帳，沒有就只提醒。**

    🔴 這份 Excel 只能 Leo 自己去 MIKEON 抓，程式沒辦法自動下載。
       所以不能「到日子就跑」——沒有新檔卻硬跑，會拿舊資料算出「一切正常」，
       而其實根本沒有核對到新的一季。
       ⭐ 同記憶 verify_final_state_not_observed：
          **程式 exit 0 不代表它核對到的是新東西。**
    """
    import datetime as dt
    f, age = newest_xlsx()
    try:
        import notify_discord as nd
    except Exception:                                       # noqa: BLE001
        nd = None

    def say(msg):
        print(msg)
        if nd:
            nd.send_discord("private", msg, persona="戰情室")

    if not f:
        say("📐 **俗貴價對帳**：`~/Downloads` 找不到 `myFavorite*.xlsx`。\n"
            "請到 MIKEON 討論區匯出自選股清單（要含 Pricey / Cheap 兩欄）"
            "放進下載資料夾，再跑一次就會自動對帳。")
        return 0
    if age is not None and age > STALE_DAYS:
        say(f"📐 **俗貴價對帳**：找到的是 **{age:.0f} 天前**的檔案"
            f"（{os.path.basename(f)}），這一季應該還沒抓。\n"
            "⚠️ 沒有拿舊檔硬跑——舊檔會算出「一切正常」，讓人以為核對過了。\n"
            "請去 MIKEON 匯出新的再放進下載資料夾。")
        return 0

    rows = load_sheet(f)
    stats, out_rows = compare(rows)
    stats["date"] = dt.date.today().isoformat()
    from obis_paths import DAILY as OBIS
    rpt = report_html(os.path.join(OBIS, "俗貴價對帳.html"), stats, out_rows)
    aligned = abs(stats["ratio"] - 1.15 ** 8) < 0.05
    say(f"📐 **俗貴價對帳**（{stats['date']}，來源檔 {age:.0f} 天前）\n"
        f"· 可比對 **{stats['n']}/{stats['total']}** 檔，"
        f"中位差距 **{stats['med']:+.1f}%**\n"
        f"· 正負 10% 內 {stats['p10']} 檔、正負 30% 內 {stats['p30']} 檔\n"
        f"· 官方 貴÷俗 {stats['ratio']:.4f}（我們 {1.15 ** 8:.4f}）"
        + ("　✅ 折現假設一致" if aligned else "　⚠️ **假設對不上，先查這個**") + "\n"
        "· 報告：obis 每日看板／俗貴價對帳.html")
    print(f"✅ {rpt}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="跟 MIKEON 官方俗貴價對帳")
    ap.add_argument("xlsx", nargs="?", help="不給且用 --auto 時自動找 ~/Downloads")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--auto", action="store_true",
                    help="排程用：有新檔才對帳，沒有就只發提醒")
    a = ap.parse_args()
    if a.auto:
        return run_auto()
    if not a.xlsx:
        raise SystemExit("要給 xlsx 路徑，或用 --auto")

    rows = load_sheet(a.xlsx)
    if a.limit:
        rows = rows[:a.limit]
    print(f"讀到 {len(rows)} 檔\n")
    stats, _ = compare(rows, verbose=True)
    print(f"\n✅ 明細已存 {OUT}")
    if stats["n"]:
        print(f"\n【俗價差距】{stats['n']}/{stats['total']} 檔算得出來")
        print(f"  中位 {stats['med']:+.1f}%  最小 {stats['lo']:+.1f}%"
              f"  最大 {stats['hi']:+.1f}%")
        for pct, key in ((10, "p10"), (20, "p20"), (30, "p30"), (50, "p50")):
            print(f"  差距 <= {pct:>2}% 的：{stats[key]:>3} 檔"
                  f"（{stats[key] / stats['n'] * 100:.0f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
