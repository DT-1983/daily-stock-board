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

from board_theme import BASE_CSS, header, NAV  # noqa: E402  統一頁首（2026-08-04 首頁改版）

# 2026-09-05 資料夾整理：路徑一律走 obis_paths，不再各自寫死。
from obis_paths import DAILY as OBIS


def parse_card(path: str) -> dict:
    """從已產生的懶人包 HTML 反推摘要資訊（不重跑 yfinance，純解析）。"""
    h = io.open(path, encoding="utf-8").read()
    def m(p, d=""):
        r = re.search(p, h, re.S)
        return r.group(1).strip() if r else d
    ticker = os.path.basename(path)[9:-5].replace("_", ".")
    market = "TW" if re.match(r"^\d{4,5}$", ticker) else "US"
    return {
        "file": os.path.basename(path),
        "ticker": ticker,
        "market": market,
        "name": m(r'<h1>([^<]*)</h1>', ticker),
        "quarter": m(r'<div class="sub">([^·]*?)財報懶人包'),
        "period": m(r'會計期間截至\s*([\d-]+)'),
        "consensus": m(r'class="bg" style="color:[^"]*">([^<]*)</div>'),
        "bottom": re.sub(r"<[^>]+>", "", m(r'<div class="c">(.*?)</div>')),
        "gates": len(re.findall(r'✅ 過', h)),
        "gates_bad": len(re.findall(r'❌ 不過', h)),
        "mtime": os.path.getmtime(path),
    }


CSS_EXTRA = """
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(272px,1fr));gap:11px;margin-top:16px}
.ecard{display:block;background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:14px;text-decoration:none;color:inherit;transition:border-color .18s,transform .18s}
.ecard:hover,.ecard:focus-visible{border-color:var(--accent);transform:translateY(-2px)}
.crow{display:flex;justify-content:space-between;align-items:flex-start;gap:9px}
.crow .tk{font-size:17px;font-weight:800;letter-spacing:-.2px}
.crow+.q,.q{color:var(--muted);font-size:11.5px;margin-top:8px}
.ecard .nm{color:var(--dim);font-size:11.5px;margin-top:1px;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap;max-width:none;display:block}
.badge{font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px;flex-shrink:0}
.gates{display:flex;gap:5px;margin-top:9px}
.gv{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:5px}
.ok{background:#052e16;color:#4ADE80}.no{background:#2E1418;color:#FCA5A5}
.bl{color:#C7D8EC;font-size:12px;line-height:1.6;margin-top:10px;
 border-top:1px solid #16223A;padding-top:9px}
.enote{color:var(--dim);font-size:11.5px;margin-top:26px;padding-top:14px;
 border-top:1px solid var(--line);line-height:1.8}
"""

BADGE = {"STRONG BUY": ("#0E3A22", "#22C55E"), "BUY": ("#0E3A22", "#22C55E"),
         "HOLD": ("#3A3212", "#F5B841"), "UNDERPERFORM": ("#3A1A18", "#EF4444"),
         "SELL": ("#3A1418", "#EF4444")}


def build(cards):
    if cards:
        n_us = sum(1 for c in cards if c["market"] == "US")
        n_tw = sum(1 for c in cards if c["market"] == "TW")
        seg = (f'<div class="ctrl" style="position:static;padding:0 0 12px;border-bottom:0;margin-bottom:0">'
               f'<div class="seg" id="mktSeg">'
               f'<button data-m="ALL" aria-pressed="true">全部 {len(cards)}</button>'
               f'<button data-m="US" aria-pressed="false">美股 {n_us}</button>'
               f'<button data-m="TW" aria-pressed="false">台股 {n_tw}</button>'
               f'</div></div>')
        items = []
        for c in cards:
            bg, fg = BADGE.get(c["consensus"], ("#22374F", "#8FA8C8"))
            gates = ""
            if c["gates"] or c["gates_bad"]:
                gates = (f'<div class="gates">'
                         f'<span class="gv ok">洪瑞泰過 {c["gates"]}</span>'
                         f'<span class="gv no">不過 {c["gates_bad"]}</span></div>')
            items.append(
                f'<a class="ecard" data-mkt="{c["market"]}" href="{c["file"]}">'
                f'<div class="crow"><div style="min-width:0">'
                f'<div class="tk num">{c["ticker"]}</div>'
                f'<div class="nm">{c["name"]}</div></div>'
                f'<span class="badge" style="background:{bg};color:{fg}">{c["consensus"] or "—"}</span>'
                f'</div>'
                f'<div class="q">{c["quarter"]}　·　截至 {c["period"]}</div>'
                f'{gates}'
                f'<div class="bl">{c["bottom"][:90]}</div></a>')
        content = f'{seg}<div class="grid" id="ecardGrid">{"".join(items)}</div>'
    else:
        content = ('<div class="empty">還沒有任何財報分析。<br>'
                   '財報守望會在<b>你的持股公布財報後</b>自動產生（每季一次）。<br>'
                   '也可以手動跑：<code>python earnings_infographic.py TSLA</code></div>')

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>財報深度分析</title>
<style>{BASE_CSS}{CSS_EXTRA}</style></head><body><div class="wrap">
{header("earnings", "財報深度分析",
  f'{len(cards)} 檔 · 更新 {datetime.now():%Y-%m-%d %H:%M} · 財報季由 earnings_watch 自動補卡，'
  f'平時手動指定個股<br><b>兩套策略並列</b>：洪瑞泰三大關卡（ROE／盈再率／配息率）＋俗貴價'
  '　｜　分析師共識＋估值倍數。兩者可能給相反結論，那是不同策略的正常結果，不是資料錯誤。',
  NAV, "earnings")}
{content}
<div class="enote">
  每季自動更新（4/5、5/20、8/19、11/19），由 <code>earnings_watch.py</code> 在持股公布財報後觸發。<br>
  所有財務數字取自 yfinance 實際申報財報，未經 AI 生成；AI 只負責文字敘述。<br>
  產生於 {datetime.now():%Y-%m-%d %H:%M}
</div>
</div>
<script>
(function(){{
  var seg = document.getElementById('mktSeg');
  if(!seg) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll('#ecardGrid .ecard'));
  seg.addEventListener('click', function(e){{
    var b = e.target.closest('button');
    if(!b) return;
    Array.prototype.forEach.call(seg.querySelectorAll('button'), function(x){{
      x.setAttribute('aria-pressed', x === b);
    }});
    var m = b.dataset.m;
    cards.forEach(function(c){{
      c.style.display = (m === 'ALL' || c.dataset.mkt === m) ? '' : 'none';
    }});
  }});
}})();
</script>
</body></html>"""


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
