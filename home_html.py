"""投資資訊首頁 → docs/index.html

2026-08-04 改版：首頁從「產業鏈看板」換成「股市動態儀表板」，
看板搬到 board.html。首頁內容：
  1. 大盤行情（market_data.json：美股四大＋台股加權＋VIX＋美元/台幣）
  2. 今日頭條（鉅亨網 台股 5＋國際 5）
  3. 各分頁快速入口（帶動態一行摘要：GDP 狀態燈、賽馬領先策略、巴菲特追蹤數…）

更新排程：早上 09:00（tw-board.yml）＋台股收盤後 14:05（market-home.yml）。

用法：python home_html.py [-o docs/index.html]
"""
import os
import sys
import json
import glob
import argparse
from datetime import datetime

from board_theme import BASE_CSS, header, icon, esc, NAV

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
GDP_STATUS_COLOR = {"尚未到頂": "#22C55E", "接近高點": "#EAB308", "已過高點": "#EF4444"}

CSS_EXTRA = """
.idxgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:12px 0}
@media(max-width:700px){.idxgrid{grid-template-columns:repeat(2,1fr)}}
.idx{background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:11px 13px}
.idx .nm{font-size:11.5px;color:var(--muted);font-weight:600}
.idx .px{font-size:17px;font-weight:700;margin-top:3px}
.idx .chg{font-size:12px;font-weight:700;margin-top:2px}
.idx .dt{font-size:10px;color:var(--dim);margin-left:5px;font-weight:400}
.newsbox{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--surface);margin:12px 0}
.nrow{display:block;padding:11px 13px;border-bottom:1px solid var(--line2);
 text-decoration:none;transition:background .15s}
.nrow:last-child{border-bottom:0}
.nrow:hover{background:#16223A}
.nrow .tt{font-size:13.5px;line-height:1.5;color:var(--ink)}
.nrow .mt{font-size:11px;color:var(--dim);margin-top:3px}
.mtag{display:inline-block;font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:4px;
 margin-right:6px;vertical-align:1px}
.mtag.tw{background:#14532D44;color:#86EFAC}
.mtag.us{background:#1E3A8A44;color:#93C5FD}
.entries{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:9px;margin:12px 0}
.entry{display:flex;align-items:center;gap:11px;background:var(--surface);
 border:1px solid var(--line);border-radius:12px;padding:13px 14px;text-decoration:none;
 transition:border-color .18s,background .18s}
.entry:hover{border-color:var(--accent);background:#152238}
.entry .eic{width:36px;height:36px;border-radius:9px;background:#1E3A5F;display:grid;
 place-items:center;flex-shrink:0}
.entry .et{flex:1;min-width:0}
.entry .en{font-size:13.5px;font-weight:700;color:var(--ink)}
.entry .es{font-size:11.5px;color:var(--muted);margin-top:2px;line-height:1.5}
.entry svg.chv{opacity:.35;flex-shrink:0}
.gdot{display:inline-block;width:7px;height:7px;border-radius:50%;margin:0 4px 0 1px;vertical-align:middle}
.hsec{margin-top:20px}
.hsec h2{font-size:15px;font-weight:700;display:flex;align-items:center;gap:7px}
.hsec .hnote{font-size:11px;color:var(--dim);margin-top:2px}
"""


def _load(path):
    p = os.path.join(HERE, path)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return None
    return None


def idx_card(i):
    if i.get("fmt") == "yield":  # 美債殖利率：值顯示 %、漲跌顯示 bp
        chg = i["chg_bp"]
        cls = "pos" if chg > 0 else ("neg" if chg < 0 else "flat")
        return (f'<div class="idx"><div class="nm">{esc(i["name"])}</div>'
                f'<div class="px num">{i["close"]:.2f}%</div>'
                f'<div class="chg num {cls}">{chg:+.1f} bp<span class="dt">{esc(i["date"])} 收</span></div></div>')
    chg = i["chg_pct"]
    cls = "pos" if chg > 0 else ("neg" if chg < 0 else "flat")
    return (f'<div class="idx"><div class="nm">{esc(i["name"])}</div>'
            f'<div class="px num">{i["close"]:,.2f}</div>'
            f'<div class="chg num {cls}">{chg:+.2f}%<span class="dt">{esc(i["date"])} 收</span></div></div>')


