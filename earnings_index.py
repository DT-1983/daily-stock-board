"""財報深度分析索引頁 → docs/earnings.html

用戶指示（2026-08-03）：財報獨立一個頁面，不要擠在看板頁首。
掃 docs/earnings_*.html，讀每份的標題／季別／洪瑞泰結論，做成一覽。

用法：python earnings_index.py [-o docs/earnings.html]
"""
import os
import re
import io
import sys
import glob
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"


def parse_card(path: str) -> dict:
    """從已產生的懶人包 HTML 反推摘要資訊（不重跑 yfinance，純解析）。"""
    h = io.open(path, encoding="utf-8").read()
    def m(p, d=""):
        r = re.search(p, h, re.S)
        return r.group(1).strip() if r else d
    ticker = os.path.basename(path)[9:-5].replace("_", ".")
    return {
        "file": os.path.basename(path),
        "ticker": ticker,
        "name": m(r'<h1>([^<]*)</h1>', ticker),
        "quarter": m(r'<div class="sub">([^·]*?)財報懶人包'),
        "period": m(r'會計期間截至\s*([\d-]+)'),
        "consensus": m(r'class="bg" style="color:[^"]*">([^<]*)</div>'),
        "bottom": re.sub(r"<[^>]+>", "", m(r'<div class="c">(.*?)</div>')),
        "gates": len(re.findall(r'✅ 過', h)),
        "gates_bad": len(re.findall(r'❌ 不過', h)),
        "mtime": os.path.getmtime(path),
    }


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#020617;--surface:#0F172A;--line:#1E293B;--ink:#F8FAFC;
 --muted:#94A3B8;--dim:#64748B;--accent:#3B82F6}
body{background:var(--bg);color:var(--ink);line-height:1.55;font-size:15px;
 font-family:Inter,-apple-system,"Microsoft JhengHei","PingFang TC",sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:900px;margin:0 auto;padding:16px 14px 60px}
.num{font-family:'Fira Code',monospace;font-variant-numeric:tabular-nums}
header{padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:18px}
h1{font-size:20px;font-weight:800;display:flex;align-items:center;gap:9px;letter-spacing:-.3px}
.sub{color:var(--muted);font-size:12.5px;margin-top:6px;line-height:1.7}
.back{display:inline-flex;align-items:center;gap:6px;margin-top:12px;padding:8px 13px;
 min-height:38px;border:1px solid var(--line);border-radius:9px;background:var(--surface);
 color:#BFDBFE;text-decoration:none;font-size:12.5px;font-weight:600;transition:border-color .18s}
.back:hover,.back:focus-visible{border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(272px,1fr));gap:11px}
.card{display:block;background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px;text-decoration:none;color:inherit;transition:border-color .18s,transform .18s}
.card:hover,.card:focus-visible{border-color:var(--accent);transform:translateY(-2px)}
.crow{display:flex;justify-content:space-between;align-items:flex-start;gap:9px}
.tk{font-size:17px;font-weight:800;letter-spacing:-.2px}
.nm{color:var(--dim);font-size:11.5px;margin-top:1px;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.badge{font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px;flex-shrink:0}
.q{color:var(--muted);font-size:11.5px;margin-top:8px}
.gates{display:flex;gap:5px;margin-top:9px}
.gv{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:5px}
.ok{background:#052e16;color:#4ADE80}.no{background:#2E1418;color:#FCA5A5}
.bl{color:#C7D8EC;font-size:12px;line-height:1.6;margin-top:10px;
 border-top:1px solid #16223A;padding-top:9px}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:12px;
 padding:34px 20px;text-align:center;color:var(--muted);font-size:13.5px;line-height:1.8}
.note{color:var(--dim);font-size:11.5px;margin-top:26px;padding-top:14px;
 border-top:1px solid var(--line);line-height:1.8}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

BADGE = {"STRONG BUY": ("#0E3A22", "#22C55E"), "BUY": ("#0E3A22", "#22C55E"),
         "HOLD": ("#3A3212", "#F5B841"), "UNDERPERFORM": ("#3A1A18", "#EF4444"),
         "SELL": ("#3A1418", "#EF4444")}


def build(cards):
    if cards:
        items = []
        for c in cards:
            bg, fg = BADGE.get(c["consensus"], ("#22374F", "#8FA8C8"))
            gates = ""
            if c["gates"] or c["gates_bad"]:
                gates = (f'<div class="gates">'
                         f'<span class="gv ok">洪瑞泰過 {c["gates"]}</span>'
                         f'<span class="gv no">不過 {c["gates_bad"]}</span></div>')
            items.append(
                f'<a class="card" href="{c["file"]}">'
                f'<div class="crow"><div style="min-width:0">'
                f'<div class="tk num">{c["ticker"]}</div>'
                f'<div class="nm">{c["name"]}</div></div>'
                f'<span class="badge" style="background:{bg};color:{fg}">{c["consensus"] or "—"}</span>'
                f'</div>'
                f'<div class="q">{c["quarter"]}　·　截至 {c["period"]}</div>'
                f'{gates}'
                f'<div class="bl">{c["bottom"][:90]}</div></a>')
        content = f'<div class="grid">{"".join(items)}</div>'
    else:
        content = ('<div class="empty">還沒有任何財報分析。<br>'
                   '財報守望會在<b>你的持股公布財報後</b>自動產生（每季一次）。<br>'
                   '也可以手動跑：<code>python earnings_infographic.py TSLA</code></div>')

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>財報深度分析</title>
<style>{CSS}</style></head><body><div class="wrap">
<header>
  <h1><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3B82F6"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <path d="M14 2v6h6M8 13h8M8 17h5"/></svg>財報深度分析</h1>
  <div class="sub">單檔財報懶人包 · <b style="color:#CBD5E1">兩套策略並列</b>：
    洪瑞泰三大關卡（ROE／盈再率／配息率）＋ 俗貴價　｜　分析師共識 ＋ 估值倍數<br>
    兩者可能給相反結論，那是不同策略的正常結果，不是資料錯誤。</div>
  <a class="back" href="./"><svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    回產業鏈看板</a>
</header>
{content}
<div class="note">
  每季自動更新（4/5、5/20、8/19、11/19），由 <code>earnings_watch.py</code> 在持股公布財報後觸發。<br>
  所有財務數字取自 yfinance 實際申報財報，未經 AI 生成；AI 只負責文字敘述。<br>
  產生於 {datetime.now():%Y-%m-%d %H:%M}
</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="docs/earnings.html")
    ap.add_argument("--obis", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob("docs/earnings_*.html"), key=os.path.getmtime, reverse=True)
    cards = []
    for f in files:
        try:
            cards.append(parse_card(f))
        except Exception as e:
            print(f"  ⚠️ 解析 {f} 失敗：{e}")
    html = build(cards)
    targets = [args.output] + ([os.path.join(OBIS, "財報深度分析.html")] if args.obis else [])
    for p in targets:
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            open(p, "w", encoding="utf-8").write(html)
            print(f"✅ {p}（{len(cards)} 份）")
        except Exception as e:
            print(f"⚠️ 寫入 {p} 失敗：{e}")


if __name__ == "__main__":
    main()
