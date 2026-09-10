# -*- coding: utf-8 -*-
"""個股整合報告（2026-09-04，Leo：「調用研究員、投資長幫我解讀報告，跟我們現有的資訊產出一份報告」）。

把**券商報告怎麼說**跟**我們自己的系統怎麼算**擺在同一頁，重點是那些
「報告裡沒有、只有我們算得出來」的交叉檢驗：

| 層 | 來源 | 回答什麼問題 |
|---|---|---|
| 券商報告 | `advisor_reports` | 憑什麼給這個目標價（倍數 × 哪一年的 EPS）|
| 估值前提 | `advisor_reports.implied_multiple` | 市場現在給幾倍、離報告假設多遠 |
| 預估前提檢查 | `state/base_rate.json` | 分析師共識隱含的要求，對照這檔**自己的歷史分布** |
| 毛利率位階 | `state/margin_profile.json` | 獲利能力在自身 24 季裡的位階 |
| 燈號 | `state/combo_result.json` | 技術面四燈與風報比 |
| 投資長 | `state/advisor_verdicts.jsonl` | 兩個獨立角度的判斷與失效條件 |

⚠️ 全部讀既有 state 檔，**不重算、不呼叫 AI、不花錢**。要更新內容請先跑對應的
產生器（`advisor_reports.py parse`／`investment_chief.py`／每日排程）。

⚠️ 樣式走 `board_theme`：header() + BASE_CSS、不寫死中性色碼、跨網域用 nav_abs()
（2026-09-03 Leo 連兩次指出風格不一致後定的四條硬規則）。

用法:
    python stock_brief.py 2454
    python stock_brief.py 2454 -o out.html
    python stock_brief.py --all       # 重產所有有券商報告的個股（每日 08:45 排程）
"""
import io
import os
import re
import sys
import json
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2026-09-05 資料夾整理：路徑一律走 obis_paths，不再各自寫死。
from obis_paths import BRIEFS as OBIS


def _load(p, d=None):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _norm(tk):
    return re.sub(r"\.(TW|TWO)$", "", str(tk).upper()).replace(".", "-")


