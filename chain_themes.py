"""
七鏈題材層（market researcher agent · Q1）
------------------------------------------
每條產業鏈用 Gemini 綜整「一段」近期研究 → chain_themes.json，
看板（board_html）在每條鏈標題下顯示可展開的 💡 題材 /⚠️ 風險 /👀 本週觀察。

- 資料源：screen_result.json（各鏈成分股 + 市值/成長/籌碼流入）+ Gemini 產業知識。
- 每鏈輸出三欄（catalyst 催化劑 / risk 風險 / watch 本週觀察），只綜整產業驅動力，
  不編造沒把握的具體新聞日期/數字。
- 每週一次即可（輸入 screen_result.json 週日才重篩，天天跑會拿同一份輸入）。

需環境變數 GEMINI_API_KEY（Actions 已設）。無金鑰時安全跳過、保留舊 json。
"""
import os
import re
import json
from datetime import datetime, timezone, timedelta

TW = timezone(timedelta(hours=8))
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("TW_LLM_MODEL", "gemini/gemini-3-flash-preview")
SCREEN_JSON = "screen_result.json"
OUT_JSON = "chain_themes.json"
TOP_N = 8                       # 每鏈餵給 AI 的成分股數（依市值）


def _chain_context(chain, us_list, tw_list):
    """組一段精簡的鏈現況給 AI（美台合併、依市值取前 TOP_N）。"""
    rows = []
    for x in (us_list or []) + (tw_list or []):
        rows.append((x.get("mktcap") or 0, x.get("name") or x.get("code"),
                     x.get("code"), x.get("growth"), x.get("inflow")))
    rows.sort(key=lambda r: r[0], reverse=True)
    lines = []
    for _, name, code, growth, inflow in rows[:TOP_N]:
        g = f"營收成長{growth*100:.0f}%" if isinstance(growth, (int, float)) else ""
        f = f"資金流入{inflow}" if isinstance(inflow, (int, float)) else ""
        lines.append(f"  {name}({code}) {g} {f}".rstrip())
    return f"產業鏈:{chain}\n成分股(依市值):\n" + "\n".join(lines)


def _ask(chain, ctx):
    import litellm
    prompt = (
        f"你是產業分析師。以下是台美股【{chain}】產業鏈守備清單的成分股與近況。\n"
        f"根據你對此產業的了解與這些個股表現，用繁體中文台灣用語輸出 JSON（只回 JSON，不要 markdown 圍欄）：\n"
        f'{{"catalyst":"近期主要題材／驅動力，1-2 句","risk":"要留意的風險或變數，1 句","watch":"本週值得觀察的重點，1 句"}}\n'
        f"每欄 45 字內、講重點且具體，但**不要編造沒把握的具體新聞日期或數字**。\n\n{ctx}")
    resp = litellm.completion(model=MODEL, api_key=GEMINI_KEY, temperature=0.4,
                              messages=[{"role": "user", "content": prompt}])
    txt = resp.choices[0].message.content.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S).strip()
    obj = json.loads(txt)
    out = {k: str(obj.get(k, "")).strip().strip('「」"\'')[:80]
           for k in ("catalyst", "risk", "watch")}
    if not out["catalyst"]:
        raise ValueError("catalyst 空白")
    return out


def main():
    if not GEMINI_KEY:
        print("[chain_themes] 無 GEMINI_API_KEY，跳過（保留舊 chain_themes.json）")
        return
    try:
        d = json.load(open(SCREEN_JSON, encoding="utf-8"))
    except Exception as e:
        print(f"[chain_themes] 讀 {SCREEN_JSON} 失敗：{e}")
        return
    us, tw = d.get("us", {}), d.get("tw", {})
    chains = list(dict.fromkeys(list(us.keys()) + list(tw.keys())))

    themes = {}
    for chain in chains:
        ctx = _chain_context(chain, us.get(chain), tw.get(chain))
        try:
            themes[chain] = _ask(chain, ctx)
            print(f"  [{chain}] 💡 {themes[chain].get('catalyst', '')}")
        except Exception as e:
            print(f"  [{chain}] 題材產生失敗：{e}")

    if not themes:
        print("[chain_themes] 無題材產出，不覆寫")
        return
    out = {"generated": datetime.now(TW).strftime("%Y-%m-%d %H:%M"), "themes": themes}
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[chain_themes] 已寫 {OUT_JSON}：{len(themes)} 條鏈")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
