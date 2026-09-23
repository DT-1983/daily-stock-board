# -*- coding: utf-8 -*-
"""燈號戰情室：左選單／中圖表／右軍師 三欄頁（2026-09-07，Leo 指定）。

Leo 看了老墨的交易室之後：「我想升級一下燈號頁……A 選單做在左邊、B 細部燈號
分析圖在中間、C 軍師對話在右邊（有需要再打開）」。

## 為什麼掛在本機而不是投資站

軍師要跑 `war_room.ask()` → `llm_board` → **本機的 claude CLI**（Max plan 訂閱額度，
不是付費 API、不產生帳單）。投資站是 GitHub Pages 靜態託管，跑不了任何伺服器程式。

Leo 問「軍師不能線上嗎？」——**可以，就是查股票頁現在這條路**：
`stock.talentxtrend.com` 已經接到本機 8030（Cloudflare tunnel），手機在外面照樣開。
唯一條件是這台電腦要開著，跟 `/lookup` 一樣。
真正做不到的是「放在靜態託管上」，那要嘛付 API 錢（違反零成本原則），
要嘛把憑證放上第三方平台（8/27 Zeabur 被入侵那次的教訓）。

## 跟公開站燈號頁的分工

| | 公開站 `docs/combo.html` | 這頁 `/room` |
|---|---|---|
| 什麼時候有 | 隨時（靜態） | 本機開著時 |
| 圖表 | 312 檔**全部預先產好**（檔案 13MB） | 選到哪檔才算哪檔 |
| 軍師 | 沒有 | 有 |

**兩邊讀同一份 `state/combo_result.json`**，不會有兩套數字。

## 路由

    GET  /room                 三欄殼 + 左欄清單（資料內嵌）
    GET  /room/detail?ticker=  中欄：關鍵數字 + 技術圖（現算，數秒）
    POST /room/ask             右欄：{role, question, ticker} → 軍師回覆

門檻沿用 `lookup_page.gate()`（LOOKUP_TOKEN，?key= 種 90 天 cookie，沒過回 404）。
"""
import io
import json
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

Q = chr(34)
RESULT = "state/combo_result.json"


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def rows():
    """左欄清單。**直接讀燈號掃描的結果**，不自己重算任何一個數字。

    ⚠️ 漲跌幅 combo_result 裡沒有，從 price_store 的快取補（`refresh=False`
    ＝純吃快取不連網）。抓不到就留空——**不要用別的數字硬湊一個漲跌**。
    """
    d = _load(RESULT, {}) or {}
    rs = [r for r in (d.get("rows") or []) if r.get("ticker")]

    chg = {}
    try:
        import price_store
        import tw_symbol
        sym = {}
        for r in rs:
            t = str(r["ticker"])
            sym[t] = tw_symbol.resolve(t) if t[:1].isdigit() else t
        cl = price_store.get_closes(sorted(set(sym.values())), period="3y",
                                    refresh=False)
        for t, s in sym.items():
            ser = cl.get(s)
            if ser is None:
                continue
            ser = ser.dropna()
            if len(ser) >= 2 and float(ser.iloc[-2]):
                chg[t] = (float(ser.iloc[-1]) / float(ser.iloc[-2]) - 1) * 100
    except Exception as e:                                  # noqa: BLE001
        print(f"  [room] 漲跌算不出來（那一欄會留空）：{str(e)[:70]}")

    import ai_theme

    out = []
    for r in rs:
        t = str(r["ticker"])
        px, tgt = r.get("price"), r.get("target")
        out.append({
            "tk": t,
            "nm": (r.get("name") or "")[:12],
            "px": px,
            "chg": chg.get(t),
            "lit": r.get("lit") or 0,
            "rr": r.get("rr"),
            "tgt": tgt,
            "gap": ((tgt / px - 1) * 100) if (px and tgt) else None,
            "bull": bool(r.get("bull")),
            "quad": (r.get("quad") or {}).get("60") if isinstance(r.get("quad"), dict)
                    else r.get("quad"),
            "sec": r.get("sector_zh") or r.get("sector") or "",
            "mkt": "tw" if t[:1].isdigit() else "us",
            "src": "／".join(r.get("src") or []),
            "theme": ai_theme.classify(t),
        })
    return out, (rs[0].get("asof") if rs else "—")


# ── 左欄 ──────────────────────────────────────────────────────────────
def left_html(items, asof):
    from board_theme import esc
    lis = []
    for r in items:
        lamps = "".join('<i class="lp on"></i>' for _ in range(r["lit"])) + \
                "".join('<i class="lp"></i>' for _ in range(4 - r["lit"]))
        chg = ("" if r["chg"] is None else
               f'<span class="{"up" if r["chg"] >= 0 else "dn"}">'
               f'{r["chg"]:+.2f}%</span>')
        # 2026-09-07 Leo：「左邊各股可以顯示目標價」。原本只有「距目標 +15.8%」，
        # 看得出差多少但看不到目標價本身——要判斷「這個目標價合不合理」得再點進去。
        gap = ("" if r["tgt"] is None else
               f'目標 <b class="tg">{r["tgt"]:,.2f}</b>'
               + ("" if r["gap"] is None else
                  f' <span class="{"up" if r["gap"] >= 0 else "dn"}">'
                  f'{r["gap"]:+.1f}%</span>'))
        lis.append(
            f'<li class="it" data-tk="{esc(r["tk"])}" data-mkt="{r["mkt"]}"'
            f' data-lit="{r["lit"]}" data-theme="{esc(r["theme"])}"'
            f' data-q="{esc((r["tk"] + " " + r["nm"] + " " + r["sec"]).lower())}"'
            f' data-sort-lit="{r["lit"]}"'
            f' data-sort-gap="{r["gap"] if r["gap"] is not None else -999}"'
            f' data-sort-rr="{r["rr"] if r["rr"] is not None else -999}"'
            f' data-sort-chg="{r["chg"] if r["chg"] is not None else -999}">'
            f'<div class="l1"><b>{esc(r["tk"])}</b> <span class="nm">{esc(r["nm"])}</span>'
            f'<span class="px">{"" if r["px"] is None else f"{r['px']:,.2f}"} {chg}</span></div>'
            f'<div class="l2"><span>{gap}</span><span class="lamps">{lamps}</span></div>'
            "</li>")
    return (
        '<aside class="pane left"><div class="grip" id="grip"></div>'
        f'<div class="phead">報價組合<span class="dim">{len(items)} 檔 · {esc(asof)}</span>''<button class="lbtn" id="lhide" title="收合左欄（把空間讓給圖表）">«</button></div>'
        '<div class="ctrlbar">'
        '<input class="q" id="q" type="search" placeholder="搜代號／名稱／產業" autocomplete="off">'
        '<div class="chips">'
        '<span class="cl">排序</span>'
        '<button class="ch on" data-s="lit">燈數 ▼</button>'
        '<button class="ch" data-s="gap">距目標 ▼</button>'
        '<button class="ch" data-s="rr">風報比 ▼</button>'
        '<button class="ch" data-s="chg">漲跌 ▼</button>'
        '</div>'
        '<div class="chips">'
        '<span class="cl">市場</span>'
        '<button class="ch" data-m="">全部</button>'
        '<button class="ch" data-m="us">美股</button>'
        '<button class="ch on" data-m="tw">台股</button>'
        '</div>'
        '<div class="chips">'
        '<span class="cl">只看</span>'
        '<button class="ch" data-l="">全部燈數</button>'
        '<button class="ch on" data-l="4">4燈</button>'
        '<button class="ch" data-l="3">≥3燈</button>'
        '</div>'
        + _theme_chips_html(items) +
        '</div>'
        '<ul class="list" id="list">' + "".join(lis) + "</ul></aside>")


def _theme_badge(ticker):
    """個股卡片用的迷你 AI 主題籤（2026-09-23，Leo：「做在呈現supertrend的地方」——
    掛在 SuperTrend 卡片的副標行，跟老墨個股畫面上那顆「代理AI基建」小籤同位置。
    查不到鏈對照就不顯示（不亂標「內需與循環」，同 lookup_page._theme_tag() 的原則）。"""
    import ai_theme
    chain = ai_theme._chain_ticker_map().get(ai_theme._tw_bare(ticker))
    if not chain:
        return ""
    theme = ai_theme.CHAIN_THEME.get(chain, "內需與循環")
    col = {"代理AI基建": "#3987e5", "記憶體外溢": "#a855f7",
           "實體AI": "#2fbf71", "內需與循環": "#eda100"}.get(theme, "#888")
    icon = ai_theme.THEME_ICON.get(theme, "")
    return (f'<br><span style="display:inline-block;margin-top:3px;padding:1px 7px;'
            f'border-radius:5px;border-left:2px solid {col};background:var(--panel,#080E1A);'
            f'color:var(--ink)">{icon} {theme}</span>')


def _theme_chips_html(items):
    """AI 主題篩選籤（2026-09-23，對標老墨戰情室頂端那排；Leo 指出實際在用的是
    這個三欄戰情室、不是公開站進出燈號頁，所以左欄清單也要有這排，不能只加在
    `combo_html.py` 產的表格頁——那個表格頁在這裡只是「列表」分頁裡的其中一個
    次要視圖，Leo 平常盯的是這個永遠可見的左欄）。"""
    from board_theme import esc
    import ai_theme
    from collections import Counter
    cnt = Counter(r["theme"] for r in items)
    chips = ['<button class="ch on" data-t="">全部 <b>' + str(len(items)) + "</b></button>"]
    for t in ai_theme.THEME_ORDER:
        n = cnt.get(t, 0)
        chips.append(f'<button class="ch" data-t="{esc(t)}" title="{esc(t)}">'
                     f'{ai_theme.THEME_ICON.get(t,"")} <b>{n}</b></button>')
    return '<div class="chips"><span class="cl">主題</span>' + "".join(chips) + "</div>"


def _combo_css():
    """進出燈號頁的樣式（table.cb / .lamp / .qb / 篩選籤）＋查股框樣式。

    🔴 這是「格式跑掉」的真正原因：我重用了 combo_html 的 HTML，
    **但沒有重用它的 CSS**，表格因此是裸的（欄位黏在一起、燈號那欄空白）。
    重用元件要連樣式一起帶——只搬 markup 是搬了一半。
    ⚠️ 已比對 ROOM_CSS 的選擇器：只有 `.on` 撞名，而戰情室一律寫成
    `.lp.on / .ch.on / .rb.on / .mb.on`（兩個 class，權重較高），不受影響。
    """
    try:
        import combo_html as ch
        from board_theme import LOOKUP_CSS
        # .lk-intro 系列不在 LOOKUP_CSS 裡（那是 lookup_page.py 自己內嵌的樣式，
        # 兩邊各自 <style> 互不共用）——複製同一份規則，數字跟排版才會一致。
        intro_css = """
.lk-intro{font-size:12.5px;line-height:1.85;color:var(--muted);margin:6px 0 10px;
          padding:9px 12px;background:var(--surface);border:1px solid var(--line2,#0E1B2B);
          border-left:2px solid var(--accent);border-radius:0 6px 6px 0}
.lk-intro-wait{color:var(--dim)}
.lk-gen{font-size:11px;color:var(--dim);opacity:.75}
.lkdot{display:inline-block;width:4px;height:4px;margin-left:5px;border-radius:50%;
       background:var(--accent);vertical-align:middle;animation:lkpulse 1.1s ease-in-out infinite}
@keyframes lkpulse{0%,100%{opacity:.25}50%{opacity:1}}
@media(prefers-reduced-motion:reduce){.lkdot{animation:none;opacity:.7}}
"""
        return ch.CSS + LOOKUP_CSS + intro_css
    except Exception:                                   # noqa: BLE001
        return ""


def table_html():
    """列表模式＝**整個「進出燈號」頁**（統計卡＋查股框＋篩選籤＋三區塊＋說明）。

    ⚠️ 不自己拼版面，直接叫 combo_html.body_html()。之前我只挑 _table() 來用，
    統計卡、篩選籤、說明全都沒有——同一份資料長出兩種頁面。
    圖表展開鈕不會出現（那要 attach_charts 先跑過，240 檔現算太慢），
    這頁改成**點整列跳到個股模式**，那邊的圖比展開鈕那張更完整。
    """
    import combo_html as ch
    d = _load(RESULT, {}) or {}
    if not (d.get("rows") or []):
        return '<div class="empty">找不到 combo_result.json。</div>'
    return ('<div class="tnote">點任一列 → 切到<b>個股模式</b>並選中那一檔'
            '（技術圖、燈號細節、軍師都在那邊）。</div>'
            # in_room=True：不要在戰情室裡再放一顆「前往戰情室」。
            + ch.body_html(d, in_room=True))