def gather(ticker):
    """把所有既有資料湊成一份 dict。缺的就是 None——**不補、不猜**。"""
    t = _norm(ticker)
    out = {"ticker": t}

    cr = _load("state/combo_result.json", {}) or {}
    rows = cr.get("rows") or cr.get("items") or []
    out["lamp"] = next((r for r in rows if _norm(r.get("ticker", "")) == t), None)

    mp = _load("state/margin_profile.json", {}) or {}
    out["margin"] = next((v.get("data") for k, v in mp.items()
                          if _norm(k) == t and isinstance(v, dict)), None)

    br = _load("state/base_rate.json", {}) or {}
    out["base_rate"] = next((c for c in (br.get("checks") or [])
                             if _norm(c.get("ticker", "")) == t), None)

    reg = _load("state/thesis_conditions.json", {}) or {}
    out["thesis"] = next((v for k, v in reg.items() if _norm(k) == t), None)

    st = _load("state/advisor_reports.json", {}) or {}
    out["reports"] = sorted(
        [r for r in st.values()
         if not r.get("_notreport") and _norm(r.get("ticker", "")) == t],
        key=lambda r: str(r.get("date")), reverse=True)

    tc = _load("state/target_changes.json", {}) or {}
    ch = []
    for v in tc.values():
        ch += [r for r in v.get("rows", []) if _norm(r.get("ticker", "")) == t]
    out["changes"] = sorted(ch, key=lambda r: str(r.get("date")), reverse=True)

    v = None
    p = "state/advisor_verdicts.jsonl"
    if os.path.exists(p):
        for ln in io.open(p, encoding="utf-8"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if _norm(d.get("ticker", "")) == t:
                v = d
    out["verdict"] = v
    return out


def _price(d):
    lamp = d.get("lamp") or {}
    if lamp.get("price"):
        return float(lamp["price"])
    try:
        import price_store, tw_symbol
        sym = (tw_symbol.resolve(d["ticker"])
               if re.match(r"^\d{4,6}[A-Z]?$", d["ticker"]) else d["ticker"])
        s = price_store.get_closes([sym], period="1y").get(sym)
        if s is not None and not s.empty:
            return float(s.dropna().iloc[-1])
    except Exception:                                       # noqa: BLE001
        pass
    return None



# 投資長 reasoning 的分段標記。它寫的時候本來就有分「事實／推論／資料缺口」，
# 但原樣輸出會變成一整片文字牆（2026-09-04 Leo：「段落不清楚，幫我重排一下」）。
# 兩種寫法都會出現：`【事實】` 與 `事實：`。
_MARKS = [("事實", "f"), ("推論/假設", "i"), ("推論", "i"), ("假設", "i"),
          ("提醒", "w"), ("資料缺口", "w"), ("綜合以上", "s"), ("結論", "s")]
_MARK_LABEL = {"f": "事實", "i": "推論", "w": "注意", "s": "結論"}


def fmt_reasoning(txt, esc):
    """把一整段 reasoning 拆成有標籤的段落。

    做法：找出所有標記出現的位置切段，每段前面掛一個彩色標籤。
    找不到任何標記就退回「照句號斷行」——**不硬套格式**，
    寧可維持原樣也不要切錯句子。
    """
    import re as _re
    t = (txt or "").strip()
    if not t:
        return ""
    pat = "|".join(_re.escape(m) for m, _ in _MARKS)
    hits = list(_re.finditer(rf"(?:【({pat})】|({pat})[：:])", t))
    if not hits:
        # 沒有標記：每 2 句斷一段，至少讓它不是一整片
        sents = [x for x in _re.split(r"(?<=。)", t) if x.strip()]
        return "".join(f'<p class="rz">{esc(x.strip())}</p>' for x in sents)
    out = []
    if hits[0].start() > 0:
        out.append(f'<p class="rz">{esc(t[:hits[0].start()].strip())}</p>')
    for i, m in enumerate(hits):
        name = m.group(1) or m.group(2)
        kind = next(k for lbl, k in _MARKS if lbl == name)
        end = hits[i + 1].start() if i + 1 < len(hits) else len(t)
        seg = t[m.end():end].strip().lstrip("：:").strip()
        if not seg:
            continue
        out.append(f'<p class="rz {kind}"><span class="rzl">{_MARK_LABEL[kind]}</span>'
                   f'{esc(seg)}</p>')
    return "".join(out)


CSS = """
.sb{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px;margin:12px 0}
.sb h2{font-size:15px;font-weight:700;color:#F5B841;margin-bottom:4px}
.sb .sub{font-size:11.5px;color:var(--dim);margin-bottom:9px;line-height:1.6}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:8px;margin:8px 0}
.kv .c{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 10px}
.kv .k{font-size:10px;color:var(--dim);letter-spacing:.3px}
.kv .v{font-size:15px;font-weight:700;margin-top:3px;
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.kv .v.zh{font-family:inherit;font-size:14px}
.kv .s{font-size:10.5px;color:var(--muted);margin-top:2px;line-height:1.5}
.txt{font-size:13px;color:var(--muted);line-height:1.85;margin-top:8px}
/* 投資長 reasoning 分段（2026-09-04）：原本一整片牆，改成每個「事實/推論/注意」
   各自一段、左邊一條色帶。色帶顏色只表示**段落性質**不是多空訊號。 */
.rz{font-size:13px;line-height:1.9;color:var(--muted);margin:7px 0 0;
 padding:7px 0 7px 11px;border-left:2px solid var(--line2)}
.rz .rzl{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.5px;
 padding:1px 7px;border-radius:5px;margin-right:8px;vertical-align:1px;
 background:var(--line);color:var(--muted)}
.rz.f{border-left-color:#475569}
.rz.f .rzl{background:#334155;color:#CBD5E1}
.rz.i{border-left-color:var(--accent)}
.rz.i .rzl{background:#1E3A5F;color:#BFDBFE}
.rz.w{border-left-color:var(--warn)}
.rz.w .rzl{background:#3A2E10;color:#FCD34D}
.rz.s{border-left-color:var(--up)}
.rz.s .rzl{background:#14311F;color:#86EFAC}
.txt b{color:#CBD5E1}
.ang{border-left:3px solid var(--line);padding-left:12px;margin:12px 0}
.ang.buy{border-left-color:var(--up)}
.ang.sell{border-left-color:var(--down)}
.ang .t{font-size:14px;font-weight:700}
.ang .b{font-size:12.5px;color:#93C5FD;margin:3px 0 6px}
.rp{border-top:1px solid var(--line);padding:9px 0;font-size:12.5px;color:var(--muted);line-height:1.7}
.rp b{color:var(--ink)}
.warn{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--warn);
 border-radius:10px;padding:12px 15px;margin:12px 0;font-size:13px;line-height:1.85;color:var(--muted)}
.warn b{color:#FCD34D}
.pos{color:var(--up)}.neg{color:var(--down)}
/* 摘要層 */
.sm{font-size:13.5px;line-height:1.95;color:#CBD5E1;margin:2px 0 0;padding-left:18px}
.sm li{margin:5px 0}
.kp{font-size:12.5px;line-height:1.8;color:var(--muted);padding:7px 0;
 border-top:1px solid var(--line2)}
.kp .tag{display:inline-block;font-size:10px;font-weight:700;padding:1px 7px;
 border-radius:5px;margin-right:8px;vertical-align:1px}
.kp .tag.nc{background:#1E3A5F;color:#BFDBFE}
.kp .tag.cl{background:#334155;color:#CBD5E1}
.kp .tag.cv{background:#3A2E10;color:#FCD34D}
/* 查核表 */
.fc{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.fc th{text-align:left;padding:7px 8px;color:var(--dim);font-weight:600;font-size:11.5px;
 border-bottom:1px solid var(--line);white-space:nowrap}
.fc td{padding:9px 8px;border-bottom:1px solid var(--line2);vertical-align:top;
 line-height:1.75;color:var(--muted)}
.fc td.k{white-space:nowrap;color:var(--ink);font-weight:600}
.fc td.v{white-space:nowrap;font-weight:700}
.fc .ok{color:var(--up)}.fc .warn{color:var(--warn)}.fc .wait{color:var(--dim)}
.fc .note{display:block;margin-top:4px;color:var(--dim);font-size:11.5px;line-height:1.7}
@media(max-width:700px){.fc td.k,.fc td.v{white-space:normal}}
"""


def _pros_cons(d, px, fc_rows):
    """回 (站得住的, 要注意的)。**兩邊都是程式判斷**，一條都不是 AI 寫的。

    ⚠️ 只列**這一檔真的成立**的，沒有就留白。湊數的條目會讓人不再讀這一段，
    然後真的有事的那天也一起跳過（同財報懶人包利多/風險的作法）。
    """
    L = d.get("lamp") or {}
    rr, gap = L.get("rr"), L.get("gap_pct")
    pros, cons = [], []

    # ── 站得住的 ──
    if L.get("combo") and rr is not None and rr >= 1:
        pros.append(f"⭐ 打點成立：亮 {L.get('lit')}/4 燈且風報比 {rr:,.1f}（≥1）")
    elif L.get("lit") is not None and L["lit"] >= 3:
        pros.append(f"技術面共振：{L['lit']}/4 燈")
    if L.get("bull") and gap is not None and gap >= 5:
        pros.append(f"距 SuperTrend 停損線還有 {gap:.1f}%，不是貼著停損進場")
    rs_s, rs_l = L.get("rs_short"), L.get("rs_long")
    if rs_s is not None and rs_l is not None and rs_s > 0 and rs_l > 0:
        pros.append(f"相對強度短長皆正（RS60 {rs_s:+.1f}%／RS240 {rs_l:+.1f}%）")
    b = d.get("base_rate") or {}
    tier = ((b.get("requirement") or {}).get("tier")) if isinstance(b, dict) else None
    if tier == "normal":
        pros.append("預估前提落在這檔自己過去做得到的範圍內，有容錯空間")
    m = d.get("margin") or {}
    if isinstance(m, dict) and m.get("pct_rank") is not None and m["pct_rank"] <= 40:
        pros.append(f"毛利率在自身歷史第 {m['pct_rank']:.0f} 百分位，還有往上的空間")
    n_ok = sum(1 for r in (fc_rows or []) if r.get("verdict") == "ok")
    if n_ok:
        pros.append(f"查核有 {n_ok} 條對得上（報告的說法跟我們算的一致）")

    # ── 要注意的 ──
    if rr is not None and rr < 0:
        cons.append("現價已高於市場共識目標——燈還亮，但上檔空間沒了")
    if L.get("bull") and gap is not None and gap < 5:
        cons.append(f"距停損線只剩 {gap:.1f}%，風報比的分母很小、數字會被放大")
    if L.get("bull") is False:
        cons.append("SuperTrend 空方——這條線現在是壓力不是停損，出場規則已觸發過")
    n_warn = sum(1 for r in (fc_rows or []) if r.get("verdict") == "warn")
    if n_warn:
        cons.append(f"查核抓到 {n_warn} 條落差：報告的假設跟這檔自己的歷史對不上")
    if tier in ("unprecedented", "rare"):
        cons.append("預估前提要求貼在或超出這檔自身歷史紀錄——不是做不到，是沒有容錯空間")
    for r in (d.get("reports") or [])[:3]:
        try:
            import broker_credibility as _bc
            note = _bc.note_for(r.get("broker"))
        except Exception:                                   # noqa: BLE001
            note = None
        # ⚠️ note_for() 回的是 **dict** 不是字串（今天 cell_fired 同一型的坑：
        #    同名不同型別而且不會報錯）。要挑欄位出來用。
        if note:
            cons.append(f"{r.get('broker')} {note.get('tag') or '有已知偏誤'}"
                        "——看它的目標價時記得折價")
            break
    if isinstance(m, dict) and m.get("pct_rank") is not None and m["pct_rank"] >= 90:
        cons.append(f"毛利率在自身歷史第 {m['pct_rank']:.0f} 百分位，"
                    "預估要靠它再擴張就要小心")
    if not (d.get("reports") or []):
        cons.append("目前沒有券商報告，下面的目標價是市場共識（多家平均）不是單一家的推導")
    return pros, cons


def _cp_css():
    """產業鏈定位的樣式。⚠️ 重用元件要**連樣式一起帶**——
    只搬 markup 是搬了一半（今天在戰情室已經踩過一次）。"""
    try:
        import chain_positioning as CP
        return CP.CSS
    except Exception:                                       # noqa: BLE001
        return ""


def _sector_html(d, prof=None):
    """類股定位：這檔屬於哪個類股、那個類股在輪動圖的哪一象限、
    同類股裡它排第幾。

    ⚠️ 為什麼要有這一層：產業鏈定位只涵蓋我們自己定義的 9 條鏈，
    實測 14 檔整合報告裡只有 2 檔在鏈裡。這一層**掃描母體裡每一檔都有**。
    ⚠️ 象限四色 import 自輪動頁，跟看板同色，不另外定義一組。
    """
    from board_theme import esc
    L = d.get("lamp") or {}
    sec = L.get("sector_zh") or ""
    if not sec:
        # 🔴 不在燈號掃描母體裡就沒有類股／象限（實測 14 檔報告有 6 檔是這樣）。
        # 這時候至少給 yfinance 的產業分類，並**明講為什麼沒有同類股對照**——
        # 整段消失的話，讀的人不知道是「沒有這個資訊」還是「我們漏了」。
        if not (prof and (prof.get("sector") or prof.get("industry"))):
            return ""
        return ('<div class="sb"><h2>類股定位 <span class="en">Sector Position</span></h2>'
                f'<div class="sub">{esc(prof.get("sector") or "—")}／'
                f'{esc(prof.get("industry") or "—")}<span class="qsec2">'
                'yfinance 分類</span></div>'
                '<div class="posnote">這一檔<b>不在每日燈號掃描的母體裡</b>，'
                '所以沒有輪動象限，也沒有同類股的燈數／RS 對照——'
                '不是漏掉，是我們沒有掃它。要看的話用查股頁即時算一次。</div></div>')
    try:
        from combo_html import QCOL, QLAB
    except Exception:                                       # noqa: BLE001
        QCOL = {"leading": "#3987e5", "improving": "#2fbf71",
                "lagging": "#e5484d", "weakening": "#eda100"}
        QLAB = {"leading": "領先", "improving": "改善",
                "lagging": "落後", "weakening": "弱化"}
    q = (L.get("quad") or {})
    q60 = q.get("60")
    qh = (f'<span class="qb2" style="background:{QCOL[q60]}">{QLAB[q60]}</span>'
          if q60 in QLAB else '<span class="dimv">未分類</span>')
    qtip = ("　".join(f'{n} 日 {QLAB.get(q.get(n), "—")}' for n in ("20", "60", "120"))
            if q60 in QLAB else "")

    # 同類股對照：從同一份 combo_result 拿，數字跟燈號頁一致
    rows = (_load("state/combo_result.json", {}) or {}).get("rows") or []
    peers = [r for r in rows if (r.get("sector_zh") or "") == sec]
    me = _norm(d["ticker"])
    peers.sort(key=lambda r: ((r.get("lit") or 0), (r.get("rs_short") or -999)),
               reverse=True)
    rank = next((i + 1 for i, r in enumerate(peers)
                 if _norm(r.get("ticker", "")) == me), None)
    # 🔴 **自己一定要在圖上**。原本只取前 12 名，2454 排第 18 就整個不見了——
    # 一張「你在哪裡」的圖沒有你，等於沒回答問題。
    show = peers[:12]
    if rank and rank > 12:
        me_row = next((r for r in peers if _norm(r.get("ticker", "")) == me), None)
        if me_row:
            show = peers[:11] + [me_row]
    cells = []
    for r in show:
        mine = _norm(r.get("ticker", "")) == me
        rs = r.get("rs_short")
        rs_s = (f'<span class="{"pos" if rs > 0 else "neg"}">{rs:+.1f}%</span>'
                if rs is not None else "—")
        cells.append(f'<div class="peer2{" focus" if mine else ""}">'
                     f'<div class="pt2">{esc((r.get("name") or r.get("ticker"))[:10])}'
                     f'<span class="pc2">{esc(r.get("ticker"))}</span></div>'
                     f'<div class="pv2">{r.get("lit", 0)}/4 燈　RS {rs_s}</div></div>')
    more = (f'<div class="posnote">同類股共 {len(peers)} 檔，這裡列燈數／RS 最高的 '
            f'{len(show) - (1 if rank and rank > 12 else 0)} 檔'
            + (f'，加上本檔（第 {rank} 名）' if rank and rank > 12 else "")
            + '</div>' if len(peers) > len(show) else "")
    rk = (f'　·　同類股 {len(peers)} 檔中燈數／RS 排第 <b>{rank}</b>'
          if rank and len(peers) > 1 else "")

    return ('<div class="sb"><h2>類股定位 <span class="en">Sector Position</span></h2>'
            f'<div class="sub">{esc(sec)}　{qh}'
            + (f'<span class="qsec2">{esc(qtip)}</span>' if qtip else "")
            + f'{rk}</div>'
            '<div class="posnote">類股取自 TradingView 分類、象限取自產業輪動圖最新快照'
            '（顯示 60 日）；同類股的燈數與 RS 來自同一份每日掃描，'
            '<b>跟進出燈號頁是同一組數字</b>。</div>'
            f'<div class="segcells">{"".join(cells)}</div>{more}</div>')


def _chain_html(d):
    """產業鏈定位——直接用財報懶人包那個元件，不重寫一套。

    ⚠️ 查不到鏈就回空字串（大部分個股都不在我們定義的 9 條鏈裡），
    這時候只有上面的類股定位。**不要為了讓版面有東西而硬湊一個鏈。**
    """
    try:
        import chain_positioning as CP
        return CP.build_html(d["ticker"]) or ""
    except Exception as e:                                  # noqa: BLE001
        print(f"  [warn] 產業鏈定位失敗：{str(e)[:60]}")
        return ""


def _intro_html(d, name, px, fc_rows=None, biz="", prof=None):
    """報告最上面那一段。版型抄財報懶人包：大數字磚＋中英雙標題＋兩欄利多風險。"""
    from board_theme import esc, esc_b
    L = d.get("lamp") or {}

    # ① 這家在做什麼（唯一一段 AI 寫的；查不到就整段不出現，不要編）
    txt = biz
    sect = ""
    if prof and (prof.get("sector") or prof.get("industry")):
        sect = f'{prof.get("sector") or "—"}／{prof.get("industry") or "—"}'

    # ② 大數字磚——**全部是既有欄位，程式填**（能算的不要讓 AI 用講的）
    def tile(lab, val, sub="", cls=""):
        return (f'<div class="bk"><div class="lb">{esc(lab)}</div>'
                f'<div class="vl {cls}">{val}</div>'
                + (f'<div class="sb2">{esc(sub)}</div>' if sub else "") + "</div>")
    tiles = []
    if L.get("lit") is not None:
        tiles.append(tile("LAMPS 燈號", f'{L["lit"]}/4',
                          "⭐ 打點成立" if (L.get("combo") and (L.get("rr") or 0) >= 1)
                          else ("COMBO 成立" if L.get("combo") else "未達 COMBO")))
    if L.get("bull") is not None:
        tiles.append(tile("TREND 趨勢", "🔴 多方" if L["bull"] else "🟢 空方",
                          (f'停損線 {L["st_line"]:,.1f}' if L.get("st_line") and L["bull"]
                           else (f'站上 {L["st_line"]:,.1f} 才翻多' if L.get("st_line") else ""))))
    if L.get("rr") is not None:
        tiles.append(tile("R:R 風報比", f'{L["rr"]:,.1f}',
                          "目標與停損的比值",
                          "pos" if L["rr"] >= 1 else ("neg" if L["rr"] < 0 else "")))
    if L.get("target") and px:
        up = (L["target"] / px - 1) * 100
        tiles.append(tile("UPSIDE 距共識目標", f'{up:+.1f}%',
                          f'共識 {L["target"]:,.0f}', "pos" if up > 0 else "neg"))
    if L.get("rs_short") is not None:
        tiles.append(tile("RS 相對強度", f'{L["rs_short"]:+.1f}%',
                          (f'長線 {L["rs_long"]:+.1f}%' if L.get("rs_long") is not None else ""),
                          "pos" if L["rs_short"] > 0 else "neg"))
    n_rep = len(d.get("reports") or [])
    tiles.append(tile("REPORTS 券商報告", f'{n_rep}',
                      (d["reports"][0].get("broker") if n_rep else "尚無") or ""))

    # ③ 站得住的 / 要注意的（兩欄並排，同財報懶人包的利多/風險）
    pros, cons = _pros_cons(d, px, fc_rows)
    def lst(title, items, cls, mark):
        if not items:
            return (f'<div class="col {cls}"><h3>{title}</h3>'
                    '<div class="none">這一檔目前沒有。</div></div>')
        li = "".join(f'<li><span class="mk">{mark}</span>{esc_b(x)}</li>' for x in items)
        return f'<div class="col {cls}"><h3>{title}</h3><ul>{li}</ul></div>'

    return ('<div class="sb intro">'
            '<h2>這是什麼 <span class="en">What It Does</span></h2>'
            + (f'<div class="ibiz">{esc(txt)}</div>' if txt else
               '<div class="sub">（yfinance 查不到這檔的業務說明——'
               '不編一段給你，下面的數字照常）</div>')
            + (f'<div class="isec">{esc(sect)}</div>' if sect else "")
            + f'<div class="bks">{"".join(tiles)}</div>'
            + '<div class="two2">'
            + lst("站得住的 <span class=\'en\'>Supports</span>", pros, "ok", "✓")
            + lst("要注意的 <span class=\'en\'>Watch</span>", cons, "warn", "✕")
            + "</div>"
            + '<div class="sub">業務描述由本機 claude 從 yfinance 的公開說明濃縮，'
              '<b>沒有給它任何數字</b>；上面的磚與兩欄清單全部是程式算的。</div>'
            '</div>')


CATALYSTS_PATH = "state/stock_catalysts.json"

# 2026-09-10 Leo 丟了一份 IG 帳號（histockhero）講大立光 CPO/FAU 技術布局的
# 圖文，要求「補到個股財報分析裡，如果還沒有請自己建立」。
# ⚠️ 內容是別人帳號的圖文創作，不能整段照抄（版權）——summary 是我自己
# 濃縮改寫過的文字，不是原貼文的逐字翻譯；技術圖也是重畫，不是截圖。
# ⭐ 這類「社群消息面」內容體質上跟上面 biz 簡介（yfinance 官方摘要）不一樣：
# 沒有公司或分析師背書，所以獨立成一個區塊、掛明顯的來源警示，不混進
# 「這是什麼」那段裡讓人誤以為是查證過的資料。
_CATALYST_SVG = {
    # 對準示意：光纖9μm要塞進晶片波導<1μm，對準才進得去、沒對準整顆報廢。
    "align": '''<svg viewBox="0 0 640 190" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:560px">
<style>.tl{font:600 12px 'Noto Sans TC',sans-serif;fill:#9DB0C8}.tb{font:700 13px 'Noto Sans TC',sans-serif;fill:#DCE7F5}.tn{font:700 12px 'IBM Plex Mono',monospace}</style>
<text x="20" y="24" class="tl" fill="#22C55E">✓ 對準</text>
<rect x="20" y="32" width="110" height="26" rx="4" fill="#0E1B2B" stroke="#16304A"/>
<text x="75" y="49" class="tn" fill="#DCE7F5" text-anchor="middle">光纖 9μm</text>
<path d="M130 45 L340 45" stroke="#22D3EE" stroke-width="2"/>
<polygon points="332,38 346,45 332,52" fill="#22D3EE"/>
<rect x="340" y="32" width="110" height="26" rx="4" fill="#0E2417" stroke="#166534"/>
<text x="395" y="49" class="tn" fill="#86EFAC" text-anchor="middle">晶片 &lt;1μm</text>
<text x="460" y="49" class="tl" fill="#86EFAC">→ 光順利進去</text>
<text x="20" y="112" class="tl" fill="#EF4444">✕ 對不準</text>
<rect x="20" y="120" width="110" height="26" rx="4" fill="#0E1B2B" stroke="#16304A"/>
<text x="75" y="137" class="tn" fill="#DCE7F5" text-anchor="middle">光纖 9μm</text>
<path d="M130 133 L330 160" stroke="#F87171" stroke-width="2" stroke-dasharray="3,3"/>
<polygon points="318,155 334,159 322,167" fill="#F87171"/>
<rect x="340" y="120" width="110" height="26" rx="4" fill="#2E1418" stroke="#7F1D1D"/>
<text x="395" y="137" class="tn" fill="#FCA5A5" text-anchor="middle">晶片 &lt;1μm</text>
<text x="460" y="137" class="tl" fill="#FCA5A5">→ 光漏掉，整顆報廢</text>
<text x="320" y="182" class="tl" text-anchor="middle" fill="#5B6E8A">FAU＝把 9μm 粗的光纖，精準對準塞進不到 1μm 的晶片入口</text>
</svg>''',
    # 三步驟：FA排整齊→PMLA放大轉向→焊到晶片，三步合起來才叫FAU。
    "fau_steps": '''<svg viewBox="0 0 640 175" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:560px">
<style>.tl{font:600 11px 'Noto Sans TC',sans-serif;fill:#9DB0C8}.tb{font:700 13px 'Noto Sans TC',sans-serif;fill:#DCE7F5}</style>
<rect x="20" y="10" width="178" height="92" rx="8" fill="#0C1524" stroke="#16304A"/>
<text x="109" y="32" class="tb" text-anchor="middle" fill="#F5B841">① FA 光纖排整齊</text>
<text x="109" y="54" class="tl" text-anchor="middle">V 槽卡住多根光纖</text>
<text x="109" y="72" class="tl" text-anchor="middle">鎖成固定間距的一把尺</text>
<polygon points="200,50 222,56 200,62" fill="#5B6E8A"/>
<rect x="231" y="10" width="178" height="92" rx="8" fill="#0C1524" stroke="#16304A"/>
<text x="320" y="32" class="tb" text-anchor="middle" fill="#22D3EE">② PMLA 稜鏡微透鏡</text>
<text x="320" y="54" class="tl" text-anchor="middle">把細光束放大、轉向 90°</text>
<text x="320" y="72" class="tl" text-anchor="middle">容差跟著放寬</text>
<polygon points="411,50 433,56 411,62" fill="#5B6E8A"/>
<rect x="442" y="10" width="178" height="92" rx="8" fill="#2E1418" stroke="#7F1D1D"/>
<text x="531" y="32" class="tb" text-anchor="middle" fill="#FCA5A5">③ 焊到晶片</text>
<text x="531" y="54" class="tl" text-anchor="middle" fill="#FCA5A5">要撐過 260°C 回焊爐</text>
<text x="531" y="72" class="tl" text-anchor="middle" fill="#FCA5A5">最難、最貴的一步</text>
<rect x="20" y="118" width="600" height="42" rx="8" fill="#0E1B2B"/>
<text x="320" y="137" class="tb" text-anchor="middle">① ＋ ② ＋ ③ ＝ FAU（光纖陣列組件）</text>
<text x="320" y="153" class="tl" text-anchor="middle" fill="#5B6E8A">前兩步是零件（大立光賣）、第三步是模組（上詮等廠焊上去）</text>
</svg>''',
    # CPO三條件同時收緊（通道數/容差/耐熱）＋良率逐根相乘算式。
    "cpo_conditions": '''<svg viewBox="0 0 640 240" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:560px">
<style>.tl{font:600 12px 'Noto Sans TC',sans-serif;fill:#9DB0C8}.tb{font:700 13px 'Noto Sans TC',sans-serif;fill:#DCE7F5}.tn{font:700 12px 'IBM Plex Mono',monospace}</style>
<text x="20" y="24" class="tb">通道數</text>
<rect x="140" y="10" width="90" height="26" rx="4" fill="#0E1B2B" stroke="#16304A"/>
<text x="185" y="27" class="tn" fill="#9DB0C8" text-anchor="middle">8~16 根</text>
<polygon points="240,16 256,23 240,30" fill="#5B6E8A"/>
<rect x="262" y="10" width="140" height="26" rx="4" fill="#3A1A12" stroke="#7F1D1D"/>
<text x="332" y="27" class="tn" fill="#FCA5A5" text-anchor="middle">64~128 根</text>
<text x="412" y="27" class="tl" fill="#5B6E8A">暴增</text>
<text x="20" y="79" class="tb">對準容差</text>
<rect x="140" y="65" width="90" height="26" rx="4" fill="#0E1B2B" stroke="#16304A"/>
<text x="185" y="82" class="tn" fill="#9DB0C8" text-anchor="middle">1μm</text>
<polygon points="240,71 256,78 240,85" fill="#5B6E8A"/>
<rect x="262" y="65" width="140" height="26" rx="4" fill="#3A1A12" stroke="#7F1D1D"/>
<text x="332" y="82" class="tn" fill="#FCA5A5" text-anchor="middle">0.3μm</text>
<text x="412" y="82" class="tl" fill="#5B6E8A">收緊 3 倍</text>
<text x="20" y="134" class="tb">耐熱</text>
<rect x="140" y="120" width="90" height="26" rx="4" fill="#0E1B2B" stroke="#16304A"/>
<text x="185" y="137" class="tn" fill="#9DB0C8" text-anchor="middle">85°C</text>
<polygon points="240,126 256,133 240,140" fill="#5B6E8A"/>
<rect x="262" y="120" width="140" height="26" rx="4" fill="#3A1A12" stroke="#7F1D1D"/>
<text x="332" y="137" class="tn" fill="#FCA5A5" text-anchor="middle">260°C</text>
<text x="412" y="137" class="tl" fill="#5B6E8A">回焊爐等級</text>
<rect x="20" y="166" width="600" height="60" rx="8" fill="#0E1B2B"/>
<text x="320" y="188" class="tl" text-anchor="middle" fill="#DCE7F5">良率逐根相乘：80 根每根 99% 合格 → 整條只剩 <tspan fill="#FCA5A5" font-weight="700">45%</tspan></text>
<text x="320" y="210" class="tl" text-anchor="middle" fill="#DCE7F5">每根拉到 99.9% → 整條才有 <tspan fill="#86EFAC" font-weight="700">92%</tspan></text>
</svg>''',
    # 時程：7月送樣→2027年中量產（原貼文用詞「最快」）。
    "timeline": '''<svg viewBox="0 0 640 110" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:560px">
<style>.tl{font:600 12px 'Noto Sans TC',sans-serif;fill:#9DB0C8}.tb{font:700 13px 'Noto Sans TC',sans-serif;fill:#DCE7F5}</style>
<line x1="60" y1="55" x2="580" y2="55" stroke="#16304A" stroke-width="2"/>
<polygon points="580,49 596,55 580,61" fill="#16304A"/>
<circle cx="140" cy="55" r="7" fill="#22D3EE"/>
<text x="140" y="35" class="tb" text-anchor="middle">7 月送樣</text>
<text x="140" y="80" class="tl" text-anchor="middle">技術驗證階段</text>
<circle cx="480" cy="55" r="7" fill="#F5B841"/>
<text x="480" y="35" class="tb" text-anchor="middle" fill="#F5B841">2027 年中量產</text>
<text x="480" y="80" class="tl" text-anchor="middle">原貼文用詞：最快</text>
</svg>''',
    # 容差堆疊示意：業界拼料誤差會疊加超標，大立光用量測補償壓到門檻內。
    "tolerance": '''<svg viewBox="0 0 640 150" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:560px">
<style>.tl{font:600 12px 'Noto Sans TC',sans-serif;fill:#9DB0C8}.tn{font:700 13px 'IBM Plex Mono',monospace}</style>
<line x1="210" y1="10" x2="210" y2="140" stroke="#FFB627" stroke-width="1.5" stroke-dasharray="4,3"/>
<text x="216" y="20" class="tl" fill="#FFB627">客戶要求 &lt;0.3μm</text>
<text x="20" y="45" class="tl" fill="#DCE7F5">業界：買最好的零件相拼</text>
<rect x="20" y="55" width="140" height="22" rx="3" fill="#2E1418" stroke="#7F1D1D"/>
<text x="90" y="70" class="tn" fill="#FCA5A5" text-anchor="middle">V槽 0.5μm</text>
<rect x="160" y="55" width="196" height="22" rx="3" fill="#3A1A12" stroke="#7F1D1D"/>
<text x="258" y="70" class="tn" fill="#FCA5A5" text-anchor="middle">+ 光纖 0.7μm = &gt;1μm ✕</text>
<text x="20" y="105" class="tl" fill="#DCE7F5">大立光：一般零件＋自研機台量測補償</text>
<rect x="20" y="115" width="95" height="22" rx="3" fill="#0E2417" stroke="#166534"/>
<text x="67" y="130" class="tn" fill="#86EFAC" text-anchor="middle">&lt;0.3μm ✓</text>
<text x="125" y="130" class="tl" fill="#5B6E8A">業界最佳約 0.5～0.8μm 做不到這裡</text>
</svg>''',
    # 供應鏈位置：零件(大立光) vs 模組(上詮)，上下游不是對手。
    "supply_chain": '''<svg viewBox="0 0 640 210" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:560px">
<style>.tl{font:600 12px 'Noto Sans TC',sans-serif;fill:#9DB0C8}.tb{font:700 13px 'Noto Sans TC',sans-serif;fill:#DCE7F5}
.tk{font:700 11px 'IBM Plex Mono',monospace;fill:#22D3EE}</style>
<rect x="20" y="10" width="600" height="50" rx="8" fill="#0C1524" stroke="#16304A"/>
<text x="34" y="30" class="tl" fill="#5B6E8A">上游・零件（拼精度／成本）</text>
<text x="34" y="50" class="tb">FA 光纖陣列 ＋ PMLA 稜鏡微透鏡</text>
<text x="500" y="50" class="tk">大立光 3008</text>
<text x="320" y="82" class="tl" text-anchor="middle" fill="#5B6E8A">↓ 零件賣給模組廠</text>
<rect x="20" y="95" width="600" height="50" rx="8" fill="#0C1524" stroke="#16304A"/>
<text x="34" y="115" class="tl" fill="#5B6E8A">下游・模組（拼對準／耐回焊／客戶認證）</text>
<text x="34" y="135" class="tb">FAU 整顆（FA + 微透鏡 + 連接器 + 焊到晶片）</text>
<text x="500" y="135" class="tk">上詮 3363</text>
<text x="320" y="167" class="tl" text-anchor="middle" fill="#5B6E8A">↓ 模組焊到晶片上</text>
<rect x="20" y="180" width="600" height="26" rx="6" fill="#0E1B2B"/>
<text x="320" y="197" class="tl" text-anchor="middle" fill="#DCE7F5">平台／光引擎：台積電 COUPE → NVIDIA Spectrum-X、Rubin</text>
</svg>''',
}


def _catalyst_html(ticker):
    """近期技術／產業催化劑（社群消息面，非官方查證）。
    讀 state/stock_catalysts.json，沒有這檔的資料就整段不出現——
    跟上面 biz 簡介同一個原則，查不到不編。"""
    import json as _json
    from board_theme import esc
    try:
        with open(CATALYSTS_PATH, encoding="utf-8") as f:
            all_c = _json.load(f)
    except Exception:
        return ""
    items = all_c.get(str(ticker)) or all_c.get(str(ticker).split(".")[0]) or []
    if not items:
        return ""
    blocks = []
    for it in items:
        diagrams = "".join(
            f'<div style="margin:12px 0;padding:12px;background:var(--card,#0C1524);'
            f'border:1px solid var(--line,#16304A);border-radius:10px;overflow-x:auto">'
            f'{_CATALYST_SVG[k]}</div>'
            for k in (it.get("diagrams") or []) if k in _CATALYST_SVG)
        paras = "".join(f'<p style="margin:8px 0;line-height:1.85">{esc(p)}</p>'
                        for p in (it.get("summary") or []))
        risk = (f'<div class="warnbox"><b>⚠️ 要注意</b>：{esc(it["risk"])}</div>'
                if it.get("risk") else "")
        blocks.append(
            f'<div style="margin-top:14px">'
            f'<div style="font-size:11px;color:var(--dim,#5B6E8A);margin-bottom:4px">{esc(it.get("date",""))}</div>'
            f'<h3 style="color:#F5B841;font-size:14.5px;margin-bottom:6px">{esc(it.get("title",""))}</h3>'
            f'<div style="font-size:11.5px;color:var(--dim,#5B6E8A);border-left:2px solid var(--warn,#FFB627);'
            f'padding-left:8px;margin-bottom:10px">📱 來源：{esc(it.get("source",""))}——'
            f'不是公司公告或分析師報告，內容經過我改寫濃縮，具體數字/時程未經第三方查證</div>'
            f'{paras}{diagrams}{risk}</div>')
    return ('<div class="sb intro" style="border-left:3px solid var(--warn,#FFB627)">'
            '<h2>近期技術／產業話題 <span class="en">Social Catalyst</span></h2>'
            f'{"".join(blocks)}</div>')


def render(d, extra_notes=None):
    from board_theme import BASE_CSS, esc, esc_b, header

    # 券商可信度標籤（2026-09-05，老墨課堂）。⚠️ 只標不濾，而且**跟目標價異動表的
    # TRUSTED 名單是兩回事**——那個名單裡沒有中信，硬對過去會撞到 CITI（花旗）。
    def _cred(b):
        try:
            import broker_credibility as _bc
            return _bc.note_for(b)
        except Exception:                                   # noqa: BLE001
            return None
    import advisor_reports as ar
    px = _price(d)
    name = (d.get("lamp") or {}).get("name") or (d["reports"][0].get("name")
                                                 if d["reports"] else d["ticker"])
    body = []

    # 🔴 查核要**先算**，因為簡介要引用「抓到幾條落差」。
    # 我第一版在 _watch 裡讀 d["factcheck"]——**gather() 根本沒有這個欄位**，
    # 永遠拿到 0 而且不會報錯（silent_failure_pattern 的標準形狀）。
    # 現在算一次、兩邊共用，查核層底下也不會再算第二次。
    _top0 = d["reports"][0] if d["reports"] else None
    fc_rows = []
    if _top0:
        try:
            import report_factcheck as _fcm
            fc_rows = _fcm.check(_top0, px, d.get("base_rate"), d.get("margin"))
        except Exception as e:                              # noqa: BLE001
            print(f"  查核層失敗：{str(e)[:80]}")

    # yfinance 的公司資料查一次就好——簡介與類股定位都要用。
    # ⚠️ 各自查一次不只是慢，兩邊還可能拿到不同的快照。
    try:
        import company_intro as ci
        biz, prof = ci.intro(d["ticker"])
    except Exception as e:                                  # noqa: BLE001
        print(f"  [warn] 簡介失敗：{str(e)[:60]}")
        biz, prof = "", None

    # ── 簡介（2026-09-07 Leo：「前面寫個簡介」）─────────────
    body.append(_intro_html(d, name, px, fc_rows, biz, prof))
    body.append(_catalyst_html(d["ticker"]))

    # ── 燈號 ───────────────────────────────────────────────
    L = d.get("lamp")
    if L:
        # 2026-09-04 Leo：「這幾個字卡可以像燈號那樣顏色呈現嗎」
        # → 用**跟查股頁/燈號頁完全同一套符號**，不另外發明一套：
        #   🔴 多方 / 🟢 空方（老墨的用法，跟一般紅綠相反，但站上早就統一了）
        #   🟢/⚫ 四顆燈、⭐ 打點成立
        # ⚠️ board_theme 的規則是「顏色只給訊號用，數字類不上色」，
        #   所以現價、風報比這種純數字維持白色；只有 RS 是有方向語意的百分比，
        #   跟 technical_indicators 的 RS 卡一致上綠/紅。
        lam = L.get("lamps") or {}
        lamp_str = "".join("🟢" if v else "⚫" for v in lam.values()) or "—"
        bull = L.get("bull")
        st_v = ("🔴 多方" if bull else "🟢 空方") if bull is not None else "—"
        st_s = ((f"停損參考線 {L['st_line']:,.1f}"
                 + (f"（現價高於 {L['gap_pct']:+.1f}%）" if L.get("gap_pct") is not None else ""))
                if bull and L.get("st_line") else
                (f"站上 {L['st_line']:,.1f} 才翻多" if L.get("st_line") else ""))
        rr = L.get("rr")
        rr_s = ("⭐ 打點成立（≥3燈且風報比≥1）" if L.get("combo") and rr and rr >= 1
                else ("空方不計風報比" if bull is False else "無目標價則不計"))
        rs_h = "—"
        if L.get("rs_short") is not None:
            def _c(x):
                return f'<span class="{"pos" if x > 0 else "neg"}">{x:+.1f}%</span>'
            rs_h = f'{_c(L["rs_short"])} / {_c(L.get("rs_long") or 0)}'
        cells = [("現價", f"{L['price']:,.2f}" if L.get("price") else "—",
                  f"資料日 {L.get('asof','—')}", False),
                 ("四燈", f'<span style="font-size:19px;letter-spacing:2px">{lamp_str}</span>',
                  f"{L.get('lit')}/4　{'COMBO 成立' if L.get('combo') else '未成立'}", True),
                 ("SuperTrend", st_v, st_s, True),
                 ("風報比", f"{rr:.2f}" if rr else "—", rr_s, False),
                 ("RS 短/長", rs_h, "對自身 60 日均線", True)]
        body.append('<div class="sb"><h2>技術面（進出燈號）</h2>'
                    '<div class="sub">來源：每日掃描 combo_result；'
                    '符號跟查股頁／進出燈號頁同一套</div><div class="kv">'
                    + "".join(f'<div class="c"><div class="k">{esc(k)}</div>'
                              f'<div class="v{" zh" if zh else ""}">{v}</div>'
                              f'<div class="s">{esc(sub_)}</div></div>'
                              for k, v, sub_, zh in cells) + "</div></div>")

    # ── 產業定位（2026-09-07 Leo：「補上這隻股票在產業那裡」）──────
    body.append(_sector_html(d, prof))
    body.append(_chain_html(d))

    # ── 券商報告 ────────────────────────────────────────────
    if d["reports"]:
        # ── 多家對照表（2026-09-04 Leo：「同一隻股票的報告請整合在一起」）──
        # 同一檔有多份時，最有資訊量的不是逐份讀，是**把假設並排看差在哪**。
        # 7750 新代實測：5 家在 10 天內出報告、目標價差 35%，而差異幾乎全來自
        # 「倍數」與「用哪一年的 EPS」，不是基本面分歧。
        cmp_ = ""
        if len(d["reports"]) > 1:
            tgs = [r["target"] for r in d["reports"] if r.get("target")]
            def _row(r):
                tg = f'{r["target"]:,.0f}' if r.get("target") else "—"
                mu = (f'{r["valuation_multiple"]:g} 倍'
                      if r.get("valuation_multiple") else "—")
                _bn = _cred(r.get("broker"))
                _t = (f'<span class="sub">{esc(_bn["tag"])}</span>' if _bn else "")
                return (f'<tr><td class="k">{esc(r.get("broker"))}{_t}</td>'
                        f'<td>{esc(r.get("date"))}</td>'
                        f'<td>{esc(r.get("rating") or "—")}</td>'
                        f'<td class="v">{tg}</td><td class="v">{mu}</td>'
                        f'<td>{esc(r.get("valuation_eps_label") or "—")}</td></tr>')
            trs = "".join(_row(r) for r in d["reports"])
            spread = ""
            if len(tgs) >= 2:
                spread = (f'目標價 {min(tgs):,.0f}～{max(tgs):,.0f}'
                          f'（差 {(max(tgs) / min(tgs) - 1) * 100:.0f}%）')
            cmp_ = ('<table class="fc"><tr><th>券商</th><th>日期</th><th>評等</th>'
                    '<th>目標價</th><th>倍數</th><th>乘在哪一期</th></tr>'
                    + trs + '</table>'
                    + (f'<div class="txt">⚠️ <b>{spread}</b>——差異多半來自'
                       f'<b>倍數與用哪一年 EPS</b>，不是基本面分歧。'
                       f'多家同時出報告代表這個看法已經擁擠。</div>' if spread else ""))
        rp = []
        for r in d["reports"]:
            tg = r.get("target")
            up = f"（距現價 {(tg / px - 1) * 100:+.1f}%）" if tg and px else ""
            im = ar.implied_multiple(r, px)
            vm = ""
            if im:
                now, want, how = im
                cls = "neg" if now >= want else "pos"
                vm = (f'<br>估值前提：市場現在給 <span class="{cls}">{now:.1f} 倍'
                      f'{esc((r.get("valuation_kind") or "").upper())}</span>、'
                      f'報告假設 {want:.1f} 倍'
                      + ("——<b>前提已用完</b>" if now >= want
                         else f"（還差 {(want / now - 1) * 100:.0f}%）")
                      + f'　<span style="color:var(--dim);font-size:11px">{esc(how)}</span>')
            rp.append(
                f'<div class="rp"><b>{esc(r.get("broker"))}</b>'
                f'{(" " + _cred(r.get("broker"))["tag"]) if _cred(r.get("broker")) else ""}'
                f'　{esc(r.get("date"))}　'
                f'{esc(r.get("rating") or "無評等")}　'
                + (f'目標 <b>{tg:,.0f}</b>{esc(up)}' if tg else "無目標價（Note 類）")
                + (f'<br>依據：{esc(r["valuation_basis"])}' if r.get("valuation_basis") else "")
                + vm
                + (f'<br>論點：{esc(r["thesis"])}' if r.get("thesis") else "")
                + (f'<br>報告自列風險：{esc("、".join(r["risks"]))}' if r.get("risks") else "")
                + "</div>")
        body.append('<div class="sb"><h2>券商研究報告</h2>'
                    f'<div class="sub">{len(d["reports"])} 份，各家自己的推導，'
                    f'不是市場共識平均</div>' + cmp_ + "".join(rp) + "</div>")

    # ── 摘要層（2026-09-04 Leo：「我希望可以等於是一份摘要」）─────────
    top = d["reports"][0] if d["reports"] else None
    if top and (top.get("summary") or top.get("key_points")):
        li = "".join(f"<li>{esc(x)}</li>" for x in (top.get("summary") or []))
        TAG = {"nonconsensus": ("nc", "非共識"), "claim": ("cl", "可查核宣稱"),
               "caveat": ("cv", "報告自己的保留")}
        kps = "".join(
            f'<div class="kp"><span class="tag {TAG.get(k.get("type"), ("cl", "重點"))[0]}">'
            f'{TAG.get(k.get("type"), ("cl", "重點"))[1]}</span>{esc(k.get("text"))}</div>'
            for k in (top.get("key_points") or []))
        body.append('<div class="sb"><h2>這份報告在講什麼</h2>'
                    f'<div class="sub">{esc(top.get("broker"))}　{esc(top.get("date"))}'
                    '　摘要由本機 claude 從原文抽出，不是我的評論</div>'
                    + (f'<ul class="sm">{li}</ul>' if li else "")
                    + kps + "</div>")

    # ── 查核層（Leo：「像老墨的 html 檢查報告商寫的是不是事實」）──────
    if top:
        rows = fc_rows            # 上面算過了，不要再算一次
        import report_factcheck as fcm   # 下面的摘要句還要用它
        if rows:
            V = {"ok": ("ok", "✅ 對得上"), "warn": ("warn", "⚠️ 有落差"),
                 "wait": ("wait", "⏳ 還不能驗")}
            trs = "".join(
                f'<tr><td class="k">{esc(r["kind"])}</td>'
                f'<td>{esc(r["claim"])}</td>'
                f'<td>{esc_b(r["ours"])}<span class="note">{esc_b(r["note"])}</span></td>'
                f'<td class="v {V[r["verdict"]][0]}">{V[r["verdict"]][1]}</td></tr>'
                for r in rows)
            body.append('<div class="sb"><h2>查核：報告的假設 vs 我們算的</h2>'
                        f'<div class="sub">{esc(fcm.summary(rows))}　'
                        '⭐ 重點不是抓券商說謊——他們寫的多半是預估。'
                        '是把「他假設什麼」跟「這檔自己的歷史做得到什麼」擺在一起，'
                        '讓落差自己現形</div>'
                        '<table class="fc"><tr><th>查核項</th><th>報告說</th>'
                        '<th>我們算的</th><th>判定</th></tr>'
                        + trs + "</table></div>")

    # ── 我們算的、報告沒有的 ─────────────────────────────────
    cross = []
    b = d.get("base_rate")
    if b and b.get("requirement"):
        q, tr = b["requirement"], (b.get("track_record") or {})
        tier = {"unprecedented": "要求超出這檔自身歷史紀錄一大截",
                "rare": "要求剛好貼在自身歷史紀錄上",
                "normal": "要求落在這檔過去做得到的範圍內",
                "low_coverage": "分析師覆蓋太少，不列入判斷"}.get(q.get("tier"), q.get("tier"))
        cross.append(
            f'<div class="txt"><b>預估前提檢查（{q.get("year")}）</b>：{esc(tier)}。'
            f'剩 {q.get("months_left")} 個月要月營收 YoY '
            f'<b>{q.get("need_yoy", 0) * 100:+.1f}%</b>，'
            f'而這檔歷史中位 {q.get("yoy_med", 0) * 100:+.1f}%、'
            f'最大 {q.get("yoy_max", 0) * 100:+.1f}%（n={q.get("yoy_n")}）。'
            + (f'分析師準頭：{tr.get("n")} 次猜中 {tr.get("beats")} 次、'
               f'中位驚喜 {tr.get("median_surprise"):+.1f}%（{esc(tr.get("bias",""))}）。'
               if tr else "")
            + '<br><span style="color:var(--dim)">這一層量的是「市場對它的期待被堆多高」，'
              '不是「公司好不好」——是容錯空間的刻度。</span></div>')
    m = d.get("margin")
    if m:
        cross.append(
            f'<div class="txt"><b>毛利率位階</b>：現值 {m.get("cur")}%，'
            f'在自身 {m.get("n")} 季裡第 <b>{m.get("pct"):.0f} 百分位</b>'
            f'（區間 {m.get("lo")}~{m.get("hi")}、中位 {m.get("med")}）。'
            f'{esc(m.get("note") or "")}</div>')
    if cross:
        body.append('<div class="sb"><h2>我們算的：報告裡沒有的那幾層</h2>'
                    '<div class="sub">這些是對照「這檔自己的歷史分布」算出來的，'
                    '不是跟同業比、也不是券商的預估</div>' + "".join(cross) + "</div>")

    # ── 投資長 ─────────────────────────────────────────────
    v = d.get("verdict")
    if v:
        angs = []
        for key, nm in (("trend_angle", "趨勢角度（SuperTrend＋RS＋產業輪動）"),
                        ("value_angle", "價值角度（洪瑞泰）")):
            a = v.get(key) or {}
            j = a.get("judgment") or "—"
            cls = "buy" if j.startswith("續抱") else ("sell" if "出場" in j else "")
            angs.append(
                f'<div class="ang {cls}"><div class="t">{esc(nm)}：{esc(j)}</div>'
                f'<div class="b">{esc(a.get("brief") or "")}</div>'
                + fmt_reasoning(a.get("reasoning"), esc) + '</div>')
        conds = []
        for key, nm in (("trend_conditions", "趨勢"), ("value_conditions", "價值")):
            for c in v.get(key) or []:
                conds.append(f'<div class="txt">· [{nm}] {esc(c.get("desc"))}</div>')
        body.append('<div class="sb"><h2>投資長判斷</h2>'
                    '<div class="sub">兩個角度獨立判斷，<b>不強迫湊成一個結論</b>；'
                    '相反的建議照實列出，最終決定是你的</div>'
                    + "".join(angs)
                    + ('<div class="txt" style="margin-top:12px"><b>失效條件（每天自動檢查）</b></div>'
                       + "".join(conds) if conds else "") + "</div>")

    # ── 券商異動 ────────────────────────────────────────────
    if d["changes"]:
        rows = "".join(
            f'<div class="rp">{esc(c.get("date"))}｜<b>{esc(c.get("broker"))}</b>｜'
            f'{esc(c.get("rating"))}｜'
            f'{"▲ 調升" if c.get("direction") == "up" else ("▼ 調降" if c.get("direction") == "down" else "－")}'
            f'　{esc(str(c.get("tp_old")))} → {esc(str(c.get("tp_new")))}</div>'
            for c in d["changes"])
        body.append('<div class="sb"><h2>近期券商目標價異動</h2>'
                    '<div class="sub">來自每日異動表；⚠️ 數字未經覆核，'
                    '只看方向不建判斷條件</div>' + rows + "</div>")

    for n in (extra_notes or []):
        body.append(f'<div class="warn">{n}</div>')

    sub = (f'{esc(name)}（{esc(d["ticker"])}）'
           + (f'　現價 {px:,.2f}' if px else "")
           + '<br>券商報告怎麼說 vs 我們自己算什麼——全部讀既有資料，沒有重算也沒有花錢')
    return ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(name)} 整合報告</title><style>" + BASE_CSS + CSS + BRIEF_INTRO_CSS
            + _cp_css()
            + "</style></head><body><div class=\"wrap\">"
            + header("earnings", f"{name} 整合報告", sub, [],
                     eyebrow="STOCK DOSSIER")
            + "".join(body) + "</div></body></html>")


