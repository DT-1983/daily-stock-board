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

from board_theme import BASE_CSS, header, icon, esc, NAV, LOOKUP_BOX, LOOKUP_CSS

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
GDP_STATUS_COLOR = {"尚未到頂": "#22C55E", "接近高點": "#EAB308", "已過高點": "#EF4444"}

CSS_EXTRA = """
/* 每週總體報告摘要（2026-09-14 Leo：「整合在投資資訊首頁，一樣要分美、台股」）
   ⚠️ 字級一律對齊首頁既有的角色，不要自己另訂一套（Leo：「字體大小要一致」）：
     .mkt 11.5px = .idx .nm（卡片標籤）
     .stc 17px   = .idx .px（卡片的主數字／結論）
     .hl  13.5px = .nrow .tt／.entry .en（卡片主文）
     .ang 11.5px = .entry .es（次要說明）
     .xtra 11px  = .nrow .mt（附註）                                        */
.mwgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}
@media(max-width:700px){.mwgrid{grid-template-columns:1fr}}
.mwcard{background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:12px 14px}
.mwcard .mkt{font-size:11.5px;color:var(--muted);font-weight:600;margin-bottom:7px}
.mwcard .hl{font-size:13.5px;line-height:1.65;color:var(--ink);margin-top:8px}
.mwcard .ang{font-size:11.5px;color:var(--muted);margin-top:7px;line-height:1.8}
.mwcard .ang b{color:var(--ink);font-weight:600}
.mwcard .xtra{font-size:11px;color:var(--dim);margin-top:8px;
 padding-top:7px;border-top:1px solid var(--line2)}
.stc{display:inline-block;font-size:17px;font-weight:800;letter-spacing:.04em;
 padding:3px 13px;border-radius:7px}
/* 展開細節：用 <details> 不用 JS，靜態頁最不容易壞 */
.mwmore{margin-top:9px;border-top:1px solid var(--line2);padding-top:7px}
.mwmore>summary{cursor:pointer;font-size:11px;color:var(--muted);list-style:none;
 padding:2px 0}
.mwmore>summary::-webkit-details-marker{display:none}
.mwmore>summary::before{content:"▸ ";color:var(--dim)}
.mwmore[open]>summary::before{content:"▾ "}
.mwmore>summary:hover{color:#93C5FD}
.mwd{font-size:11.5px;line-height:1.75;margin-top:7px}
.mwd .lbl{color:var(--dim);font-size:11px}
.mwd .blk{margin:8px 0;padding-left:9px;border-left:2px solid var(--line)}
.mwd .rs{color:var(--ink)}
.mwd .fx{color:#FCA5A5;font-size:11px;margin-top:3px}
.mwd .cl{margin:5px 0;color:var(--muted)}
.mwd .tg{display:inline-block;font-size:9.5px;padding:1px 6px;border-radius:4px;
 margin-right:5px;font-weight:600}
.tg-observed{background:#0E2417;color:#86EFAC;border:1px solid #166534}
.tg-inference{background:#0E1B2B;color:#9DB0C8;border:1px solid var(--line)}
.tg-speculation{background:#2E1418;color:#FCA5A5;border:1px solid #7F1D1D}
.mwd .bs{color:var(--dim);font-size:10px}
.stc-積極{background:#0E2417;color:#4ADE80;border:1px solid #166534}
.stc-偏積極{background:#0E2417;color:#86EFAC;border:1px solid #166534}
.stc-中性{background:#0E1B2B;color:#9DB0C8;border:1px solid var(--line)}
.stc-偏保守{background:#2E1418;color:#FCA5A5;border:1px solid #7F1D1D}
.stc-保守{background:#2E1418;color:#F87171;border:1px solid #7F1D1D}
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
.nrow:hover{background:#0E1B2B}
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


def macro_block():
    """每週總體報告摘要（美股／台股分開）。

    來源 `docs/macro_weekly.json` 由本機的 `macro_weekly.py` 週一產出後，
    跟著每日批次的 `git add docs` 進 repo；這支在 GitHub Actions 上跑，
    只讀得到 repo 裡的東西，所以才走 docs/ 不走 state/。
    ⚠️ 沒有這個檔就整段不顯示——首頁其他區塊照常，不要因為多一段而壞掉。
    """
    d = _load("docs/macro_weekly.json") or _load("macro_weekly.json")
    if not d or not d.get("us"):
        return ""

    KIND = {"observed": "有數據", "inference": "推論", "speculation": "推測·無數據"}

    def card(key, label):
        mk = d.get(key) or {}
        st = mk.get("stance") or "中性"
        angles = mk.get("angles") or []
        angs = "".join(
            f'<div>· {esc(a.get("name",""))}：<b>{esc(a.get("verdict",""))}</b></div>'
            for a in angles)
        xtra = ""
        if key == "tw":
            bits = []
            lt = mk.get("景氣燈號") or {}
            if lt.get("light"):
                bits.append(f'景氣對策信號 {esc(lt["light"])}燈 {lt.get("score")}分'
                            f'（{esc(str(lt.get("month","")))}）')
            g = mk.get("GDP") or {}
            if g.get("value") is not None:
                bits.append(f'GDP {esc(g.get("period",""))} 年增 {g.get("value")}%')
            if bits:
                xtra = f'<div class="xtra">{"　".join(bits)}</div>'

        # 展開後才顯示的細節（2026-09-14 Leo：「可以做點下去看得到資料嗎？」）
        det = ""
        basis = mk.get("stance_basis")
        if basis:
            det += f'<div class="blk"><span class="lbl">表態依據</span><br>{esc(basis)}</div>'
        for a in angles:
            if not (a.get("reason") or a.get("falsifier")):
                continue
            det += (f'<div class="blk"><span class="lbl">{esc(a.get("name",""))}</span>'
                    f'　<b>{esc(a.get("verdict",""))}</b>'
                    f'<div class="rs">{esc(a.get("reason",""))}</div>'
                    + (f'<div class="fx">✕ 失效條件：{esc(a["falsifier"])}</div>'
                       if a.get("falsifier") else "") + '</div>')
        cls = mk.get("claims") or []
        if cls:
            rows = "".join(
                f'<div class="cl"><span class="tg tg-{esc(c.get("kind","inference"))}">'
                f'{esc(KIND.get(c.get("kind"), "推論"))}</span>{esc(c.get("text",""))}'
                + (f'<br><span class="bs">依據：{esc(c["basis"])}</span>' if c.get("basis") else "")
                + '</div>' for c in cls)
            det += f'<div class="blk"><span class="lbl">支撐的事實與推論</span>{rows}</div>'
        more = (f'<details class="mwmore"><summary>看依據與失效條件</summary>'
                f'<div class="mwd">{det}</div></details>') if det else ""

        return (f'<div class="mwcard"><div class="mkt">{label}</div>'
                f'<span class="stc stc-{esc(st)}">{esc(st)}</span>'
                f'<div class="hl">{esc(mk.get("headline",""))}</div>'
                f'<div class="ang">{angs}</div>{xtra}{more}</div>')

    link = esc(d.get("linkage") or "")
    return (f'<div class="hsec"><h2>{icon("gdp", 16, "#3B82F6")}每週總體判讀</h2>'
            f'<div class="hnote">投資長 孔明 每週一判讀 · '
            f'{esc(d.get("week_of",""))} 週 · 數字全部取自官方公開來源</div>'
            # ⚠️ 不要用 🇺🇸🇹🇼 這種 regional indicator 國旗 emoji：
            #    Windows 內建字型不支援，會退化成 "us" / "tw" 兩個字母
            #    （2026-09-14 Leo 截圖就是這樣）。手機看得到、桌機看不到＝更難發現。
            #    Discord 那邊維持用國旗沒問題（Discord 有自己的 emoji 字型）。
            f'<div class="mwgrid">{card("us", "美股")}{card("tw", "台股")}</div>'
            + (f'<div class="hnote" style="margin-top:2px">🔗 {link}</div>' if link else "")
            + '</div>')


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
<style>{BASE_CSS}{CSS_EXTRA}{LOOKUP_CSS}</style></head><body><div class="wrap">
{header("home", "投資資訊首頁", f"行情更新 {esc(m['updated'])} · 平日 09:00／15:10 自動更新", NAV, "home")}
{stale_note}
<div class="hsec"><h2>{icon("board", 16, "#3B82F6")}大盤行情</h2>
<div class="hnote">漲跌為對前一交易日收盤；美股為美東前一晚收盤</div>
<div class="idxgrid">{idx_html}</div></div>
{macro_block()}
<div class="hsec"><h2>{icon("earnings", 16, "#3B82F6")}今日頭條</h2>
<div class="hnote">鉅亨網 台股 5 條＋國際 5 條，依發布時間排序</div>
<div class="newsbox">{news_html}</div></div>
<div class="hsec"><h2>{icon("chevron", 16, "#3B82F6")}查任意股票</h2>
<div class="hnote">不限本站掃描母體；台股可直接打中文名（台積電）。
每台裝置第一次要用帶 key 的網址授權一次，之後記住 90 天</div>
{LOOKUP_BOX}</div>
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
