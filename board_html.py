"""把美股分析報告做成「按 7 條鏈分區」的 HTML 儀表板(繁中、手機友善)

用法:python board_html.py reports/report_YYYYMMDD.md [-o out.html]
不指定 -o 時存到 obis 04_AI Report/Investment/YYYY-MM-DD_美股看板.html
"""
import sys
import os
import re
import argparse
from datetime import datetime
import markdown as md
from tw_report import convert  # 繁中 OpenCC + 台灣金融詞典

OBIS = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"

# ticker → 7 條鏈
CHAIN_MAP = {
    "NVDA": "AI 伺服器", "AVGO": "AI 伺服器",
    "ALAB": "矽光子/光通訊", "CRDO": "矽光子/光通訊",
    "RKLB": "低軌衛星", "ASTS": "低軌衛星",
    "FSLR": "太陽能",
    "CORZ": "Bitcoin→AI 機房", "IREN": "Bitcoin→AI 機房",
    "CEG": "AI 電力/核能", "VST": "AI 電力/核能",
    "TSLA": "機器人",
}
CHAIN_ORDER = ["AI 伺服器", "矽光子/光通訊", "機器人", "低軌衛星",
               "AI 電力/核能", "太陽能", "Bitcoin→AI 機房"]
CHAIN_ICON = {"AI 伺服器": "🖥️", "矽光子/光通訊": "🔦", "機器人": "🤖",
              "低軌衛星": "🛰️", "AI 電力/核能": "⚡", "太陽能": "☀️",
              "Bitcoin→AI 機房": "⛏️"}

SIG_CLASS = {"🔴": "sell", "🟢": "buy", "🔵": "hold", "🟡": "watch", "⚪": "watch"}

CSS = """
*{box-sizing:border-box}
body{font-family:"Microsoft JhengHei","PingFang TC",-apple-system,sans-serif;
 margin:0;background:#0f1115;color:#e6e6e6;line-height:1.6;font-size:15px}
.wrap{max-width:960px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0}
.sub{color:#9aa0a6;font-size:13px;margin-bottom:12px}
.nav{position:sticky;top:0;background:#0f1115;padding:10px 0;z-index:10;
 display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid #2a2e35}
.nav a{font-size:13px;text-decoration:none;color:#cfd3d8;background:#1c2128;
 padding:5px 10px;border-radius:14px;white-space:nowrap}
.chain{margin:22px 0 8px;font-size:17px;border-left:4px solid #4a9eff;padding-left:10px}
.card{background:#1a1d23;border:1px solid #2a2e35;border-radius:10px;margin:10px 0;overflow:hidden}
.card.sell{border-left:4px solid #ff5c5c}
.card.buy{border-left:4px solid #3ddc84}
.card.hold,.card.watch{border-left:4px solid #8a8f98}
summary{cursor:pointer;padding:12px 14px;list-style:none;display:flex;
 align-items:center;gap:8px;flex-wrap:wrap}
summary::-webkit-details-marker{display:none}
.tk{font-weight:700;font-size:16px}
.nm{color:#9aa0a6;font-size:13px}
.badge{margin-left:auto;font-size:13px;padding:2px 8px;border-radius:10px;background:#262b33}
.oneliner{flex-basis:100%;color:#cfd3d8;font-size:13.5px;margin-top:2px}
.detail{padding:0 14px 14px;border-top:1px solid #2a2e35}
.detail h3{font-size:14px;margin:14px 0 4px;color:#bcd2ff}
.detail table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}
.detail th,.detail td{border:1px solid #2a2e35;padding:5px 8px;text-align:left}
.detail th{background:#222831}
.detail blockquote{border-left:3px solid #4a9eff;margin:6px 0;padding:2px 10px;color:#cfd3d8}
.detail ul{padding-left:18px;margin:4px 0}
.empty{color:#6b7280;font-size:13px}
"""


def parse_report(text):
    """回傳 (summary_md, [(sig, ticker, name, block_md), ...])"""
    parts = re.split(r"(?m)^## ", text)
    summary, stocks = "", []
    for p in parts:
        if p.startswith("📊") or "分析結果摘要" in p[:20] or "分析结果摘要" in p[:20]:
            summary = p
        else:
            m = re.match(r"\s*([🔴🟢🔵🟡⚪])?\s*(.+?)\s*\(([A-Z\.]+)\)", p)
            if m:
                sig = m.group(1) or "⚪"
                name = m.group(2).strip()
                ticker = m.group(3).split(".")[0]
                stocks.append((sig, ticker, name, "## " + p))
    return summary, stocks


def oneliner(block):
    m = re.search(r"一句話決策\*\*[:：]\s*(.+)", block)
    return m.group(1).strip() if m else ""


def score(block):
    m = re.search(r"評分\s*(\d+)", block)
    return m.group(1) if m else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    raw = open(args.input, encoding="utf-8").read()
    raw = convert(raw)  # 轉繁中
    summary, stocks = parse_report(raw)

    # 依鏈分組
    by_chain = {c: [] for c in CHAIN_ORDER}
    other = []
    for sig, tk, nm, block in stocks:
        c = CHAIN_MAP.get(tk)
        (by_chain[c] if c else other).append((sig, tk, nm, block))

    date = datetime.now().strftime("%Y-%m-%d")
    mdconv = md.Markdown(extensions=["tables", "sane_lists"])

    # 導覽列(只列有股票的鏈)
    active = [c for c in CHAIN_ORDER if by_chain[c]]
    nav = "".join(f'<a href="#{i}">{CHAIN_ICON[c]} {c}</a>' for i, c in enumerate(active))

    body = []
    for i, c in enumerate(active):
        body.append(f'<div class="chain" id="{i}">{CHAIN_ICON[c]} {c}</div>')
        for sig, tk, nm, block in by_chain[c]:
            cls = SIG_CLASS.get(sig, "watch")
            ol = oneliner(block)
            sc = score(block)
            # 移除區塊第一行標題(已在卡片頭顯示)
            detail_md = re.sub(r"(?s)^##.*?\n", "", block, count=1)
            detail_html = mdconv.convert(detail_md)
            mdconv.reset()
            body.append(f'''<details class="card {cls}">
<summary><span class="tk">{sig} {tk}</span><span class="nm">{nm}</span>
<span class="badge">評分 {sc}</span>
<span class="oneliner">{ol}</span></summary>
<div class="detail">{detail_html}</div></details>''')

    summary_html = mdconv.convert(summary) if summary else ""
    mdconv.reset()

    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{date} 美股晨會看板</title><style>{CSS}</style></head><body><div class="wrap">
<h1>🎯 {date} 美股晨會看板</h1>
<div class="sub">按 7 條產業鏈分區 · 點卡片展開詳情 · 分析模型 Gemini</div>
<div class="nav">{nav}</div>
<div class="summary">{summary_html}</div>
{''.join(body)}
<div class="sub" style="margin-top:30px">產生時間 {datetime.now():%Y-%m-%d %H:%M}</div>
</div></body></html>"""

    if args.output:
        out = args.output
    else:
        os.makedirs(OBIS, exist_ok=True)
        out = os.path.join(OBIS, f"{date}_美股看板.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"✅ HTML 看板已存:{out}")


if __name__ == "__main__":
    main()