def _brief_href(tk, name):
    nm = _fname_safe(name)
    return (f"{tk}_{nm}_整合報告.html" if nm and nm != tk
            else f"{tk}_整合報告.html")


def _zh_href(tk, name, d):
    """最新那份中文重點頁的檔名。**用檔案系統實際存在的那個**，
    不是拼出來就算——report_zh 的命名規則改過，拼錯就是 404。"""
    import glob as _glob
    import os as _os
    pats = _glob.glob(_os.path.join(OBIS, f"{tk}_*中文重點.html"))
    if not pats:
        return ""
    pats.sort(key=_os.path.getmtime)
    return _os.path.basename(pats[-1])


def _fname_safe(x):
    """檔名安全字串：拿掉 Windows 不允許的字元與空白。"""
    import re as _re
    return _re.sub(r'[\\/:*?"<>|\s]+', "", str(x or "")).strip()[:12]


def briefed_tickers():
    """有券商報告的代號集合——`--all` 的母體。

    ⚠️ 母體刻意只取「有券商報告的」，不取全部持股：沒有報告的話這一頁的
    上半部（券商怎麼說、估值前提）整段是空的，產出來只會是一頁我們自己
    系統的數字，跟燈號頁重複。
    """
    st = _load("state/advisor_reports.json", {}) or {}
    out = []
    for v in st.values():
        if v.get("_notreport"):
            continue
        tk = v.get("ticker")
        if tk and str(tk) not in out:
            out.append(str(tk))
    return sorted(out)


