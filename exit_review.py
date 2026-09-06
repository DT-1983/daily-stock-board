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
    python exit_review.py            # 產出到 obis 存檔（帶日期，一次性快照）
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

# 🔴 2026-09-06 Leo（兩次修正，順序很重要）：
#   ① 「檔案不要顯示在網頁上」→ 不推投資站。**家人看得到那個站**，
#      這一頁有實際持股、成本、損益、誰的帳戶。
#   ② 「網頁還是可以每週更新」→ 所以它不是一次性的，是**每週覆寫的看板**。
#
# 因此放 `每日看板/`（＝程式會再寫它一次的東西）而不是 `存檔/`，檔名**不帶日期**。
# 9/5 定的分法是「看誰會再寫它一次」，不是看更新頻率——每週覆寫仍然是覆寫，
# 而檔名帶日期會讓 52 週堆出 52 份，還會讓「壞掉沒更新」跟「本來就是那天的」
# 分不出來。頁內有「資料日期」，要知道新舊看那裡。
#
# ✅ 不公開的做法：只寫 obis、不寫 docs/、不進版控、網站導覽不連它。
#    這三件事任何一件破掉，家人就看得到——所以排程裡**不准**加 git add。
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
    # 原本只讀 load_holdings()（＝主帳戶那一個），漏掉其餘帳戶——實際有 92 筆、
    # 4 個帳戶。首版就是因為這樣，其中一檔（不在主帳戶裡的）部位欄印成「—」。
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

    # 🔴 2026-09-06 Leo：「可以幫我加貴價嗎？還有是否超過貴價」。
    # 直接讀 `state/valuation_state.json`——那是每天 07:33 算好的俗/貴價快取
    # （洪瑞泰法，美股用預期 EPS、台股用實績 EPS，見 hongruitai_method）。
    # ⚠️ **不重算**：compute_valuation 要現抓每一檔的財報，慢而且會跟站上其他頁
    #    算出不一樣的數字。同一個指標只能有一個來源。
    # ⚠️ 貴價的幣別跟現價一致（美股美元、台股台幣）——這點 8/31 修過一次
    #    （ADR 幣別錯位害 12 檔全錯），所以這裡可以直接跟 px 相除。
    val = _load("state/valuation_state.json", {}) or {}
    val = {ic.norm_ticker(k): v for k, v in val.items()}

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
            "name": (r.get("name") or p.get("name") or "")[:14],
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
            # 🔴 2026-09-06 Leo：「美股可以用美金嗎」。
            # 報表的 market_value／cost_basis 都是台幣，但 Leo 看美股部位是用美元想的
            # （成本 114.32、現價 477.57 都是美元，市值卻是台幣＝腦袋要一直換算）。
            # 匯率同樣用「市值÷股數÷現價」反推——**不引外部匯率表**：
            # 這樣算出來的數字跟報表自己完全自洽，也不會因為匯率表過期而對不上。
            # ⚠️ `mv`（台幣）保留不動：佔部位、排序、跨帳戶合計都需要共同單位。
            "fx": ((mv / sh) / px) if (sh and mv and px) else None,
            "mv_n": (mv / ((mv / sh) / px)) if (sh and mv and px) else None,
            "pnl_n": ((mv - cb) / ((mv / sh) / px))
                     if (sh and mv and cb and px) else None,
            # 幣別看代號（純數字＝台股），跟系統其他地方同一把尺；
            # 不用「fx 接近 1」去猜——那在匯率真的接近 1 的市場會判錯。
            "cur": "NT$" if str(n)[:1].isdigit() else "US$",
            "owner": owner, "acct": acct,
            "hi52": hi.get("hi52"), "hi52_d": hi.get("hi52_d"),
            "hi3y": hi.get("hi3y"), "hi3y_d": hi.get("hi3y_d"),
            "dd52": ((px / hi["hi52"] - 1) * 100) if (px and hi.get("hi52")) else None,
            "dd3y": ((px / hi["hi3y"] - 1) * 100) if (px and hi.get("hi3y")) else None,
            "exp": (val.get(n) or {}).get("expensive"),
            "cheap": (val.get(n) or {}).get("cheap"),
            "val_at": (val.get(n) or {}).get("updated_at"),
            # 「超過貴價多少」——正數＝已經比貴價還貴。
            "over": (((px / (val[n]["expensive"]) - 1) * 100)
                     if (px and (val.get(n) or {}).get("expensive")) else None),
            "target": r.get("target"),
            "filled": bool(r.get("_filled")),
        })
    # 部位大的排前面——要動的話那才是真的影響總資產的
    rows.sort(key=lambda x: -(x["mv"] or 0))
    # 「只有 ST 翻空」那組不列在這頁，但要**數出來寫在頁面上**——
    # 有一盞「ST 翻空」的燈卻看不到那種情況，會以為它不存在。
    st_only = sum(1 for n2 in held
                  if (by.get(n2) and not by[n2].get("bull")
                      and not (by[n2].get("rs_short") is not None
                               and by[n2]["rs_short"] < 0)))
    return rows, {"asof": asof, "total_mv": total_mv, "n_pos": len(pos),
                  "st_only": st_only,
                  "acct_mv": dict(acct_mv), "filled": filled}


