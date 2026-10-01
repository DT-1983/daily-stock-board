# -*- coding: utf-8 -*-
"""外部券商報告 → 軍師評論（2026-10-01，Leo 看老墨的阿福回答「高盛過去兩週的報告」後要的升級原型）

老墨的阿福能做到、我們戰情室做不到的：**不綁單一個股**，一次拿「某券商／某段時間的一批報告」
排成表，逐檔對照系統自己的數字，提醒哪裡衝突。戰情室的孔明一次只能判一檔（沒指定股票就拒答）。

這支是**跨檔入口的原型**：
  輸入  JSON 清單 [{ticker,name,broker,date,rating,target,source}]（**私人資料，不進 repo**）
  ① 每檔即時燈號（lamp_lookup live，不用早上 07:00 的快取——它是前一個交易日的收盤）
  ② 程式算比對表：報告目標價距現價、跟市場共識目標價差多少、SuperTrend 線與風報比、評等與目標價是否矛盾
  ③ 孔明逐檔評論（走 war_room_chat.ask，**存進續談線**——事後在戰情室或 Discord 問同一檔會接著談）
  ④ 產 HTML 存 obis（私人）

🔴 數字一律程式算、孔明只評論；報告原文沒有的（目標價怎麼推）要他明講推不出，不准猜。
🔴 輸入資料若來自第三方畫面（截圖），頁面必須標明「未核對原文」。

用法:
    python report_review.py --input reports.json --title "高盛八檔" [--workers 3] [--no-ai]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                  # noqa: E402

RATING_SIDE = {"buy": 1, "買進": 1, "增加持股": 1, "outperform": 1, "overweight": 1,
               "neutral": 0, "中立": 0, "持有": 0, "hold": 0,
               "sell": -1, "賣出": -1, "減碼": -1, "underweight": -1}


def facts(rep, lk):
    """程式算的比對數字＋旗標。lk＝lamp_lookup.lookup(live=True) 結果（可能 None）。"""
    px = (lk or {}).get("price")
    tp = float(rep["target"])
    f = {"price": px, "target": tp}
    if not px:
        f["flags"] = ["⚪ 查不到現價，沒有比對"]
        return f
    up = tp / px - 1
    f["upside"] = up
    st, bull = lk.get("st_line"), lk.get("bull")
    f.update(st_line=st, bull=bull, lit=lk.get("lit"), gap=lk.get("gap_pct"),
             rs_s=lk.get("rs_short"), rs_l=lk.get("rs_long"), quad=lk.get("quad") or {},
             cons=lk.get("target"), cons_up=(lk["target"] / px - 1) if lk.get("target") else None)
    # 風報比＝(目標價−現價)÷(現價−SuperTrend 線)。只有「價在線上（多方）」算得出；
    # 價在線下，分母是負的——不是風報比很好，是**沒有停損可以對照**（老墨畫面上緯穎就是這種）。
    if bull and st and px > st and tp > px:
        f["rr"] = (tp - px) / (px - st)
    else:
        f["rr"] = None
    flags = []
    side = RATING_SIDE.get(str(rep.get("rating", "")).strip().lower(), None)
    if side == 0 and up >= 0.15:
        flags.append(f"🟡 評等中立，目標價卻比現價高 {up:+.0%}（券商評等多為相對評等，不等於絕對報酬）")
    if side == 1 and up < 0.10:
        flags.append(f"🟡 評等買進，目標價只比現價高 {up:+.0%}")
    if side == -1 and up > 0:
        flags.append(f"🟡 評等賣出，目標價卻比現價高 {up:+.0%}")
    if f.get("cons"):
        d = tp / f["cons"] - 1
        f["vs_cons"] = d
        if abs(d) >= 0.15:
            flags.append(f"🟠 報告目標價比市場共識目標價（{f['cons']:,.1f}）{'高' if d > 0 else '低'} {abs(d):.0%}")
    if bull is False and st:
        flags.append(f"🔴 現價在 SuperTrend 線（{st:,.1f}）下方 {abs(lk.get('gap_pct') or 0):.1f}%，風報比不適用")
    elif f.get("rr") is not None and f["rr"] < 1:
        flags.append(f"🔴 以報告目標價算風報比只有 {f['rr']:.2f}（上檔不到下檔）")
    f["flags"] = flags
    return f


def _n(x):
    """價格寫成千分位。⚠️ 問題文字會被 war_room 拿去「認股票」：連續 4 位以上的數字（3777、2110.0）
    會被當成台股代號、2～5 個大寫字母（RS、EPS）當成美股代號，連「數字」都是一家公司名（5287）。
    千分位讓 3,777 不再是連續四碼；其餘用中文寫。"""
    return f"{x:,.1f}" if x < 100 else f"{x:,.0f}"


def question_for(rep, f):
    import war_room
    px = f.get("price")
    pos = f"{f['upside']:+.1%}" if f.get("upside") is not None else "（現價查不到）"
    src = rep.get("source") or "Leo 提供"
    d = str(rep.get("date", ""))[-5:].replace("-", "/")
    q = (f"【外部資料——{src}；報告原文我們沒有，未核對原文，引用時要說明這一點】\n"
         f"{rep.get('broker', '')} 在 {d} 對 {rep['name']}（{rep['ticker']}）的評等是「{rep.get('rating', '')}」、"
         f"目標價 {_n(float(rep['target']))}（對現價 {_n(px) if px else '？'} 距離 {pos}）。\n\n"
         f"請孔明評論 {rep['name']}（{rep['ticker']}）：\n"
         "1. 這個評等與目標價，跟我們系統自己的判斷（燈號、SuperTrend、相對強度、俗貴價、預估前提檢查、市場共識目標價）"
         "是一致還是衝突？**逐項**對照，每一項前面標 ✅一致／⚠️方向同但幅度有落差／❌衝突／❔材料沒有比不了，"
         "再用一句話說明。\n"
         "2. 這個目標價能不能回推成「某年每股盈餘乘上幾倍」？材料裡沒有報告的每股盈餘與倍數就明講推不出來，**不要猜**。\n"
         "3. 若只提醒 Leo 一件事，是什麼？\n"
         "回答精簡，用到的價格與比率只取材料裡有的。")
    # 🔴 硬檢查：問題文字認得出的股票必須「只有這一檔」，否則孔明可能拿錯股票的材料（問高力答 HIG 那類錯）
    picks = war_room._tickers_in_question(q)
    if [c for c, _ in picks] != [rep["ticker"]]:
        raise ValueError(f"問題文字會被認成 {picks[:6]}，不只 {rep['ticker']}——請改寫問題，不要讓孔明用錯材料")
    return q


def prepare(rep):
    """即時燈號＋比對數字。⚠️ 必須循序做：lamp_lookup 底下的 yfinance 在多執行緒下會回錯格式的資料
    （平行跑 3 檔，有 3 檔噴 'DataFrame' object has no attribute 'tolist'；循序同樣 8 檔全部正常）。"""
    import lamp_lookup as L
    try:
        lk = L.lookup(rep["ticker"], live=True)
    except Exception as e:                                       # noqa: BLE001
        print(f"  [{rep['ticker']}] 即時查詢失敗：{str(e)[:80]}")
        lk = None
    return facts(rep, lk)


def ask_kongming(rep, f):
    """孔明逐檔評論——這段才可以平行（各自一個 claude 子行程，互不相干）。"""
    try:
        import war_room_chat as W
        txt, meta, _info = W.ask("孔明", question_for(rep, f), ticker=rep["ticker"], fresh=True,
                                 src="report_review")
        return txt or "", ""
    except Exception as e:                                       # noqa: BLE001
        print(f"  [{rep['ticker']}] 孔明失敗：{str(e)[:120]}")
        return "", str(e)[:120]


# ───────────────────────────── HTML ─────────────────────────────
CSS = """
.wrap{max-width:1040px;margin:0 auto;padding:0 16px 60px}
h2{font-size:18px;margin:30px 0 10px;padding-left:10px;border-left:3px solid var(--accent)}
.note{background:var(--card);border:1px solid var(--line);padding:12px 14px;margin:14px 0;color:var(--muted);font-size:14px;line-height:1.7}
.note b{color:var(--ink)}
.tbl{overflow-x:auto;border:1px solid var(--line)}
table.t{border-collapse:collapse;width:100%;min-width:760px;font-size:14px}
table.t th{background:var(--surface);color:var(--muted);font-weight:500;text-align:right;padding:8px 10px;white-space:nowrap}
table.t td{padding:8px 10px;border-top:1px solid var(--line2);text-align:right;font-family:'IBM Plex Mono',monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
table.t th:first-child,table.t td:first-child{text-align:left;position:sticky;left:0;background:var(--card);font-family:inherit}
.up{color:#ff8a8a}.dn{color:#4ade80}
.card{background:var(--card);border:1px solid var(--line);margin:14px 0;padding:14px 16px}
.card h3{margin:0 0 6px;font-size:17px}
.card .meta{color:var(--muted);font-size:13px;margin-bottom:8px;font-family:'IBM Plex Mono',monospace}
.flag{font-size:14px;line-height:1.7;margin:2px 0}
.ans{margin-top:10px;padding-top:10px;border-top:1px dashed var(--line);font-size:15px;line-height:1.85;color:var(--ink)}
.ans p{margin:0 0 .7em}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border:1px solid var(--line);color:var(--muted);margin-right:6px}
@media(max-width:640px){.card{padding:12px}.ans{font-size:16px}}
"""


def _md(s):
    s = esc(s or "")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return "".join(f"<p>{p.strip()}</p>" for p in re.split(r"\n\s*\n", s.strip()) if p.strip()).replace("\n", "<br>")


def _pc(x, nd=1):
    return "—" if x is None else f'<span class="{"up" if x > 0 else "dn" if x < 0 else ""}">{x:+.{nd}%}</span>'


def render(results, title, src_note):
    rows = []
    for r in results:
        rep, f = r["rep"], r["f"]
        side = "多" if f.get("bull") else ("空" if f.get("bull") is False else "—")
        rows.append(
            f"<tr><td>{esc(rep['name'])} {rep['ticker']}</td><td>{esc(str(rep.get('date', '')))}</td>"
            f"<td>{esc(str(rep.get('rating', '')))}</td><td>{rep['target']:,.1f}</td>"
            f"<td>{f['price']:,.2f}</td><td>{_pc(f.get('upside'))}</td>"
            f"<td>{'—' if not f.get('cons') else format(f['cons'], ',.1f')}</td><td>{_pc(f.get('cons_up'))}</td>"
            f"<td>{side}</td><td>{'—' if f.get('lit') is None else str(f['lit']) + '/4'}</td>"
            f"<td>{'—' if f.get('rr') is None else format(f['rr'], '.2f')}</td></tr>"
            if f.get("price") else f"<tr><td>{esc(rep['name'])} {rep['ticker']}</td><td colspan=10>查不到現價</td></tr>")
    table = ('<div class="tbl"><table class="t"><tr><th>股票</th><th>報告日</th><th>評等</th><th>報告目標</th>'
             '<th>現價</th><th>距目標</th><th>共識目標</th><th>距共識</th><th>SuperTrend</th><th>燈號</th>'
             '<th>風報比</th></tr>' + "".join(rows) + "</table></div>")
    cards = []
    for r in results:
        rep, f = r["rep"], r["f"]
        fl = "".join(f'<div class="flag">{esc(x)}</div>' for x in f.get("flags", [])) or '<div class="flag">⚪ 程式沒有標出矛盾</div>'
        quad = "／".join(f"{k}日{ {'leading':'領先','weakening':'轉弱','improving':'改善','lagging':'落後'}.get(v, v) }"
                        for k, v in (f.get("quad") or {}).items())
        meta = (f"報告 {rep.get('date', '')}　{rep.get('rating', '')}　目標 {rep['target']:,.1f}　｜　現價 "
                f"{f['price'] if f.get('price') else '—'}　RS 短/長 "
                f"{'—' if f.get('rs_s') is None else format(f['rs_s'], '+.1f')}/{'—' if f.get('rs_l') is None else format(f['rs_l'], '+.1f')}"
                + (f"　象限 {quad}" if quad else ""))
        ans = _md(r["ans"]) if r["ans"] else f'<p class="flag">孔明沒有回覆（{esc(r["err"] or "已跳過 AI")}）</p>'
        cards.append(f'<div class="card"><h3>{esc(rep["name"])} <span class="tag">{rep["ticker"]}</span></h3>'
                     f'<div class="meta">{esc(meta)}</div>{fl}<div class="ans">{ans}</div></div>')
    sub = f"{len(results)} 檔　製作 {dt.datetime.now():%Y-%m-%d %H:%M}"
    return ("<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>" + BASE_CSS + CSS + "</style></head><body>"
            + header("board", title, sub, [], eyebrow="REPORT REVIEW")
            + f'<div class="wrap"><div class="note"><b>資料來源與限制：</b>{esc(src_note)}</div>'
            '<div class="note"><b>資料日期：</b>上表現價、SuperTrend、風報比是 <b>即時重算</b>（以最近收盤為準）；'
            '下方孔明的材料多來自每日 07:00 掃描的快取（前一個交易日收盤），引用的燈號、風報比、貴價可能比上表<b>舊一天</b>，'
            '兩者不同時以上表為準。</div>'
            "<h2>一張表看完</h2>" + table +
            '<div class="note">風報比＝（報告目標價−現價）÷（現價−SuperTrend 線）；價在線下算不出來。'
            '「共識目標」是市場分析師均值（yfinance），跟報告目標價是兩件事。</div>'
            "<h2>逐檔評論（孔明）</h2>" + "".join(cards) + "</div></body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--title", default="券商報告軍師評論")
    ap.add_argument("--source-note", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--render-only", action="store_true", help="不重跑孔明，用上次的 <input>_out.json 重產 HTML")
    ap.add_argument("--sub", default="個股筆記")
    a = ap.parse_args()
    reps = json.load(io.open(a.input, encoding="utf-8"))
    print(f"{len(reps)} 檔，孔明並行 {a.workers}（{'跳過 AI' if a.no_ai else '本機 Max，不計費'}）")
    if a.render_only:
        old = {o["ticker"]: o for o in json.load(io.open(os.path.splitext(a.input)[0] + "_out.json", encoding="utf-8"))}
        fs = [old[r["ticker"]]["f"] for r in reps]
        outs = [(old[r["ticker"]]["ans"], "") for r in reps]
    else:
        fs = [prepare(r) for r in reps]
    if a.render_only:
        pass
    elif a.no_ai:
        outs = [("", "已跳過 AI")] * len(reps)
    else:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            outs = list(ex.map(lambda rf: ask_kongming(*rf), zip(reps, fs)))
    results = [{"rep": r, "f": f, "ans": o[0], "err": o[1]} for r, f, o in zip(reps, fs, outs)]
    note = a.source_note or "報告的評等與目標價取自 Leo 提供的第三方畫面，我們沒有報告原文、未核對。"
    html = render(results, a.title, note)
    dst = a.out or op.archive(f"{dt.date.today():%Y-%m-%d}_{re.sub(r'[^0-9A-Za-z一-鿿]+', '_', a.title)}.html", sub=a.sub)
    io.open(dst, "w", encoding="utf-8").write(html)
    print("✅", dst, f"({len(html):,} 字)")
    json.dump([{"ticker": r["rep"]["ticker"], "f": r["f"], "ans": r["ans"]} for r in results],
              io.open(os.path.splitext(a.input)[0] + "_out.json", "w", encoding="utf-8"),
              ensure_ascii=False, default=str, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
