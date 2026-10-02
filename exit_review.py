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
    # 原本只讀 load_holdings()（＝主帳戶那一個），漏掉其餘帳戶——實際有好幾個
    # 帳戶。首版就是因為這樣，其中一檔（不在主帳戶裡的）部位欄印成「—」。
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
    # 每個持有人自己的部位（30 秒看懂區一人一塊用）：{持有人: {代號: {sh, mv, cb}}}
    own = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"sh": 0.0, "mv": 0.0, "cb": 0.0}))
    for r in rows_all:
        o = own[r.get("owner") or "?"][ic.norm_ticker(r.get("ticker"))]
        o["sh"] += r.get("shares") or 0
        o["mv"] += r.get("market_value") or 0
        o["cb"] += r.get("cost_basis") or 0
    own = {k: dict(v) for k, v in own.items()}
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
        # 2026-09-06（第二次）Leo：「加」——「只有 ST 翻空」那組也列進來。
        # 原本只收 both/rs 兩組，是照 9/6 上午他圈的範圍。加了「ST 翻空」這盞燈
        # 之後那組不列就變成「有一盞永遠不會單獨亮的燈」，等於做了個看不到的東西。
        if bear and rsdn:
            want.append((n, "both", r))
        elif rsdn:
            want.append((n, "rs", r))
        elif bear:
            want.append((n, "st", r))

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
                if bear or rsdn:
                    want.append((n, "both" if (bear and rsdn)
                                 else ("rs" if rsdn else "st"),
                                 {"ticker": n, "name": "", "price": None,
                                  "rs_short": None, "bull": not bear,
                                  "st_line": None, "gap_pct": None, "_filled": True}))
                filled.append((n, (bear, rsdn)))
        except Exception as e:                              # noqa: BLE001
            print(f"  [warn] 補算失敗：{str(e)[:60]}")

    # 🔴 2026-10-02 Leo 把這頁跟密報的「今日新變化」整合成一頁：兩邊「RS 跌破」定義不同——
    # 這裡原本用 rs_short<0（RS 值為負），密報／持股警示用的是「RS 跌破自身 60 日均線」
    # （＝這頁自己 warnbox 寫的規則）。實測差 3 檔（有一檔 RS 值為正、但已在自身均線下）。
    # 同一頁不能有兩個數字，分類改以 holdings_exit.overview() 為準（含今日翻面事件校正）；
    # 它沒涵蓋到的代號才保留上面的本地判斷。
    try:
        import holdings_exit as _hx
        _ov = _hx.overview()
    except Exception as e:                                   # noqa: BLE001
        print(f"  [warn] 取不到統一分類，沿用本地判斷：{str(e)[:60]}")
        _ov = None
    if _ov:
        _bk = {nk: b for b, names in _ov["buckets"].items() for nk in names}
        _km = {"both": "both", "rs_only": "rs", "st_only": "st"}
        _loc = {n: (k, r) for n, k, r in want}
        want = []
        for n in held:
            b = _bk.get(_hx._nk(n))
            if b is None:
                if n in _loc:
                    want.append((n, *_loc[n]))
                continue
            kind = _km.get(b)
            if not kind:
                continue
            r = (_loc[n][1] if n in _loc else by.get(n)) or {
                "ticker": n, "name": "", "price": None, "rs_short": None, "bull": kind == "rs",
                "st_line": None, "gap_pct": None, "_filled": True}
            want.append((n, kind, r))

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
            # 首版並排放，某一檔美股的「平均成本」（台幣）比「現價」（美元）大好幾倍——
            # **看起來像大賠**，實際是大賺。⭐ 同一列的兩個數字不同單位，比不上色的錯誤更容易誤導。
            # （2026-09-30：這裡原本寫了那一檔的代號與實際成本——公開 repo 的註解不放持股數字。）
            # 換算係數用「市值÷股數÷現價」自己反推，不引外部匯率表（自洽且不會過期）。
            "avg": ((cb / sh) / ((mv / sh) / px) if (sh and mv and px) else
                    (cb / sh) if sh else None),
            "nopos": not sh,
            "pnl": (mv - cb) if (mv and cb) else None,
            "pnl_pct": (mv / cb - 1) * 100 if cb else None,
            "w": (mv / base_mv * 100) if base_mv else None,
            # 🔴 2026-09-06 Leo：「美股可以用美金嗎」。
            # 報表的 market_value／cost_basis 都是台幣，但 Leo 看美股部位是用美元想的
            # （成本、現價都是美元，市值卻是台幣＝腦袋要一直換算）。
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
                  # 「做完之後會變怎樣」要用：每一檔的市值（台幣，跨帳戶合計）
                  # 🔴 按持有人分開——小孩的錢不跟 Leo 的加總（硬規則），30 秒區一人一塊。
                  "own": own,
                  "acct_mv": dict(acct_mv), "filled": filled}