# ── 中欄 ──────────────────────────────────────────────────────────────
def live_lamps(tk):
    """**現在**這一檔幾盞燈（抓到最新交易日重算）。算不出來回 None。

    為什麼要有（2026-09-08 Leo：「上面字卡是4燈，但下面圖表是3燈? 到底是幾燈?」）：
      上面的卡是掃描快取（每天 07:45 跑，用的是**前一個收盤**），
      下面的圖是現抓的到最新交易日 —— 兩者本來就差一天。
      2313 華通 9/7 收 240、RS 3.33%（4燈）；9/8 收 231、RS 掉到 +0.22%（3燈）。
      頁面上本來有一行免責聲明解釋這件事，但 Leo 讀了還是被搞混
      → ⭐ **要解釋才看得懂的東西，就是還沒做好。把答案直接算出來擺上去。**

    🔴 **直接呼叫 combo_scan.scan_one，不自己重寫一套燈號邏輯。**
       燈號定義是凍結的（Leo：「燈號等老墨吧」），這裡只是換一份比較新的資料
       去跑同一套規則。自己寫第二套遲早會跟掃描漂移。
    """
    try:
        import combo_scan as cs
        import price_store
        import tw_symbol
        sym = (tw_symbol.resolve(tk) if str(tk)[:1].isdigit()
               else str(tk).replace(".", "-"))
        is_tw = cs._is_tw(tk)
        # 🔴 一定要 force=True。price_store 的 STALE_HOURS=12，而每天 07:45 的掃描
        #    會把快取標成「新鮮」→ 到 19:45 前都不重抓，拿到的是**前一交易日**收盤。
        #    不加 force 的話這裡算出來的「今日現算」會跟快取一模一樣（2313 都是 9/7 的 240），
        #    ⭐ 那就變成「多一行字宣稱是今天的，其實是昨天的」——比不做還糟。
        #    price_store.get_ohlc 的註解早就寫過這件事：「即時重算如果只重算指標
        #    不重抓價格就是騙人的」。我第一版還是漏了。
        bench = price_store.get_closes(["^TWII" if is_tw else "^GSPC"],
                                       period="3y", force=True)
        b = bench.get("^TWII" if is_tw else "^GSPC")
        ohlc = price_store.get_ohlc([sym], period="3y", force=True)
        df = ohlc.get(sym)
        if df is None or df.empty or b is None:
            return None
        return cs.scan_one(tk, sym, df, b.dropna().tolist())
    except Exception:                                       # noqa: BLE001
        return None            # 算不出來就不顯示，不要讓整頁掛掉


def _intro(r):
    """個股一句話簡介（2026-09-16 Leo：「進出燈號加上這家在做什麼，像查的功能一樣」）。

    不重寫一套——直接借用 `lookup_page._intro()` 同一份邏輯跟同一份快取
    （`state/company_intro.json`），戰情室跟查股頁講的必須是同一段話，
    不能各寫各的、兩邊敘述不一樣。行為完全比照：
      · 快取有 → 立刻顯示
      · 快取沒有 → 先讓卡片出來，前端輪詢 `/lookup/intro`（discord_bot.py
        已經有這支端點，兩邊共用同一道 gate，不用另外開路由）補進來
    """
    from board_theme import esc
    tk = str(r.get("tk") or "")
    if not tk:
        return ""
    txt = ""
    try:
        import company_intro as ci
        hit = (ci._load() or {}).get(tk.upper())
        if hit and hit.get("text"):
            txt = hit["text"]
    except Exception:                                       # noqa: BLE001
        pass
    if txt:
        return f'<div class="lk-intro">{esc(txt)}</div>'
    sec = esc(str(r.get("sec") or ""))
    import lookup_page
    return (f'<div class="lk-intro lk-intro-wait" id="lkintro" '
            f'data-tk="{esc(tk)}">{sec}{"　" if sec else ""}'
            f'<span class="lk-gen">簡介產生中<i class="lkdot"></i></span></div>'
            + lookup_page.INTRO_JS)


def _tgt_card(r, num, lv=None):
    """投顧目標價卡（2026-09-20，Leo：「戰情室還是沒有」→ 隔天再問「燈號判斷
    改一起重算呢」，兩個反饋一起處理）。

    lookup_page.py 的 _summary() 9/19已經改成「多家投顧時顯示中位數＋異議」
    （對標老墨畫面），但戰情室這裡是完全獨立的一份卡片HTML，沒有共用那段
    邏輯，改了那邊這裡不會跟著動。這裡直接呼叫 lookup_page._advisor_consensus()
    同一份函式，兩邊算出來的答案才不會不一樣。

    `lv`：現抓重算的結果（lamp_lookup.lookup()），detail_html() 改成一律
    即時算之後，沒有多家投顧報告時的備用目標價（yfinance共識）要用這份
    現抓的 target/price，不能再用 r 裡那份可能過期的快取數字。
    """
    from board_theme import esc
    try:
        import lookup_page
        adv = lookup_page._advisor_consensus(r["tk"])
    except Exception:                                       # noqa: BLE001
        adv = None
    px = (lv or {}).get("price") or r.get("px")
    if adv:
        median, n, dissent = adv
        gap = ((median / px - 1) * 100) if (px and median) else None
        sub = f"中位數‧{n}家" + (f"　距現價{gap:+.1f}%" if gap is not None else "")
        if dissent:
            sub += f"<br>{dissent}"
        return (f'<div class="dc"><div class="k">投顧目標價</div>'
                f'<div class="v">{num(median)}</div><div class="s">{sub}</div></div>')
    tgt = (lv.get("target") if lv else None)
    if tgt is None:
        tgt, gap = r.get("tgt"), r.get("gap")
    else:
        gap = ((tgt / px - 1) * 100) if (px and tgt) else None
    return (f'<div class="dc"><div class="k">分析師共識目標價</div>'
            f'<div class="v">{num(tgt)}</div>'
            f'<div class="s">{"" if gap is None else f"距現價 {gap:+.1f}%"}</div></div>')


def _row_from_live(lv):
    """即時查詢的結果 → 跟 rows() 同形狀的一列。給「不在掃描母體」的股票用。"""
    t = str(lv.get("ticker") or "")
    px, tgt = lv.get("price"), lv.get("target")
    chg = None
    try:
        import price_store
        import tw_symbol
        s = tw_symbol.resolve(t) if t[:1].isdigit() else t.replace(".", "-")
        ser = price_store.get_closes([s], period="3y", refresh=False).get(s)
        if ser is not None:
            ser = ser.dropna()
            if len(ser) >= 2 and float(ser.iloc[-2]):
                chg = (float(ser.iloc[-1]) / float(ser.iloc[-2]) - 1) * 100
    except Exception:                                       # noqa: BLE001
        pass
    q = lv.get("quad")
    return {
        "tk": t, "nm": (lv.get("name") or "")[:12], "px": px, "chg": chg,
        "lit": lv.get("lit") or 0, "rr": lv.get("rr"), "tgt": tgt,
        "gap": ((tgt / px - 1) * 100) if (px and tgt) else None,
        "bull": bool(lv.get("bull")),
        "quad": q.get("60") if isinstance(q, dict) else q,
        "sec": lv.get("sector_zh") or lv.get("sector") or "",
        "mkt": "tw" if t[:1].isdigit() else "us",
        "src": "即時查詢（不在掃描母體）",
    }


def _bars_note(tk):
    """算不出燈號時，說明原因：上市太短（K 棒不夠）還是抓不到資料。"""
    try:
        import combo_scan as CS
        import price_store
        import tw_symbol
        sym = tw_symbol.resolve(tk) if tk[:1].isdigit() else tk.replace(".", "-")
        o = price_store.get_ohlc([sym], period="3y").get(sym)
        n = 0 if o is None else len(o)
        need = CS.RS_LONG + 20
        if 0 < n < need:
            return (f"這檔只有 {n} 個交易日的資料（上市不久），四燈用到 RS 一年期，"
                    f"至少要 {need} 個交易日（約一年多）才算得出來，目前算不出燈號。")
        if n == 0:
            return "抓不到這檔的價格資料。"
    except Exception:                                       # noqa: BLE001
        pass
    return ""


def _resolve_outside(query, exact=False):
    """輸入不在掃描母體 → (即時結果 lv, None) 或 (None, 要顯示的 html)。

    2026-09-20 Leo：「輸入個股的地方如果沒有在清單裡，則即時重算」。
    做法跟查股頁一致（lookup_page.resolve：代號直接查；公司名先解析並**顯示解析結果**，
    多個候選讓人點，不安靜換一檔）。⚠️ 純代號形狀 resolve() 回空＝直接用它當代號。
    """
    from board_theme import esc
    import lamp_lookup
    import lookup_page
    q = str(query or "").strip()
    if not q:
        return None, '<div class="empty">請輸入代號或名稱。</div>'
    # 順序跟 lookup_page.render 一致：先當代號查，查不到才當公司名解析
    # （反過來會把 KO 這種合法代號當成模糊名稱丟出一堆候選）。
    tk, note = q, ""
    try:
        lv = lamp_lookup.lookup(tk, live=True)
    except Exception as e:                                  # noqa: BLE001
        return None, f'<div class="warn">{esc(tk)} 即時計算失敗：{esc(str(e)[:120])}</div>'
    if lv is None and not exact:
        cands = lookup_page.resolve(q)
        if len(cands) > 1:
            btns = "".join(
                f'<button class="rpick" data-rpick="{esc(c)}">{esc(c)}　{esc(n)}</button>'
                for c, n in cands[:8])
            return None, ('<div class="empty">「' + esc(q) + '」有多個可能，選一個：</div>'
                          '<div class="rpicks">' + btns + '</div>')
        if len(cands) == 1:
            tk = cands[0][0]
            note = (f'<div class="dim" style="padding:2px 0 8px">'
                    f'🔁 「{esc(q)}」→ {esc(tk)}　{esc(cands[0][1])}</div>')
            try:
                lv = lamp_lookup.lookup(tk, live=True)
            except Exception as e:                          # noqa: BLE001
                return None, f'<div class="warn">{esc(tk)} 即時計算失敗：{esc(str(e)[:120])}</div>'
    if not lv:
        note = _bars_note(tk) or "可能是代號打錯，或暫時抓不到資料。"
        return None, f'<div class="empty">查無燈號：{esc(q)}。{esc(note)}</div>'
    lv["_note"] = note
    return lv, None


