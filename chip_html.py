# -*- coding: utf-8 -*-
"""籌碼異動頁 → docs/chip.html（2026-08-31，Leo：「異常大買的細項做成 html？」）

**為什麼要獨立一頁**：Discord 日報④段只列得下每類 3-4 檔（手機版面限制），
但 chip_scan 每天實際掃出 50-90 筆。細項（倍數/連幾天/張數/所屬七鏈）在
訊息裡塞不下，頁面才放得開——訊息負責「今天有事」，頁面負責「查細節」。

**同時補上日報做不到的事**：標註每檔**在不在七鏈守備清單**。
「3049 精金異常大買」單看不知道要不要在意，「3037 欣興（玻璃基板鏈）連買15天」
才有行動意義——這正是 8/29 評估「全市場覆蓋用在哪」時的結論。

資料源：state/chip_events.json（chip_scan.py 每日產出）
用法：python chip_html.py [-o docs/chip.html]
"""
import os
import io
import sys
import json
import argparse
from datetime import datetime

# 2026-09-01 從 TextIOWrapper 改 reconfigure：被 import 時原本會把呼叫端已包好的
# stdout 關掉，之後對方 print 就 ValueError（earnings_watch 同一個坑 8/31 修過）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from board_theme import BASE_CSS, header, NAV, esc  # noqa: E402

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"


def _chain_map():
    """{代號: 鏈名}。同一檔可能在多條鏈（例如 3037 欣興在 AI伺服器＋玻璃基板），
    全部列出來不要只取第一條——那會讓「它到底屬於哪個題材」看起來比實際窄。"""
    out = {}
    try:
        scr = json.load(open("screen_result.json", encoding="utf-8"))
        for chain, rows in (scr.get("tw") or {}).items():
            for r in rows:
                out.setdefault(str(r["code"]), []).append(chain)
    except Exception:
        pass
    return out


def _rows(events, chains):
    """整理成表格列，並標註七鏈歸屬。"""
    out = []
    for e in events:
        code = e["code"]
        kind = "anomaly" if e["kind"] == "anomaly" else "streak"
        buy = ("買" in e["event"])
        out.append({
            "code": code, "name": e.get("name", code),
            "event": e["event"], "buy": buy, "kind": kind,
            # 異常看倍數、連續看天數——兩種訊號的「強度」單位本來就不同，
            # 硬湊成同一欄會沒辦法比較，所以分開存、表格分開排序。
            "mult": e.get("vs_avg"), "days": e.get("days"),
            "lots": abs(e.get("shares") or 0) / 1000,
            "chains": chains.get(code, []),
        })
    return out


