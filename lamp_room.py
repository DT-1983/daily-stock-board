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
        gap = ("" if r["gap"] is None else
               f'距目標 <span class="{"up" if r["gap"] >= 0 else "dn"}">'
               f'{r["gap"]:+.1f}%</span>')
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
        '<aside class="pane left">'
        f'<div class="phead">報價組合<span class="dim">{len(items)} 檔 · {esc(asof)}</span></div>'
        '<input class="q" id="q" type="search" placeholder="搜代號／名稱／產業" autocomplete="off">'
        '<div class="chips">'
        '<span class="cl">排序</span>'
        '<button class="ch on" data-s="lit">燈數</button>'
        '<button class="ch" data-s="gap">距目標</button>'
        '<button class="ch" data-s="rr">風報比</button>'
        '<button class="ch" data-s="chg">漲跌</button>'
        '</div>'
        '<div class="chips">'
        '<span class="cl">市場</span>'
        '<button class="ch on" data-m="">全部</button>'
        '<button class="ch" data-m="us">美股</button>'
        '<button class="ch" data-m="tw">台股</button>'
        '<span class="cl">燈數</span>'
        '<button class="ch on" data-l="">全部</button>'
        '<button class="ch" data-l="4">4燈</button>'
        '<button class="ch" data-l="3">≥3燈</button>'
        '</div>'
        '<ul class="list" id="list">' + "".join(lis) + "</ul></aside>")


# ── 中欄 ──────────────────────────────────────────────────────────────
def detail_html(ticker):
    """中欄：關鍵數字 + 技術圖。**圖是現算的**（抓 2 年資料算指標，數秒）。

    ⚠️ 圖畫不出來不要讓整區掛掉——上面那排數字本身就有價值（同 lookup_page 的作法）。
    """
    from board_theme import esc
    items, _ = rows()
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
        + f'<span class="dim">{esc(r["sec"])}</span></div>')

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
        f'<div class="dc"><div class="k">輪動象限</div>'
        f'<div class="v">{QL.get(r["quad"], "—")}</div>'
        f'<div class="s">{esc(r["src"])}</div></div>',
    ])

    tech = ""
    try:
        import technical_indicators as ti
        import tw_symbol
        sym = (tw_symbol.resolve(r["tk"]) if r["tk"][:1].isdigit()
               else r["tk"].replace(".", "-"))
        tech = ti.build_html(sym, expanded=True) or ""
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
        '<button class="x" id="rclose">✕</button></div>'
        f'<div class="roles">{btns}</div>'
        '<div class="msgs" id="msgs">'
        '<div class="hint">選一檔股票，再挑一位軍師。<br>'
        '走本機 claude（Max plan 訂閱額度，<b>不另外計費</b>），'
        '一位大約 40-60 秒，軍議四位約 3-4 分鐘。</div></div>'
        '<div class="ask"><textarea id="qbox" rows="2" '
        'placeholder="想問什麼？留空＝這位軍師的預設問題（Ctrl+Enter 送出）"></textarea>'
        '<button class="send" id="send">送出</button></div>'
        '</aside>')