def build_one(ticker, output=""):
    """產一檔，回 (輸出路徑, gather 結果)。"""
    d = gather(ticker)
    html = render(d)
    # b：檔名帶中文名，Drive 的清單裡一眼認得出是哪一檔。
    # ⚠️ 名稱要從 gather 的結果拿（跟索引那邊同一個來源），這個函式的
    # 區域範圍裡沒有 `name` 這個變數——我第一版直接寫 name 就 NameError。
    _nm = _fname_safe((d.get("lamp") or {}).get("name")
                      or ((d.get("reports") or [{}])[0].get("name"))
                      or "")
    out = output or os.path.join(
        OBIS, (f"{d['ticker']}_{_nm}_整合報告.html" if _nm and _nm != d["ticker"]
               else f"{d['ticker']}_整合報告.html"))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    return out, d, len(html)


def _stat(d):
    return (f"燈號 {'有' if d['lamp'] else '無'}｜券商報告 {len(d['reports'])} 份"
            f"｜異動 {len(d['changes'])} 筆｜投資長判斷 {'有' if d['verdict'] else '無'}"
            f"｜毛利率位階 {'有' if d['margin'] else '無'}"
            f"｜預估前提 {'有' if d['base_rate'] else '無'}")


BRIEF_INTRO_CSS = """
/* 版型抄財報懶人包（.kpis / 中英雙標題 / 利多風險兩欄），
   ⚠️ 但**不 import 它的 CSS**——那份整份寫死 #132A47/#1E3A5F，
   搬過來等於把偏離色票的問題一起搬。這裡只抄版型，顏色一律 var(--*)。 */
.intro{border-left:3px solid var(--cy,#22D3EE)}
.intro h2 .en,.intro h3 .en{font-family:'IBM Plex Mono',ui-monospace,monospace;
 font-size:10.5px;letter-spacing:.18em;color:var(--dim);font-weight:400;margin-left:7px}
.ibiz{font-size:14.5px;line-height:1.95;color:var(--ink);margin:8px 0 2px}
.isec{font-size:11px;color:var(--dim);letter-spacing:.14em;margin-bottom:12px;
 font-family:'IBM Plex Mono',ui-monospace,monospace}
.bks{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:var(--hud,#16304A);
 border:1px solid var(--hud,#16304A);margin:10px 0 14px}
.bk{background:var(--panel,#080E1A);padding:10px 11px;min-width:0}
.bk .lb{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:9px;
 letter-spacing:.13em;color:var(--dim);text-transform:uppercase;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis}
.bk .vl{font-size:21px;font-weight:700;margin:4px 0 2px;letter-spacing:-.01em;
 font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.bk .vl.pos{color:var(--up)}.bk .vl.neg{color:var(--down)}
.bk .sb2{font-size:10.5px;color:var(--dim);line-height:1.5}
.two2{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--hud,#16304A);
 border:1px solid var(--hud,#16304A)}
.two2 .col{background:var(--panel,#080E1A);padding:11px 13px}
.two2 h3{font-size:12.5px;font-weight:700;margin:0 0 7px}
.two2 .ok h3{color:var(--up)}.two2 .warn h3{color:var(--warn,#FFB627)}
.two2 ul{margin:0;padding:0;list-style:none}
.two2 li{font-size:12.5px;line-height:1.8;color:var(--muted);margin-bottom:6px;
 display:flex;gap:7px}
.two2 li b{color:var(--ink)}
.two2 .mk{flex:0 0 auto;font-weight:700}
.two2 .ok .mk{color:var(--up)}.two2 .warn .mk{color:var(--warn,#FFB627)}
.two2 .none{font-size:12px;color:var(--dim)}
.qb2{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 8px;
 color:#fff;letter-spacing:.06em;margin:0 6px}
.qsec2{font-size:11px;color:var(--dim);margin-left:4px}
.peer2{background:var(--panel,#080E1A);border:1px solid var(--hud,#16304A);
 padding:6px 9px;font-size:11.5px;min-width:118px}
.peer2.focus{border-color:var(--cy,#22D3EE);box-shadow:0 0 0 1px var(--cy,#22D3EE)}
.pt2{font-weight:700;color:var(--ink)}
.pc2{color:var(--dim);font-weight:400;margin-left:5px;font-size:10.5px;
 font-family:'IBM Plex Mono',ui-monospace,monospace}
.pv2{color:var(--muted);margin-top:2px;
 font-family:'IBM Plex Mono',ui-monospace,monospace}
@media(max-width:820px){
 .bks{grid-template-columns:repeat(2,1fr)}
 .two2{grid-template-columns:1fr}
}
"""