CSS = """
/* 🔴 2026-09-07：class 名全部加 `ex` 前綴。
   今天**第二次**撞到 board_theme 的共用樣式：
     早上 `.nm`（帶 max-width:190px+ellipsis）→ 手機卡片版整列鎖成 190px；
     現在 `.row`（帶 display:flex）→ <details> 變橫向 flex，
            summary 與細節被排成左右兩欄，桌機整個版面壞掉。
   ⭐ **共用元件的 class 名不是中性的**。`.row/.rows/.big/.tk/.empty` 這種
      通用字在任何設計系統裡都會被用掉——自己的頁面一律加前綴，
      不要每次都靠踩到才發現。 */

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
/* 2026-09-10 Leo:「出場檢視表按鍵(圓框)跟其它設計不一樣，幫我改方框」——
   原本是 999px 全圓角，跟投資站其他頁篩選/標籤用的小方框(2-9px)不一致。 */
.fb{font:inherit;font-size:12px;padding:4px 10px;border-radius:6px;cursor:pointer;
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
 /* 2026-09-10：這裡原本寫 Fira Code，全站數字一律 IBM Plex Mono（見 BASE_CSS
    的 .num）——沒載入 Fira Code 字型檔，所以其實是退回瀏覽器預設 monospace，
    看起來就跟其他頁面的數字字體不一樣。Leo 一眼看出來了。 */
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
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
.exrows{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.exrow{border:1px solid var(--line);border-radius:10px;background:var(--surface);
 overflow:hidden}
.exrow.big{border-color:rgba(248,113,113,.45)}
.exrow[open]{border-color:var(--accent,#3b82f6)}
/* ⚠️ 要 width:100%+box-sizing：<summary> 設 display:grid 之後在 Chrome 上是
   縮成內容寬（實測桌機 642px 塞在 1037px 的列裡，右邊空一大塊）。 */
.exsm{list-style:none;cursor:pointer;display:grid;align-items:center;gap:6px 10px;
 width:100%;box-sizing:border-box;
 padding:9px 12px;
 grid-template-columns:minmax(120px,1.5fr) auto minmax(46px,.5fr)
                       minmax(62px,.6fr) minmax(62px,.6fr) minmax(84px,.8fr)}
.exsm::-webkit-details-marker{display:none}
.exsm:hover{background:rgba(148,163,184,.06)}
.c1{font-weight:700;font-size:14px;color:var(--ink);display:flex;
 align-items:baseline;gap:7px;min-width:0}
.nm2{font-weight:400;font-size:11px;color:var(--dim);overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.c2{display:flex;gap:5px;flex-wrap:wrap}
.c3{font-size:11px;color:var(--dim);text-align:right}
.c4,.c5,.c6{text-align:right;font-size:12.5px;
 font-variant-numeric:tabular-nums}
.c6{font-weight:600}
.exrow[open] .exsm{border-bottom:1px solid var(--line2)}

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

/* 展開的細節：**分段**（2026-09-07 Leo：「排這樣更難看懂了，幫我分段」）。
   原本是一個 15 格的大 grid 一路流下去，相關欄位被版面切斷
   （「歷史高點」在第二排結尾、「距高點/52週高」掉到第三排）。
   改成四段，每段一個左側標籤：部位／估值／出場訊號／離高點多遠。 */
.exdet{display:flex;flex-direction:column;gap:1px;background:var(--line2)}
.exgrp{display:grid;grid-template-columns:78px 1fr;background:var(--line2);gap:1px}
.exglab{background:var(--card,var(--surface));padding:8px 10px;font-size:10.5px;
 color:var(--dim);display:flex;align-items:center;letter-spacing:.05em}
/* ⚠️ auto-FILL 不是 auto-FIT：只有兩格的那段（估值／出場訊號）用 auto-fit
   會把兩格拉滿整列寬，標籤跟數字被扯到左右兩端，比不分段還難讀。
   auto-fill 保留空軌道，每格維持正常寬度。 */
.exgf{display:grid;gap:1px;background:var(--line2);
 grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
.exwarnrow{background:var(--surface);padding:8px 11px;font-size:12px;color:var(--dim)}
@media(max-width:620px){
 /* 手機：段標籤改成橫的一條，不然 78px 佔掉太多寬度 */
 .exgrp{grid-template-columns:1fr}
 .exglab{padding:5px 11px;font-size:10px}
}
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
 .exsm{grid-template-columns:1fr auto auto auto;gap:5px 8px}
 .c1{grid-column:1/-1}
 .c2{grid-column:1/-1}
 .c3{text-align:left}
}
"""