def detail_html(ticker, exact=False):
    """中欄：關鍵數字 + 技術圖。**圖是現算的**（抓 2 年資料算指標，數秒）。

    ⚠️ 圖畫不出來不要讓整區掛掉——上面那排數字本身就有價值（同 lookup_page 的作法）。
    不在掃描母體的股票（2026-09-20）：不再回「不在母體裡」，改即時重算，
    版面跟母體內的完全一樣，只在標題標明「即時查詢」。
    """
    from board_theme import esc
    items, _asof = rows()
    r = next((x for x in items if x["tk"].upper() == str(ticker).upper()), None)
    pre_lv, pre_note = None, ""
    if not r:
        pre_lv, err = _resolve_outside(ticker, exact)
        if err:
            return err
        pre_note = pre_lv.get("_note", "")
        r = _row_from_live(pre_lv)
        hit = next((x for x in items if x["tk"].upper() == r["tk"].upper()), None)
        if hit:                                   # 名稱解析後發現其實在母體裡
            r, pre_lv = hit, None

    d = _load(RESULT, {}) or {}
    raw = next((x for x in (d.get("rows") or [])
                if str(x.get("ticker")).upper() == r["tk"].upper()), {})

    # 2026-09-20 Leo：「燈號判斷改一起重算呢？」——原本卡片用今天07:00掃描
    # 快取的數字，圖是現抓的，兩者偶爾對不上（掃描那天剛好某些股票yfinance
    # 抓價失敗、靜默退回舊快取時，落差可以到兩三天，見同一輪對話查MSFT/
    # 聯發科那次）。改成卡片也一律用現抓的重算（跟下面的技術圖同一份資料、
    # 同一套 lamp_lookup.lookup() 邏輯），不再有「快取版」這個分支——也就
    # 不再需要「今日現算」對照行、也不再需要「⚠️兩者會不一樣」的警告，
    # 因為畫面上永遠只有一個數字。查不到才退回舊的cached r/raw，不要讓
    # 整頁掛掉（跟lookup_page.render()的容錯同一個精神）。
    import lamp_lookup
    lv = pre_lv
    if lv is None:
        try:
            lv = lamp_lookup.lookup(r["tk"], live=True)
        except Exception:                                   # noqa: BLE001
            pass
    live_ok = bool(lv)
    _row_asof = (lv.get("asof") if live_ok else None) or raw.get("asof") or _asof

    def num(v, n=2, suf=""):
        return "—" if v is None else f"{v:,.{n}f}{suf}"

    QL = {"leading": "🟢 領先", "improving": "🔵 改善",
          "weakening": "🟡 轉弱", "lagging": "🔴 落後"}
    # 跟四燈同一種「亮/滅」語彙。半亮＝改善（還沒到領先但在往上走）。
    QDOT = {"leading": '<i class="lp on"></i>亮　',
            "improving": '<i class="lp half"></i>半亮　',
            "weakening": '<i class="lp"></i>滅　',
            "lagging": '<i class="lp"></i>滅　'}
    lamps = (lv.get("lamps") if live_ok else raw.get("lamps")) or {}
    lamp_rows = "".join(
        f'<div class="lrow"><i class="lp {"on" if v else ""}"></i>{esc(k)}</div>'
        for k, v in lamps.items())
    lit = lv.get("lit") if live_ok else r["lit"]
    bull = lv.get("bull") if live_ok else r["bull"]
    px = lv.get("price") if live_ok else r["px"]
    st = ("🟢 空方" if not bull else "🔴 多方")
    stl = lv.get("st_line") if live_ok else raw.get("st_line")
    stsub = ("" if stl is None else
             (f"停損參考線 {stl:,.2f}" if bull else f"站上 {stl:,.2f} 才翻多"))
    rr_v = lv.get("rr") if live_ok else r["rr"]
    rs_v = lv.get("rs_short") if live_ok else raw.get("rs_short")
    # lamp_lookup.lookup() 回的 quad 是 {"20":.., "60":.., "120":..} 巢狀字典（跟
    # attach_sector() 原始輸出一樣）；rows() 那份快取已經在自己的迴圈裡拆成單一
    # 60日字串了——兩邊資料形狀不一樣，這裡統一拆成同一種扁平值再往下用。
    if live_ok:
        _q = lv.get("quad") or {}
        quad = _q.get("60") if isinstance(_q, dict) else _q
    else:
        quad = r["quad"]

    head = (
        f'<div class="dhead"><span class="tk">{esc(r["tk"])}</span>'
        f'<span class="nm">{esc(r["nm"])}</span>'
        f'<span class="px">{num(px)}</span>'
        + ("" if r["chg"] is None else
           f'<span class="{"up" if r["chg"] >= 0 else "dn"}">{r["chg"]:+.2f}%</span>')
        # 🔴 2026-09-08 Leo 問「9/8 沒對齊」時查到：原本這裡用 rows() 回的全頁 _asof，
        #    而那是**清單第一列**的資料日。但同一份掃描檔本來就有兩個資料日——
        #    台股 9/7、美股 9/4（美股 9/7 是勞動節休市，兩個都對）。
        #    結果：點美股個股時標成 9/7，實際資料是 9/4，**標錯一天**。
        # ⭐ 日期要跟著「這一檔自己的資料」走，不能用別檔的日期代表它。
        + f'<span class="dim">{esc(r["sec"])}　資料 {esc(_row_asof)}'
        + ("" if live_ok else "（現抓失敗，退回今天掃描快取）")
        + f'</span></div>')

    intro = _intro(r)

    cards = "".join([
        f'<div class="dc"><div class="k">燈數</div><div class="v">{lit} / 4'
        f'<span class="asof">{esc(_row_asof)}</span></div>'
        f'<div class="s">{lamp_rows}</div></div>',
        f'<div class="dc"><div class="k">SuperTrend</div><div class="v">{st}</div>'
        f'<div class="s">{esc(stsub)}{_theme_badge(r["tk"])}</div></div>',
        _tgt_card(r, num, lv if live_ok else None),
        f'<div class="dc"><div class="k">風報比</div><div class="v">{num(rr_v)}</div>'
        f'<div class="s">{"⭐ 打點成立" if (lit >= 3 and (rr_v or 0) >= 1) else ""}</div></div>',
        f'<div class="dc"><div class="k">RS60</div>'
        f'<div class="v">{num(rs_v, 2, "%")}</div>'
        f'<div class="s">{"高於自身 60 日均線" if (rs_v or 0) > 0 else "低於自身 60 日均線"}</div></div>',
        # H（Leo：「可以加上 RRG 的訊號嗎? 跟燈號一樣（在最上面的字卡）」）
        # 象限本來就有，但只是一行文字。改成跟四燈同一種「亮/滅」語彙：
        # 領先＝亮，改善＝半亮（在往上走），轉弱/落後＝滅。
        # ⚠️ 這**不是新指標**，就是同一份 RRG 象限換個畫法——不要讓人以為多了一個訊號。
        f'<div class="dc"><div class="k">RRG 輪動</div>'
        f'<div class="v">{QL.get(quad, "—")}</div>'
        f'<div class="s">{QDOT.get(quad, "")}{esc(r["src"])}</div></div>',
    ])

    tech = ""
    try:
        import technical_indicators as ti
        import tw_symbol
        sym = (tw_symbol.resolve(r["tk"]) if r["tk"][:1].isdigit()
               else r["tk"].replace(".", "-"))
        # F：把分析師共識目標價傳給圖，主圖才畫得出那條黃色目標價線
        #    （technical_indicators 自己不知道目標價，那是 combo_result 的欄位）
        tech = ti.build_html(sym, expanded=True, target=r.get("tgt")) or ""
    except Exception as e:                                  # noqa: BLE001
        tech = (f'<div class="warn">技術圖產生失敗（上面的數字仍然有效）：'
                f'{esc(str(e)[:140])}</div>')
    tech = _with_chip_tab(r["tk"], tech)
    # data-resolved：前端靠它把「目前看著的標的」更新成解析後的代號（軍師欄的「這一檔」要對得上）
    marker = f'<span data-resolved="{esc(r["tk"])}" hidden></span>'
    return marker + pre_note + head + intro + '<div class="dcards">' + cards + "</div>" + tech


def _with_chip_tab(tk, tech):
    """技術面下方加「技術分析／籌碼面」切換（2026-09-22 Leo：「個股的籌碼面…可以做在燈號頁裡?」）。

    籌碼圖本來就有（chip_scan.chart_html，進出燈號舊表格的展開列用過），戰情室個股頁沒接。
    只有台股且歷史檔查得到資料才加分頁——美股/查無資料就原樣回技術面，不放永遠空的分頁。
    籌碼圖預設隱藏，要**第一次顯示時才畫**（display:none 建圖會量到 0 寬），
    且每次載入都把 chip_drawn 旗標清掉：同一檔重開時 canvas 是新的，旗標若殘留會不畫而空白。
    """
    if not tk[:1].isdigit() or not tech:
        return tech
    code = tk.split(".")[0]
    uid = "rm_" + "".join(c if c.isalnum() else "_" for c in code)
    try:
        import chip_scan
        chip = chip_scan.chart_html(code, uid=uid)
    except Exception:                                       # noqa: BLE001
        chip = ""
    if not chip:
        return tech
    Q = chr(34)
    return (
        f'<div class="tvtabs" id="{uid}_box"><div class="seg" role="group" aria-label="切換視角">'
        '<button data-tv="tech" aria-pressed="true">技術分析</button>'
        '<button data-tv="chip" aria-pressed="false">籌碼面</button></div></div>'
        f'<div id="{uid}_tech">{tech}</div>'
        f'<div id="{uid}_chip" style="display:none">{chip}</div>'
        '<script>(function(){'
        f'window.chip_drawn_{uid}=false;'
        f'var box=document.getElementById({Q}{uid}_box{Q}),'
        f'tech=document.getElementById({Q}{uid}_tech{Q}),'
        f'chip=document.getElementById({Q}{uid}_chip{Q});'
        'box.querySelectorAll("button[data-tv]").forEach(function(b){'
        'b.addEventListener("click",function(){'
        'box.querySelectorAll("button[data-tv]").forEach(function(x){'
        'x.setAttribute("aria-pressed",x===b?"true":"false");});'
        'var c=b.dataset.tv==="chip";'
        'tech.style.display=c?"none":"";chip.style.display=c?"":"none";'
        f'if(c&&window.chip_draw_{uid}){{window.chip_draw_{uid}();}}'
        '});});})();</script>')


# ── 右欄：軍師 ────────────────────────────────────────────────────────
ROLES = [("軍議", "四位依序"), ("龐統", "找材料"), ("孔明", "下判斷"),
         ("仲達", "看風險"), ("陳壽", "回頭看")]


def right_html():
    """軍師欄。**預設收合**（Leo：「幫我做有需要再打開」）。

    ⚠️ 每問一次要 40-60 秒（本機 claude 跑一輪），所以：
      · 送出後要有明確的「跑很久是正常的」提示，不然會以為當掉
      · 軍議是四位依序跑，一位答完先顯示一位，不要等全部
    ⚠️ 這裡**不重寫軍師邏輯**，直接呼叫 war_room.ask()——Discord 的 /仲達 跟這頁
       講出來的話必須是同一套，兩份實作遲早會分岔。
    """
    from board_theme import esc
    # 2026-09-21 Leo：「只留孔明做窗口，後面還是可以跑其它的」——孔明是唯一常駐的窗口（預設選中），
    # 其他四位（軍議／龐統／仲達／陳壽）收進「更多」，要用隨時展開。孔明的材料已附上龐統那份新聞。
    names = [k for k, _ in ROLES]
    others = [k for k in names if k != "孔明"]
    btns = ('<button class="rb on" data-r="孔明">孔明</button>'
            '<button class="rmore" id="rmore" title="展開其他軍師">更多▾</button>'
            + "".join(f'<button class="rb more" data-r="{esc(k)}">{esc(k)}</button>' for k in others))
    return (
        '<aside class="pane right" id="right" hidden>'
        '<div class="phead">軍師<span class="dim" id="rtk">未選標的</span>'
        '<span class="dim" id="rstate"></span>'
        '<button class="x" id="rclose">✕</button></div>'
        # 範圍：這一檔 / 全部持股。⚠️ 兩個範圍的對話是**分開記**的，
        # 不然「全部持股的風險」會接到「某一檔的風險」那條線上。
        # 2026-09-21 Leo：「軍師這欄太擠了，把軍議那一排跟這一檔排成一排」——
        # 範圍鈕與五位軍師合成同一排（角色副標「四位依序／找材料…」拿掉，那是佔高度的主因）；
        # 說明字 scnote 移到下一行，沒內容時不佔位。
        '<div class="rrow"><div class="scope"><button class="sb on" id="sc-one">這一檔</button>'
        '<button class="sb" id="sc-all" title="全部持股">全部</button></div>'
        f'<div class="roles">{btns}</div></div>'
        '<div class="scn" id="scnote"></div>'
        # 全本的範例問題（學 阿福 的提示）。要給**具體問句**，
        # 使用者才知道這裡問得到什麼；不是寫「可以問全部」然後讓他自己想。
        '<div class="quick" id="quick" hidden>'
        '<button class="qk">所有個股有什麼重要的事？條列給我</button>'
        '<button class="qk">現在整體最大的風險是什麼</button>'
        '<button class="qk">最近的判斷準不準</button></div>'
        '<div class="msgs" id="msgs">'
        '<div class="hint">選一檔股票（或在上方輸入代號），直接問孔明。<br>'
        '其他軍師（軍議／龐統／仲達／陳壽）在「更多」裡。<br>'
        '走本機 claude（Max plan 訂閱額度，<b>不另外計費</b>），'
        '一位大約 40-60 秒，軍議四位約 3-4 分鐘。</div></div>'
        # 提示要給**具體的問題**（學老墨的 阿福）。原本寫「想問什麼？」等於沒說，
        # 使用者要自己想；給三個範例才知道這裡問得到什麼。
        '<div class="ask"><textarea id="qbox" rows="2" '
        'placeholder="投顧怎麼說？現在幾燈？距目標多少？　(Ctrl+Enter 送出)"></textarea>'
        '<button class="send" id="send">送出</button>'
        '<button class="send alt" id="restart" title="這一檔跟這位軍師重新開一條對話'
        '（不接續之前談過的）">重開</button></div>'
        '</aside>')


