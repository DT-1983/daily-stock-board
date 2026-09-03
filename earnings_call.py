# -*- coding: utf-8 -*-
"""法說會逐字稿摘要層 ——「管理層口頭重點」，補財報卡缺的公司自訂 KPI 與展望。

背景（2026-08-09）：比對第三方報告（PLTR/3037）發現，分部營收成長、客戶數、
RDV（剩餘合約價值）這類公司自訂 KPI，以及中長期毛利率目標、資本支出計畫、
產能爬坡時程這類管理層展望，都不在標準財報三表裡（yfinance/FinMind 抓不到），
但法說會逐字稿裡管理層通常會口頭唸出來。調查過 Finnhub／EarningsCall.dev／
Alpha Vantage 等逐字稿 API，多半要付費或免費層覆蓋率太差（只開 AAPL/MSFT）。

改用本機 headless Claude（Max plan、零 API 成本）：叫它自己上網搜尋 + 抓取
The Motley Fool（fool.com，公開免費逐字稿，備援 GuruFocus）+ 摘要成結構化 JSON，
比接一個要花錢的逐字稿 API 划算，也比自己寫爬蟲穩（頁面結構變動、URL 猜不到日期）。

`llm_board._ask_claude()` 用 `claude -p --dangerously-skip-permissions` 呼叫，
沒有停用工具，所以 WebSearch/WebFetch 在這個 subprocess 裡是可以用的。

架構教訓（2026-08-09）：schema 原本設計成 {found, highlights[], guidance, quote_zh}
巢狀物件，但本機 claude 不管怎麼提醒都習慣直接回傳一個扁平陣列，guidance/quote
這些額外欄位常常整個被丟掉——不是內容找不到，是格式設計跟模型的實際輸出習慣不合。
改成單一陣列＋type 分類（metric／guidance／quote），順著模型會自然回傳列表的習慣，
展望類內容才穩定進得來。

用法：
    from earnings_call import build
    html, summary_text = build(ticker, company_name, quarter_label)
"""
import io
import os
import json
import llm_board

_SCHEMA_HINT = """只能回傳一個 JSON 陣列，不要包在其他物件裡，不要有陣列以外的文字。
陣列每個元素格式：
{"type": "metric 或 guidance 或 quote", "label": "...", "value": "...", "speaker": "..."}

- type="metric"：本季已公布的具體數字（如：美國商業營收年增149%、客戶數653家）
- type="guidance"：管理層對未來的展望或目標，包含但不限於：
  下季/全年營收或毛利率展望、中長期毛利率或獲利目標、資本支出計畫與用途、
  新產能/新廠爬坡時程、產品/客戶佔比展望（如「AI營收占比預計從60%提升到70%」）
  label 用一句話說這是什麼展望，value 放管理層講的具體內容/數字
- type="quote"：管理層原話中最能代表這季基調的一句話，翻成繁體中文放在 value，
  speaker 填發言人姓名與職稱；非 quote 類型 speaker 留空字串即可

最多回 15 項，guidance 類型至少嘗試找 2-3 項（法說會通常都會提到未來展望，
不要只抓本季數字），找不到就別硬湊。

所有 label／value 一律用繁體中文書寫，不要簡體字：
- 「年增」「季增」要寫中文，不要寫 YoY／QoQ 這種英文縮寫
- RDV／RPO／TCV／EPS／FCF／ROE 這類財報術語縮寫維持英文（跟本站其他卡片一致），敘述文字一律中文
- 公司名稱、人名可保留英文原名
只萃取逐字稿裡**明確講出來**的數字或句子，不要用你自己的財務知識推算或補充。
完全找不到逐字稿時回傳空陣列 []。"""