CSS30 = """
/* ── 30 秒看懂（2026-09-30 Leo：「出場檢視表可以套用另一個對話幫 mom 做的 skill 嗎」）──
   版式照 stock-holdings-dashboard skill：三個大數字 → 影響最大的幾件事 → 做完前後 → 圖。
   ⚠️ 只套**版面**：動作一律是「老墨規則說什麼」，沒有叫孔明逐檔判斷（這頁每天自動覆寫、
      而且原則是不下建議）。class 一律 x3 前綴（見上面 9/7 撞 board_theme 共用樣式的教訓）。 */
:root{--half:#F97316}
.x3sec{background:var(--surface);border:1px solid var(--line);border-radius:4px;
 padding:14px 16px;margin:12px 0}
.x3sec h2{font-size:17px;margin:0 0 8px;color:var(--ink);font-weight:700}
.x3sec h2 small{font-weight:400;color:var(--dim);font-size:12px;margin-left:6px}
.x3tag{display:inline-block;background:var(--cy-dim);color:var(--accent);
 border:1px solid var(--accent);border-radius:3px;padding:2px 10px;font-size:12.5px;margin-bottom:8px}
.x3hero{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.x3hn{background:var(--card);border:1px solid var(--line2);border-radius:3px;padding:8px 12px}
.x3hn .l{font-size:12.5px;color:var(--muted)}
.x3hn .v{font-size:23px;font-weight:700;line-height:1.25;
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.x3hn .s{font-size:11.5px;color:var(--dim);margin-top:1px}
.x3g{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.x3c{display:flex;gap:10px;background:var(--card);border:1px solid var(--line2);
 border-radius:3px;padding:8px 10px;align-items:flex-start}
.x3n{flex:none;width:30px;height:30px;border-radius:3px;background:var(--accent);color:var(--bg);
 font-weight:800;font-size:16px;display:flex;align-items:center;justify-content:center}
.x3t{font-size:16px;font-weight:700;line-height:1.35}
.x3t .x3nm{font-weight:400;color:var(--muted);font-size:12.5px;margin-left:6px}
.x3act{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:700;
 border-radius:3px;padding:1px 7px;margin-left:6px;color:var(--bg);white-space:nowrap}
.x3s{font-size:12.5px;color:var(--muted);margin-top:2px}
.x3w{font-size:12.5px;margin-top:3px;color:var(--muted)}
.x3then{margin-top:10px;font-size:13.5px;line-height:1.75;background:var(--card);
 border:1px solid var(--line2);border-left:3px solid var(--accent);border-radius:3px;padding:8px 12px}
.x3bag{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.x3ba{background:var(--card);border:1px solid var(--line2);border-radius:3px;padding:6px 10px}
.x3bal{font-size:13px;font-weight:700;margin-bottom:2px}
.x3cols{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
.x3sl{fill:var(--ink)}.x3sv{fill:var(--muted);font-family:'IBM Plex Mono',ui-monospace,monospace}
.x3svb{fill:var(--ink);font-weight:700;font-family:'IBM Plex Mono',ui-monospace,monospace}
.x3sm{fill:var(--dim)}
.x3sin{fill:var(--bg);font-weight:700;font-family:'IBM Plex Mono',ui-monospace,monospace}
.x3lgs{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;font-size:12.5px;color:var(--muted)}
.x3lgs i{display:inline-flex;width:16px;height:16px;border-radius:2px;margin-right:5px;
 vertical-align:-3px;align-items:center;justify-content:center;color:var(--bg);
 font-size:10px;font-style:normal;font-weight:700}
.x3why{margin:0;padding-left:20px}.x3why li{margin:4px 0;font-size:13.5px;line-height:1.6;color:var(--muted)}
.x3why b{color:var(--ink)}
.x3mb{display:none}
.x3own{margin:14px 0 4px}
.x3oh{font-size:16px;font-weight:700;color:#F5B841;padding:4px 2px;cursor:default}
.x3oh small{font-weight:400;color:var(--dim);font-size:12.5px;margin-left:10px}
details.x3own>summary.x3oh{cursor:pointer;border:1px solid var(--line);border-radius:4px;
 padding:9px 12px;background:var(--surface)}
@media (max-width:640px){
 .x3hero{grid-template-columns:1fr 1fr}.x3hero .x3hn:first-child{grid-column:1/3}
 .x3g,.x3cols,.x3bag{grid-template-columns:1fr}
 .x3dk{display:none}.x3mb{display:block}
 .x3t{font-size:17px}.x3s,.x3w{font-size:14px}.x3then,.x3why li{font-size:14.5px}
}
"""

CIRC = "①②③④⑤⑥⑦⑧"


def _svg_hbar(rows, width=560, bar_h=22, gap=8, label_w=92, val_w=170, fs=13):
    """水平長條：rows=[(label, value, color, right_text)]。（同 stock-holdings-dashboard 的 svg_hbar）
    ⚠️ 桌機寬度畫的 SVG 縮到手機字只剩 8–9px → 同一張圖畫兩份（width=360, fs=15），用 .x3dk/.x3mb 切換。"""
    from board_theme import esc
    maxv = max(r[1] for r in rows) or 1
    plot = width - label_w - val_w
    h = len(rows) * (bar_h + gap)
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" preserveAspectRatio="xMinYMin meet">']
    for i, (lab, v, col, txt) in enumerate(rows):
        yy = i * (bar_h + gap)
        bw = max(3, v / maxv * plot)
        out.append(f'<text x="{label_w-8}" y="{yy+bar_h*0.72}" text-anchor="end" class="x3sl" '
                   f'font-size="{fs}">{esc(lab)}</text>')
        out.append(f'<rect x="{label_w}" y="{yy}" width="{bw:.1f}" height="{bar_h}" rx="2" '
                   f'style="fill:{col}"><title>{esc(lab)}：{esc(txt)}</title></rect>')
        out.append(f'<text x="{label_w+bw+6:.1f}" y="{yy+bar_h*0.72}" class="x3sv" '
                   f'font-size="{fs-1}">{esc(txt)}</text>')
    out.append("</svg>")
    return "".join(out)