INDEX_NAME = "整合報告索引.html"

INDEX_CSS = """
.ix{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.ix th{text-align:left;padding:8px 9px;color:var(--dim);font-weight:600;font-size:11.5px;
 border-bottom:1px solid var(--line);white-space:nowrap}
.ix td{padding:11px 9px;border-bottom:1px solid var(--line2);vertical-align:top;
 color:var(--muted);line-height:1.7}
.ix tr.hot td{background:rgba(248,113,113,.06)}
.ix a{color:var(--ink);font-weight:700;text-decoration:none;border-bottom:1px dotted var(--line2)}
.ix a:hover{color:#93C5FD}
.ix .code{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums;font-size:13.5px}
.ix /* a（2026-09-07 Leo：「投資報告，可以中文放大嗎?」）——中文名才是認得出
   哪一檔的東西，代號是拿來查的。名稱升級成可點的大字（連最新中文重點頁），
   代號降成下面一行的小連結（連整合報告）。 */
.nm{display:block;font-size:11.5px;color:var(--dim);font-weight:400;margin-top:2px}
.ix .nm.big{font-size:17px;font-weight:700;color:var(--ink);margin:0;
 text-decoration:none;letter-spacing:.01em;line-height:1.35}
.ix .nm.big:hover{color:var(--accent,#60a5fa);text-decoration:underline}
/* 2026-09-07 Leo：「整合報告字斷行了」——「3008 · 整合報告」被折成兩行。
   那一格是表格的第一欄，內容比欄寬長就會折。兩件事一起做：
     · 這一行本身不准折（它是一個連結，斷開之後兩半看起來像兩個東西）
     · 給「個股」欄一個最小寬度，不要讓其他欄把它擠扁 */
.ix .main{min-width:132px}
.ix .main .sub{white-space:nowrap}
.ix .main .sub a{color:var(--dim);text-decoration:none;white-space:nowrap}
.ix .main .sub a:hover{color:var(--accent,#60a5fa);text-decoration:underline}
.ix .num{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
.ix .sub{display:block;font-size:11px;color:var(--dim);margin-top:2px;line-height:1.6}
.ix .pos{color:var(--up)}.ix .neg{color:var(--down)}
.ix .fire{color:var(--down);font-weight:700}
.ix .quiet{color:var(--dim)}
.pill{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;
 border-radius:5px;margin-right:5px;vertical-align:1px}
.pill.ok{background:#14311F;color:#86EFAC}
.pill.warn{background:#3A2E10;color:#FCD34D}
.pill.wait{background:var(--line);color:var(--muted)}
@media(max-width:700px){
 .ix,.ix tbody,.ix tr,.ix td{display:block;width:100%}
 .ix thead{display:none}
 .ix tr{border:1px solid var(--line);border-radius:10px;padding:4px 2px;margin:9px 0;
  background:var(--surface)}
 .ix td{border-bottom:1px solid var(--line2);padding:8px 12px}
 .ix tr td:last-child{border-bottom:none}
 .ix td::before{content:attr(data-h);display:block;font-size:10px;color:var(--dim);
  letter-spacing:.3px;margin-bottom:3px}
 .ix td.main::before{content:none}
}
"""