def inst_card(inst):
    """三大法人買賣超（上市）。買超綠、賣超紅，跟全站漲跌色一致。"""
    if not inst:
        return ('<div class="idx"><div class="nm">三大法人買賣超</div>'
                '<div class="px num">—</div><div class="chg flat">資料未取得</div></div>')
    t = inst["total_yi"]
    cls = "pos" if t > 0 else ("neg" if t < 0 else "flat")
    word = "買超" if t > 0 else ("賣超" if t < 0 else "持平")  # 用字講明白，正負號易誤讀
    return (f'<div class="idx"><div class="nm">三大法人（上市）</div>'
            f'<div class="px {cls}">{word} <span class="num">{abs(t):,.0f}</span> 億</div>'
            f'<div class="chg num flat" style="font-weight:400">'
            f'外資 {inst["foreign_yi"]:+,.0f} · 投信 {inst["trust_yi"]:+,.0f} 億'
            f'<span class="dt">· {esc(inst["date"])}</span></div></div>')


def news_row(n):
    tag = f'<span class="mtag {n["mkt"].lower()}">{ "台股" if n["mkt"]=="TW" else "國際" }</span>'
    return (f'<a class="nrow" href="{esc(n["url"])}" target="_blank" rel="noopener">'
            f'<div class="tt">{tag}{esc(n["title"])}</div>'
            f'<div class="mt">{esc(n["ts"])} · 鉅亨網</div></a>')


def entry(key, name, summary, href):
    return (f'<a class="entry" href="{href}"><span class="eic">{icon(key, 18, "#93C5FD")}</span>'
            f'<span class="et"><span class="en">{esc(name)}</span>'
            f'<span class="es" style="display:block">{summary}</span></span>'
            f'{icon("chevron", 15)}</a>')


def build_summaries():
    """各分頁的一行動態摘要，任何來源缺檔都退回靜態文字。"""
    s = {"board": "七條產業鏈 · 美股／台股每日訊號",
         "buffett": "洪瑞泰俗貴價法選股清單",
         "portfolio": "三主策略＋七產業鏈績效對決",
         "earnings": "每季財報圖卡（洪瑞泰＋分析師共識雙軌）",
         "gdp": "GDP 高點賣股票、不買股票",
         "ark": "ARKK/ARKW/ARKG 產業方向＋重倉法說會＋回測"}

    w = _load("buffett_watch.json")
    if w:
        upd = next((v.get("updated") for v in w.values() if v.get("updated")), None)
        s["buffett"] = f"追蹤 {len(w)} 檔" + (f" · 資料 {upd}" if upd else "")

    p = _load("portfolios.json")
    if p:
        mains = {k: p["portfolios"][k].get("ret") for k in p.get("main", [])
                 if k in p.get("portfolios", {})}
        mains = {k: v for k, v in mains.items() if v is not None}
        if mains:
            top = max(mains, key=mains.get)
            s["portfolio"] = f"領先：{top} <b class='num'>{mains[top]:+.2f}%</b>（{p.get('updated','')}）"

    n_earn = len(glob.glob(os.path.join(HERE, "docs", "earnings_*.html")))
    if n_earn:
        s["earnings"] = f"{n_earn} 檔財報圖卡 · 洪瑞泰＋分析師共識雙軌"

    g = _load("gdp_data.json")
    if g and g.get("peak"):
        parts = []
        for flag, k in (("美", "us"), ("台", "tw")):
            st = g["peak"][k]["status"]
            col = GDP_STATUS_COLOR.get(st, "#64748B")
            parts.append(f'{flag}<span class="gdot" style="background:{col}"></span>{st}')
        s["gdp"] = " · ".join(parts)
    return s