CSS = """
.sb{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px;margin:12px 0}
.sb h2{font-size:15px;font-weight:700;color:#F5B841;margin-bottom:4px}
.sb .sub{font-size:11.5px;color:var(--dim);margin-bottom:9px;line-height:1.7}
.sb .sub b{color:#CBD5E1}
/* 篩選列。這頁不上站，所以不套 board_theme 的 .ctrl/.seg，自己寫最小一組。 */
.fbar{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;
 margin:14px 0 4px;padding:10px 12px;border:1px solid var(--line);
 border-radius:12px;background:var(--surface)}
.fg{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.fl{font-size:11px;color:var(--dim);margin-right:2px}
.fb{font:inherit;font-size:12px;padding:4px 10px;border-radius:999px;cursor:pointer;
 border:1px solid var(--line);background:transparent;color:var(--dim)}
.fb:hover{border-color:var(--accent,#93c5fd)}
.fb.on{background:var(--accent,#3b82f6);border-color:var(--accent,#3b82f6);
 color:#fff;font-weight:600}
.fq{font:inherit;font-size:12px;padding:5px 10px;border-radius:8px;min-width:150px;
 border:1px solid var(--line);background:transparent;color:var(--ink)}
.fcount{margin-left:auto;font-size:12px;color:var(--dim)}
.cur{font-size:9.5px;color:var(--dim);margin-right:3px}
.exempty{padding:14px 4px;color:var(--dim);font-size:12.5px}
/* 現價已經高過貴價（洪瑞泰法）——用底色標，比多一欄文字省版面 */
.ex td.overexp{color:var(--neg,#f87171);background:rgba(248,113,113,.07)}
/* ⚠️ 2026-09-06：改成卡片列時我把 .exwrap 之後的樣式整段砍掉，
   結果連**跟表格無關**的 .pos/.warnbox/.kv（合計那四格）也一起沒了，
   合計區塊變成一堆裸文字。⭐ 用「從某個選擇器砍到區塊結尾」的方式刪 CSS，
   刪掉的範圍會遠大於想刪的東西。以下是撿回來的部分。 */
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
@media(max-width:900px){
 .exwrap{overflow-x:visible;margin:0;padding:0}
 .ex{min-width:0}
 .scrollhint{display:none}
 .ex,.ex tbody,.ex tr,.ex td{display:block;width:100%}
 .ex thead{display:none}
 .ex tr{border:1px solid var(--line);border-radius:10px;margin:9px 0;
  background:var(--surface);padding:3px 2px}
 /* 🔴 2026-09-06 Leo：「手機閱讀空間有點大，可以改密集一點嗎？」
    原本每個欄位各佔一整列（15 列），一檔就吃掉一整個螢幕，37 檔要滑很久。
    改成**兩欄格線**：列數砍半，padding 7px→4px，字級 12.5→12。
    代號與名稱跨滿整行當卡片標題；帶副行的欄位（歷史高點/貴價/ST線）也跨滿，
    否則副行會把那一格撐高、兩欄高度對不齊。 */
 .ex tr{display:grid;grid-template-columns:1fr 1fr;gap:0 8px;padding:4px 6px}
 .ex td{border-bottom:1px solid var(--line2);padding:4px 6px;text-align:right;
  display:flex;justify-content:space-between;align-items:baseline;gap:8px;
  font-size:12px;line-height:1.45}
 .ex td::before{float:none;flex:0 0 auto}
 .ex td.tk,.ex td.exnm,.ex td[data-h="歷史高點"],.ex td[data-h="貴價"],
 .ex td[data-h="SuperTrend線"]{grid-column:1/-1}
 .ex tr td:last-child{border-bottom:none}
 .ex td::before{content:attr(data-h);color:var(--dim);font-size:10.5px;
  font-family:inherit}
 /* 手機卡片版：解掉桌機版的截字寬度；代號與名稱不加欄位標籤（它們就是卡片標題，
    加了會變成「代號AMD」黏在一起），但「誰的」要留標籤，否則只看到一個「Leo」。 */
 .ex td.exnm,.ex td.exwho{max-width:none;overflow:visible;white-space:normal}
 .ex td.tk::before,.ex td.exnm::before{content:none}
 .ex td.tk{font-size:15px}
}

/* ── 三燈摘要 + 展開細節（2026-09-06 Leo：「可以做像燈號那樣？」）──
   改成 <details> 之後**不再是表格**，所以沒有 min-width、沒有橫捲，
   手機與桌機共用同一份版面，不用再維護兩套排版。 */
.rows{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.row{border:1px solid var(--line);border-radius:10px;background:var(--surface);
 overflow:hidden}
.row.big{border-color:rgba(248,113,113,.45)}
.row[open]{border-color:var(--accent,#3b82f6)}
/* ⚠️ 要 width:100%+box-sizing：<summary> 設 display:grid 之後在 Chrome 上是
   縮成內容寬（實測桌機 642px 塞在 1037px 的列裡，右邊空一大塊）。 */
.sm{list-style:none;cursor:pointer;display:grid;align-items:center;gap:6px 10px;
 width:100%;box-sizing:border-box;
 padding:9px 12px;
 grid-template-columns:minmax(120px,1.5fr) auto minmax(46px,.5fr)
                       minmax(62px,.6fr) minmax(62px,.6fr) minmax(84px,.8fr)}
.sm::-webkit-details-marker{display:none}
.sm:hover{background:rgba(148,163,184,.06)}
.c1{font-weight:700;font-size:14px;color:var(--ink);display:flex;
 align-items:baseline;gap:7px;min-width:0}
.nm2{font-weight:400;font-size:11px;color:var(--dim);overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.c2{display:flex;gap:5px;flex-wrap:wrap}
.c3{font-size:11px;color:var(--dim);text-align:right}
.c4,.c5,.c6{text-align:right;font-size:12.5px;
 font-variant-numeric:tabular-nums}
.c6{font-weight:600}
.row[open] .sm{border-bottom:1px solid var(--line2)}

/* 燈：亮的有底色，暗的只留輪廓——一眼掃得出哪幾檔三盞全亮 */
.lamp{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;
 padding:2px 8px 2px 6px;border-radius:999px;border:1px solid var(--line);
 color:var(--dim);white-space:nowrap}
.lamp i{width:7px;height:7px;border-radius:50%;background:var(--line);
 flex:0 0 auto}
.lamp.off{opacity:.42}
.lamp.st.on{color:#fbbf24;border-color:rgba(251,191,36,.5);
 background:rgba(251,191,36,.10)}
.lamp.st.on i{background:#fbbf24}
.lamp.all.on{color:#f87171;border-color:rgba(248,113,113,.5);
 background:rgba(248,113,113,.10)}
.lamp.all.on i{background:#f87171}
.lamp.val.on{color:#c084fc;border-color:rgba(192,132,252,.5);
 background:rgba(192,132,252,.10)}
.lamp.val.on i{background:#c084fc}

/* 展開的細節：自動排欄，寬螢幕四欄、手機兩欄，不用寫斷點 */
.det{display:grid;gap:1px;background:var(--line2);
 grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.d{background:var(--surface);padding:7px 11px;display:flex;
 justify-content:space-between;align-items:baseline;gap:8px;font-size:12px}
.d.wide{grid-column:1/-1}
.d b{font-weight:400;color:var(--dim);font-size:10.5px}
.d span{font-variant-numeric:tabular-nums}
.d.overexp{background:rgba(248,113,113,.08)}
.d.overexp span{color:var(--neg,#f87171)}
.expandbar{display:flex;gap:8px;justify-content:flex-end;margin-top:8px}
@media(max-width:620px){
 /* 手機：燈自己一行，數字擠在第二行——欄位再細就讀不了了 */
 .sm{grid-template-columns:1fr auto auto auto;gap:5px 8px}
 .c1{grid-column:1/-1}
 .c2{grid-column:1/-1}
 .c3{text-align:left}
}
"""


