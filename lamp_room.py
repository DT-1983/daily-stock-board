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
            f' data-lit="{r["lit"]}"'
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
        f'<div class="phead">報價組合<span class="dim">{len(items)} 檔 · {esc(asof)}</span></div>'
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
        '</div></div>'
        '<ul class="list" id="list">' + "".join(lis) + "</ul></aside>")


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
        return ch.CSS + LOOKUP_CSS
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
            '（技術圖、燈號細節、軍師都在那邊）。</div>' + ch.body_html(d))


# ── 中欄 ──────────────────────────────────────────────────────────────
def detail_html(ticker):
    """中欄：關鍵數字 + 技術圖。**圖是現算的**（抓 2 年資料算指標，數秒）。

    ⚠️ 圖畫不出來不要讓整區掛掉——上面那排數字本身就有價值（同 lookup_page 的作法）。
    """
    from board_theme import esc
    items, _asof = rows()
    r = next((x for x in items if x["tk"].upper() == str(ticker).upper()), None)
    if not r:
        return f'<div class="empty">{esc(str(ticker))} 不在今天的掃描母體裡。</div>'

    d = _load(RESULT, {}) or {}
    raw = next((x for x in (d.get("rows") or [])
                if str(x.get("ticker")).upper() == r["tk"].upper()), {})

    def num(v, n=2, suf=""):
        return "—" if v is None else f"{v:,.{n}f}{suf}"

    QL = {"leading": "🟢 領先", "improving": "🔵 改善",
          "weakening": "🟡 轉弱", "lagging": "🔴 落後"}
    # 跟四燈同一種「亮/滅」語彙。半亮＝改善（還沒到領先但在往上走）。
    QDOT = {"leading": '<i class="lp on"></i>亮　',
            "improving": '<i class="lp half"></i>半亮　',
            "weakening": '<i class="lp"></i>滅　',
            "lagging": '<i class="lp"></i>滅　'}
    lamps = raw.get("lamps") or {}
    lamp_rows = "".join(
        f'<div class="lrow"><i class="lp {"on" if v else ""}"></i>{esc(k)}</div>'
        for k, v in lamps.items())
    st = ("🟢 空方" if not r["bull"] else "🔴 多方")
    stl = raw.get("st_line")
    stsub = ("" if stl is None else
             (f"停損參考線 {stl:,.2f}" if r["bull"] else f"站上 {stl:,.2f} 才翻多"))

    head = (
        f'<div class="dhead"><span class="tk">{esc(r["tk"])}</span>'
        f'<span class="nm">{esc(r["nm"])}</span>'
        f'<span class="px">{num(r["px"])}</span>'
        + ("" if r["chg"] is None else
           f'<span class="{"up" if r["chg"] >= 0 else "dn"}">{r["chg"]:+.2f}%</span>')
        + f'<span class="dim">{esc(r["sec"])}　燈號資料 {esc(_asof)}</span></div>'
        # 🔴 2026-09-07 查 Leo 的「9/3 沒日期」時發現的：上面這排卡是
        # combo_result 的快取（每天 07:45 掃，內容是前一交易日收盤），
        # 下面的圖是**現抓**的（到今天）。2454 當下卡片 4,415 / 圖 4,760，差 7.8%。
        # 同一頁兩個現價卻沒有任何線索說明——兩邊的資料日都要標出來。
        + '<div class="datewarn">⚠️ 上面的數字是<b>燈號掃描快取</b>（'
        + esc(_asof) + '）；下面的圖是<b>現抓的</b>（到最新交易日）。'
        '掃描之後又有交易日的話，兩者會不一樣。</div>')

    cards = "".join([
        f'<div class="dc"><div class="k">燈數</div><div class="v">{r["lit"]} / 4</div>'
        f'<div class="s">{lamp_rows}</div></div>',
        f'<div class="dc"><div class="k">SuperTrend</div><div class="v">{st}</div>'
        f'<div class="s">{esc(stsub)}</div></div>',
        f'<div class="dc"><div class="k">分析師共識目標價</div>'
        f'<div class="v">{num(r["tgt"])}</div>'
        f'<div class="s">{"" if r["gap"] is None else f"距現價 {r['gap']:+.1f}%"}</div></div>',
        f'<div class="dc"><div class="k">風報比</div><div class="v">{num(r["rr"])}</div>'
        f'<div class="s">{"⭐ 打點成立" if (r["lit"] >= 3 and (r["rr"] or 0) >= 1) else ""}</div></div>',
        f'<div class="dc"><div class="k">RS60</div>'
        f'<div class="v">{num(raw.get("rs_short"), 2, "%")}</div>'
        f'<div class="s">{"高於自身 60 日均線" if (raw.get("rs_short") or 0) > 0 else "低於自身 60 日均線"}</div></div>',
        # H（Leo：「可以加上 RRG 的訊號嗎? 跟燈號一樣（在最上面的字卡）」）
        # 象限本來就有，但只是一行文字。改成跟四燈同一種「亮/滅」語彙：
        # 領先＝亮，改善＝半亮（在往上走），轉弱/落後＝滅。
        # ⚠️ 這**不是新指標**，就是同一份 RRG 象限換個畫法——不要讓人以為多了一個訊號。
        f'<div class="dc"><div class="k">RRG 輪動</div>'
        f'<div class="v">{QL.get(r["quad"], "—")}</div>'
        f'<div class="s">{QDOT.get(r["quad"], "")}{esc(r["src"])}</div></div>',
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
    return head + '<div class="dcards">' + cards + "</div>" + tech


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
    btns = "".join(
        f'<button class="rb{" on" if i == 0 else ""}" data-r="{esc(k)}">'
        f'{esc(k)}<span>{esc(v)}</span></button>'
        for i, (k, v) in enumerate(ROLES))
    return (
        '<aside class="pane right" id="right" hidden>'
        '<div class="phead">軍師<span class="dim" id="rtk">未選標的</span>'
        '<span class="dim" id="rstate"></span>'
        '<button class="x" id="rclose">✕</button></div>'
        f'<div class="roles">{btns}</div>'
        '<div class="msgs" id="msgs">'
        '<div class="hint">選一檔股票，再挑一位軍師。<br>'
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
.room{display:grid;grid-template-columns:320px minmax(0,1fr) 0;gap:var(--gap);
 height:100vh;padding:var(--gap);box-sizing:border-box;background:var(--bg)}
.room.chat{grid-template-columns:320px minmax(0,1fr) 380px}
.pane{background:var(--panel,#080E1A);border:1px solid var(--hud,#16304A);border-radius:2px;
 overflow:auto;min-height:0}
.pane.left{position:relative}
.grip{right:-3px}
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
.ctrlbar{position:sticky;top:38px;z-index:2;background:var(--panel,#080E1A);
 border-bottom:1px solid var(--hud,#16304A);padding-bottom:6px}
.q{width:calc(100% - 24px);margin:10px 12px 6px;padding:7px 10px;font:inherit;
 font-size:12.5px;border-radius:0;border:1px solid var(--hud,#16304A);
 background:transparent;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:5px;padding:0 12px 8px;align-items:center}
.cl{font-size:10.5px;color:var(--dim);margin-right:2px}
.ch{font:inherit;font-size:11.5px;padding:3px 9px;border-radius:0;cursor:pointer;
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
 overflow-x:auto;-webkit-overflow-scrolling:touch}
.dc{flex:1 0 150px}
.dc{background:var(--surface);padding:9px 12px;min-width:0}
.dc .k{font-size:9px;color:var(--dim);letter-spacing:.14em;text-transform:uppercase;
 font-family:'IBM Plex Mono',ui-monospace,monospace}
.dc .v{font-size:16px;font-weight:600;margin-top:2px;
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.dc .s{font-size:10.5px;color:var(--muted,#94a3b8);margin-top:3px;line-height:1.7}
.lrow{display:flex;align-items:center;gap:5px}
.empty,.warn{padding:22px 16px;color:var(--dim);font-size:13px}
.datewarn{padding:6px 14px;font-size:11px;color:var(--dim);
 border-bottom:1px solid var(--line)}
.datewarn b{color:#FCD34D}
.roles{display:flex;flex-wrap:wrap;gap:5px;padding:9px 12px;
 border-bottom:1px solid var(--line)}
.rb{font:inherit;font-size:11.5px;padding:4px 9px;border-radius:0;cursor:pointer;
 border:1px solid var(--hud,#16304A);background:transparent;color:var(--dim);
 display:flex;flex-direction:column;align-items:center;line-height:1.35}
.rb span{font-size:9.5px;opacity:.75}
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
.modebar{position:fixed;left:50%;transform:translateX(-50%);bottom:14px;z-index:9;
 display:flex;border:1px solid var(--hud,#16304A);border-radius:0;overflow:hidden;
 background:var(--surface);box-shadow:0 6px 20px rgba(0,0,0,.45)}
.mb{font:inherit;font-size:12.5px;padding:8px 18px;border:0;cursor:pointer;
 background:transparent;color:var(--dim);font-weight:600;letter-spacing:.05em}
.mb.on{background:var(--cy-dim,rgba(34,211,238,.10));color:var(--cy,#22D3EE)}
@media(max-width:900px){.modebar{bottom:10px}.tablepane{padding:0 8px 14px}}
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
.chatbtn{position:fixed;right:14px;bottom:14px;z-index:9;font:inherit;font-size:13px;
 padding:9px 15px;border-radius:0;cursor:pointer;font-weight:700;letter-spacing:.05em;
 border:1px solid var(--cy,#22D3EE);background:var(--panel,#080E1A);color:var(--cy,#22D3EE);box-shadow:0 6px 20px rgba(0,0,0,.45)}
@media(max-width:900px){
 /* 手機：三欄疊成一欄，靠上面的分頁鈕切換——並排在 375px 上誰都看不清楚 */
 .room,.room.chat{grid-template-columns:1fr;height:auto}
 .pane{max-height:none}
 .room .pane.left{max-height:46vh}
 .room:not(.chat) .right{display:none}
}

/* 數字一律等寬對齊（HUD）：欄位不會因為字寬不同而跳動。 */
.l1 .px,.l2,.dhead .px{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
"""

ROOM_JS = r"""
<script>
(function(){
  // I（Leo：「預設選台股、四燈」）。⚠️ 初值要跟上面 class="ch on" 的那兩顆一致，
  // 兩邊分開寫就是遲早會對不上——畫面標亮但實際沒套用，最難查的那種。
  var F = {q:"", mkt:"tw", lit:"4", sort:"lit"};
  var list = document.getElementById("list");
  var items = Array.prototype.slice.call(list.querySelectorAll(".it"));
  var cur = null;

  function apply(){
    var vis = items.filter(function(el){
      var d = el.dataset;
      return (!F.mkt || d.mkt === F.mkt)
          && (!F.lit || (+d.lit) >= (+F.lit))
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
      var g = b.dataset.s !== undefined ? "s" : (b.dataset.m !== undefined ? "m" : "l");
      var f = {s:"sort", m:"mkt", l:"lit"}[g];
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
    cur = el.dataset.tk;
    document.getElementById("rtk").textContent = "看著 " + cur;
    mid.innerHTML = '<div class="empty">正在算 ' + cur +
      ' 的指標與三年日線…（抓兩年資料，數秒）</div>';
    fetch("/room/detail?ticker=" + encodeURIComponent(cur))
      .then(function(r){ return r.text(); })
      .then(function(h){
        mid.innerHTML = h;
        // technical_indicators 產的是「畫圖的程式碼」不是圖片，
        // innerHTML 塞進去的 <script> 不會執行，要自己重建一次。
        mid.querySelectorAll("script").forEach(function(old){
          var s = document.createElement("script");
          if (old.src) { s.src = old.src; } else { s.textContent = old.textContent; }
          old.parentNode.replaceChild(s, old);
        });
      })
      .catch(function(e){
        mid.innerHTML = '<div class="warn">讀取失敗：' + e + '</div>';
      });
  }
  items.forEach(function(el){ el.addEventListener("click", function(){
    lastTk = el.dataset.tk;
    pick(el);
    loadHist(el.dataset.tk);
  }); });

  // ── 模式切換（列表 / 個股）──
  // ⚠️ 列表模式是**預設**：Leo 的用法是先掃描再鑽進去，開頁就看到表比較順。
  //    手機在外面也是先看列表。
  // 之前談過什麼：換標的就重載一次。
  // ⚠️ 只在軍師欄開著的時候抓，關著抓等於每點一檔就多打一次伺服器。
  function loadHist(tk){
    var box = document.getElementById("msgs");
    if (!box || !room.classList.contains("chat")) return;
    fetch("/room/history?ticker=" + encodeURIComponent(tk || ""))
      .then(function(r){ return r.text(); })
      .then(function(h){
        var old = box.querySelector(".hist");
        if (old) old.remove();
        if (h) box.insertAdjacentHTML("afterbegin", h);
      })
      .catch(function(){});
  }

  var mStock = document.getElementById("mode-stock");
  var mList = document.getElementById("mode-list");
  function setMode(list){
    room.classList.toggle("list", list);
    mList.classList.toggle("on", list);
    mStock.classList.toggle("on", !list);
    // 切回個股要讓圖重算——它在 display:none 底下量到的寬度是 0
    if (!list) {
      setTimeout(function(){
        document.querySelectorAll("#mid canvas").forEach(function(c){
          var ch = (window.Chart && Chart.getChart) ? Chart.getChart(c) : null;
          if (ch) ch.resize();
        });
      }, 30);
    }
    try { localStorage.setItem("roomMode", list ? "list" : "stock"); } catch(e) {}
  }
  mStock.addEventListener("click", function(){ setMode(false); });
  mList.addEventListener("click", function(){ setMode(true); });

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
    // 開起來才抓歷史：關著抓等於每點一檔就多打一次伺服器。
    if (on) loadHist(cur || "");
  }
  btn.addEventListener("click", function(){ toggle(!room.classList.contains("chat")); });
  document.getElementById("rclose").addEventListener("click", function(){ toggle(false); });

  var role = "軍議";
  // 2026-09-07：不再需要「換股票就重開」——續談的 key 綁標的（war_room_chat._key），
  // 換股票本來就是另一條線。留著 freshNext 反而會把那一檔存好的對話洗掉，
  // 跟「跨天要能翻回去續談」直接衝突。fresh 只剩「重開這一條」按鈕會用到。
  var freshNext = false;
  var lastTk = null;
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
    // 沒選股票也可以問仲達/陳壽（他們的材料是全局的），但要提醒。
    var full = (cur && q) ? (cur + " " + q) : (q || (cur || ""));
    add("me", null, (cur ? "【" + cur + "】" : "") + (q || "（用預設問題）"));
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
      + "&ticker=" + encodeURIComponent(cur || "")
      + (fresh ? "&fresh=1" : "");
    var es;
    try { es = new EventSource(url); }
    catch (e) { es = null; }
    if (!es) { askFallback(full, fresh); return; }

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
        askFallback(full, fresh);
      } else {
        Array.prototype.forEach.call(box.children, function(c){ c.classList.remove("now"); });
        Object.keys(bubbles).forEach(function(k){ bubbles[k].classList.remove("live"); });
      }
    };
  }

  // 舊的一次拿全部（串流不通時的退路）。⚠️ 保留它是因為串流多了一層可能斷的東西，
  // 斷了要還有辦法拿到答案，不是只看到一句紅字。
  function askFallback(full, fresh){
    send.disabled = true;
    var wait = add("", role, "思考中…（串流不可用，改用一次回全部；一位約 40-60 秒）");
    fetch("/room/ask", {method:"POST", headers:{"Content-Type":"application/json"},
                        body: JSON.stringify({role: role, question: full,
                                              ticker: cur || "", fresh: !!fresh})})
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
    let dragging = false;
    grip.addEventListener("mousedown", function(e){
      dragging = true; grip.classList.add("on");
      document.body.style.userSelect = "none"; e.preventDefault();
    });
    window.addEventListener("mousemove", function(e){
      if (!dragging) return;
      const w = Math.min(640, Math.max(220, e.clientX - 10));
      room.style.setProperty("--lw", w + "px");
    });
    window.addEventListener("mouseup", function(){
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
    var saved = null;
    try { saved = localStorage.getItem("roomMode"); } catch(e) {}
    setMode(saved !== "stock");        // 預設列表
  })();

  apply();
  // ⚠️ 要選**篩選後看得到的**第一檔，不是 items[0]。
  //    預設是台股+4燈，items[0] 卻是美股 MA → 中間顯示一檔左邊看不到的股票。
  const first = items.find(function(e){ return !e.hidden; });
  if (first) { pick(first); }
})();
</script>
"""


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
            '<div class="room">'
            + left_html(items, asof)
            + '<main class="pane" id="mid"><div class="empty">左邊選一檔。</div></main>'
            + f'<div class="pane tablepane" id="tablepane">{table_html()}</div>'
            + right_html()
            + "</div>"
            '<div class="modebar"><button class="mb" id="mode-stock">個股</button>'
            '<button class="mb on" id="mode-list">列表</button></div>'
            '<button class="chatbtn" id="chatbtn">🏛️ 軍師</button>'
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