def _svg_stack(segs, width=560, h=34, fs=13):
    """一條 100% 堆疊：segs=[(label, value, color)]，片段間 2px 縫。"""
    tot = sum(v for _l, v, _c in segs) or 1
    x = 0
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    for lab, v, col in segs:
        w = v / tot * width
        out.append(f'<rect x="{x+1:.1f}" y="0" width="{max(0, w-2):.1f}" height="{h}" rx="2" '
                   f'style="fill:{col}"><title>{lab} {v/tot*100:.0f}%</title></rect>')
        if w > 44:
            out.append(f'<text x="{x+w/2:.1f}" y="{h*0.66}" text-anchor="middle" class="x3sin" '
                       f'font-size="{fs}">{v/tot*100:.0f}%</text>')
        x += w
    out.append("</svg>")
    return "".join(out)


def _svg_ba(label, b, a, fmt, maxv, width=230):
    """做完前後：兩條細長條（前＝灰、後＝青），數字在尾端。"""
    from board_theme import esc
    plot = width - 78
    maxv = maxv or 1
    wb, wa = b / maxv * (plot - 34), a / maxv * (plot - 34)
    return (f'<div class="x3ba"><div class="x3bal">{esc(label)}</div>'
            f'<svg viewBox="0 0 {width} 48" width="100%">'
            f'<text x="0" y="15" class="x3sm" font-size="13">現在</text>'
            f'<rect x="34" y="4" width="{wb:.1f}" height="14" rx="2" style="fill:var(--dim)"/>'
            f'<text x="{34+wb+5:.1f}" y="15" class="x3sv" font-size="13">{fmt(b)}</text>'
            f'<text x="0" y="40" class="x3sm" font-size="13">做完</text>'
            f'<rect x="34" y="29" width="{wa:.1f}" height="14" rx="2" style="fill:var(--accent)"/>'
            f'<text x="{34+wa+5:.1f}" y="41" class="x3svb" font-size="14">{fmt(a)}</text></svg></div>')


def brief(rows, meta):
    """最上面的「30 秒看懂」。回 html。動作只有兩種、都來自老墨規則：
    ✖ 全出（ST＋RS 都到，或 RS 已跌破）／½ 賣一半（只有 ST 翻空）。

    🔴 **一個持有人一塊**：小孩的錢不跟 Leo 的加總（硬規則）。首版把四個帳戶加成一個
    大數字、金額最大的幾件事也被小孩的台股佔滿——版面做出來一看才發現。
    市值最大的那位展開，其餘各自收合，收合列上就寫得出重點。"""
    from board_theme import esc

    own = meta.get("own") or {}
    sig = {r["tk"]: r for r in rows}
    owners = sorted(own, key=lambda o: -sum(p["mv"] for p in own[o].values()))
    out = []
    for i, o in enumerate(owners):
        pos = {k: v for k, v in own[o].items() if (v["mv"] or 0) > 0}
        tot = sum(v["mv"] for v in pos.values())
        if not tot:
            continue
        hit = []
        for n, p in pos.items():
            r = sig.get(n)
            if not r:
                continue
            fx = r.get("fx") or 1                 # 台幣／原幣（台股＝1）
            hit.append({**r, "sh": p["sh"], "mv": p["mv"], "cb": p["cb"],
                        "mv_n": p["mv"] / fx,
                        "pnl": (p["mv"] - p["cb"]) if p["cb"] else None,
                        "pnl_pct": (p["mv"] / p["cb"] - 1) * 100 if p["cb"] else None})
        body, line = _brief_one(hit, tot, pos)
        if i == 0:
            out.append(f'<div class="x3own"><div class="x3oh">{esc(o)} 的持股'
                       f'<small>{esc(line)}</small></div>{body}</div>')
        else:
            out.append(f'<details class="x3own"><summary class="x3oh">{esc(o)} 的持股'
                       f'<small>{esc(line)}</small></summary>{body}</details>')
    return "".join(out)