FILTER_JS = r'''
<script>
(function(){
  // 篩選：五組按鈕（各組互斥）＋關鍵字。作用對象是 <details class="row">。
  // ⚠️ 只切 hidden，不重排 DOM——展開狀態（open）才不會因為篩選而被重置。
  var F = {kind:"", mkt:"", who:"", pnl:"", val:""};
  var q = "";
  var rows = Array.prototype.slice.call(document.querySelectorAll("details.row"));

  function apply(){
    var shown = 0, mv = 0;
    rows.forEach(function(el){
      var d = el.dataset;
      var ok = (!F.kind || d.kind === F.kind)
            && (!F.mkt  || d.mkt  === F.mkt)
            && (!F.who  || d.who  === F.who)
            && (!F.pnl  || d.pnl  === F.pnl)
            && (!F.val  || d.val  === F.val)
            && (!q      || (d.q || "").indexOf(q) >= 0);
      el.hidden = !ok;
      if (ok){ shown++; mv += parseFloat(d.mv) || 0; }
    });
    // 某一組被篩空就換一句話，不要留一個空盒子
    document.querySelectorAll(".rows").forEach(function(w){
      var vis = w.querySelectorAll("details.row:not([hidden])").length;
      w.style.display = vis ? "" : "none";
      var em = w.parentNode.querySelector(".exempty.f");
      if (!em){
        em = document.createElement("div");
        em.className = "exempty f";
        em.textContent = "這一組沒有符合篩選條件的標的。";
        w.parentNode.insertBefore(em, w.nextSibling);
      }
      em.style.display = vis ? "none" : "";
    });
    document.getElementById("fcount").textContent =
      "顯示 " + shown + " / " + rows.length + " 檔　市值合計 NT$ "
      + Math.round(mv).toLocaleString();
  }

  document.querySelectorAll(".fb[data-f]").forEach(function(b){
    b.addEventListener("click", function(){
      var f = b.dataset.f;
      F[f] = b.dataset.v;
      document.querySelectorAll('.fb[data-f="' + f + '"]').forEach(function(o){
        o.classList.toggle("on", o === b);
      });
      apply();
    });
  });
  var box = document.getElementById("fq");
  box.addEventListener("input", function(){ q = box.value.trim().toLowerCase(); apply(); });
  document.getElementById("fclear").addEventListener("click", function(){
    F = {kind:"", mkt:"", who:"", pnl:"", val:""};
    q = ""; box.value = "";
    document.querySelectorAll(".fb[data-f]").forEach(function(o){
      o.classList.toggle("on", o.dataset.v === "");
    });
    apply();
  });

  // 全部展開／收合：只作用在**目前篩選後看得到的**那些，
  // 不然按一下會把被隱藏的 30 幾檔也展開，收回去時一頭霧水。
  var ex = document.getElementById("fexpand");
  if (ex){
    ex.addEventListener("click", function(){
      var vis = rows.filter(function(r){ return !r.hidden; });
      var anyClosed = vis.some(function(r){ return !r.open; });
      vis.forEach(function(r){ r.open = anyClosed; });
      ex.textContent = anyClosed ? "全部收合" : "全部展開";
    });
  }
  apply();
})();
</script>
'''


