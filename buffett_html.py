"""巴菲特價值清單 v2（統一風格版）

資料邏輯完全沿用 buffett_html.py（hong_signal / quality_flags / DE_HIGH…），
只換渲染層為 board_theme 的列式設計系統，跟看板 v2 統一。

用法：python buffett_html_v2.py [-o docs/buffett.html]
"""
import os
import json
import argparse
from datetime import datetime

import yfinance as yf
from buffett_html_legacy import (hong_signal, quality_flags, sector_tw, DE_HIGH, OBIS)
from board_theme import BASE_CSS, header, icon, esc, score_class, SIG_COLOR, SIG_LABEL, NAV

import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 印 emoji 會炸

ORDER = ["buy", "watch", "sell", "na"]
SIGMAP = {"buy": "buy", "watch": "watch", "sell": "sell", "na": "watch"}


def _row(r, rid):
    cls = SIGMAP[r["sig"]]
    col = SIG_COLOR[cls]
    lead = f'<span style="color:#F5B841;font-size:10.5px;font-weight:700;margin-right:5px">龍頭#{int(r["rank"])}</span>' if r.get("rank") else ""
    trap = "".join(f'<span style="color:#FCA5A5;font-size:10.5px;margin-right:6px">⚠ {esc(t)}</span>' for t in (r.get("tags") or []))
    roe = f'{r["roe"]*100:.0f}%' if r.get("roe") is not None else "—"
    if r.get("roe_years") is not None:
        roe += f' <span style="color:var(--dim)">{int(r["roe_years"])}/4</span>'
    po = f'{r["payout"]*100:.0f}%' if r.get("payout") is not None else "—"
    dis = f'{r["dis"]:.0f}%' if r.get("dis") else "—"
    cheap = f'{r["cheap"]:.1f}' if r.get("cheap") else "—"
    exp = f'{r["exp"]:.0f}' if r.get("exp") else "—"
    price = f'{r["price"]:.1f}' if r.get("price") else "—"
    # 盈再率：2026-08-25 補上。先前頁面說明寫著「品質關：盈再率<80%」卻**沒有這一欄**——
    # 使用者看得到條件、看不到數值，也看不出這個數字是官方公式算的還是替代算法。
    ri, rg = r.get("reinvest"), r.get("reinvest_grade")
    if ri is None:
        reinv = '<span style="color:var(--dim)">—</span>'
    else:
        # 顏色照分級，不是照數字大小：負值（縮表）不是好事，不能跟低盈再率同色
        rc = {"ideal": "#34D399", "acceptable": "#F5B841",
              "shrinking": "#FCA5A5", "warn": "#FCA5A5"}.get(rg, "var(--dim)")
        mark = ""
        if (r.get("reinvest_method") or "") == "capex_fallback":
            mark = '<span style="color:#FCA5A5;font-size:10px">＊</span>'   # 替代算法
        elif rg == "shrinking":
            mark = '<span style="color:#FCA5A5;font-size:10px">↓</span>'    # 縮表
        reinv = f'<span style="color:{rc}">{ri*100:.0f}%</span>{mark}'
    grid = "".join(f'<div class="dcell"><div class="k">{k}</div><div class="v num">{v}</div></div>'
                   for k, v in [("現價", price), ("俗價", cheap), ("貴價", exp), ("折價%", dis),
                               ("ROE", r.get("roe") and f'{r["roe"]*100:.0f}%' or "—"),
                               ("盈再率", reinv),
                               ("配息率", po), ("產業", sector_tw(r.get("sector", "")))])
    note = r.get("reinvest_note")
    detail = f'<div class="dgrid">{grid}</div>' + (
        f'<div class="mdbody" style="color:var(--muted);font-size:11.5px">{esc(note)}</div>'
        if note else "") + (
        f'<div class="mdbody">{trap}</div>' if trap else "")
    return (
        f'<button class="row" data-id="{rid}" data-sig="{cls}" aria-expanded="false">'
        f'<span class="dot" style="background:{col}"></span>'
        f'<span class="info"><span class="t1">{lead}<span class="tk">{esc(r["tk"])}</span>'
        f'<span class="nm">{esc(r.get("name",""))}</span>'
        f'<span class="sigtag" style="background:{col}22;color:{col}">{SIG_LABEL[cls]}</span></span>'
        f'<span class="one">俗價 {cheap} · 貴價 {exp} · ROE {roe} · 盈再 {reinv}'
        f'{" · " + trap if trap else ""}</span></span>'
        f'<span class="rt"><span class="sv num {score_class(r.get("dis") or 0)}">{dis}</span>'
        f'<span class="bar" style="width:{min(max((r.get("dis") or 0)*1.2,4),46):.0f}px"></span></span>'
        f'{icon("chevron",15,"currentColor",2.5)}</button>'
        f'<div class="detail" data-for="{rid}">{detail}</div>')