def _brief_one(hit, tot, pos):
    """單一持有人的 30 秒區。回 (html, 一行摘要)。hit＝這個人被規則點到的持股；
    tot＝這個人的持股總市值（台幣）；pos＝這個人全部持股 {代號: {mv,...}}。"""
    from board_theme import SIG_COLOR, esc

    SELL, HALF, HOLD = SIG_COLOR["sell"], "var(--half)", SIG_COLOR["hold"]

    def act(r):                                  # (圖示, 文字, 顏色, 賣出比例)
        return ("½", "賣一半", HALF, 0.5) if r["kind"] == "st" else ("✖", "全出", SELL, 1.0)

    def W(x):
        return f"{x/10000:,.0f} 萬" if abs(x) >= 1e5 else f"{x/10000:,.1f} 萬"

    def sg(x):
        return ("+" if x >= 0 else "−") + W(abs(x))

    why = {"both": "SuperTrend 翻空＋RS(60) 跌破",
           "rs": "RS(60) 跌破，SuperTrend 還在多方（股價沒轉弱、只是跑輸大盤）",
           "st": "SuperTrend 翻空，RS(60) 還沒跌破"}

    for r in hit:
        r["_sell"] = r["mv"] * act(r)[3]
    sell_tot = sum(r["_sell"] for r in hit)
    hit_mv = sum(r["mv"] for r in hit)
    pnl_tot = sum(r["pnl"] or 0 for r in hit)
    n_all = sum(1 for r in hit if r["kind"] != "st")
    n_half = len(hit) - n_all
    n_up = sum(1 for r in hit if (r["pnl"] or 0) >= 0)
    line = (f'規則點到 {len(hit)} 檔（占 {hit_mv/tot*100:.1f}%）・照做賣出約 NT$ {W(sell_tot)}'
            if hit else "沒有持股被規則點到")
    if not hit:
        return ('<div class="x3sec"><div class="x3then">✅ 目前沒有持股符合出場條件。</div></div>', line)

    hero = (
        '<div class="x3hero">'
        f'<div class="x3hn"><div class="l">持股市值</div><div class="v">NT$ {W(tot)}</div>'
        f'<div class="s">{len(pos)} 檔</div></div>'
        f'<div class="x3hn"><div class="l">規則點到的</div><div class="v">{len(hit)} 檔'
        f'<span style="font-size:14px;color:var(--muted)">　{hit_mv/tot*100:.1f}%</span></div>'
        f'<div class="s">✖ 全出 {n_all} 檔・½ 賣一半 {n_half} 檔</div></div>'
        f'<div class="x3hn"><div class="l">這些的帳上損益</div>'
        f'<div class="v {"pos" if pnl_tot >= 0 else "neg"}">{sg(pnl_tot)}</div>'
        f'<div class="s">賺的 {n_up} 檔・賠的 {len(hit)-n_up} 檔</div></div>'
        '</div>')

    # 影響最大的幾件事：按「照規則要賣掉的金額」排，不是按整檔市值（賣一半的只算一半）
    top = sorted(hit, key=lambda r: -r["_sell"])[:6]
    cards = []
    for i, r in enumerate(top):
        ic_, lab, col, frac = act(r)
        sh = (r["sh"] or 0) * frac
        twd = f'（約 NT$ {W(r["_sell"])}）' if r["cur"] != "NT$" else ""
        over = (f'｜<b style="color:var(--warn)">已超過貴價 +{r["over"]:,.0f}%</b>' if (r.get("over") or 0) > 0
                else (f'｜低於貴價 {abs(r["over"]):,.0f}%' if r.get("over") is not None else ""))
        pnl = ("" if r["pnl_pct"] is None else
               f'帳上 <span class="{"pos" if r["pnl_pct"] >= 0 else "neg"}">{r["pnl_pct"]:+,.0f}%</span>｜')
        cards.append(
            f'<div class="x3c"><div class="x3n">{CIRC[i]}</div><div>'
            f'<div class="x3t">{esc(r["tk"])}<span class="x3nm">{esc(r["name"])}</span>'
            f'<span class="x3act" style="background:{col}">{ic_} {lab}</span></div>'
            f'<div class="x3s">賣 {sh:,.{0 if sh == int(sh) else 2}f} 股'
            f' ≈ {r["cur"]} {r["mv_n"] * frac:,.0f}{twd}</div>'
            f'<div class="x3w">{pnl}{why[r["kind"]]}{over}</div></div></div>')
    rest = len(hit) - len(top)

    # 做完之後（三組照規則全做）
    after = {k: v["mv"] for k, v in pos.items()}
    for r in hit:
        after[r["tk"]] = after.get(r["tk"], 0) - r["_sell"]
    a_tot = max(tot - sell_tot, 1)
    top1_b = max(v["mv"] for v in pos.values()) / tot * 100
    top1_a = max(after.values()) / a_tot * 100
    cnt_b, cnt_a = len(pos), sum(1 for v in after.values() if v > 1)
    ba = "".join([
        _svg_ba("股票市值（台幣）", tot / 1e4, a_tot / 1e4, lambda v: f"{v:,.0f} 萬", tot / 1e4),
        _svg_ba("持股檔數", cnt_b, cnt_a, lambda v: f"{v:.0f} 檔", cnt_b),
        _svg_ba("最大單一持股占比", top1_b, top1_a, lambda v: f"{v:.1f}%", max(top1_b, top1_a)),
    ])

    # 圖 1：規則點到的前 10 大（顏色＝規則的動作）；圖 2：這個人的持股裡占多少
    t10 = sorted(hit, key=lambda r: -r["mv"])[:10]
    rows10 = [((r["tk"] if r["cur"] != "NT$" else (r["name"] or r["tk"])[:5]), r["mv"], act(r)[2],
               f'{W(r["mv"])}・{act(r)[0]} {act(r)[1]}') for r in t10]
    mv_all = sum(r["mv"] for r in hit if r["kind"] != "st")
    mv_half = sum(r["mv"] for r in hit if r["kind"] == "st")
    keep = max(tot - hit_mv, 0)
    segs = [("全出", mv_all, SELL), ("賣一半", mv_half, HALF), ("沒有出場訊號", keep, HOLD)]
    legend = (f'<span><i style="background:{SELL}">✖</i>全出 {mv_all/tot*100:.1f}%</span>'
              f'<span><i style="background:{HALF}">½</i>賣一半 {mv_half/tot*100:.1f}%</span>'
              f'<span><i style="background:{HOLD}">○</i>沒有出場訊號 {keep/tot*100:.1f}%</span>')

    html = (
        '<div class="x3sec"><span class="x3tag">⏱ 30 秒看懂</span>' + hero
        + f'<h2>照規則，金額最大的 {len(top)} 件事'
        + (f'<small>其餘 {rest} 檔在下面清單</small>' if rest > 0 else "") + '</h2>'
        + '<div class="x3g">' + "".join(cards) + '</div>'
        + f'<div class="x3then">💰 照規則全做：賣出約 <b>NT$ {W(sell_tot)}</b>'
        f'（持股的 <b>{sell_tot/tot*100:.1f}%</b>）；這 {len(hit)} 檔現在帳上合計 '
        f'<b class="{"pos" if pnl_tot >= 0 else "neg"}">{sg(pnl_tot)}</b>。<br>'
        '⚠️ 這裡寫的是「<b>規則說什麼</b>」，不是「該不該賣」——理由在下面黃框。</div></div>'

        '<div class="x3sec"><h2>做完之後，會變怎樣？<small>照規則全做</small></h2>'
        f'<div class="x3bag">{ba}</div></div>'

        '<div class="x3cols">'
        '<div class="x3sec"><h2>規則點到哪幾檔？<small>前 10 大（台幣市值），顏色＝規則的動作</small></h2>'
        f'<div class="x3dk">{_svg_hbar(rows10)}</div>'
        f'<div class="x3mb">{_svg_hbar(rows10, width=360, label_w=70, val_w=150, fs=15)}</div></div>'
        '<div class="x3sec"><h2>占持股多少？</h2>'
        f'<div class="x3dk">{_svg_stack(segs)}</div>'
        f'<div class="x3mb">{_svg_stack(segs, width=360, h=38, fs=15)}</div>'
        f'<div class="x3lgs">{legend}</div>'
        '<h2 style="margin-top:14px">🔔 什麼時候回頭看？</h2><ul class="x3why">'
        '<li>這份名單<b>每個工作日 08:30 重算</b>：SuperTrend 翻回多方或 RS(60) 站回均線，那一檔會自動消失。</li>'
        '<li>收盤當天新翻空／跌破的，會先推 Telegram（台股 14:05、美股 05:35），不用等這頁。</li>'
        '<li>名單是<b>現在的狀態</b>，不是「今天剛觸發」——可能幾天前就成立了。</li>'
        '</ul></div></div>')
    return html, line