ROOM_CSS = """
:root{--gap:10px}
body{margin:0}
/* 標題排（2026-09-10 Leo：「標題跟其它分頁一樣」，見 title_html()）。
   🔴 這裡原本自己又定義了一份 .roomtitle .eye / .roomtitle h1（10px/letter-
   spacing .12em、16.5px），結果跟 BASE_CSS 本來就有的 .eye/h1（10px/.22em、
   19px）不一樣大——Leo 比對「進出燈號」發現字級不一致。BASE_CSS 早就有
   一份了，這裡的 markup 本來就是用同樣的 class name（.eye/h1），根本不用
   重寫，重寫還寫錯尺寸，是自己重複發明了一份還發明壞了。全部刪掉，
   讓它自然套用跟其他頁完全相同的規則，不用另外維護一份。
   .roomtitle 只留「排版容器」本身的樣式（背景/邊框/間距），這是 BASE_CSS
   的 header{} 沒有涵蓋到的（這裡用 <div> 不是 <header>，100vh 版型要更
   緊湊，不能照搬整個 header 含 padding-bottom:14px 那麼寬鬆）。 */
.roomtitle{padding:7px 12px 6px;background:var(--panel,#080E1A);
 border-top:2px solid var(--cy,#22D3EE);
 border-bottom:1px solid var(--hud,#16304A)}
.roomtitle .titlerow{display:flex;align-items:center;gap:8px;margin-top:3px}
/* 導覽列（2026-09-07 Leo：「最上面可以加一個其它各頁的快捷嗎? 跟其它投資頁一樣」）。
   2026-09-10：原本標題（🚦燈號戰情室 + 本機・即時標籤）跟連結、控制項
   全擠在這一排裡，Leo 說太擠——標題搬去 title_html() 自己一排，
   這裡現在**只有**連結跟控制項，兩排各自呼吸空間比較夠。 */
.roomnav{display:flex;align-items:center;gap:6px;height:38px;padding:0 10px;
 border-bottom:1px solid var(--hud,#16304A);background:var(--panel,#080E1A);
 white-space:nowrap;overflow:hidden}
.rtag{font-size:9px;letter-spacing:.12em;color:var(--void,#04070E);
 background:var(--cy,#22D3EE);padding:2px 5px;border-radius:2px;
 flex:0 0 auto;font-weight:700}
/* 連結區自己捲；控制項在外面，永遠看得到。 */
.navls{display:flex;align-items:center;gap:6px;flex:1 1 auto;min-width:0;
 overflow-x:auto;scrollbar-width:none}
.navls::-webkit-scrollbar{display:none}
.roomnav .nl{padding:4px 9px;min-height:0;font-size:11.5px;flex:0 0 auto;
 border-radius:0;background:transparent}
.roomnav .nl svg{width:13px;height:13px}
.roomnav .nl.alt{font-size:10.5px;color:var(--dim);border-style:dashed;
 margin-left:-3px}
/* ⚠️ 高度要扣掉標題排+導覽列兩排的實際高度，不然版型會比視窗高，
   底下多一條捲軸——2026-09-10 兩排化之後這個數字變了，改動時要
   實際拿瀏覽器量過再填，不要用算的（這頁的版位數學已經因為沒量測
   壞過好幾次，見上面幾則舊註解）。 */
/* --lw＝左欄寬度，由拖曳把手改（存 localStorage）。
   🔴 原本這裡寫死 320px，所以 JS 設的 --lw 沒有任何人在讀——拖了不會動。 */
:root{--lw:320px;--hdrh:98px}   /* 標題排59.7px + 導覽列38px，瀏覽器實測量出來的，不是算的 */
.room{display:grid;grid-template-columns:var(--lw) minmax(0,1fr) 0;gap:var(--gap);
 height:calc(100vh - var(--hdrh));padding:var(--gap);box-sizing:border-box;background:var(--bg)}
/* 收合：左欄整個不佔位。⚠️ 用 grid-template-columns 收掉而不是 display:none——
   中欄要拿到多出來的寬度，圖表才會跟著變寬。 */
.room.lhide{grid-template-columns:0 minmax(0,1fr) 0}
/* 🔴 2026-09-08 Leo：「縮小整個不見了」。
   原本用 `display:none` 收左欄 —— 那會把它**整個移出格線排列**，
   於是中欄遞補到第一欄（寬度 0），實測中欄只剩 2px，整頁看起來是空的。
   ⭐ **grid 子項目 display:none 不只是隱藏，是重新排列**。
   改用 visibility:hidden：位置留著，欄寬照 grid-template-columns 給的 0。 */
.room.lhide .pane.left{visibility:hidden;overflow:hidden;border:0;padding:0;
 min-width:0}
.room.lhide.chat{grid-template-columns:0 minmax(0,1fr) 380px}
.room.chat{grid-template-columns:var(--lw) minmax(0,1fr) 380px}
.pane{background:var(--panel,#080E1A);border:1px solid var(--hud,#16304A);border-radius:2px;
 overflow:auto;min-height:0}
.pane.left{position:relative}
/* 🔴 原本只有 `right:-3px`：沒有 position、沒有寬高、沒有 cursor，
   那條把手在畫面上不存在也抓不到——所以「可以拉動」這件事從來沒有生效過。 */
.grip{position:absolute;top:0;right:-4px;width:8px;height:100%;z-index:5;
 cursor:col-resize;touch-action:none}
.grip::after{content:"";position:absolute;top:0;left:3px;width:2px;height:100%;
 background:transparent;transition:background .15s}
.grip:hover::after,.grip.on::after{background:var(--cy,#22D3EE)}
/* 收合／展開鍵 */
.lbtn{background:none;border:1px solid var(--hud,#16304A);color:var(--dim);
 cursor:pointer;font:inherit;font-size:11px;padding:2px 7px;margin-left:6px;
 line-height:1.4}
.lbtn:hover{border-color:var(--cy,#22D3EE);color:var(--cy,#22D3EE)}
.lshow{display:none;flex:0 0 auto}
.room.chat .right{display:flex;flex-direction:column}
.phead{position:sticky;top:0;z-index:2;background:var(--panel,#080E1A);
 padding:10px 12px;border-bottom:1px solid var(--hud,#16304A);font-weight:700;font-size:13px;
 letter-spacing:.04em;
 display:flex;align-items:center;gap:8px}
.phead .dim{margin-left:auto;font-weight:400;font-size:11px;color:var(--dim)}
.phead .x{margin-left:6px;background:none;border:0;color:var(--dim);cursor:pointer;
 font-size:14px}
/* 🔴 2026-09-07 Leo：「選燈號不會跑／選風報比也不會跑」。
   實測不是邏輯壞掉（4燈→98 檔、風報比排序正確），是**看不出來**：
     · 篩選列會跟著清單一起捲走（捲到 600px 時它在 -498px，根本點不到）
     · 排序後不捲回頂 → 重排發生在畫面外，看起來像沒反應
   ⭐ 「功能沒壞但使用者說壞了」＝**回饋不足**，要修的是看得見的那一半。 */
/* 2026-09-10 修正：這裡原本被我改成 top:var(--hdrh)，是我自己搞混的坑——
   這個 38px 從來就跟頁首(--hdrh，題排+導覽列)無關，是 .phead(上面那個
   「報價組合」小標題列，sticky top:0)自己的高度，ctrlbar 要貼在它下面，
   兩個 38px 只是數字剛好一樣。改成頁首高度後，ctrlbar 在左欄自己的捲動
   容器裡往下貼了 98px，第一筆股票資料就會冒到篩選列上面——Leo 回報
   「篩選做壞了，固定不住，會跑出其它股票」就是這個。改回獨立的字面值，
   不要再共用 --hdrh。 */
.ctrlbar{position:sticky;top:38px;z-index:2;background:var(--panel,#080E1A);
 border-bottom:1px solid var(--hud,#16304A);padding-bottom:6px}
/* 2026-09-10 Leo:「做4排就好，可以改小一點」——四排（搜尋/排序/市場/只看）
   數量不變，只是把每排的內距/字級收窄一點，省一點高度給下面的清單。 */
.q{width:calc(100% - 24px);margin:7px 12px 4px;padding:5px 10px;font:inherit;
 font-size:12px;border-radius:0;border:1px solid var(--hud,#16304A);
 background:transparent;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:4px;padding:0 12px 5px;align-items:center}
.cl{font-size:10px;color:var(--dim);margin-right:2px}
.ch{font:inherit;font-size:11px;padding:2px 8px;border-radius:0;cursor:pointer;
 border:1px solid var(--hud,#16304A);background:transparent;color:var(--dim);
 letter-spacing:.03em}
.ch.on{background:var(--cy-dim,rgba(34,211,238,.10));border-color:var(--cy,#22D3EE);
 color:var(--cy,#22D3EE);font-weight:600}
.list{list-style:none;margin:0;padding:0 6px 10px}
.it{padding:8px 10px;border-radius:0;cursor:pointer;border:1px solid transparent}
.it:hover{background:rgba(34,211,238,.06)}
.it.sel{border-color:var(--cy,#22D3EE);background:var(--cy-dim,rgba(34,211,238,.10))}
.l1{display:flex;align-items:baseline;gap:6px;font-size:13px}
/* Leo 2026-09-07：「學一下老墨中文字比較大，不是代號」——名稱才是認得出
   是哪一檔的東西，代號是拿來查的。所以名稱吃粗體大字、代號縮小當附註。
   ⚠️ 美股沒有中文名時，代號自己當主角（HTML 那邊判斷），不要留一個空的大字。 */
.l1 b{color:var(--dim);font-weight:400;font-size:11px;order:2}
.l1 .nm{color:var(--ink);font-size:14.5px;font-weight:700;order:1;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:58%}
.l1 .px{margin-left:auto;order:3;font-variant-numeric:tabular-nums;font-size:12.5px;
 display:flex;gap:6px;white-space:nowrap}
.l2 .tg{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.l2{display:flex;align-items:center;gap:8px;margin-top:3px;font-size:10.5px;
 color:var(--dim)}
.l2 .lamps{margin-left:auto;display:flex;gap:3px}
.lp{width:7px;height:7px;border-radius:50%;background:var(--line);display:inline-block}
.lp.on{background:#fbbf24}
.lp.half{background:#fbbf24;opacity:.45}
.up{color:var(--up,#4ade80)}.dn{color:var(--down,#f87171)}
.dhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
 padding:12px 14px;border-bottom:1px solid var(--line)}
.dhead .tk{font-size:20px;font-weight:800;color:var(--ink)}
.dhead .nm{color:var(--dim);font-size:13px}
.dhead .px{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums}
.dhead .dim{margin-left:auto;font-size:11px;color:var(--dim)}
/* G（2026-09-07 Leo：「上面字卡幫我做成一排就好」）
   原本 auto-fit minmax(180px) 會折成兩排，把圖擠下去。改成單排橫向捲，
   欄位再多也只佔一排；窄螢幕靠自己捲，不吃圖的高度。 */
.dcards{display:flex;gap:1px;background:var(--hud,#16304A);margin-bottom:10px;
 overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.dcards::-webkit-scrollbar{display:none}
.dc{flex:1 0 150px}
.dc{background:var(--surface);padding:9px 12px;min-width:0}
.dc .k{font-size:9px;color:var(--dim);letter-spacing:.14em;text-transform:uppercase;
 font-family:'IBM Plex Mono',ui-monospace,monospace}
.dc .v{font-size:16px;font-weight:600;margin-top:2px;
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.dc .s{font-size:10.5px;color:var(--muted,#94a3b8);margin-top:3px;line-height:1.7}
.lrow{display:flex;align-items:center;gap:5px}
/* 「今日現算」：快取燈數底下再擺一行現算的。只有兩者資料日不同才會出現。 */
.dc .v .asof{font-size:9px;color:var(--dim);letter-spacing:.06em;margin-left:6px;
             font-weight:400;white-space:nowrap}
.livelit{margin-top:5px;padding-top:5px;border-top:1px dashed var(--line2,#0E1B2B);
         display:flex;flex-wrap:wrap;align-items:baseline;gap:6px}
.livelit b{font-size:16px;font-weight:600}
.livelit b.dn{color:var(--warn,#FFB627)}
.livelit b.up{color:var(--accent,#22D3EE)}
.livelit .tag{font-size:9px;letter-spacing:.14em;color:var(--void,#04070E);
              background:var(--accent,#22D3EE);padding:1px 5px;border-radius:2px}
.livelit .offs{flex:1 0 100%;font-size:10px;color:var(--warn,#FFB627);margin-top:2px}
.empty,.warn{padding:22px 16px;color:var(--dim);font-size:13px}
.msearch{display:flex;gap:8px;padding:10px 12px;border-bottom:1px solid var(--line);
 position:sticky;top:0;z-index:5;background:var(--surface,#080E1A)}
.msearch input{flex:1;min-width:0;padding:9px 11px;background:var(--bg,#04070E);border:1px solid var(--line);
 color:var(--ink,#DCE7F5);font:inherit;font-size:16px}
.msearch button{padding:0 16px;border:1px solid var(--cy,#22D3EE);background:var(--cy-dim,transparent);
 color:var(--cy,#22D3EE);font:inherit;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap}
.rpicks{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 16px}
.rpick{padding:8px 12px;border:1px solid var(--line);background:var(--surface,transparent);
 color:inherit;font:inherit;font-size:13px;cursor:pointer}
.rpick:hover{border-color:var(--cy,#22D3EE)}
.datewarn{padding:6px 14px;font-size:11px;color:var(--dim);
 border-bottom:1px solid var(--line)}
.datewarn b{color:#FCD34D}
.roles{display:flex;flex-wrap:wrap;gap:4px;padding:0}
.roles:not(.open) .rb.more{display:none}
.rmore{font:inherit;font-size:11px;padding:4px 6px;border-radius:0;cursor:pointer;white-space:nowrap;
 line-height:1.35;border:1px dashed var(--hud,#16304A);background:transparent;color:var(--dim)}
.rmore:hover{border-color:var(--cy,#22D3EE);color:var(--cy,#22D3EE)}
.rb{font:inherit;font-size:11.5px;padding:4px 6px;border-radius:0;cursor:pointer;
 border:1px solid var(--hud,#16304A);background:transparent;color:var(--dim);
 white-space:nowrap;line-height:1.35}
/* 範圍鈕＋五位軍師同一排（窄到放不下才換行） */
.rrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;padding:9px 12px;
 border-bottom:1px solid var(--line)}
.rb.on{background:var(--cy-dim,rgba(34,211,238,.10));border-color:var(--cy,#22D3EE);
 color:var(--cy,#22D3EE)}
.msgs{flex:1;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px}
.hint{font-size:11.5px;color:var(--dim);line-height:1.8}
.msg{border:1px solid var(--hud,#16304A);border-radius:2px;padding:9px 11px;font-size:12px;
 line-height:1.75;white-space:pre-wrap;word-break:break-word}
.msg.me{background:var(--cy-dim,rgba(34,211,238,.10));border-color:rgba(34,211,238,.35)}
.msg .who{font-weight:700;font-size:11px;color:var(--lamp,#FFB627);letter-spacing:.04em;display:block;margin-bottom:3px}
.msg.err{border-color:rgba(248,113,113,.5);color:var(--down,#f87171)}
.ask{border-top:1px solid var(--line);padding:9px 12px;display:flex;gap:7px}
.ask textarea{flex:1;font:inherit;font-size:12px;padding:7px 9px;border-radius:0;
 border:1px solid var(--hud,#16304A);background:transparent;color:var(--ink);resize:vertical}
.send{font:inherit;font-size:12px;padding:0 14px;border-radius:0;cursor:pointer;
 border:1px solid var(--cy,#22D3EE);background:var(--cy-dim,rgba(34,211,238,.10));
 color:var(--cy,#22D3EE);font-weight:600;letter-spacing:.06em}
.send[disabled]{opacity:.5;cursor:default}
/* 模式切換（2026-09-07 Leo：「整合在同一張，一個指令轉換」）。
   列表模式＝整頁一張表（掃描用，手機/平板在外面看的那種）
   個股模式＝左清單＋中圖＋右軍師（鑽進去用）
   ⚠️ 兩個模式共用同一份 combo_result，表格是重用 combo_html 的產生器，
      不是另外寫一套——不然遲早兩邊數字不一樣。 */
.tablepane{grid-column:1/-1;padding:0 14px 16px}
.room.list .left,.room.list #mid{display:none}
.room.list{grid-template-columns:minmax(0,1fr)}
.room.list.chat{grid-template-columns:minmax(0,1fr) 380px}
.room:not(.list) .tablepane{display:none}
.tnote{padding:10px 2px 12px;font-size:11.5px;color:var(--dim)}
.tnote b{color:var(--ink)}
.tsec{margin-bottom:20px}
.tsec h3{font-size:14px;margin:0 0 8px;color:var(--lamp,#FFB627);display:flex;
 align-items:baseline;gap:10px}
.tsec h3 small{font-weight:400;font-size:11px;color:var(--dim)}
.tablepane table.cb tr[data-tid]{cursor:pointer}
.tablepane table.cb tr[data-tid]:hover td{background:rgba(34,211,238,.09)}
/* 導覽列裡的控制項（2026-09-08 從 position:fixed 搬進來）。 */
.modebar{display:inline-flex;flex:0 0 auto;border:1px solid var(--hud,#16304A);
 overflow:hidden}
.mb{font:inherit;font-size:11.5px;padding:3px 12px;border:0;cursor:pointer;
 background:transparent;color:var(--dim);font-weight:600;letter-spacing:.05em}
.mb.on{background:var(--cy-dim,rgba(34,211,238,.10));color:var(--cy,#22D3EE)}
@media(max-width:900px){.tablepane{padding:0 8px 14px}}
/* 範圍切換（2026-09-07）：這一檔 / 全部持股 */
.scope{display:flex;gap:4px;align-items:center;padding:0}
.sb{font:inherit;font-size:11.5px;line-height:1.35;padding:4px 7px;border-radius:0;cursor:pointer;white-space:nowrap;
 border:1px solid var(--hud,#16304A);background:transparent;color:var(--dim);
 letter-spacing:.03em}
.sb.on{background:var(--cy-dim,rgba(34,211,238,.10));border-color:var(--cy,#22D3EE);
 color:var(--cy,#22D3EE);font-weight:600}
.scn{font-size:10.5px;color:var(--dim);padding:5px 12px 0;text-align:left}
.scn:empty{display:none}
.rb[disabled]{opacity:.35;cursor:not-allowed}
.quick{display:flex;flex-wrap:wrap;gap:5px;padding:8px 12px 0}
.qk{font:inherit;font-size:11px;padding:3px 9px;border-radius:0;cursor:pointer;
 border:1px dashed var(--hud,#16304A);background:transparent;color:var(--muted)}
.qk:hover{border-style:solid;border-color:var(--cy,#22D3EE);color:var(--cy,#22D3EE)}
/* 進度籤（2026-09-07，學老墨的 阿福「正在讀新聞」）。
   ⭐ 重點不是字一個一個浮出來，是**知道它在忙什麼**——等 50 秒跟當掉
   在畫面上長得一模一樣。我們的進度是照實回報的：材料在呼叫 AI 之前就用
   Python 組好了，哪幾塊載了我們明確知道，不是編出來的假進度條。 */
.stages{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:5px}
.stg{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10px;
 letter-spacing:.03em;padding:2px 7px;border:1px solid var(--hud,#16304A);
 color:var(--dim);white-space:nowrap}
.stg.now{border-color:var(--cy,#22D3EE);color:var(--cy,#22D3EE)}
.msg.live::after{content:"▊";color:var(--cy,#22D3EE);animation:blink 1s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
@media(prefers-reduced-motion:reduce){.msg.live::after{animation:none}}
.send.alt{background:transparent;color:var(--dim);border-color:var(--hud,#16304A);
 font-weight:500;padding:0 10px}
/* 之前談過（2026-09-07 Leo：「可以會翻回之前的討論」）。
   刻意做得比新訊息淡一階——它是背景，不是這一輪的回答。 */
.hist{border-bottom:1px dashed var(--line);margin-bottom:8px;padding-bottom:8px}
.histh{font-size:11px;color:var(--dim);padding:4px 2px 8px;letter-spacing:.04em}
.hist .msg{opacity:.72}
.hist .msg .who{font-size:10.5px}
.chatbtn{font:inherit;font-size:11.5px;padding:3px 11px;cursor:pointer;
 font-weight:700;letter-spacing:.04em;flex:0 0 auto;margin-left:6px;
 border:1px solid var(--cy,#22D3EE);background:var(--panel,#080E1A);
 color:var(--cy,#22D3EE)}
@media(max-width:900px){
 /* 手機：三欄疊成一欄，靠上面的分頁鈕切換——並排在 375px 上誰都看不清楚 */
 .room,.room.chat{grid-template-columns:1fr;height:auto}
 /* 手機的導覽列可橫向捲，不折行——折成兩三排會把圖擠到看不見 */
 .roomnav{position:sticky;top:0;z-index:8}
 .pane{max-height:none}
 .room .pane.left{max-height:46vh}
 .room:not(.chat) .right{display:none}
 /* 🔴 2026-09-07 Leo：「手機沒辦法展開軍師」。
    軍師欄其實有開（鈕變成「收起軍師」），但疊成一欄之後它是**第三列**——
    排在整份技術圖下面，要捲過所有圖表才看得到，等於沒開。
    ⭐ 「有渲染」不等於「看得到」；在手機上這兩件事差一整個螢幕的距離。
    手機改成**蓋上來的浮層**：本來就是「問一下就關掉」的用法，不是並排參考。 */
 .room.chat .right{position:fixed;inset:0;z-index:40;max-height:none;
  border-radius:0;border:0;display:flex;flex-direction:column}
 .room.chat .msgs{flex:1;min-height:0}
 /* 浮層打開時把兩顆浮動鈕收掉：它們會壓在輸入框和送出鈕上面。
    關閉走軍師欄自己的 ✕（右上角），不缺出口。 */
 /* ⚠️ 不要用 :has()——舊一點的 WebView 沒有，而且它靜默失效（選擇器整條被丟掉）。
    改成開軍師時在 body 掛一個 class，JS 一行的事，哪個瀏覽器都吃。 */
 /* 軍師浮層蓋住導覽列是對的——關閉走浮層自己的 ✕ */
}

/* 數字一律等寬對齊（HUD）：欄位不會因為字寬不同而跳動。 */
.l1 .px,.l2,.dhead .px{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
"""