def render(data, chains):
    ev = data.get("events") or []
    rows = _rows(ev, chains)
    date = data.get("date", "")
    n_chain = sum(1 for r in rows if r["chains"])

    groups = [
        ("異常大買", "🟢", [r for r in rows if r["kind"] == "anomaly" and r["buy"]], "mult"),
        ("異常大賣", "🔴", [r for r in rows if r["kind"] == "anomaly" and not r["buy"]], "mult"),
        ("法人連買", "📈", [r for r in rows if r["kind"] == "streak" and r["buy"]], "days"),
        ("法人連賣", "📉", [r for r in rows if r["kind"] == "streak" and not r["buy"]], "days"),
    ]

    secs = []
    for title, ic, lst, sortkey in groups:
        if not lst:
            continue
        lst.sort(key=lambda r: -(r[sortkey] or 0))
        unit = "倍" if sortkey == "mult" else "天"
        trs = []
        for r in lst:
            ch = "".join(f'<span class="chain">{esc(c)}</span>' for c in r["chains"])
            strength = (f'{r["mult"]:.1f} 倍' if sortkey == "mult"
                        else f'連 {r["days"]} 天')
            # 在七鏈裡的整列加底色——這是全頁最重要的視覺區分，
            # 不在清單裡的股票對 Leo 沒有行動意義（見檔頭說明）
            cls = ' class="hit"' if r["chains"] else ""
            trs.append(
                f'<tr{cls}><td class="c">{esc(r["code"])}</td>'
                f'<td>{esc(r["name"])}</td>'
                f'<td class="n">{strength}</td>'
                f'<td class="n">{r["lots"]:,.0f}</td>'
                f'<td>{ch or "<span class=\'no\'>—</span>"}</td></tr>')
        secs.append(
            f'<section><h2>{ic} {esc(title)}'
            f'<span class="cnt">{len(lst)} 檔</span></h2>'
            f'<table><thead><tr><th>代號</th><th>名稱</th>'
            f'<th class="n">強度（{unit}）</th><th class="n">張數</th>'
            f'<th>七鏈守備清單</th></tr></thead><tbody>'
            + "".join(trs) + '</tbody></table></section>')

    sub = (f'{len(ev)} 筆・資料日 {esc(date)}・三大法人買賣超（上市＋上櫃約 1,870 檔全掃）'
           f'　|　<b>{n_chain} 檔在七鏈守備清單內</b>（整列淺色標示）')
    hdr = header("chip", "籌碼異動", sub, NAV, "chip")

    note = (
        '<div class="note"><b>怎麼看</b>'
        '<p><b>異常大買／大賣</b>：今天的買賣超是這檔<b>自己近 20 日平均的幾倍</b>'
        '（每檔跟自己比，不是跟全市場比——大型股天天幾萬張、小型股幾百張就算大）。'
        '門檻 5 倍，實測約 9% 的股票會觸發。</p>'
        '<p><b>法人連買／連賣</b>：連續同方向的天數，門檻 5 天。</p>'
        '<p><b>七鏈守備清單</b>：有標的代表這檔在你追蹤的產業鏈裡——'
        '清單外的異動多半跟你的方向無關，這欄是用來快速過濾的。</p>'
        '<p class="disc">資料來源：臺灣證券交易所 T86、櫃買中心公開資料。'
        '本頁僅彙整統計公開資訊，非投資建議。</p></div>')

    css = BASE_CSS + """
section{margin:22px 0}
h2{font-size:16px;margin:0 0 10px;display:flex;align-items:center;gap:8px}
.cnt{font-size:12px;color:var(--muted);font-weight:400;
     background:var(--card2);padding:2px 8px;border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;
   padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line)}
td.c{font-family:ui-monospace,monospace;color:var(--muted)}
.n{text-align:right;font-variant-numeric:tabular-nums}
tr.hit{background:rgba(59,130,246,.07)}
tr.hit td.c{color:var(--accent);font-weight:600}
.chain{display:inline-block;font-size:11px;background:rgba(59,130,246,.15);
       color:#93C5FD;padding:1px 7px;border-radius:9px;margin:1px 3px 1px 0}
.no{color:var(--line)}
.note{margin-top:26px;padding:14px 16px;background:var(--card2);
      border-radius:10px;font-size:13px;line-height:1.7}
.note p{margin:6px 0;color:var(--muted)}
.disc{font-size:11px;opacity:.75;margin-top:10px}
@media(max-width:640px){table{font-size:12px}td,th{padding:6px 5px}}
"""
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>籌碼異動</title><style>{css}</style></head><body>'
            + hdr + "".join(secs) + note + '</body></html>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/chip.html")
    a = ap.parse_args()
    try:
        data = json.load(open("state/chip_events.json", encoding="utf-8"))
    except Exception as e:
        print(f"讀不到 state/chip_events.json（先跑 chip_scan.py）：{e}")
        return
    html = render(data, _chain_map())
    for out in (a.output, os.path.join(OBIS, "籌碼異動.html")):
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            io.open(out, "w", encoding="utf-8").write(html)
            print(f"✅ {out}")
        except Exception as e:
            print(f"⚠️ 寫入 {out} 失敗（不影響其他輸出）：{e}")


if __name__ == "__main__":
    main()