FILTER_JS = r'''
<script>
(function(){
  // 篩選：五組按鈕（各組互斥）＋關鍵字。作用對象是 <details class="exrow">。
  // ⚠️ 只切 hidden，不重排 DOM——展開狀態（open）才不會因為篩選而被重置。
  var F = {kind:"", mkt:"", who:"", pnl:"", val:""};
  var q = "";
  var rows = Array.prototype.slice.call(document.querySelectorAll("details.exrow"));

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
    document.querySelectorAll(".exrows").forEach(function(w){
      var vis = w.querySelectorAll("details.exrow:not([hidden])").length;
      // 套了「訊號」篩選時，別組整段收起來（不留「這一組沒有符合」的空盒子，名單才會緊接在上面）
      var gr = w.querySelector("details.exrow");
      var otherKind = !!F.kind && !!gr && gr.dataset.kind !== F.kind;
      w.parentNode.style.display = otherKind ? "none" : "";
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
  // 頂端階段計數（.hx-go）：點一下＝套用「訊號」篩選並捲到清單，再點同一個＝取消（2026-10-02 Leo）
  function syncGo(){
    var cur = document.querySelector('.fb[data-f="kind"].on');
    var v = cur ? cur.dataset.v : "";
    document.querySelectorAll(".hx-go").forEach(function(o){
      o.classList.toggle("on", !!v && o.dataset.kind === v);
    });
  }
  document.querySelectorAll(".hx-go").forEach(function(c){
    c.addEventListener("click", function(){
      var cur = document.querySelector('.fb[data-f="kind"].on');
      var tgt = (cur && cur.dataset.v === c.dataset.kind) ? "" : c.dataset.kind;
      var btn = document.querySelector('.fb[data-f="kind"][data-v="' + tgt + '"]');
      if (btn) btn.click();
      syncGo();
      // 跳到那一組的標題（取消篩選時回到篩選列）
      var tgtEl = document.querySelector(".fbar");
      if (tgt) {
        var g = document.querySelector('details.exrow[data-kind="' + tgt + '"]');
        if (g && g.closest(".sb")) tgtEl = g.closest(".sb");
      }
      if (tgtEl) tgtEl.scrollIntoView({behavior: "smooth", block: "start"});
    });
  });
  document.querySelectorAll('.fb[data-f="kind"]').forEach(function(b){
    b.addEventListener("click", syncGo);
  });
})();
</script>
'''