def index_rows():
    """每一檔一行摘要。**只讀既有 state 檔＋跑查核，不呼叫 AI、不重算行情。**

    ⚠️ 這裡刻意重跑一次 `gather()`／`report_factcheck.check()`，跟 `--all` 有重複
    計算。換來的是「索引不依賴 --all 的內部狀態」——`--index` 單獨跑得起來，
    而且改 render() 不會連帶弄壞索引。12 檔的成本是幾秒，不值得為此耦合。
    """
    today = _load("state/advisor_reports_today.json", {}) or {}
    fired_by = {}
    for r in today.get("rows", []):
        tk = _norm(str(r.get("ticker") or ""))
        for f in (r.get("fired") or []):
            fired_by.setdefault(tk, []).append(f)

    out = []
    for tk in briefed_tickers():
        d = gather(tk)
        px = _price(d)
        top = d["reports"][0] if d["reports"] else None
        fc = []
        if top:
            try:
                import report_factcheck as fcm
                fc = fcm.check(top, px, d.get("base_rate"), d.get("margin"))
            except Exception:                               # noqa: BLE001
                fc = []
        cnt = {"ok": 0, "warn": 0, "wait": 0}
        for r in fc:
            cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1

        # 目標價取最新一份「有給目標價」的報告——不是最高的那一份，也不平均。
        tgt = tgt_src = None
        for r in d["reports"]:
            if r.get("target"):
                tgt, tgt_src = float(r["target"]), r
                break

        lamp = d.get("lamp") or {}
        out.append({
            "ticker": d["ticker"],
            "name": (top or {}).get("name") or lamp.get("name") or d["ticker"],
            "zh_href": _zh_href(tk, (top or {}).get("name")
                                or lamp.get("name") or tk, d),
            "brief_href": _brief_href(tk, (top or {}).get("name")
                                      or lamp.get("name") or tk),
            "n_reports": len(d["reports"]),
            "brokers": sorted({str(r.get("broker") or "?") for r in d["reports"]}),
            "last_date": (top or {}).get("date"),
            "rating": (top or {}).get("rating"),
            "price": px,
            "target": tgt,
            "target_broker": (tgt_src or {}).get("broker"),
            "upside": (round((tgt / px - 1) * 100, 1)
                       if tgt and px else None),
            "fc": cnt,
            "n_fc": len(fc),
            "fired": fired_by.get(_norm(tk), []),
            "lit": lamp.get("lit"),
            "has_lamp": bool(lamp),
            "verdict": bool(d.get("verdict")),
            "n_changes": len(d.get("changes") or []),
        })

    # 要看的排前面：先失效線觸發、再落差條數、再報告份數。
    out.sort(key=lambda r: (-len(r["fired"]), -r["fc"]["warn"],
                            -r["n_reports"], r["ticker"]))
    return out