ROOM_CSS = """
:root{--gap:10px}
body{margin:0}
.room{display:grid;grid-template-columns:320px minmax(0,1fr) 0;gap:var(--gap);
 height:100vh;padding:var(--gap);box-sizing:border-box;background:var(--bg)}
.room.chat{grid-template-columns:320px minmax(0,1fr) 380px}
.pane{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 overflow:auto;min-height:0}
.room.chat .right{display:flex;flex-direction:column}
.phead{position:sticky;top:0;z-index:2;background:var(--surface);
 padding:10px 12px;border-bottom:1px solid var(--line);font-weight:700;font-size:13px;
 display:flex;align-items:center;gap:8px}
.phead .dim{margin-left:auto;font-weight:400;font-size:11px;color:var(--dim)}
.phead .x{margin-left:6px;background:none;border:0;color:var(--dim);cursor:pointer;
 font-size:14px}
.q{width:calc(100% - 24px);margin:10px 12px 6px;padding:7px 10px;font:inherit;
 font-size:12.5px;border-radius:8px;border:1px solid var(--line);
 background:transparent;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:5px;padding:0 12px 8px;align-items:center}
.cl{font-size:10.5px;color:var(--dim);margin-right:2px}
.ch{font:inherit;font-size:11.5px;padding:3px 9px;border-radius:999px;cursor:pointer;
 border:1px solid var(--line);background:transparent;color:var(--dim)}
.ch.on{background:var(--accent,#3b82f6);border-color:var(--accent,#3b82f6);
 color:#fff;font-weight:600}
.list{list-style:none;margin:0;padding:0 6px 10px}
.it{padding:8px 10px;border-radius:9px;cursor:pointer;border:1px solid transparent}
.it:hover{background:rgba(148,163,184,.07)}
.it.sel{border-color:var(--accent,#3b82f6);background:rgba(59,130,246,.10)}
.l1{display:flex;align-items:baseline;gap:6px;font-size:13px}
.l1 b{color:var(--ink)}
.l1 .nm{color:var(--dim);font-size:11px;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.l1 .px{margin-left:auto;font-variant-numeric:tabular-nums;font-size:12.5px;
 display:flex;gap:6px;white-space:nowrap}
.l2{display:flex;align-items:center;gap:8px;margin-top:3px;font-size:10.5px;
 color:var(--dim)}
.l2 .lamps{margin-left:auto;display:flex;gap:3px}
.lp{width:7px;height:7px;border-radius:50%;background:var(--line);display:inline-block}
.lp.on{background:#fbbf24}
.up{color:var(--up,#4ade80)}.dn{color:var(--down,#f87171)}
.dhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
 padding:12px 14px;border-bottom:1px solid var(--line)}
.dhead .tk{font-size:20px;font-weight:800;color:var(--ink)}
.dhead .nm{color:var(--dim);font-size:13px}
.dhead .px{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums}
.dhead .dim{margin-left:auto;font-size:11px;color:var(--dim)}
.dcards{display:grid;gap:1px;background:var(--line);
 grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:10px}
.dc{background:var(--surface);padding:9px 12px}
.dc .k{font-size:10px;color:var(--dim)}
.dc .v{font-size:16px;font-weight:700;margin-top:2px}
.dc .s{font-size:10.5px;color:var(--muted,#94a3b8);margin-top:3px;line-height:1.7}
.lrow{display:flex;align-items:center;gap:5px}
.empty,.warn{padding:22px 16px;color:var(--dim);font-size:13px}
.roles{display:flex;flex-wrap:wrap;gap:5px;padding:9px 12px;
 border-bottom:1px solid var(--line)}
.rb{font:inherit;font-size:11.5px;padding:4px 9px;border-radius:8px;cursor:pointer;
 border:1px solid var(--line);background:transparent;color:var(--dim);
 display:flex;flex-direction:column;align-items:center;line-height:1.35}
.rb span{font-size:9.5px;opacity:.75}
.rb.on{background:var(--accent,#3b82f6);border-color:var(--accent,#3b82f6);color:#fff}
.msgs{flex:1;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px}
.hint{font-size:11.5px;color:var(--dim);line-height:1.8}
.msg{border:1px solid var(--line);border-radius:10px;padding:9px 11px;font-size:12px;
 line-height:1.75;white-space:pre-wrap;word-break:break-word}
.msg.me{background:rgba(59,130,246,.10);border-color:rgba(59,130,246,.4)}
.msg .who{font-weight:700;font-size:11px;color:#F5B841;display:block;margin-bottom:3px}
.msg.err{border-color:rgba(248,113,113,.5);color:var(--down,#f87171)}
.ask{border-top:1px solid var(--line);padding:9px 12px;display:flex;gap:7px}
.ask textarea{flex:1;font:inherit;font-size:12px;padding:7px 9px;border-radius:8px;
 border:1px solid var(--line);background:transparent;color:var(--ink);resize:vertical}
.send{font:inherit;font-size:12px;padding:0 14px;border-radius:8px;cursor:pointer;
 border:0;background:var(--accent,#3b82f6);color:#fff;font-weight:600}
.send[disabled]{opacity:.5;cursor:default}
.chatbtn{position:fixed;right:14px;bottom:14px;z-index:9;font:inherit;font-size:13px;
 padding:9px 15px;border-radius:999px;border:0;cursor:pointer;font-weight:700;
 background:var(--accent,#3b82f6);color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.45)}
@media(max-width:900px){
 /* 手機：三欄疊成一欄，靠上面的分頁鈕切換——並排在 375px 上誰都看不清楚 */
 .room,.room.chat{grid-template-columns:1fr;height:auto}
 .pane{max-height:none}
 .room .pane.left{max-height:46vh}
 .room:not(.chat) .right{display:none}
}
"""

