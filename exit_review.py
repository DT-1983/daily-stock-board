# -*- coding: utf-8 -*-
"""出場檢視表（2026-09-06，Leo：「週一要來研究做進出」）。

把**已經符合老墨出場條件**的持股，跟做決定需要的數字擺在同一頁：
持有成本／股數／現在損益／歷史高點／距停損／訊號已經成立多久。

## 兩組（老墨的規則）

・🔴 **兩條都成立**：SuperTrend 翻空 ＋ RS(60) 跌破自身均線
・🟡 **只有 RS 跌破**：他的規則裡 RS 跌破就是「剩餘全出」，所以也列進來

⚠️ 「只有 SuperTrend 翻空」那組**不在這頁**——那組是「賣一半」，Leo 這次指定
只要這兩組。

## ⚠️ 這頁不下建議

它只把數字擺在一起。我們自己 5.5 年的回測結論是**日線 SuperTrend 賣訊在高波動
個股上 75% 事後看是錯的**（正常回檔被誤判成反轉，趨勢倉因此改成週線判斷）；
老墨的「RS 跌破」那條我們**沒有單獨回測過**。所以這頁標的是「規則說什麼」，
不是「該不該賣」。

## 資料來源

・訊號：`state/combo_result.json`（每日燈號掃描）
・成本/股數/市值：`trade_plan.load_holdings()`（Firstrade 報表）
・歷史高點：price_store 的 3 年日線

用法:
    python exit_review.py            # 產出到 obis 每日看板
    python exit_review.py -o x.html
"""
import argparse
import collections
import io
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                      # noqa: E402

FNAME = "出場檢視表.html"