ROOM_JS = r"""
<script>
(function(){
  // I（Leo：「預設選台股、四燈」）。⚠️ 初值要跟上面 class="ch on" 的那兩顆一致，
  // 兩邊分開寫就是遲早會對不上——畫面標亮但實際沒套用，最難查的那種。
  var F = {q:"", mkt:"tw", lit:"4", sort:"lit", theme:""};
  var list = document.getElementById("list");
  var items = Array.prototype.slice.call(list.querySelectorAll(".it"));
  var cur = null;

  function apply(){
    var vis = items.filter(function(el){
      var d = el.dataset;
      return (!F.mkt || d.mkt === F.mkt)
          && (!F.lit || (+d.lit) >= (+F.lit))
          && (!F.theme || d.theme === F.theme)
          && (!F.q || (d.q || "").indexOf(F.q) >= 0);
    });
    items.forEach(function(el){ el.hidden = vis.indexOf(el) < 0; });
    // 排序：一律由大到小。⚠️ 沒有值的排最後（資料裡放 -999），
    // 不要讓「查不到風報比」的排在「風報比很低」前面。
    var key = "sort" + F.sort.charAt(0).toUpperCase() + F.sort.slice(1);
    vis.sort(function(a, b){ return (+b.dataset[key]) - (+a.dataset[key]); });
    vis.forEach(function(el){ list.appendChild(el); });
    document.querySelector(".left .phead .dim").textContent =
      vis.length + " / " + items.length + " 檔";
    // 🔴 重排後捲回頂。不捲的話，你在清單中段按排序，變動全發生在畫面上方，
    // 看起來就是「按了沒反應」——Leo 2026-09-07 回報的「不會跑」就是這個。
    list.parentNode.scrollTop = 0;
  }

  document.getElementById("q").addEventListener("input", function(){
    F.q = this.value.trim().toLowerCase(); apply();
  });
  document.querySelectorAll(".ch").forEach(function(b){
    b.addEventListener("click", function(){
      var g = b.dataset.s !== undefined ? "s" : (b.dataset.m !== undefined ? "m" :
              (b.dataset.l !== undefined ? "l" : "t"));
      var f = {s:"sort", m:"mkt", l:"lit", t:"theme"}[g];
      F[f] = b.dataset[g];
      document.querySelectorAll(".ch[data-" + g + "]").forEach(function(o){
        o.classList.toggle("on", o === b);
      });
      apply();
    });
  });

  // ── 選股票 → 中欄 ──
  var mid = document.getElementById("mid");
  function pick(el){
    items.forEach(function(o){ o.classList.toggle("sel", o === el); });
    loadDetail(el.dataset.tk);
  }
  // 2026-09-20：不在清單裡的股票也走這條（伺服端即時重算，回傳片段裡帶
  // data-resolved＝解析後的代號；名稱輸入會被解析成代號，前端要跟著更新）。
  // 2026-09-21 Leo：「現在燈號個股沒有查的按鈕，要到列表才能查？」——查詢框原本只在列表模式。
  // 個股模式的中欄頂端也放一顆（每次換內容都重放，因為 innerHTML 整塊會被換掉）。
  function barHtml(v){
    var e = String(v == null ? "" : v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
    return '<form class="msearch" autocomplete="off"><input name="q" type="search" enterkeyhint="search" ' +
      'placeholder="查任意股票：代號或名稱（2454／台積電／COST）" value="' + e + '">' +
      '<button type="submit">查燈號</button></form>';
  }
  // exact＝使用者是從候選清單點的（已經是確定的代號）：伺服端不要再當名稱解析一次，
  // 否則算不出燈號時會又跳回同一份候選清單，看起來就是「點了沒反應」（SPCX 那次）。
  function loadDetail(q, exact){
    cur = q;
    document.getElementById("rtk").textContent = "看著 " + cur;
    mid.innerHTML = barHtml(q) + '<div class="empty">正在算 ' + cur +
      ' 的指標與三年日線…（抓兩年資料，數秒）</div>';
    fetch("/room/detail?ticker=" + encodeURIComponent(q) + (exact ? "&exact=1" : ""))
      .then(function(r){ return r.text(); })
      .then(function(h){
        mid.innerHTML = barHtml(q) + h;
        var m = mid.querySelector("[data-resolved]");
        if (m && m.dataset.resolved) {
          cur = m.dataset.resolved;
          var _qi = mid.querySelector(".msearch input"); if (_qi) _qi.value = cur;
          document.getElementById("rtk").textContent = "看著 " + cur;
          lastTk = cur;
          items.forEach(function(o){ o.classList.toggle("sel", o.dataset.tk === cur); });
        }
        // technical_indicators 產的是「畫圖的程式碼」不是圖片，
        // innerHTML 塞進去的 <script> 不會執行，要自己重建一次。
        mid.querySelectorAll("script").forEach(function(old){
          var s = document.createElement("script");
          if (old.src) { s.src = old.src; } else { s.textContent = old.textContent; }
          old.parentNode.replaceChild(s, old);
        });
      })
      .catch(function(e){
        mid.innerHTML = barHtml(q) + '<div class="warn">讀取失敗：' + e + '</div>';
      });
  }
  items.forEach(function(el){ el.addEventListener("click", function(){
    lastTk = el.dataset.tk;
    pick(el);
    loadHist(el.dataset.tk);
    // 點了個股就是想看那一檔——自動切回「這一檔」，不然會以為在問它、
    // 其實問的是全本（反過來的誤會比較難發現）。
    scope = "one";
    applyScope();
  }); });

  // ── 兩組篩選同步（2026-09-07 Leo：「選美股就兩邊都選美股」）──
  // 兩邊狀態各自存在自己的閉包裡，我不去改它——改成**按對方那顆鈕**，
  // 讓它自己的 handler 跑，狀態與每顆籤的計數都會正確更新。
  var syncing = false;                       // 防止互按無限迴圈
  var MKT_L2T = {"": "all", "us": "us", "tw": "tw"};
  var MKT_T2L = {"all": "", "us": "us", "tw": "tw"};
  // ⚠️ 有損的對應：列表多了含風報比條件的兩顆，左欄沒有（左欄的風報比是排序）。
  //    打點→3燈、⭐⭐→4燈，只取燈數那一半。寧可左欄少濾一點，
  //    也不要讓它的檔數比列表少而說不出原因。
  var LIT_L2T = {"": "all", "3": "3", "4": "4"};
  var LIT_T2L = {"all": "", "3": "3", "4": "4", "hit": "3", "hit4": "4"};

  function clickIf(sel){
    var el = document.querySelector(sel);
    if (el && el.getAttribute("aria-pressed") !== "true"
           && !el.classList.contains("on")) { el.click(); }
  }

  // 左欄 → 列表
  document.querySelectorAll(".ch").forEach(function(b){
    b.addEventListener("click", function(){
      if (syncing) return;
      syncing = true;
      try {
        // ⚠️ 左欄的籤是 data-m / data-l（不是 data-mkt / data-lit）。
        //    我第一版寫錯屬性名 → 同步整個沒接上**而且不會報錯**。
        if (b.dataset.m !== undefined) {
          var v = MKT_L2T[b.dataset.m];
          if (v) clickIf('[data-f="mkt"][data-v="' + v + '"]');
        } else if (b.dataset.l !== undefined) {
          var w = LIT_L2T[b.dataset.l];
          if (w) clickIf('[data-f="lit"][data-v="' + w + '"]');
        }
      } finally { syncing = false; }
    });
  });

  // 列表 → 左欄
  document.querySelectorAll('.tablepane [data-f]').forEach(function(b){
    b.addEventListener("click", function(){
      if (syncing) return;
      syncing = true;
      try {
        var m = null;
        if (b.dataset.f === "mkt") m = MKT_T2L[b.dataset.v];
        else if (b.dataset.f === "lit") m = LIT_T2L[b.dataset.v];
        if (m === null || m === undefined) return;    // 象限/來源左欄沒有，跳過
        var g = (b.dataset.f === "mkt") ? "m" : "l";
        var el = document.querySelector('.ch[data-' + g + '="' + m + '"]');
        if (el && !el.classList.contains("on")) el.click();
      } finally { syncing = false; }
    });
  });

  // 開頁時把左欄的預設（台股＋4燈）推到列表去。
  // ⚠️ 沒有這一步，開頁就是**兩邊不一致**：左欄已經濾成台股 4 燈，
  //    表格還顯示 312 檔全部——同一個畫面兩套數字，比沒有同步更糟。
  (function(){
    syncing = true;
    try {
      var m0 = document.querySelector(".ch[data-m].on");
      var l0 = document.querySelector(".ch[data-l].on");
      if (m0 && MKT_L2T[m0.dataset.m])
        clickIf('[data-f="mkt"][data-v="' + MKT_L2T[m0.dataset.m] + '"]');
      if (l0 && LIT_L2T[l0.dataset.l])
        clickIf('[data-f="lit"][data-v="' + LIT_L2T[l0.dataset.l] + '"]');
    } finally { syncing = false; }
  })();

  // ── 模式切換（列表 / 個股）──
  // ⚠️ 列表模式是**預設**：Leo 的用法是先掃描再鑽進去，開頁就看到表比較順。
  //    手機在外面也是先看列表。
  // 之前談過什麼：換標的就重載一次。
  // ⚠️ 只在軍師欄開著的時候抓，關著抓等於每點一檔就多打一次伺服器。
  function loadHist(tk){
    var box = document.getElementById("msgs");
    if (!box || !room.classList.contains("chat")) return;
    fetch("/room/history?ticker=" + encodeURIComponent(tk || ""))
      .then(function(r){ return r.ok ? r.text() : ""; })
      .then(function(h){
        var old = box.querySelector(".hist");
        if (old) old.remove();
        // ⚠️ 只認我們自己那段。服務沒起來時回的是 HTML 錯誤頁，
        //    直接 insertAdjacentHTML 會把「Error response 404」整片塞進對話裡
        //    （2026-09-07 手機實測看到）。看不懂的東西就當沒有，不要往畫面上倒。
        if (h && h.indexOf('<div class="hist"') === 0) {
          box.insertAdjacentHTML("afterbegin", h);
        }
      })
      .catch(function(){});
  }

  var mStock = document.getElementById("mode-stock");
  var mList = document.getElementById("mode-list");
  function setMode(list){
    room.classList.toggle("list", list);
    mList.classList.toggle("on", list);
    mStock.classList.toggle("on", !list);
    // 切回個股要讓圖重算——它在 display:none 底下量到的寬度是 0。
    // 2026-09-19 Leo 反饋圖表還是空白（第二次回報同一症狀）：懷疑是預設列表
    // 模式時 pick(first) 提前把圖建在隱藏的 #mid 裡，單純呼叫不帶參數的
    // resize() 沒有穩定補回寬度（不同瀏覽器的 ResizeObserver 對「從沒有
    // layout box 到有」這個轉場處理不一致）。改成：直接讀容器當下量到的
    // 實際寬高帶進 resize(w, h)，不靠 Chart.js 自己重新量；且補兩次
    // （30ms 一次、200ms 再一次），避免單次時機沒抓準。
    if (!list) {
      [30, 200].forEach(function(delay){
        setTimeout(function(){
          document.querySelectorAll("#mid canvas").forEach(function(c){
            var ch = (window.Chart && Chart.getChart) ? Chart.getChart(c) : null;
            if (!ch) return;
            var box = c.parentElement;
            if (box && box.clientWidth > 0) ch.resize(box.clientWidth, box.clientHeight);
            else ch.resize();
          });
        }, delay);
      });
    }
    try { localStorage.setItem("roomMode", list ? "list" : "stock"); } catch(e) {}
  }
  mStock.addEventListener("click", function(){ setMode(false); });
  mList.addEventListener("click", function(){ setMode(true); });

  // ── 搜尋框：母體內就留在戰情室，母體外才跳查股頁 ──
  // 2026-09-08 Leo：「改在母體內不跳出」。
  // 原本這顆框（board_theme 的共用 LOOKUP_BOX）一律 target=_blank 開查股頁，
  // 連母體裡本來就有的股票也被丟出去 → 等於離開軍師與左欄。
  // ⭐ 只攔「找得到的」，找不到的完全不動它——讓表單照原本的方式送出去，
  //    這樣「母體外要能查」這件事不會因為我多寫了 JS 而壞掉。
  (function(){
    var f = document.querySelector("form.lkbox");
    if (!f) return;
    var inp = f.querySelector('input[name="ticker"]');
    if (!inp) return;
    // 2026-09-20 Leo：「輸入個股的地方如果沒有在清單裡，則即時重算」——
    // 原本母體外＝放行表單、開新分頁到 /lookup（等於跳出戰情室）。現在一律攔下：
    // 母體內直接選；母體外就在中欄即時重算（伺服端 detail_html 處理名稱解析／查無資料）。
    window.roomSearch = function(q, exact){
      q = (q || "").trim();
      if (!q) return;
      var lo = q.toLowerCase();
      var hit = items.find(function(x){
        return (x.dataset.tk || "").toLowerCase() === lo;
      }) || items.find(function(x){
        return (x.dataset.q || "").indexOf(lo) >= 0;
      });
      setMode(false);
      scope = "one"; applyScope();
      if (hit) {
        lastTk = hit.dataset.tk;
        pick(hit);
        loadHist(hit.dataset.tk);
        try { hit.scrollIntoView({block: "nearest"}); } catch(_e) {}
      } else {
        lastTk = q;
        loadDetail(q, exact);
        loadHist(q);
      }
    };
    f.addEventListener("submit", function(e){
      e.preventDefault();
      window.roomSearch(inp.value);
      inp.blur();
    });
    // 名稱有多個候選時，候選鈕在中欄裡（事件委派，片段是後來才塞進去的）
    document.getElementById("mid").addEventListener("click", function(e){
      var b = e.target.closest && e.target.closest("[data-rpick]");
      if (b) window.roomSearch(b.dataset.rpick, true);
    });
    // 中欄頂端的查詢框（個股模式用）
    document.getElementById("mid").addEventListener("submit", function(e){
      var fm = e.target;
      if (fm && fm.classList && fm.classList.contains("msearch")) {
        e.preventDefault();
        var qi = fm.querySelector("input");
        window.roomSearch(qi ? qi.value : "");
        if (qi) qi.blur();
      }
    });
  })();

  // 點表格任一列 → 切到個股模式並選中那一檔
  document.querySelectorAll(".tablepane table.cb tr[data-tid]").forEach(function(tr){
    tr.addEventListener("click", function(e){
      // 表格自己的「圖」展開鈕不要被攔截
      if (e.target.closest("button, a")) return;
      // ⚠️ combo_html 的 data-tid 帶 `d_` 前綴（它自己的 DOM id 規則），
      //    直接拿來當代號會對不上——我第一版就是這樣，點了完全沒反應。
      var tk = tr.dataset.tk || "";
      var el = items.find(function(x){ return x.dataset.tk === tk; });
      setMode(false);
      if (el) {
        // 選中的那一檔可能被目前的篩選藏起來 → 先清掉篩選，不然點了看不到
        if (el.hidden) {
          F = {q:"", mkt:"", lit:"", sort:F.sort};
          document.getElementById("fq") && (document.getElementById("fq").value = "");
          document.querySelectorAll(".ch").forEach(function(o){
            var g = o.dataset.s !== undefined ? "s" : (o.dataset.m !== undefined ? "m" : "l");
            if (g !== "s") o.classList.toggle("on", o.dataset[g] === "");
          });
          apply();
        }
        lastTk = el.dataset.tk;
        pick(el);
        el.scrollIntoView({block:"center"});
      }
    });
  });

  // ── 軍師欄 ──
  var room = document.querySelector(".room");
  var right = document.getElementById("right");
  var btn = document.getElementById("chatbtn");
  function toggle(on){
    room.classList.toggle("chat", on);
    right.hidden = !on;
    btn.textContent = on ? "✕ 收起軍師" : "🏛️ 軍師";
    document.body.classList.toggle("chatting", on);   // 手機浮層用（見 ROOM_CSS）
    // 開起來才抓歷史：關著抓等於每點一檔就多打一次伺服器。
    if (on) loadHist(cur || "");
  }
  btn.addEventListener("click", function(){ toggle(!room.classList.contains("chat")); });
  document.getElementById("rclose").addEventListener("click", function(){ toggle(false); });
  applyScope();

  // 範圍：one＝目前選中的那一檔，all＝全部持股（仲達/陳壽的材料本來就是全本）。
  // ⚠️ 孔明在全本模式下**不能用**——他是個股判斷的角色，他的材料在沒有指定
  //    股票時會明寫「請使用者說要問哪一檔」。與其讓他回一句沒用的話，
  //    不如在介面上就講清楚為什麼不能選。
  var scope = "one";
  var ONLY_ONE = {"孔明": "孔明一次只判一檔，要先選股票"};
  var autoSwitched = false;      // 因為「全部」範圍被自動從孔明切到軍議 → 切回「這一檔」時要自動回到孔明
  function applyScope(){
    document.getElementById("sc-one").classList.toggle("on", scope === "one");
    document.getElementById("sc-all").classList.toggle("on", scope === "all");
    document.getElementById("quick").hidden = (scope !== "all");
    // 「全部」範圍孔明不能用（一次只判一檔）→ 自動展開「更多」，讓被切過去的軍議看得到
    if (scope === "all") {
      var _rs = document.querySelector(".roles"), _rm = document.getElementById("rmore");
      if (_rs) _rs.classList.add("open");
      if (_rm) _rm.textContent = "收起▴";
    }
    var note = document.getElementById("scnote");
    if (note) note.textContent = (scope === "all")
      ? "仲達／陳壽的材料本來就是全本"
      : (cur ? "" : "還沒選股票");
    document.querySelectorAll(".rb").forEach(function(b){
      var why = (scope === "all") ? ONLY_ONE[b.dataset.r] : null;
      b.disabled = !!why;
      b.title = why || "";
      if (why && b.classList.contains("on")) {
        // 目前選的軍師在這個範圍不能用 → 退回軍議，不要留一個按不動的選擇
        var g = document.querySelector('.rb[data-r="軍議"]');
        if (g) { g.click(); autoSwitched = true; }
      }
    });
    // 切回「這一檔」：如果剛剛是被自動切走的，窗口回到孔明並收起「更多」
    if (scope === "one" && autoSwitched) {
      var k = document.querySelector('.rb[data-r="孔明"]');
      if (k) { k.click(); }
      autoSwitched = false;
      var _rs2 = document.querySelector(".roles"), _rm2 = document.getElementById("rmore");
      if (_rs2) _rs2.classList.remove("open");
      if (_rm2) _rm2.textContent = "更多▾";
    }
    var rtk = document.getElementById("rtk");
    if (rtk) rtk.textContent = (scope === "all") ? "看著 全部持股"
      : (cur ? "看著 " + cur : "未選標的");
  }
  document.getElementById("sc-one").addEventListener("click", function(){
    scope = "one"; applyScope();
  });
  document.getElementById("sc-all").addEventListener("click", function(){
    scope = "all"; applyScope();
  });
  document.querySelectorAll(".qk").forEach(function(b){
    b.addEventListener("click", function(){
      qbox.value = b.textContent;
      ask(false);
    });
  });

  var role = "孔明";
  // 2026-09-07：不再需要「換股票就重開」——續談的 key 綁標的（war_room_chat._key），
  // 換股票本來就是另一條線。留著 freshNext 反而會把那一檔存好的對話洗掉，
  // 跟「跨天要能翻回去續談」直接衝突。fresh 只剩「重開這一條」按鈕會用到。
  var freshNext = false;
  var lastTk = null;
  // 「更多」：展開／收起其他四位軍師
  (function(){
    var rm = document.getElementById("rmore");
    if (!rm) return;
    rm.addEventListener("click", function(){
      var rs = document.querySelector(".roles");
      var open = rs.classList.toggle("open");
      rm.textContent = open ? "收起▴" : "更多▾";
    });
  })();
  document.querySelectorAll(".rb").forEach(function(b){
    b.addEventListener("click", function(){
      role = b.dataset.r;
      document.querySelectorAll(".rb").forEach(function(o){
        o.classList.toggle("on", o === b);
      });
    });
  });

  var msgs = document.getElementById("msgs");
  var send = document.getElementById("send");
  var qbox = document.getElementById("qbox");
  function add(cls, who, text){
    var d = document.createElement("div");
    d.className = "msg " + cls;
    if (who){ var w = document.createElement("b"); w.className = "who";
              w.textContent = who; d.appendChild(w); }
    d.appendChild(document.createTextNode(text));
    msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
    return d;
  }
  // 累計成本與輪數（學老墨的 阿福 footer）。**一輪一輪加上去**——
  // 單看一次多少錢沒有意義，會想知道的是「今天這樣問下來花了多少」。
  var accCost = 0, accTurns = 0;
  function stateLine(extra){
    var tag = document.getElementById("rstate");
    if (!tag) return;
    tag.textContent = (extra ? extra + "・" : "")
      + (cur ? cur + "・" : "") + accTurns + " 輪・等值 US$" + accCost.toFixed(3);
  }

  function ask(fresh){
    var q = qbox.value.trim();
    // 全本模式**不要**把目前選中的那一檔黏到問題前面——那正是原本
    // 「看一下所有個股」會變成問單一檔的原因。
    var tk = (scope === "all") ? "" : (cur || "");
    var full = (tk && q) ? (tk + " " + q) : (q || (tk || ""));
    add("me", null, (scope === "all" ? "【全部持股】" : (tk ? "【" + tk + "】" : ""))
        + (q || "（用預設問題）"));
    qbox.value = "";
    send.disabled = true;

    // 進度籤：一格一格加，最後一格高亮＝現在在做的事
    var box = document.createElement("div");
    box.className = "stages";
    msgs.appendChild(box);
    function stage(txt){
      Array.prototype.forEach.call(box.children, function(c){ c.classList.remove("now"); });
      var e = document.createElement("span");
      e.className = "stg now";
      e.textContent = txt;
      box.appendChild(e);
      msgs.scrollTop = msgs.scrollHeight;
    }
    stage("送出");

    var bubbles = {};        // 軍師名 → 那一段的 div（軍議有四位）
    function bubble(name){
      if (!bubbles[name]) bubbles[name] = add("live", name, "");
      return bubbles[name];
    }

    var url = "/room/ask_stream?role=" + encodeURIComponent(role)
      + "&question=" + encodeURIComponent(full)
      + "&ticker=" + encodeURIComponent(tk)
      + (fresh ? "&fresh=1" : "");
    var es;
    try { es = new EventSource(url); }
    catch (e) { es = null; }
    if (!es) { askFallback(full, fresh, tk); return; }

    var got = false;
    es.addEventListener("stage", function(ev){
      got = true;
      var d = JSON.parse(ev.data);
      stage(d.text);
    });
    es.addEventListener("start", function(ev){
      var d = JSON.parse(ev.data);
      stage(d.name + " 開始回答");
      bubble(d.name);
    });
    es.addEventListener("delta", function(ev){
      got = true;
      var d = JSON.parse(ev.data);
      var b = bubble(d.name);
      b.appendChild(document.createTextNode(d.text));
      msgs.scrollTop = msgs.scrollHeight;
    });
    es.addEventListener("end", function(ev){
      var d = JSON.parse(ev.data);
      var b = bubble(d.name);
      // 用完整版覆蓋串流拼出來的：重寫過的那一輪，串流那份是作廢的舊稿。
      b.textContent = "";
      var w = document.createElement("b");
      w.className = "who";
      w.textContent = d.name + (d.resumed ? "　續談" : "")
        + (d.refreshed ? "　材料已換成今天" : "");
      b.appendChild(w);
      b.appendChild(document.createTextNode(d.text));
      b.classList.remove("live");
      accCost = d.cost || accCost;
      accTurns += 1;
      stateLine();
    });
    es.addEventListener("error", function(ev){
      try { add("err", role, JSON.parse(ev.data).text); } catch (e) {}
    });
    es.addEventListener("done", function(ev){
      var d = JSON.parse(ev.data);
      accCost = d.cost || accCost;
      stateLine();
      Array.prototype.forEach.call(box.children, function(c){ c.classList.remove("now"); });
      es.close();
      send.disabled = false;
    });
    es.onerror = function(){
      es.close();
      send.disabled = false;
      if (!got) {
        // 完全沒收到東西＝串流這條路不通（服務沒起來／中間層擋 SSE）。
        // ⚠️ 這時候不要只印一句錯誤就算了，退回原本那條會拿到答案的路。
        box.remove();
        askFallback(full, fresh, tk);
      } else {
        Array.prototype.forEach.call(box.children, function(c){ c.classList.remove("now"); });
        Object.keys(bubbles).forEach(function(k){ bubbles[k].classList.remove("live"); });
      }
    };
  }

  // 舊的一次拿全部（串流不通時的退路）。⚠️ 保留它是因為串流多了一層可能斷的東西，
  // 斷了要還有辦法拿到答案，不是只看到一句紅字。
  function askFallback(full, fresh, askTk){
    send.disabled = true;
    var wait = add("", role, "思考中…（串流不可用，改用一次回全部；一位約 40-60 秒）");
    fetch("/room/ask", {method:"POST", headers:{"Content-Type":"application/json"},
                        body: JSON.stringify({role: role, question: full,
                                              ticker: askTk, fresh: !!fresh})})
      .then(function(r){
        // ⚠️ 不能直接 r.json()。服務重啟或 tunnel 斷線時回的是 HTML 錯誤頁，
        //    JSON.parse 會丟 "Unexpected token '<'"——使用者只看到一句
        //    看不懂的 SyntaxError（2026-09-07 Leo 踩到）。
        return r.text().then(function(t){
          try { return JSON.parse(t); }
          catch (e) {
            if (r.status === 404) {
              return {error: "沒有授權：這頁需要用 ?key=… 開一次（會種 90 天 cookie）。"};
            }
            return {error: "服務沒有回 JSON（HTTP " + r.status + "）。"
                    + "多半是本機服務正在重啟或沒開著——過幾秒再送一次。"};
          }
        });
      })
      .then(function(j){
        wait.remove();
        if (j.error){ add("err", role, j.error); return; }
        (j.answers || []).forEach(function(a){ add("", a.name, a.text); });
        var inf = j.info || {};
        accCost += (inf.cost || 0);
        accTurns += (inf.turns || 1);
        stateLine(inf.resumed ? "續談" : "新對話");
      })
      .catch(function(e){ wait.remove(); add("err", role, "呼叫失敗：" + e); })
      .finally(function(){ send.disabled = false; });
  }
  send.addEventListener("click", function(){ ask(false); });
  document.getElementById("restart").addEventListener("click", function(){
    // 重開＝這一檔這位軍師另起一條線（不接續）。
    add("me", null, "（重開一條對話）");
    ask(true);
  });
  qbox.addEventListener("keydown", function(e){
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { ask(false); }
  });

  // 左欄拖曳（Leo 2026-09-07：「左邊字卡可以讓我拉動嗎?」）。
  // 寬度存 localStorage，下次開還在。⚠️ 拖完要讓圖表 resize()——中欄變寬了，
  // Chart.js 不會自己察覺（跟隱藏說明卡那顆鈕同一個坑）。
  (function(){
    const grip = document.getElementById("grip");
    const room = document.querySelector(".room");
    const saved = (function(){ try { return localStorage.getItem("roomLW"); }
                               catch(e) { return null; } })();
    if (saved) room.style.setProperty("--lw", saved);
    // 收合／展開。⚠️ 收合後圖要 resize()——中欄變寬了 Chart.js 不會自己察覺。
    function resizeCharts(){
      setTimeout(function(){
        document.querySelectorAll("#mid canvas").forEach(function(c){
          const ch = (window.Chart && Chart.getChart) ? Chart.getChart(c) : null;
          if (ch) ch.resize();
        });
      }, 40);
    }
    function setHide(on){
      room.classList.toggle("lhide", on);
      const sb = document.getElementById("lshow");
      if (sb) sb.style.display = on ? "block" : "none";
      try { localStorage.setItem("roomLHide", on ? "1" : "0"); } catch(e) {}
      resizeCharts();
    }
    const hb = document.getElementById("lhide");
    const sb = document.getElementById("lshow");
    if (hb) hb.addEventListener("click", function(){ setHide(true); });
    if (sb) sb.addEventListener("click", function(){ setHide(false); });
    try { if (localStorage.getItem("roomLHide") === "1") setHide(true); } catch(e) {}

    // ⚠️ pointer events 不是 mouse events：Leo 也用平板，mousedown 在觸控上不會觸發。
    let dragging = false;
    grip.addEventListener("pointerdown", function(e){
      dragging = true; grip.classList.add("on");
      grip.setPointerCapture(e.pointerId);
      document.body.style.userSelect = "none"; e.preventDefault();
    });
    window.addEventListener("pointermove", function(e){
      if (!dragging) return;
      const w = Math.min(640, Math.max(220, e.clientX - 10));
      room.style.setProperty("--lw", w + "px");
    });
    window.addEventListener("pointerup", function(){
      if (!dragging) return;
      dragging = false; grip.classList.remove("on");
      document.body.style.userSelect = "";
      try { localStorage.setItem("roomLW", room.style.getPropertyValue("--lw")); }
      catch(e) {}
      // 中欄寬度變了，圖要重算
      document.querySelectorAll("#mid canvas").forEach(function(c){
        const ch = (window.Chart && Chart.getChart) ? Chart.getChart(c) : null;
        if (ch) ch.resize();
      });
    });
  })();

  (function(){
    // 2026-09-21 Leo：「進出燈號一樣都先進列表」。原本記住上次的模式（roomMode），
    // 上次停在個股，下次打開就直接是個股。改成一律列表；帶 ?ticker= 進來會由 roomSearch 切到個股。
    setMode(true);
  })();

  apply();
  // ⚠️ 要選**篩選後看得到的**第一檔，不是 items[0]。
  //    預設是台股+4燈，items[0] 卻是美股 MA → 中間顯示一檔左邊看不到的股票。
  const first = items.find(function(e){ return !e.hidden; });
  // 從入口頁／首頁查股框帶 ?ticker= 進來 → 直接查那一檔（不先載預設那檔，
  // 不然兩個請求誰後回來誰就蓋掉對方）。
  var qp = "";
  try { qp = new URLSearchParams(location.search).get("ticker") || ""; } catch(_e) {}
  if (qp.trim()) { window.roomSearch(qp); }
  else if (first) { pick(first); }
})();
</script>
"""