ROOM_JS = r"""
<script>
(function(){
  var F = {q:"", mkt:"", lit:"", sort:"lit"};
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
  items.forEach(function(el){ el.addEventListener("click", function(){ pick(el); }); });

  // ── 軍師欄 ──
  var room = document.querySelector(".room");
  var right = document.getElementById("right");
  var btn = document.getElementById("chatbtn");
  function toggle(on){
    room.classList.toggle("chat", on);
    right.hidden = !on;
    btn.textContent = on ? "✕ 收起軍師" : "🏛️ 軍師";
  }
  btn.addEventListener("click", function(){ toggle(!room.classList.contains("chat")); });
  document.getElementById("rclose").addEventListener("click", function(){ toggle(false); });

  var role = "軍議";
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
  function ask(){
    var q = qbox.value.trim();
    // 沒選股票也可以問仲達/陳壽（他們的材料是全局的），但要提醒。
    var full = (cur && q) ? (cur + " " + q) : (q || (cur || ""));
    add("me", null, (cur ? "【" + cur + "】" : "") + (q || "（用預設問題）"));
    qbox.value = "";
    send.disabled = true;
    var wait = add("", role, "思考中…（本機 claude，一位約 40-60 秒；軍議四位約 3-4 分鐘，"
                   + "跑完才會一起顯示）");
    fetch("/room/ask", {method:"POST", headers:{"Content-Type":"application/json"},
                        body: JSON.stringify({role: role, question: full})})
      .then(function(r){ return r.json(); })
      .then(function(j){
        wait.remove();
        if (j.error){ add("err", role, j.error); return; }
        (j.answers || []).forEach(function(a){ add("", a.name, a.text); });
      })
      .catch(function(e){ wait.remove(); add("err", role, "呼叫失敗：" + e); })
      .finally(function(){ send.disabled = false; });
  }
  send.addEventListener("click", ask);
  qbox.addEventListener("keydown", function(e){
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { ask(); }
  });

  apply();
  if (items.length) { pick(items[0]); }
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
            + "<style>" + BASE_CSS + ti_css + ROOM_CSS + "</style></head><body>"
            '<div class="room">'
            + left_html(items, asof)
            + '<main class="pane" id="mid"><div class="empty">左邊選一檔。</div></main>'
            + right_html()
            + "</div>"
            '<button class="chatbtn" id="chatbtn">🏛️ 軍師</button>'
            + ROOM_JS + "</body></html>")


def ask(role, question):
    """呼叫軍師。回 [{name, text}]。**不重寫任何判斷邏輯**，直接用 war_room。"""
    import war_room
    if role == "軍議":
        out, prior = [], []
        for r in war_room.council_roles(question):
            t = war_room.ask(r, question, prior=prior)
            prior.append((war_room.ROLES[r]["name"], t))
            out.append({"name": war_room.ROLES[r]["name"], "text": t})
        return out
    if role not in war_room.ROLES:
        return [{"name": role, "text": f"沒有這位軍師（可用：{'、'.join(war_room.ROLES)}）"}]
    return [{"name": war_room.ROLES[role]["name"],
             "text": war_room.ask(role, question)}]


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