def build(watch):
    tickers = list(watch.keys())
    prices = {}
    try:
        data = yf.download(tickers, period="5d", progress=False, threads=False,
                           auto_adjust=True, group_by="ticker")
        for tk in tickers:
            try:
                prices[tk] = float(data[tk]["Close"].dropna().iloc[-1])
            except Exception:
                pass
    except Exception as e:
        print("price fetch err:", e)

    mkts = {"US": {k: [] for k in ORDER}, "TW": {k: [] for k in ORDER}}
    for tk, d in watch.items():
        mkt = d.get("market", "US")
        mkts.setdefault(mkt, {k: [] for k in ORDER})
        price = prices.get(tk)
        cheap, exp = d.get("cheap"), d.get("expensive")
        sig = hong_signal(price, cheap, exp)
        dis = ((cheap - price) / cheap * 100) if (price and cheap and price <= cheap) else None
        tags = quality_flags(tk) if sig in ("buy", "watch") else []
        disp_tk = tk.rsplit(".", 1)[0] if mkt == "TW" else tk
        mkts[mkt][sig].append({
            "tk": disp_tk, "sig": sig, "name": d.get("name"), "sector": d.get("sector", ""),
            "rank": d.get("rank"), "price": price, "cheap": cheap, "exp": exp,
            "roe": d.get("roe"), "eps": d.get("eps"), "dis": dis, "tags": tags,
            "payout": d.get("payout"), "roe_years": d.get("roe_years"),
            "reinvest": d.get("reinvest"), "reinvest_grade": d.get("reinvest_grade"),
            "reinvest_method": d.get("reinvest_method"), "reinvest_note": d.get("reinvest_note"),
        })

    n_us = sum(len(mkts["US"][s]) for s in ORDER)
    n_tw = sum(len(mkts["TW"][s]) for s in ORDER)
    upd = next((v.get("updated") for v in watch.values() if v.get("updated")), "?")
    # 盈再率有多少檔是官方公式算的——這個比例要讓使用者看得到，
    # 否則「替代算法」跟「官方公式」在頁面上長得一模一樣。
    n_total = len(watch)
    n_official = sum(1 for v in watch.values()
                     if (v.get("reinvest_method") or "").startswith("official"))

    def section(mkt_key, label):
        rows_html, i = [], 0
        for sig in ORDER:
            for r in mkts[mkt_key][sig]:
                rows_html.append(_row(r, f'{mkt_key}{i}')); i += 1
        n = len(rows_html)
        counts = {s: len(mkts[mkt_key][s]) for s in ORDER}
        return f"""<section class="sec" data-mkt="{mkt_key}" style="{'' if mkt_key=='US' else 'display:none'}">
  <div class="ctrl" style="position:static;border:0;padding:0 0 10px">
    <div class="sorts" role="group" aria-label="依訊號篩選">
      <button class="sc f" data-f="all" aria-pressed="true">全部 <b>{n}</b></button>
      <button class="sc f" data-f="buy" aria-pressed="false" style="border-color:#166534">
        <span class="d2" style="background:#22C55E"></span>買進 <b>{counts['buy']}</b></button>
      <button class="sc f" data-f="watch" aria-pressed="false">
        <span class="d2" style="background:#64748B"></span>觀望 <b>{counts['watch']}</b></button>
      <button class="sc f" data-f="sell" aria-pressed="false" style="border-color:#7F1D1D">
        <span class="d2" style="background:#EF4444"></span>太貴 <b>{counts['sell']}</b></button>
    </div>
  </div>
  <div class="rows">{"".join(rows_html) or '<div class="empty">此市場暫無 BUY/WATCH 標的</div>'}</div>
</section>"""

    body = section("US", "美股") + section("TW", "台股")

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>巴菲特價值清單</title>
<style>{BASE_CSS}</style></head><body><div class="wrap">
{header("buffett", "巴菲特價值清單",
  f"洪瑞泰俗貴價法 · 資料更新 {esc(upd)} · 美股 {n_us} / 台股 {n_tw} 檔"
  f" · 每週六重掃", NAV, "buffett")}