def _load(p, d=None):
    import json
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def gather():
    """回 (rows, meta)。rows 每筆含訊號、成本、損益、高點。"""
    import re
    import investment_chief as ic
    import trade_plan

    cr = _load("state/combo_result.json", {}) or {}
    scan = cr.get("rows") or cr.get("items") or []
    by = {ic.norm_ticker(r.get("ticker")): r for r in scan}
    asof = scan[0].get("asof") if scan else "—"

    # 🔴 2026-09-06 Leo：「同時說明是誰的持股」。
    # 原本只讀 load_holdings()（＝Leo 的 Firstrade），漏掉另外三個帳戶——
    # 實際有 **92 筆、4 個帳戶**：Leo Firstrade 66／Leo 繼承台股 12／Ian 8／Loewe 6。
    # 首版就是因為這樣，2303 聯電（小孩的）的部位欄印成「—」。
    # ⭐ 「持股」不是一個母體是四個，混在一起算佔比會失真——所以**佔比按各帳戶自己算**。
    rows_all = trade_plan._read_rows()
    pos = collections.defaultdict(lambda: {"sh": 0.0, "mv": 0.0, "cb": 0.0,
                                           "name": "", "who": set()})
    for r in rows_all:
        n = ic.norm_ticker(r.get("ticker"))
        p = pos[n]
        p["sh"] += r.get("shares") or 0
        p["mv"] += r.get("market_value") or 0
        p["cb"] += r.get("cost_basis") or 0
        p["name"] = p["name"] or (r.get("name") or "")
        p["who"].add((r.get("owner") or "?", r.get("account") or "?"))
    total_mv = sum(p["mv"] for p in pos.values())
    # 各帳戶自己的總市值（算「佔該帳戶多少」用）
    acct_mv = collections.defaultdict(float)
    for r in rows_all:
        acct_mv[r.get("account") or "?"] += r.get("market_value") or 0

    held = {}
    for raw in ic.held_universe():
        held.setdefault(ic.norm_ticker(raw), raw)

    # 歷史高點：3 年日線。⚠️ 只對要列出來的那些檔抓，不掃全母體。
    want = []
    missing = []
    for n in held:
        r = by.get(n)
        if not r:
            missing.append(n)
            continue
        bear = not r.get("bull")
        rsdn = (r.get("rs_short") is not None and r["rs_short"] < 0)
        if bear and rsdn:
            want.append((n, "both", r))
        elif rsdn:
            want.append((n, "rs", r))

    # 🔴 沒進每日掃描的持股要**補算**，不能靜默略過。
    # 首版就是這樣漏掉 R（Ryder）——它兩條都成立、是真的該進這張表，
    # 但因為 combo_scan 判定「資料長度不足」而被排除，表上完全看不到它存在。
    # ⭐ 「沒被檢查」長得像「檢查過沒事」——這個專案踩過太多次，這裡直接補。
    filled = []
    if missing:
        try:
            import thesis_check as tcm
            for n in missing:
                st = tcm._st_state(n)
                if not st:
                    filled.append((n, None))
                    continue
                bear, rsdn = bool(st.get("st_bearish")), bool(st.get("rs60_broken"))
                if bear and rsdn or rsdn:
                    want.append((n, "both" if (bear and rsdn) else "rs",
                                 {"ticker": n, "name": "", "price": None,
                                  "rs_short": None, "bull": not bear,
                                  "st_line": None, "gap_pct": None, "_filled": True}))
                filled.append((n, (bear, rsdn)))
        except Exception as e:                              # noqa: BLE001
            print(f"  [warn] 補算失敗：{str(e)[:60]}")

    highs = {}
    try:
        import price_store
        import tw_symbol
        sym = {n: (tw_symbol.resolve(n) if re.match(r"^\d{4,6}[A-Z]?$", n)
                   else n.replace(".", "-")) for n, _, _ in want}
        closes = price_store.get_closes(sorted(set(sym.values())), period="3y")
        for n, _k, _r in want:
            s = closes.get(sym[n])
            if s is None or s.dropna().empty:
                continue
            s = s.dropna()
            highs[n] = {"hi3y": float(s.max()), "hi3y_d": str(s.idxmax())[:10],
                        "hi52": float(s.tail(252).max()),
                        "hi52_d": str(s.tail(252).idxmax())[:10]}
    except Exception as e:                                  # noqa: BLE001
        print(f"  [warn] 歷史高點抓不到（那幾欄會空著）：{str(e)[:70]}")

    rows = []
    for n, kind, r in want:
        p = pos.get(n) or {}
        sh, mv, cb = p.get("sh") or 0, p.get("mv") or 0, p.get("cb") or 0
        who = sorted(p.get("who") or [])
        acct = "／".join(sorted({a for _o, a in who})) or "—"
        owner = "／".join(sorted({o for o, _a in who})) or "—"
        base_mv = sum(acct_mv.get(a, 0) for a in {a for _o, a in who}) or total_mv
        hi = highs.get(n) or {}
        px = r.get("price")
        rows.append({
            "tk": n, "kind": kind,
            "name": (r.get("name") or p.get("name") or "")[:22],
            "px": px, "rs": r.get("rs_short"), "lit": r.get("lit"),
            "st_line": r.get("st_line"), "gap": r.get("gap_pct"),
            "sh": sh, "mv": mv, "cb": cb,
            # 🔴 平均成本換成**跟現價同一種幣別**。
            # 報表的 cost_basis／market_value 都是台幣，但 `現價` 是原幣（美股美元）。
            # 首版並排放，AMD 顯示「平均成本 3,457／現價 477.57」——**看起來像賠了 86%**，
            # 實際是賺 317%。⭐ 同一列的兩個數字不同單位，比不上色的錯誤更容易誤導。
            # 換算係數用「市值÷股數÷現價」自己反推，不引外部匯率表（自洽且不會過期）。
            "avg": ((cb / sh) / ((mv / sh) / px) if (sh and mv and px) else
                    (cb / sh) if sh else None),
            "nopos": not sh,
            "pnl": (mv - cb) if (mv and cb) else None,
            "pnl_pct": (mv / cb - 1) * 100 if cb else None,
            "w": (mv / base_mv * 100) if base_mv else None,
            "owner": owner, "acct": acct,
            "hi52": hi.get("hi52"), "hi52_d": hi.get("hi52_d"),
            "hi3y": hi.get("hi3y"), "hi3y_d": hi.get("hi3y_d"),
            "dd52": ((px / hi["hi52"] - 1) * 100) if (px and hi.get("hi52")) else None,
            "dd3y": ((px / hi["hi3y"] - 1) * 100) if (px and hi.get("hi3y")) else None,
            "target": r.get("target"),
            "filled": bool(r.get("_filled")),
        })
    # 部位大的排前面——要動的話那才是真的影響總資產的
    rows.sort(key=lambda x: -(x["mv"] or 0))
    return rows, {"asof": asof, "total_mv": total_mv, "n_pos": len(pos),
                  "acct_mv": dict(acct_mv), "filled": filled}