def build():
    m = _load("market_data.json") or {"updated": "—", "indices": [], "news": []}
    s = build_summaries()

    # 2 排 × 4 格（用戶 2026-08-04 定版）：美股 4 檔｜台股加權、法人、匯率、美債殖利率
    cards = []
    for i in m["indices"]:
        cards.append(idx_card(i))
        if i["sym"] == "^TWII":  # 法人卡緊跟在台股加權後面
            cards.append(inst_card(m.get("inst")))
    idx_html = "".join(cards) or \
        '<div class="empty">尚無行情資料，先跑 python market_fetch.py</div>'
    news_html = "".join(news_row(n) for n in m["news"]) or \
        '<div class="empty" style="border:0">尚無新聞資料</div>'

    entries_html = "".join([
        entry("board", "產業鏈看板", s["board"], "board.html"),
        entry("buffett", "巴菲特價值清單", s["buffett"], "buffett.html"),
        entry("portfolio", "策略賽馬模擬倉", s["portfolio"], "portfolios.html"),
        entry("earnings", "財報深度分析", s["earnings"], "earnings.html"),
        entry("gdp", "GDP 觀察", s["gdp"], "gdp.html"),
        entry("ark", "ARK ETF 追蹤", s["ark"], "ark.html"),
    ])

    # 行情過期警示（2026-08-19）：market_fetch.py 失敗時 workflow 會沿用舊的
    # market_data.json 照樣畫首頁。標題的時間本來就是「資料時間」不是「畫圖時間」
    # （這點原本就沒騙人），但只是一個小小的日期，落後了不容易注意到 → 明講出來。
    # 只比日期不比時分：盤中每次更新時分本來就會不同，比到分會天天誤報。
    stale_note = ""
    try:
        data_day = str(m["updated"])[:10]
        today = datetime.now().strftime("%Y-%m-%d")
        if data_day and data_day != today:
            stale_note = (f'<div class="stalewarn">⚠️ 大盤行情停在 <b>{esc(m["updated"])}</b>，'
                          f'今天（{today}）沒有抓到新行情。'
                          f'下方價格是上次成功抓取的，不是最新的。'
                          f'<br><span style="font-size:12px">（頭條新聞與下方各分頁入口不受影響）</span></div>')
    except Exception:   # noqa: BLE001
        pass

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>投資資訊首頁</title>
<style>{BASE_CSS}{CSS_EXTRA}</style></head><body><div class="wrap">
{header("home", "投資資訊首頁", f"行情更新 {esc(m['updated'])} · 平日 09:00／15:10 自動更新", NAV, "home")}
{stale_note}
<div class="hsec"><h2>{icon("board", 16, "#3B82F6")}大盤行情</h2>
<div class="hnote">漲跌為對前一交易日收盤；美股為美東前一晚收盤</div>
<div class="idxgrid">{idx_html}</div></div>
<div class="hsec"><h2>{icon("earnings", 16, "#3B82F6")}今日頭條</h2>
<div class="hnote">鉅亨網 台股 5 條＋國際 5 條，依發布時間排序</div>
<div class="newsbox">{news_html}</div></div>
<div class="hsec"><h2>{icon("chevron", 16, "#3B82F6")}分頁入口</h2>
<div class="entries">{entries_html}</div></div>
<p class="sub" style="margin-top:20px">產生於 {datetime.now():%Y-%m-%d %H:%M} ·
行情 yfinance · 新聞 鉅亨網 · 顏色語彙：綠漲紅跌（與全站訊號色一致）</p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/index.html")
    args = ap.parse_args()
    html = build()
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    open(args.output, "w", encoding="utf-8").write(html)
    print(f"✅ 已存 {args.output}")


if __name__ == "__main__":
    main()