<div class="note">
<b>訊號</b>：買進＝現價≤俗價　觀望＝俗價~貴價之間　太貴＝現價&gt;貴價<br>
<b>俗價</b>=EPS×12（買進線，報酬15%）　<b>貴價</b>=EPS×30（賣出線，報酬0%）—— 洪瑞泰只設這兩條線，不用合理價<br>
<b>初篩母體</b>（依洪瑞泰講稿的篩選器設定）：美股 <b>S&amp;P 500</b> 成分股、PE≤15、ROE≥10%　·　台股 <b>TWSE+TPEX</b>、PE≤15、ROE≥15%<br>
<b>品質關（全過才進買進/觀望）</b>：ROE≥15% 且近4年至少3年達標　·　盈再率&lt;80%　·　配息率≥40%<br>
初篩 ROE 放寬到 10% 是他刻意的——現在 ROE 12% 但過去 4 年有 3 年達標的公司，才不會在第一關就被刷掉。
台股初篩僅看當期 ROE（資料源無近3年欄位），真正的「近4年至少3年達標」在品質關硬性把關。<br>
<b>盈再率</b>＝四年來（固資+長投）的增加 ÷ 四年稅後淨利，看「賺的錢留不留得住」。
<span style="color:#34D399">綠 &lt;40% 理想</span>　<span style="color:#F5B841">黃 40~80% 可接受</span>
<span style="color:#FCA5A5">紅 ↓為負＝公司在縮表（處分資產），不等於資本效率好</span>
<span style="color:#FCA5A5">＊</span>＝資料不足、用 CapEx÷淨利 替代算法，<b>與官方公式偏差方向不定，不可比大小</b><br>
資料源：台股 FinMind、美股 SEC EDGAR 官方申報。本次 {n_official}/{n_total} 檔走官方公式。<br>
龍頭#N＝同 sector 市值前3（補充參考）　⚠ 照妖鏡＝forward EPS 衰退／負債&gt;{DE_HIGH}%
</div>
<div class="ctrl">
  <div class="seg" role="group" aria-label="切換市場">
    <button data-m="US" aria-pressed="true">美股</button>
    <button data-m="TW" aria-pressed="false">台股</button></div>
</div>
{body}
<p class="sub" style="margin-top:20px">產生於 {datetime.now():%Y-%m-%d %H:%M} · 資料源 TV-Screener + yfinance</p>
</div>
<script>
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let MKT='US';
function applyMkt(m){{MKT=m;
 $$('.seg button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.m===m));
 $$('.sec').forEach(s=>s.style.display=s.dataset.mkt===m?'':'none');}}
$$('.seg button').forEach(b=>b.onclick=()=>applyMkt(b.dataset.m));
$$('.sc.f').forEach(b=>b.onclick=()=>{{const box=b.closest('.sec');
 box.querySelectorAll('.sc.f').forEach(x=>x.setAttribute('aria-pressed',x===b));
 box.querySelectorAll('.row').forEach(r=>{{const v=b.dataset.f==='all'||r.dataset.sig===b.dataset.f;
  r.style.display=v?'':'none';
  const d=box.querySelector(`.detail[data-for="${{r.dataset.id}}"]`);
  if(d&&!v)d.style.display='none';}});}});
$$('.row').forEach(r=>r.onclick=()=>{{const d=$(`.detail[data-for="${{r.dataset.id}}"]`),
 open=r.getAttribute('aria-expanded')==='true';
 r.setAttribute('aria-expanded',!open);d.classList.toggle('on',!open);
 d.style.display=!open?'block':'none';}});
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/buffett.html")
    args = ap.parse_args()
    if not os.path.exists("buffett_watch.json"):
        print("無 buffett_watch.json，跳過")
        return
    watch = json.load(open("buffett_watch.json", encoding="utf-8"))
    html = build(watch)
    for out in [args.output, os.path.join(OBIS, "巴菲特價值清單.html")]:
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            open(out, "w", encoding="utf-8").write(html)
            print(f"✅ 已存:{out}")
        except Exception as e:
            print(f"⚠️ 寫 {out} 失敗:{e}")


if __name__ == "__main__":
    main()