def render_index(rows):
    from board_theme import BASE_CSS, esc, esc_b, header, nav_abs

    def cell_target(r):
        if not r["target"]:
            return '<span class="quiet">報告未給</span>'
        s = f'<span class="num">{r["target"]:,.0f}</span>'
        if r["upside"] is not None:
            k = "pos" if r["upside"] >= 0 else "neg"
            s += f' <span class="num {k}">{r["upside"]:+.1f}%</span>'
        if r["target_broker"]:
            s += f'<span class="sub">{esc(r["target_broker"])}</span>'
        return s

    def cell_fc(r):
        if not r["n_fc"]:
            return '<span class="quiet">未查核</span>'
        c, p = r["fc"], []
        if c["ok"]:
            p.append(f'<span class="pill ok">{c["ok"]} 對得上</span>')
        if c["warn"]:
            p.append(f'<span class="pill warn">{c["warn"]} 有落差</span>')
        if c["wait"]:
            p.append(f'<span class="pill wait">{c["wait"]} 等財報</span>')
        return "".join(p)

    def cell_fired(r):
        """🔴 2026-09-07 Leo 回報「有出現錯誤」：這格印出的是
        `{'type': 'price_above', 'value': 5000.0, 'desc': '現價達到目標價 50`
        ——整個 dict 的 repr，而且被切在第 60 字，句子斷在一半。

        原因：`fired` 的元素是 **dict** 不是字串，`str()` 就把結構印出來了。
        ⭐ 對一個不知道型別的東西呼叫 str() 再截斷，壞掉的時候長得像資料，
           不像錯誤——所以它可以一直印在畫面上沒人發現。
        改成明確取 `desc`；萬一哪天結構變了，也印得出型別與值而不是一坨 repr。
        """
        if not r["fired"]:
            return '<span class="quiet">未觸發</span>'
        f = r["fired"][0]
        if isinstance(f, dict):
            txt = (f.get("desc")
                   or f"{f.get('type', '條件')} {f.get('value', '')}".strip())
        else:
            txt = str(f)
        extra = (f'<span class="sub">另有 {len(r["fired"]) - 1} 條</span>'
                 if len(r["fired"]) > 1 else "")
        return f'<span class="fire">🔴 {esc(txt)}</span>{extra}'

    def cell_ours(r):
        p = []
        if r["has_lamp"]:
            p.append(f'燈號 {r["lit"]}/4')
        else:
            p.append('<span class="quiet">不在燈號母體</span>')
        if r["verdict"]:
            p.append("有投資長判斷")
        if r["n_changes"]:
            p.append(f'異動 {r["n_changes"]} 筆')
        return "　".join(p)

    trs = []
    for r in rows:
        cls = ' class="hot"' if r["fired"] else ""
        trs.append(
            f"<tr{cls}>"
            # a（Leo：「中文放大嗎? 點擊個股可以直接進去中文報告嗎?」）
            # 中文名變成主要的、可點的連結，直接進**最新那份中文重點頁**——
            # 那是他真正要讀的東西；整合報告改成旁邊一個小連結。
            # ⚠️ 沒有中文重點頁時（例如報告解析成功但 report_zh 還沒跑）
            #    連結退回整合報告，不要給一個 404。
            f'<td class="main" data-h="個股">'
            f'<a class="nm big" href="{esc(r["zh_href"] or r["brief_href"])}">'
            f'{esc(r["name"])}</a>'
            f'<span class="sub"><a class="code" href="{esc(r["brief_href"])}">'
            f'{esc(r["ticker"])} · 整合報告</a></span></td>'
            f'<td data-h="券商報告"><span class="num">{r["n_reports"]}</span> 份'
            f'<span class="sub">{esc("、".join(r["brokers"][:3]))}'
            f'{"…" if len(r["brokers"]) > 3 else ""}　最新 {esc(r["last_date"] or "-")}</span></td>'
            f'<td data-h="報告目標價">{cell_target(r)}</td>'
            f'<td data-h="查核">{cell_fc(r)}</td>'
            f'<td data-h="失效線">{cell_fired(r)}</td>'
            f'<td data-h="我們自己的資料">{cell_ours(r)}</td>'
            "</tr>")

    n_fire = sum(1 for r in rows if r["fired"])
    n_warn = sum(r["fc"]["warn"] for r in rows)
    sub = (f"{len(rows)} 檔有券商研究報告　"
           f"{n_fire} 檔的失效線被觸發　共 {n_warn} 條假設與我們算的有落差")

    head = ('<div class="sb"><h2>這頁是什麼</h2><div class="sub">'
            '每一列是一檔**有券商研究報告**的個股，點代號進去看整合報告。'
            '排序＝失效線被觸發的排最前，其次是查核落差多的。<br>'
            '⚠️ 目標價是「最新一份報告」的數字，不是共識也不是最高的那份；'
            '風報比用的仍然是共識目標價，兩者不同源，不要互相對照。<br>'
            '⚠️ 沒有券商報告的持股不會出現在這裡——那些看燈號頁就好，'
            '這一頁的價值在「報告說的 vs 我們算的」。'
            '</div></div>')
    head = head.replace("**有券商研究報告**", "<b>有券商研究報告</b>")

    tbl = ('<div class="sb"><h2>個股一覽</h2>'
           '<table class="ix"><thead><tr>'
           "<th>個股</th><th>券商報告</th><th>報告目標價</th>"
           "<th>查核</th><th>失效線</th><th>我們自己的資料</th>"
           "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>")

    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>整合報告索引</title><style>" + BASE_CSS + CSS + INDEX_CSS
            + '</style></head><body><div class="wrap">'
            + header("earnings", "整合報告索引", sub, nav_abs(),
                     eyebrow="DOSSIER INDEX")
            + head + tbl + "</div></body></html>")