def _prompt(ticker, company_name, quarter_label):
    return f"""你有 WebSearch 和 WebFetch 工具，請完成以下任務：

1. 用 WebSearch 搜尋「{ticker} {company_name} {quarter_label} earnings call transcript site:fool.com」，
   優先找 The Motley Fool（fool.com）上的公開逐字稿。如果 fool.com 沒有，改搜
   「{ticker} {quarter_label} earnings call transcript」找 GuruFocus 或其他免費公開全文來源
   （不要用需要訂閱/付費牆的來源，例如 Seeking Alpha 的付費文章）。
2. 找到候選網址後用 WebFetch 實際打開確認：
   - 內容必須是「{ticker}」公司「{quarter_label}」那一季的法說會逐字稿（不是新聞稿摘要、不是別一季）
   - 必須是完整逐字稿或至少包含管理層準備稿，不是三言兩語的短摘要
3. 從逐字稿裡萃取「不在標準財報三表裡、但管理層口頭提到」的內容，本季數字跟未來展望都要找：
   - 分部/地區營收成長、客戶數/淨新增客戶數、剩餘合約價值（RDV）、訂單backlog、RPO
   - 中長期毛利率或獲利目標、資本支出計畫、新產能爬坡時程、產品占比展望——
     這類「管理層自己講的未來目標」很有價值，法說會幾乎都會提到，不要漏掉
   - 一句最能代表這季基調的管理層發言

{_SCHEMA_HINT}"""


_TYPE_LABEL = {"guidance": "展望", "quote": "引述"}



# ── 結構化保存（2026-09-03）────────────────────────────────────────
# **這些項目原本產完就丟**：build() 只回 HTML 嵌進財報卡，程式沒辦法回頭查
# 「台積電上一季法說對 N2 產能講了什麼」。而 guidance 型項目裡正好就有
# 「新產能/新廠爬坡時程」——那是 state/roadmap_milestones.json 那 11 條
# 驗證日程唯一的免費結構化來源（法說會逐字稿走本機 claude，Max plan 不花現金）。
# 抓都抓了卻不存，等於每季重付一次時間成本又拿不回來。
NOTES = "state/earnings_call_notes.json"