def render(rows, meta):
    from board_theme import BASE_CSS, esc, header
    try:
        from holdings_exit import CSS as _hx_css
    except Exception:                      # noqa: BLE001
        _hx_css = ""

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
        k = r["kind"]                          # both / rs / st
        st_flip = k in ("both", "st")          # SuperTrend 已翻空
        all_out = k in ("both", "rs")          # 老墨規則裡「剩餘全出」那一段
        over = (r.get("over") or 0) > 0
        # 🟡 只有 RS 跌破那組：老墨規則裡它也是「全出」，但 SuperTrend 還沒翻空。
        # 不能把①點亮（那是假的），也不能說它沒事——所以②用不同的字。
        L = [("st", st_flip, "ST 翻空", "賣一半"),
             ("all", all_out, "全出",
              "ST＋RS 都到" if k == "both" else
              ("RS 跌破" if k == "rs" else "尚未")),
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
            big = " exbig" if (r["w"] or 0) >= 3 else ""
            # 摘要列：代號｜名稱｜誰的｜三燈｜現價｜報酬｜市值
            # 這七項是「要不要點開」的判斷依據，其餘全部收在裡面。
            head = (f'<summary class="exsm">'
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

            def grp(title, cells):
                """一段。⚠️ 分段的重點不是好看，是**相關的欄位要排在一起**：
                原本 15 格一路流下去，「歷史高點」在第二排結尾、「距高點／52週高」
                被切到第三排——上下文被版面切斷，數字就要重新找。"""
                cells = [c for c in cells if c]
                if not cells:
                    return ""
                return (f'<div class="exgrp"><div class="exglab">{title}</div>'
                        f'<div class="exgf">{"".join(cells)}</div></div>')

            def kv(k, v, cls=""):
                return f'<div class="d{" " + cls if cls else ""}"><b>{k}</b><span>{v}</span></div>'

            body = ['<div class="exdet">']
            if r.get("nopos"):
                body.append('<div class="exwarnrow">⚠️ 報表查無部位</div>')
            body.append(grp("部位", [
                kv("股數", n(r["sh"], 2)),
                kv("平均成本", n(r["avg"])),
                kv("現價", n(r["px"])),
                kv("市值", f'<span class="cur">{r["cur"]}</span>'
                   + n(r["mv_n"] if r["mv_n"] is not None else r["mv"], 0)),
                kv("損益", sgn(r["pnl_n"] if r["pnl_n"] is not None else r["pnl"], 0, "")),
                kv("報酬", sgn(r["pnl_pct"])),
                kv("佔所屬帳戶", n(r["w"], 1, "%")),
            ]))
            body.append(grp("估值", [
                kv("貴價（洪瑞泰）",
                   n(r["exp"]) + (f' <span class="dim">'
                                  f'{"貴 +" if (r["over"] or 0) > 0 else "低 "}'
                                  f'{r["over"]:,.0f}%</span>'
                                  if r.get("over") is not None else ""),
                   "overexp" if (r.get("over") or 0) > 0 else ""),
                kv("俗價（洪瑞泰）", n(r.get("cheap"))),
            ]))
            body.append(grp("出場訊號", [
                kv("SuperTrend 線",
                   n(r["st_line"]) + (f' <span class="dim">距 {r["gap"]:+.1f}%</span>'
                                      if r.get("gap") is not None else "")),
                kv("RS60", sgn(r["rs"], 2)),
            ]))
            body.append(grp("離高點多遠", [
                kv("3 年高", n(r["hi3y"]) + (f' <span class="dim">{esc(r["hi3y_d"])}</span>'
                                            if r.get("hi3y_d") else "")),
                kv("距 3 年高", sgn(r["dd3y"])),
                kv("52 週高", n(r["hi52"])),
                kv("距 52 週高", sgn(r["dd52"])),
            ]))
            body.append("</div>")
            out.append(f'<details class="exrow{big}"{attrs}>{head}'
                       + "".join(body) + "</details>")
        return '<div class="exrows">' + "".join(out) + "</div>"


    both = [r for r in rows if r["kind"] == "both"]
    rs_only = [r for r in rows if r["kind"] == "rs"]
    st_only = [r for r in rows if r["kind"] == "st"]
    mv_b = sum(r["mv"] or 0 for r in both)
    mv_r = sum(r["mv"] or 0 for r in rs_only)
    mv_s = sum(r["mv"] or 0 for r in st_only)
    pnl_s = sum(r["pnl"] or 0 for r in st_only)
    tot = meta["total_mv"] or 1
    n_st_only = meta.get("st_only", 0)
    n_over = sum(1 for r in rows if (r.get("over") or 0) > 0)
    n_under = sum(1 for r in rows if r.get("over") is not None and r["over"] <= 0)
    n_noval = sum(1 for r in rows if r.get("over") is None)
    pnl_b = sum(r["pnl"] or 0 for r in both)
    pnl_r = sum(r["pnl"] or 0 for r in rs_only)

    B = []
    try:                                  # 頂端：今日新變化（2026-10-02 與持股出場訊號整合）
        import holdings_exit as _hx
        _blk = _hx.block()
    except Exception as _e:                # noqa: BLE001
        print(f"[exit_review] 今日新變化區塊略過：{_e}")
        _blk = ""
    B.append(_blk)
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
           '<button class="fb" data-f="kind" data-v="rs">🟡 只有 RS</button>'
           '<button class="fb" data-f="kind" data-v="st">🟠 只有 ST</button></div>'
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
        f'<div class="c"><div class="k">🟠 只有 ST 翻空</div><div class="v">{len(st_only)} 檔</div>'
        f'<div class="s">市值 {mv_s:,.0f}（全部持股的 {mv_s/tot*100:.1f}%）</div></div>',
        f'<div class="c"><div class="k">三組合計佔部位</div>'
        f'<div class="v">{(mv_b+mv_r+mv_s)/tot*100:.1f}%</div>'
        f'<div class="s">NT$ {mv_b+mv_r+mv_s:,.0f}</div></div>',
        f'<div class="c"><div class="k">三組未實現損益</div>'
        f'<div class="v {"pos" if pnl_b+pnl_r+pnl_s >= 0 else "neg"}">'
        f'{pnl_b+pnl_r+pnl_s:+,.0f}</div>'
        f'<div class="s">🔴 {pnl_b:+,.0f}　🟡 {pnl_r:+,.0f}　🟠 {pnl_s:+,.0f}</div></div>',
        '</div>',
        # 貴價涵蓋率要寫出來——**「沒有貴價」跟「沒超過貴價」是兩件事**，
        # 不寫的話那幾檔在「超過/未超過」兩個篩選裡都不出現，看起來像不存在。
        # 2026-09-06（第二次）Leo：「加」——「只有 ST 翻空」那組已經列進來了，
        # 所以三盞燈的組合現在都看得到（只亮①＝賣一半、①②都亮＝全出）。
        f'<div class="sub">🚦 三盞燈＝老墨規則的三個條件：<b>ST 翻空</b>（賣一半）／'
        f'<b>全出</b>（ST＋RS 都到，或 RS 已跌破）／<b>超過貴價</b>。點一列展開細節。<br>'
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

    B.append('<div class="sb"><h2>🟠 只有 SuperTrend 翻空</h2>'
             '<div class="sub">SuperTrend 翻空、但 RS(60) <b>還沒</b>跌破——'
             '老墨規則裡這一段是<b>「賣一半」</b>，不是全出。<br>'
             '⚠️ 這組跟上面兩組性質不同：<b>它還沒到「全出」那一條</b>，'
             '列在這裡是為了讓三盞燈的階段看得完整（只亮第一盞就是這組）。'
             '</div>' + table(st_only) + "</div>")

    B.append(brief(rows, meta))          # 2026-10-02 Leo：持股那塊移到清單後面
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
             f'⚠️ 名單是<b>現在的狀態</b>不是「今天剛觸發」——可能是幾天前就跌破了。<br>'
             # 2026-09-10 改每日（Leo：「每週檢視是不是不夠，能不能做每日」）。
             # 檔名不帶日期，所以「上次產出」要寫在頁內——沒有它就分不出
             # 「今天沒有新變化」跟「排程已經壞掉好幾天了」。
             f'🕗 本頁每個工作日 08:30 自動覆寫，上次產出 <b>{esc(gen)}</b>。'
             # 2026-09-30 Leo：「出場檢查不用只存在本機了，反正登入要密碼」→ 資產中控台
             # 的 /exit-review 開放經通道連（仍要帳密）。投資站照舊不放。
             f'<b>不會出現在投資站</b>（站上家人看得到）——從資產中控台（要登入）或 Google Drive 開。'
             f'</div></div>')

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>出場檢視表</title><style>" + BASE_CSS + CSS + CSS30 + _hx_css
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
    nr = sum(1 for r in rows if r["kind"] == "rs")
    ns = sum(1 for r in rows if r["kind"] == "st")
    print(f"✅ 已存 {out}（{len(html):,} bytes）")
    print(f"   🔴 兩條都成立 {nb} 檔｜🟡 只有 RS 跌破 {nr} 檔｜🟠 只有 ST 翻空 {ns} 檔"
          f"｜訊號日 {meta['asof']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