def render(rows, meta):
    from board_theme import BASE_CSS, esc, header

    def n(v, d=2, suf=""):
        return "—" if v is None else f"{v:,.{d}f}{suf}"

    def sgn(v, d=1, suf="%"):
        if v is None:
            return '<span class="dim">—</span>'
        c = "pos" if v >= 0 else "neg"
        return f'<span class="{c}">{v:+,.{d}f}{suf}</span>'

    # 帳戶 → 顯示標記。⚠️ 這幾個是不同的錢與不同的決策權，別混在一起看。
    #
    # 🔴 2026-09-06：這張對照表原本**寫死在程式裡**（券商分公司名 + 小孩的名字），
    # 而這支程式是版控的、repo 是公開的 → 等於把家人的券商帳戶結構推上 GitHub。
    # 產出的 HTML 一直都沒公開，但**程式碼本身也是資料**，我漏看了這一層。
    # ⭐ 「這份輸出不公開」不代表「產生它的程式可以寫死私人資訊」。
    #
    # 改成讀 gitignore 的 `account_labels.json`：
    #     {"含這段字的帳戶名": ["圖示", "顯示標籤"], ...}
    # 找不到檔案就退回顯示帳戶名本身——功能不會壞，只是標籤不好看。
    # 標籤刻意短——這一欄 37 列裡有 30 幾列都是同一個值，寫長只是佔寬度。
    WHO = {k: (tuple(v) if isinstance(v, (list, tuple)) else ("", str(v)))
           for k, v in (_load("account_labels.json", {}) or {}).items()}

    def who_tag(acct):
        for k, (ic_, lab) in WHO.items():
            if k in (acct or ""):
                return ic_, lab
        return "", acct or "—"

    def lamps(r):
        """三盞燈（Leo 2026-09-06 指定的三個條件）。回 (html, 亮了幾盞, 標籤list)。

        ⚠️ ①②不是獨立事件而是**階段**：②成立時①一定也成立（②＝①再加 RS）。
        照樣兩盞都畫出來，因為老墨的規則就是分兩段執行——
        只亮①是「賣一半」，①②都亮才是「全出」。把②畫成③的樣子會看不出階段。
        """
        st_flip = r["kind"] == "both"          # 這頁只收 RS 已跌破的兩組
        all_out = r["kind"] == "both"
        over = (r.get("over") or 0) > 0
        # 🟡 只有 RS 跌破那組：老墨規則裡它也是「全出」，但 SuperTrend 還沒翻空。
        # 不能把①點亮（那是假的），也不能說它沒事——所以②用不同的字。
        rs_only = r["kind"] == "rs"
        L = [("st", st_flip, "ST 翻空", "賣一半"),
             ("all", all_out or rs_only, "全出",
              "ST＋RS 都到" if all_out else "RS 跌破"),
             ("val", over, "超過貴價",
              f'貴 +{r["over"]:,.0f}%' if over else
              ("—" if r.get("over") is None else f'低 {r["over"]:,.0f}%'))]
        html = "".join(
            f'<span class="lamp {k} {"on" if on else "off"}" title="{esc(t)}：{esc(sub)}">'
            f'<i></i>{esc(t)}</span>' for k, on, t, sub in L)
        return html, sum(1 for _k, on, _t, _s in L if on)

    def table(rs):
        if not rs:
            return '<div class="exempty">這一組目前沒有標的。</div>'
        out = []
        for r in rs:
            lam, lit = lamps(r)
            attrs = (f' data-kind="{r["kind"]}"'
                     f' data-mkt="{"tw" if r["cur"] == "NT$" else "us"}"'
                     f' data-who="{esc(who_tag(r["acct"])[1])}"'
                     f' data-pnl="{"up" if (r["pnl"] or 0) >= 0 else "down"}"'
                     f' data-val="{"" if r.get("over") is None else ("over" if r["over"] > 0 else "under")}"'
                     f' data-mv="{r["mv"] or 0:.0f}"'
                     f' data-q="{esc((str(r["tk"]) + " " + str(r["name"])).lower())}"')
            big = " big" if (r["w"] or 0) >= 3 else ""
            # 摘要列：代號｜名稱｜誰的｜三燈｜現價｜報酬｜市值
            # 這七項是「要不要點開」的判斷依據，其餘全部收在裡面。
            head = (f'<summary class="sm">'
                    f'<span class="c1">{esc(r["tk"])}'
                    + ('<span class="dim" style="font-size:10px"> ⚠️補算</span>'
                       if r.get("filled") else "")
                    + f'<span class="nm2">{esc(r["name"])}</span></span>'
                    f'<span class="c2">{lam}</span>'
                    f'<span class="c3">{esc(who_tag(r["acct"])[1])}</span>'
                    f'<span class="c4">{n(r["px"])}</span>'
                    f'<span class="c5">{sgn(r["pnl_pct"])}</span>'
                    f'<span class="c6"><span class="cur">{r["cur"]}</span>'
                    f'{n(r["mv_n"] if r["mv_n"] is not None else r["mv"], 0)}</span>'
                    f'</summary>')

            def kv(k, v, cls=""):
                return f'<div class="d{" " + cls if cls else ""}"><b>{k}</b><span>{v}</span></div>'

            body = ['<div class="det">']
            if r.get("nopos"):
                body.append('<div class="d wide"><b>部位</b>'
                            '<span class="dim">⚠️ 報表查無部位</span></div>')
            body += [
                kv("股數", n(r["sh"], 2)),
                kv("平均成本", n(r["avg"])),
                kv("現價", n(r["px"])),
                kv("市值", f'<span class="cur">{r["cur"]}</span>'
                   + n(r["mv_n"] if r["mv_n"] is not None else r["mv"], 0)),
                kv("損益", sgn(r["pnl_n"] if r["pnl_n"] is not None else r["pnl"], 0, "")),
                kv("報酬", sgn(r["pnl_pct"])),
                kv("佔所屬帳戶", n(r["w"], 1, "%")),
                kv("貴價（洪瑞泰）",
                   n(r["exp"]) + (f' <span class="dim">'
                                  f'{"貴 +" if (r["over"] or 0) > 0 else "低 "}'
                                  f'{r["over"]:,.0f}%</span>'
                                  if r.get("over") is not None else ""),
                   "overexp" if (r.get("over") or 0) > 0 else ""),
                kv("俗價（洪瑞泰）", n(r.get("cheap"))),
                kv("SuperTrend 線",
                   n(r["st_line"]) + (f' <span class="dim">距 {r["gap"]:+.1f}%</span>'
                                      if r.get("gap") is not None else "")),
                kv("RS60", sgn(r["rs"], 2)),
                kv("歷史高點（3年）",
                   n(r["hi3y"]) + (f' <span class="dim">{esc(r["hi3y_d"])}</span>'
                                   if r.get("hi3y_d") else "")),
                kv("距高點", sgn(r["dd3y"])),
                kv("52 週高", n(r["hi52"])),
                kv("距 52 週高", sgn(r["dd52"])),
            ]
            body.append("</div>")
            out.append(f'<details class="row{big}"{attrs}>{head}'
                       + "".join(body) + "</details>")
        return '<div class="rows">' + "".join(out) + "</div>"


    both = [r for r in rows if r["kind"] == "both"]
    rs_only = [r for r in rows if r["kind"] == "rs"]
    mv_b = sum(r["mv"] or 0 for r in both)
    mv_r = sum(r["mv"] or 0 for r in rs_only)
    tot = meta["total_mv"] or 1
    n_st_only = meta.get("st_only", 0)
    n_over = sum(1 for r in rows if (r.get("over") or 0) > 0)
    n_under = sum(1 for r in rows if r.get("over") is not None and r["over"] <= 0)
    n_noval = sum(1 for r in rows if r.get("over") is None)
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

    # ── 篩選列（2026-09-06 Leo 指定）────────────────────────────────
    # ⚠️ 這頁**不上投資站**，所以刻意不套 board_theme 的 .ctrl/.seg（那是站上頁面
    # 的統一元件）。這裡自己寫一組最小的，少一層相依、也不會反過來影響站上樣式。
    owners = []
    for r in rows:
        w = who_tag(r["acct"])[1]
        if w not in owners:
            owners.append(w)
    seg = ('<div class="fbar">'
           '<div class="fg"><span class="fl">訊號</span>'
           '<button class="fb on" data-f="kind" data-v="">全部</button>'
           '<button class="fb" data-f="kind" data-v="both">🔴 兩條都成立</button>'
           '<button class="fb" data-f="kind" data-v="rs">🟡 只有 RS</button></div>'
           '<div class="fg"><span class="fl">市場</span>'
           '<button class="fb on" data-f="mkt" data-v="">全部</button>'
           '<button class="fb" data-f="mkt" data-v="us">美股</button>'
           '<button class="fb" data-f="mkt" data-v="tw">台股</button></div>'
           '<div class="fg"><span class="fl">誰的</span>'
           '<button class="fb on" data-f="who" data-v="">全部</button>'
           + "".join(f'<button class="fb" data-f="who" data-v="{esc(o)}">{esc(o)}</button>'
                     for o in owners)
           + '</div>'
           '<div class="fg"><span class="fl">損益</span>'
           '<button class="fb on" data-f="pnl" data-v="">全部</button>'
           '<button class="fb" data-f="pnl" data-v="up">獲利</button>'
           '<button class="fb" data-f="pnl" data-v="down">虧損</button></div>'
           '<div class="fg"><span class="fl">估值</span>'
           '<button class="fb on" data-f="val" data-v="">全部</button>'
           '<button class="fb" data-f="val" data-v="over">超過貴價</button>'
           '<button class="fb" data-f="val" data-v="under">未超過</button></div>'
           '<div class="fg"><input class="fq" id="fq" type="search" '
           'placeholder="代號或名稱…" autocomplete="off">'
           '<button class="fb" id="fclear">清除</button>'
           '<button class="fb" id="fexpand">全部展開</button></div>'
           '<div class="fcount" id="fcount"></div>'
           '</div>')
    B.append(seg)

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
        # 貴價涵蓋率要寫出來——**「沒有貴價」跟「沒超過貴價」是兩件事**，
        # 不寫的話那幾檔在「超過/未超過」兩個篩選裡都不出現，看起來像不存在。
        # ⚠️ 有了「ST 翻空」這盞燈，就一定要講「只有 ST 翻空」那組不在這頁——
        # 不講的話那盞燈永遠不會單獨亮，看起來像那種情況不存在。
        # ⚠️ **沒有自己把那幾檔加進來**：母體是 Leo 9/6 指定的（兩條都成立＋
        #    只有 RS 跌破），改母體是他的決定不是我的。
        f'<div class="sub">🚦 三盞燈＝老墨規則的三個條件：<b>ST 翻空</b>（賣一半）／'
        f'<b>全出</b>（ST＋RS 都到，或 RS 已跌破）／<b>超過貴價</b>。點一列展開細節。<br>'
        f'⚠️ <b>「只有 ST 翻空、RS 還沒跌破」那組（目前 {n_st_only} 檔）不在這頁</b>'
        f'——你 9/6 指定的範圍是「兩條都成立」與「只有 RS 跌破」。要加說一聲。<br>'
        f'📐 <b>貴價</b>用洪瑞泰法（美股預期 EPS、台股實績 EPS），'
        f'讀每日 07:33 算好的快取，跟站上其他頁同一個來源。'
        f'<b>{n_over} 檔已經超過貴價</b>，{n_under} 檔還沒，'
        f'<b>{n_noval} 檔沒有貴價資料</b>（財報抓不到 EPS）——'
        f'那幾檔在「超過／未超過」兩個篩選裡都不會出現。<br>'
        '⚠️ <b>表格裡每一列都是原幣</b>——美股標 US$、台股標 NT$，'
        '成本、現價、市值、損益四欄同單位，可以直接比。<br>'
        '⚠️ <b>上面四格的合計是新台幣</b>（美股用報表自己的匯率換算過）——'
        '跨帳戶跨幣別要相加，只能用同一種單位。<br>'
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

    import time
    gen = time.strftime("%Y-%m-%d %H:%M")
    B.append(f'<div class="sb"><div class="sub">'
             f'訊號資料日 <b>{esc(meta["asof"])}</b>（最後一個交易日）｜'
             f'成本與股數來自 Firstrade 報表｜高點取 price_store 3 年日線。<br>'
             f'⚠️ 名單是<b>現在的狀態</b>不是「今天剛觸發」——多數是幾週前就跌破了。<br>'
             # 這一頁每週日 08:30 覆寫。檔名不帶日期，所以「上次產出」要寫在頁內——
             # 沒有它就分不出「這週沒有新變化」跟「排程已經壞掉三週了」。
             f'🕗 本頁每週日 08:30 自動覆寫，上次產出 <b>{esc(gen)}</b>。'
             f'<b>不會出現在投資站</b>（站上家人看得到）——只存在這台電腦與 Google Drive。'
             f'</div></div>')

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>出場檢視表</title><style>" + BASE_CSS + CSS
            + '</style></head><body><div class="wrap">'
            # 🔴 2026-09-06 Leo：「上面還是有欸？」——指那排導覽按鈕。
            # 這頁**不上投資站**，nav_abs() 那些連結指向的是公開站的頁面，
            # 在這裡點了只會跳出去，而且佔掉手機上整整三行。傳空清單＝不畫導覽。
            # ⚠️ 仍然用 header()（站上元件），只是不給它 nav——版式一致但沒有連結。
            + header("lamp", "出場檢視表",
                     f"符合老墨出場條件的持股　{len(both)+len(rs_only)} 檔／"
                     f"佔部位 {(mv_b+mv_r)/tot*100:.1f}%　訊號日 {esc(meta['asof'])}",
                     [])
            + "".join(B) + "</div>" + FILTER_JS + "</body></html>")


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