CSS = """
.sb{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px;margin:12px 0}
.sb h2{font-size:15px;font-weight:700;color:#F5B841;margin-bottom:4px}
.sb .sub{font-size:11.5px;color:var(--dim);margin-bottom:9px;line-height:1.7}
.sb .sub b{color:#CBD5E1}
.ex{width:100%;border-collapse:collapse;font-size:12.5px}
.ex th{text-align:right;padding:7px 7px;color:var(--dim);font-weight:600;font-size:11px;
 border-bottom:1px solid var(--line);white-space:nowrap}
.ex th:first-child,.ex th:nth-child(2){text-align:left}
.ex td{padding:9px 7px;border-bottom:1px solid var(--line2);text-align:right;
 font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums;
 color:var(--muted);white-space:nowrap}
.ex td:first-child,.ex td:nth-child(2){text-align:left;font-family:inherit}
.ex td.tk{color:var(--ink);font-weight:700}
.ex td.nm{color:var(--dim);font-size:11.5px}
.ex tr.big td{background:rgba(248,113,113,.05)}
.pos{color:var(--up)}.neg{color:var(--down)}.dim{color:var(--dim)}
.warnbox{background:var(--surface);border:1px solid var(--line);
 border-left:3px solid var(--warn);border-radius:10px;padding:12px 15px;margin:12px 0;
 font-size:13px;line-height:1.9;color:var(--muted)}
.warnbox b{color:#FCD34D}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:8px 0}
.kv .c{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 10px}
.kv .k{font-size:10px;color:var(--dim)}
.kv .v{font-size:16px;font-weight:700;margin-top:3px;
 font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums}
.kv .s{font-size:10.5px;color:var(--muted);margin-top:2px}
@media(max-width:760px){
 .ex,.ex tbody,.ex tr,.ex td{display:block;width:100%}
 .ex thead{display:none}
 .ex tr{border:1px solid var(--line);border-radius:10px;margin:9px 0;
  background:var(--surface);padding:3px 2px}
 .ex td{border-bottom:1px solid var(--line2);padding:7px 12px;text-align:right}
 .ex tr td:last-child{border-bottom:none}
 .ex td::before{content:attr(data-h);float:left;color:var(--dim);font-size:10.5px;
  font-family:inherit}
 .ex td.tk::before,.ex td.nm::before{content:none}
 .ex td.tk{font-size:15px}
}
"""