def build_index():
    rows = index_rows()
    if not rows:
        print("沒有任何已解析的券商報告，不產索引。")
        return None, []
    html = render_index(rows)
    out = os.path.join(OBIS, INDEX_NAME)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(html)
    return out, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?", default="")
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--all", action="store_true",
                    help="重產所有「有券商報告」的個股＋索引（每日排程用）")
    ap.add_argument("--index", action="store_true",
                    help="只重產索引頁（不重產個股）")
    a = ap.parse_args()

    if a.index and not a.all:
        out, rows = build_index()
        if out:
            print(f"✅ 已存 {out}（{len(rows)} 檔）")
        return 0

    if a.all:
        tks = briefed_tickers()
        if not tks:
            print("沒有任何已解析的券商報告，不產出。")
            return 0
        ok = fail = 0
        for tk in tks:
            try:
                out, d, n = build_one(tk)
                ok += 1
                print(f"  ✅ {d['ticker']:8} {os.path.basename(out)}  ({n:,} bytes)  {_stat(d)}")
            except Exception as e:                          # noqa: BLE001
                fail += 1
                # 一檔壞掉不能讓其餘 N-1 檔跟著不產出（排程裡尤其重要）。
                print(f"  ❌ {tk:8} 失敗：{str(e)[:120]}")
        # 索引一定要在個股全部產完之後才產（它讀的是同一批 state，順序不影響
        # 內容，但先產索引會讓「索引列了某檔、那檔的頁面卻沒更新」變得可能）。
        try:
            ip, irows = build_index()
            if ip:
                n_fire = sum(1 for r in irows if r["fired"])
                print(f"  📇 索引 {os.path.basename(ip)}"
                      f"（{len(irows)} 檔，其中 {n_fire} 檔失效線被觸發）")
        except Exception as e:                              # noqa: BLE001
            fail += 1
            print(f"  ❌ 索引失敗：{str(e)[:120]}")
        print()
        print(f"完成 {ok} 檔，失敗 {fail} 檔｜存放 {OBIS}")
        return 1 if fail and not ok else 0

    if not a.ticker:
        ap.error("要給代號，或用 --all 重產全部")
    out, d, n = build_one(a.ticker, a.output)
    print(f"✅ 已存 {out}（{n:,} bytes）")
    print(f"   {_stat(d)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