def _persist(ticker, quarter_label, items):
    """把這次抓到的項目存進 NOTES，key = ticker，同一季覆蓋、不同季累積。"""
    import datetime
    try:
        d = json.load(io.open(NOTES, encoding="utf-8")) if os.path.exists(NOTES) else {}
    except Exception:                                       # noqa: BLE001
        d = {}
    # 沒給季別就用「年+季」當 key，**不要用今天的日期**（2026-09-03 發現）——
    # roadmap_milestones --fetch 不帶 quarter_label，用日期當 key 的話每跑一次
    # 就多一筆同內容的紀錄，一季跑四次就有四份重複，guidance() 會把同一句話回四遍。
    q = str(quarter_label or "").strip()
    if not q:
        t = datetime.date.today()
        q = f"{t.year}Q{(t.month - 1) // 3 + 1}"
    d.setdefault(ticker, {})[q] = {
        "fetched": datetime.date.today().isoformat(),
        "items": items,
    }
    try:
        os.makedirs("state", exist_ok=True)
        json.dump(d, io.open(NOTES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:                                  # noqa: BLE001
        print(f"  [earnings_call] {ticker} 展望存檔失敗（不影響卡片）：{e}")


def guidance(ticker=None, contains=None):
    """讀回存下來的管理層展望。contains 給關鍵字就只回含該字的項目。

    回 [(ticker, quarter, item)]，新的季在前。給 roadmap_milestones 驗證用。
    """
    try:
        d = json.load(io.open(NOTES, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return []
    out = []
    for tk, qs in d.items():
        if ticker and tk != ticker:
            continue
        for q, blk in sorted(qs.items(), reverse=True):
            for it in blk.get("items", []):
                if it.get("type") != "guidance":
                    continue
                if contains:
                    txt = f"{it.get('label','')}{it.get('value','')}"
                    if not any(k in txt for k in contains):
                        continue
                out.append((tk, q, it))
    return out


def build(ticker, company_name="", quarter_label=""):
    """回 (html, summary_text)。抓不到逐字稿或解析失敗都回 ("", "")，不中斷主流程。"""
    try:
        # tries=1（2026-08-31）：繁體驗收預設重試 3 次，而 llm_board.TIMEOUT 是 600 秒，
        # 相乘後單一張卡片的法說會步驟最壞要 30 分鐘——2882 實測卡了 20 分鐘還沒回。
        # 這一段是**選配的加值資訊**（抓不到就回 ("","") 不中斷主流程），
        # 沒必要為它付三倍的等待。回來是簡體就整段不用，不重試。
        data = llm_board.ask_json_traditional(
            _prompt(ticker, company_name, quarter_label), tries=1)
    except Exception as e:
        print(f"  [earnings_call] {ticker} 逐字稿摘要失敗：{e}")
        return "", ""

    # 容錯：萬一還是回了 {"highlights":[...]} 這種舊格式包裝，撥出內層陣列
    if isinstance(data, dict):
        data = data.get("highlights") or data.get("items") or []
    if not isinstance(data, list):
        return "", ""

    items = [x for x in data if isinstance(x, dict) and x.get("label") and x.get("value")][:15]
    if not items:
        return "", ""

    _persist(ticker, quarter_label, items)

    metrics = [x for x in items if x.get("type", "metric") == "metric"]
    guidance = [x for x in items if x.get("type") == "guidance"]
    quotes = [x for x in items if x.get("type") == "quote"]

    metric_html = "".join(
        f'<div class="ttile"><div class="tn">{_esc(x["label"])}</div>'
        f'<div class="tv">{_esc(str(x["value"]))}</div></div>' for x in metrics)
    grid_html = f'<div class="techgrid">{metric_html}</div>' if metric_html else ""

    guidance_html = ""
    if guidance:
        rows = "".join(
            f'<div class="callnote-text"><b>{_esc(x["label"])}</b>：{_esc(str(x["value"]))}</div>'
            for x in guidance)
        guidance_html = f'<div class="callnote-block"><div class="realitysub">管理層展望</div>{rows}</div>'

    quote_html = ""
    for x in quotes[:1]:
        speaker = f'—— {_esc(x["speaker"])}' if x.get("speaker") else ""
        q_text = str(x["value"]).strip().strip("「」\"'“”")
        quote_html = f'<div class="callnote-quote">「{_esc(q_text)}」<div class="callnote-speaker">{speaker}</div></div>'

    source_html = ('<div class="posnote">資料來源：法說會逐字稿公開內容（Motley Fool／GuruFocus等），'
                   '管理層口頭發言，非公司正式財報數字，數字未經覆核</div>')

    html = f"""<div class="reality"><h3>管理層口頭重點</h3>
{source_html}
{grid_html}
{guidance_html}
{quote_html}
</div>"""

    sum_parts = [f'{x["label"]}：{x["value"]}' for x in metrics]
    sum_parts += [f'展望－{x["label"]}：{x["value"]}' for x in guidance]
    summary = "法說會逐字稿重點：" + "；".join(sum_parts) if sum_parts else ""
    return html, summary


CSS = """
.callnote-block{margin-top:10px}
.callnote-text{font-size:12.5px;color:#e8eaed;line-height:1.6;background:#1a1d23;
 border:1px solid #2a2e35;border-radius:8px;padding:9px 11px;margin-top:6px}
.callnote-quote{margin-top:10px;font-size:12.5px;color:#C7D8EC;line-height:1.6;
 font-style:italic;border-left:2px solid #F5B841;padding-left:10px}
.callnote-speaker{font-size:11px;color:#8a8f98;margin-top:4px;font-style:normal}
"""


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def main():
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "PLTR"
    quarter = sys.argv[2] if len(sys.argv) > 2 else "Q2 2026"
    html, summary = build(ticker, quarter_label=quarter)
    print("=== summary ===")
    print(summary or "(空)")
    print("=== html ===")
    print(html or "(空)")


if __name__ == "__main__":
    main()