def title_html():
    """2026-09-10 Leo:「標題跟其它分頁一樣」——原本標題只是導覽列裡一個
    12px 的小字（`.rnb`），擠在連結旁邊，跟其他頁那種「眉標+大標題」的
    頁首完全不像。這裡不整包套 board_theme.header()（那還會帶 subtitle+
    navlinks，100vh 版型放不下），只把「標題該長什麼樣」對齊，導覽連結
    留在 nav_html() 自己那排。"""
    from board_theme import icon, esc, EYEBROW
    eye = EYEBROW.get("room", "TERMINAL")
    return (f'<div class="roomtitle"><span class="eye">{esc(eye)}<em> // 隆中對</em></span>'
            f'<div class="titlerow">{icon("lamp", 19, "#22D3EE")}<h1>燈號戰情室</h1>'
            f'<span class="rtag">本機・即時</span></div></div>')


def nav_html():
    """細導覽列。**只有連結**，不放標題——標題移到 title_html() 那排了
    （2026-09-10 起是兩排：標題一排、連結+控制項一排，原本擠在同一排）。

    ⚠️ 用 nav_abs() 不是 NAV：這頁跑在 stock.talentxtrend.com，
    相對路徑會連到自己那台的 404。
    """
    from board_theme import nav_abs, icon, esc
    # 🔴 2026-09-07 Leo：「從上面快捷按鍵進去是舊的」。
    # 「進出燈號」原本連到公開的靜態燈號頁（GitHub Pages），
    # 等於從戰情室按一下就被送出去，而且看到的是同一份資料的另一種呈現。
    # 戰情室的列表模式**就是**進出燈號，所以這一顆改成指回自己並標成目前頁。
    # ⚠️ 公開那份沒有被取代——它的存在理由是「不需要本機開機」，
    #    電腦沒開的時候只有它看得到。所以另外留一顆「公開版」。
    out = []
    for k, ic, lab, href in nav_abs():
        if k == "combo":
            # 2026-09-20 Leo：本機離線就直接「無法使用」，不留備援列表 → 不再有第二顆連結。
            out.append(f'<a class="nl cur" href="/room">{icon(ic, 13)}{esc(lab)}</a>')
        else:
            out.append(f'<a class="nl" href="{href}">{icon(ic, 13)}{esc(lab)}</a>')
    links = "".join(out)
    # 2026-09-10 Leo：「報價組合縮小後要打開的按鍵可以做在左邊嗎? 不然這樣
    # 縮小要放大還要移到最右邊」——展開鈕（lshow）原本跟模式/軍師擺一起，
    # 在導覽列最右邊；但收合鈕（左欄自己 .phead 裡的「«」）在最左邊，
    # 兩顆位置對不上，滑鼠要整條移過去，跟他要收合左欄的動作方向剛好相反。
    # 展開鈕移到導覽列最左邊（.navls 之前），跟收合鈕同一側，滑鼠不用大移動。
    lshow = '<button class="lbtn lshow" id="lshow" title="展開左欄">» 報價組合</button>'
    # 右側的控制項：模式／軍師。
    # ⭐ 原本這三顆都是 position:fixed 浮在畫面上，結果三個都擋到東西
    #    （模式鈕擋圖、軍師鈕蓋住送出、展開鈕蓋住中欄左上）。
    #    浮動鈕沒有「不擋東西的位置」——畫面滿的時候每個角落都有內容。
    ctrl = ('<span class="modebar"><button class="mb" id="mode-stock">個股</button>'
            '<button class="mb on" id="mode-list">列表</button></span>'
            '<button class="chatbtn" id="chatbtn">🏛️ 軍師</button>')
    # 🔴 2026-09-08 Leo：「右上少一個軍師的按鍵」。
    #    整條導覽列是 overflow-x:auto，連結一多就把最後一顆（軍師）推出右邊界，
    #    在 1900px 的螢幕上剛好差幾十 px —— 看起來像「沒有這顆鈕」。
    #    ⭐ 修法不是縮小字，是**分成兩區**：連結自己捲，控制項固定不參與捲動。
    #       這樣不管幾個連結、螢幕多窄，控制項一定在畫面上。
    return f'<nav class="roomnav">{lshow}<span class="navls">{links}</span>{ctrl}</nav>'