def render(rows, meta):
    from board_theme import BASE_CSS, esc, header, nav_abs

    def n(v, d=2, suf=""):
        return "—" if v is None else f"{v:,.{d}f}{suf}"

    def sgn(v, d=1, suf="%"):
        if v is None:
            return '<span class="dim">—</span>'
        c = "pos" if v >= 0 else "neg"
        return f'<span class="{c}">{v:+,.{d}f}{suf}</span>'

    # 帳戶 → 顯示標記。⚠️ 這四個是不同的錢與不同的決策權，別混在一起看。
    WHO = {"Firstrade": ("", "Leo 自己操作"),
           "台股(繼承帳戶)": ("🏠", "Leo 繼承（監控不參與風控）"),
           "子帳戶A": ("👦", "Ian"),
           "子帳戶B": ("👧", "Loewe")}

    def who_tag(acct):
        for k, (ic_, lab) in WHO.items():
            if k in (acct or ""):
                return ic_, lab
        return "", acct or "—"

    def table(rs):
        if not rs:
            return '<div class="sub">這一組目前沒有標的。</div>'
        head = ("<tr><th>代號</th><th>名稱</th><th>誰的</th><th>股數</th><th>平均成本</th><th>現價</th>"
                "<th>市值</th><th>損益</th><th>報酬</th><th>佔部位</th>"
                "<th>52週高</th><th>距52週高</th><th>3年高</th><th>距3年高</th>"
                "<th>RS60</th><th>SuperTrend線</th></tr>")
        body = []
        for r in rs:
            big = ' class="big"' if (r["w"] or 0) >= 3 else ""
            body.append(
                f"<tr{big}>"
                f'<td class="tk" data-h="代號">{esc(r["tk"])}'
                + ('<span class="dim" style="font-size:10px"> ⚠️補算</span>'
                   if r.get("filled") else "") + "</td>"
                f'<td class="nm" data-h="名稱">{esc(r["name"])}</td>'
                f'<td class="nm" data-h="誰的">'
                + ('<span class="dim">⚠️ 報表查無部位</span>' if r.get("nopos")
                   else f'{who_tag(r["acct"])[0]} {esc(who_tag(r["acct"])[1])}')
                + "</td>"
                f'<td data-h="股數">{n(r["sh"], 2)}</td>'
                f'<td data-h="平均成本">{n(r["avg"])}</td>'
                f'<td data-h="現價">{n(r["px"])}</td>'
                f'<td data-h="市值">{n(r["mv"], 0)}</td>'
                f'<td data-h="損益">{sgn(r["pnl"], 0, "")}</td>'
                f'<td data-h="報酬">{sgn(r["pnl_pct"])}</td>'
                f'<td data-h="佔部位">{n(r["w"], 1, "%")}</td>'
                f'<td data-h="52週高">{n(r["hi52"])}'
                + (f'<br><span class="dim" style="font-size:10px">{esc(r["hi52_d"])}</span>'
                   if r.get("hi52_d") else "")
                + "</td>"
                f'<td data-h="距52週高">{sgn(r["dd52"])}</td>'
                f'<td data-h="3年高">{n(r["hi3y"])}'
                + (f'<br><span class="dim" style="font-size:10px">{esc(r["hi3y_d"])}</span>'
                   if r.get("hi3y_d") else "")
                + "</td>"
                f'<td data-h="距3年高">{sgn(r["dd3y"])}</td>'
                f'<td data-h="RS60">{sgn(r["rs"], 2)}</td>'
                f'<td data-h="SuperTrend線">{n(r["st_line"])}'
                + (f'<br><span class="dim" style="font-size:10px">'
                   f'距 {r["gap"]:+.1f}%</span>' if r.get("gap") is not None else "")
                + "</td></tr>")
        return f'<table class="ex">{head}{"".join(body)}</table>'

    both = [r for r in rows if r["kind"] == "both"]
    rs_only = [r for r in rows if r["kind"] == "rs"]
    mv_b = sum(r["mv"] or 0 for r in both)
    mv_r = sum(r["mv"] or 0 for r in rs_only)
    tot = meta["total_mv"] or 1
    pnl_b = sum(r["pnl"] or 0 for r in both)
    pnl_r = sum(r["pnl"] or 0 for r in rs_only)

    B = []
    B.append('<div class="warnbox">'
             '<b>這頁只擺數字，不建議買賣。</b><br>'
             '・老墨的規則：<b>SuperTrend 翻空 → 賣一半</b>；'
             '<b>RS(60) 跌破自身均線 → 剩餘全出</b>。這兩組都已經到「全出」那一條。<br>'
             '・⚠️ 我們自己 5.5 年的回測結論是：<b>日線 SuperTrend 的賣訊，'
             '在高波動個股上 75% 事後看是錯的</b>（正常回檔被誤判成反轉）——'
             '趨勢倉因此改成週線判斷。老墨的「RS 跌破」那條，<b>我們沒有單獨回測過</b>。<br>'
             '・所以這頁標的是「<b>規則說什麼</b>」，不是「<b>該不該賣</b>」。'
             '</div>')

    B.append('<div class="sb"><h2>合計</h2>' + "".join([
        '<div class="kv">',
        f'<div class="c"><div class="k">🔴 兩條都成立</div><div class="v">{len(both)} 檔</div>'
        f'<div class="s">市值 {mv_b:,.0f}（全部持股的 {mv_b/tot*100:.1f}%）</div></div>',
        f'<div class="c"><div class="k">🟡 只有 RS 跌破</div><div class="v">{len(rs_only)} 檔</div>'
        f'<div class="s">市值 {mv_r:,.0f}（全部持股的 {mv_r/tot*100:.1f}%）</div></div>',
        f'<div class="c"><div class="k">兩組合計佔部位</div>'
        f'<div class="v">{(mv_b+mv_r)/tot*100:.1f}%</div>'
        f'<div class="s">NT$ {mv_b+mv_r:,.0f}</div></div>',
        f'<div class="c"><div class="k">兩組未實現損益</div>'
        f'<div class="v {"pos" if pnl_b+pnl_r >= 0 else "neg"}">{pnl_b+pnl_r:+,.0f}</div>'
        f'<div class="s">🔴 {pnl_b:+,.0f}　🟡 {pnl_r:+,.0f}</div></div>',
        '</div>',
        '<div class="sub">⚠️ <b>市值與損益的單位是新台幣</b>（美股已換算）；'
        '<b>平均成本與現價則是原幣</b>（美股美元、台股台幣）——'
        '這樣同一列的成本與現價才能直接比。<br>'
        '⚠️ 上面四格的百分比分母是<b>全部四個帳戶合計</b>；'
        '表格裡每一列的「佔部位」分母是<b>那一檔所屬帳戶自己的總市值</b>'
        '——四個帳戶是不同的錢與不同的決策權，混在一起算佔比會失真。<br>'
        '底色偏紅的列＝佔它所屬帳戶 ≥3%。</div>']) + "</div>")

    B.append('<div class="sb"><h2>🔴 兩條都成立</h2>'
             '<div class="sub">SuperTrend 翻空 <b>而且</b> RS(60) 跌破自身均線'
             '——老墨規則裡兩個階段都到了。按<b>市值大小</b>排序，'
             '要動的話大部位才真的影響總資產。</div>' + table(both) + "</div>")

    B.append('<div class="sb"><h2>🟡 只有 RS 跌破 60MA</h2>'
             '<div class="sub">SuperTrend 還在多方，但 RS 已經跌破——'
             '老墨的規則裡<b>這一條就是「剩餘全出」</b>，不用等 SuperTrend。'
             '⚠️ 這也表示「<b>股價還沒轉弱、只是跑輸大盤</b>」，跟上面那組性質不同。'
             '</div>' + table(rs_only) + "</div>")

    B.append('<div class="sb"><h2>欄位怎麼讀</h2><div class="sub">'
             '<b>RS60</b>＝相對大盤 60 日強弱的乖離，<b>負數就是跌破自身均線</b>。<br>'
             '<b>SuperTrend 線</b>＝那條動態支撐；「距 x%」是現價離它多遠。'
             '⚠️ 這兩組都已經翻空或轉弱，那條線現在是<b>壓力不是支撐</b>。<br>'
             '<b>距 52 週高／距 3 年高</b>＝現價從高點回落多少。'
             '⚠️ 回檔深不等於便宜，也不等於該賣——它只告訴你「離最好的時候多遠」。<br>'
             '<b>平均成本</b>由 Firstrade 報表的總成本 ÷ 股數推得；'
             '<b>沒有逐筆買進紀錄，所以算不出「買進後的最高點」</b>，'
             '這裡給的是 52 週／3 年的絕對高點。'
             '</div></div>')

    B.append(f'<div class="sb"><div class="sub">'
             f'訊號資料日 <b>{esc(meta["asof"])}</b>（最後一個交易日）｜'
             f'成本與股數來自 Firstrade 報表｜高點取 price_store 3 年日線。<br>'
             f'⚠️ 名單是<b>現在的狀態</b>不是「今天剛觸發」——多數是幾週前就跌破了。'
             f'</div></div>')

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>出場檢視表</title><style>" + BASE_CSS + CSS
            + '</style></head><body><div class="wrap">'
            + header("lamp", "出場檢視表",
                     f"符合老墨出場條件的持股　{len(both)+len(rs_only)} 檔／"
                     f"佔部位 {(mv_b+mv_r)/tot*100:.1f}%　訊號日 {esc(meta['asof'])}",
                     nav_abs())
            + "".join(B) + "</div></body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="")
    a = ap.parse_args()
    rows, meta = gather()
    if not rows:
        print("目前沒有持股符合這兩組條件。")
        return 0
    html = render(rows, meta)
    out = a.output or op.daily(FNAME)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    nb = sum(1 for r in rows if r["kind"] == "both")
    print(f"✅ 已存 {out}（{len(html):,} bytes）")
    print(f"   🔴 兩條都成立 {nb} 檔｜🟡 只有 RS 跌破 {len(rows)-nb} 檔"
          f"｜訊號日 {meta['asof']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