def page_html():
    """三欄殼。CDN 圖表函式庫沿用 lookup_page 那組（同一套圖，不另外挑）。"""
    from board_theme import BASE_CSS
    import lookup_page as lp
    try:
        import technical_indicators as ti
        ti_css = ti.CSS
    except Exception:                                       # noqa: BLE001
        ti_css = ""
    items, asof = rows()
    scripts = "".join(f'<script src={Q}{u}{Q}></script>' for u in lp.CDN)
    return ("<!doctype html><html lang=" + Q + "zh-Hant" + Q + "><head><meta charset="
            + Q + "utf-8" + Q + "><meta name=" + Q + "viewport" + Q + " content="
            + Q + "width=device-width,initial-scale=1" + Q + ">"
            "<title>燈號戰情室</title>" + scripts
            + "<style>" + BASE_CSS + _combo_css() + ti_css + ROOM_CSS + "</style></head><body>"
            + title_html()
            + nav_html()
            + '<div class="room">'
            + left_html(items, asof)
            + '<main class="pane" id="mid"><div class="empty">左邊選一檔。</div></main>'
            + f'<div class="pane tablepane" id="tablepane">{table_html()}</div>'
            + right_html()
            + "</div>"
            + ROOM_JS + "</body></html>")


# 續談用的 session（2026-09-07 Leo：「做吧」）。
# 續談與對話記錄都搬到 war_room_chat.py（2026-09-07 Leo：「需要跨天，可以會翻回
# 之前的討論」＋「discord 也同步」）。原本是這裡一個記憶體 dict，
# bot 重啟就沒、跨天不接、Discord 那邊完全是另一條線。


def ask(role, question, ticker=None, fresh=False):
    """呼叫軍師。回 (answers, info)。**不重寫任何判斷邏輯**，直接用 war_room。"""
    import war_room
    import war_room_chat as wc

    out, info = [], {"resumed": False, "refreshed": False, "since": "",
                     "cost": 0.0, "turns": 0}

    def _acc(x):
        info["resumed"] = info["resumed"] or x["resumed"]
        info["refreshed"] = info["refreshed"] or x["refreshed"]
        info["since"] = info["since"] or x.get("since") or ""

    if role == "軍議":
        prior = []
        for r in war_room.council_roles(question):
            t, m, x = wc.ask(r, question, ticker, fresh, prior=prior, src="room")
            prior.append((war_room.ROLES[r]["name"], t))
            out.append({"name": war_room.ROLES[r]["name"], "text": t})
            _acc(x)
            info["cost"] += float(m.get("cost_usd") or 0)
            info["turns"] += 1
    elif role not in war_room.ROLES:
        out = [{"name": role,
                "text": f"沒有這位軍師（可用：{'、'.join(war_room.ROLES)}）"}]
    else:
        t, m, x = wc.ask(role, question, ticker, fresh, src="room")
        out = [{"name": war_room.ROLES[role]["name"], "text": t}]
        _acc(x)
        info["cost"] = float(m.get("cost_usd") or 0)
        info["turns"] = 1
    return out, info


def chat_html(ticker):
    """右欄開啟時先端出「之前談過什麼」。

    ⚠️ 只端這一檔的。翻全部的歷史是 CLI（`python war_room_chat.py -n 30`）的事，
    在只有 380px 寬的欄位裡塞別檔的對話只會蓋掉現在要看的東西。
    """
    from board_theme import esc
    import war_room_chat as wc
    h = wc.history(ticker or "", limit=12)
    if not h:
        return ""
    out = ['<div class="hist"><div class="histh">之前談過（'
           + str(len(h)) + ' 輪）</div>']
    for r in h:
        d = str(r.get("ts") or "")[5:16].replace("T", " ")
        tag = "🔁" if r.get("refreshed") else ""
        src = "Discord" if r.get("src") == "discord" else ""
        out.append(f'<div class="msg me"><span class="who">你 · {esc(d)}'
                   f'{" · " + src if src else ""}</span>'
                   f'{esc(r.get("q") or "（預設問題）")}</div>')
        out.append(f'<div class="msg"><span class="who">{esc(r.get("role"))} {tag}'
                   f'</span>{esc(r.get("a") or "")}</div>')
    out.append("</div>")
    return "".join(out)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="", help="寫成檔案（除錯用；正式走 /room）")
    a = ap.parse_args()
    h = page_html()
    if a.output:
        io.open(a.output, "w", encoding="utf-8").write(h)
        print(f"✅ {a.output}（{len(h):,} bytes）")
    else:
        items, asof = rows()
        print(f"母體 {len(items)} 檔｜資料日 {asof}｜殼 {len(h):,} bytes")
        print("正式入口：本機 8030 的 /room（tunnel: stock.talentxtrend.com/room）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
