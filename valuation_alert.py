# -*- coding: utf-8 -*-
"""貴俗價警示：實際持股（非巴菲特候選池 41 檔）現算俗/貴價，翻貴才推 Telegram。

跟 st_alert.py 同一種模式：state/valuation_state.json 存上次每檔訊號，
翻成 🔴（現價≥貴價）才推；首次執行只記狀態不推，避免一次噴滿 60+ 檔。

同一份 state 檔案兼兩用：
  1. 翻貴判斷的「上次狀態」
  2. assets-dashboard／Sonia 讀取的「持久顯示」資料源
不另存第二份，避免兩邊各存一份又漏同步（BB-8 週報那次的教訓）。

2026-08-25 加台股（繼承帳戶，家人留下的資產）：valuation 計算涵蓋 active+legacy
（俗貴價是顯示不是策略計算，跟 legacy「僅顯示不參與計算」的既有原則不衝突）；
但 **Telegram 翻貴警示只算 Firstrade**——台股用 .TW 硬套的已知限制（上櫃股查不到、
且用戶自己說了「還要跟 Mike 核對」數字），數字還沒驗證過不該拿去推警示噪音。

用法：python valuation_alert.py
"""
import os
import json
from pathlib import Path
from datetime import datetime

import requests
from dotenv import dotenv_values

from trade_plan import load_holdings, compute_valuation

# 本機 Windows 排程（board_analyze_daily.cmd）不會預先 export 環境變數，
# 跟 st_alert.py/alert_telegram.py（GitHub Actions 雲端跑、吃 Actions Secrets）
# 是不同執行環境——這裡跟 main.py 一樣直接讀本機 .env。
_env = {**dotenv_values(Path(__file__).parent / ".env"), **os.environ}
TOKEN = _env.get("TELEGRAM_BOT_TOKEN", "")
CHAT = _env.get("TELEGRAM_CHAT_ID", "")
STATE_PATH = Path("state/valuation_state.json")


def send(text):
    if not (TOKEN and CHAT):
        print("缺 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return False
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=30)
    if r.status_code != 200:
        print(f"telegram failed: {r.status_code} {r.text[:200]}")
    return r.status_code == 200


def main():
    active, legacy = load_holdings()
    if not active:
        print("讀不到 Firstrade 持股，中止")
        return
    active_tickers = {r.get("ticker") for r in active}

    valuation = compute_valuation(active + legacy)
    n_us = sum(1 for v in valuation.values() if v["market"] == "US")
    n_tw = sum(1 for v in valuation.values() if v["market"] == "TW")
    print(f"算出 {len(valuation)}/{len({r.get('ticker') for r in active + legacy})} 檔俗貴價"
          f"（美股 {n_us}/{len(active_tickers)}、台股 {n_tw}/{len({r.get('ticker') for r in legacy})}）")

    prev = {}
    if STATE_PATH.exists():
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    first_run = not prev

    flips = []
    if not first_run:
        for tk, v in valuation.items():
            if tk not in active_tickers:
                continue                          # 台股(legacy)不推警示，見檔頭說明
            if v["icon"] == "🔴" and (prev.get(tk) or {}).get("icon") != "🔴":
                flips.append((tk, v["price"], v["expensive"]))

    if flips:
        flips.sort(key=lambda x: -(x[1] / x[2]))     # 超過貴價幅度最大的排前面
        lines = ["🔴 <b>貴俗價警示：跨過貴價</b>（Firstrade 實際持股）\n",
                 "<i>洪瑞泰出場依據：現價 ≥ 貴價（EPS×30）才考慮賣，不是自動賣出、也不看短線波動</i>\n"]
        for tk, price, exp in flips:
            lines.append(f"· <b>{tk}</b>　現價 ${price:,.2f} ≥ 貴價 ${exp:,.2f}")
        send("\n".join(lines))
        print(f"推播 {len(flips)} 檔翻貴：{[f[0] for f in flips]}")
    elif first_run:
        print(f"首次執行，只記狀態不推播（{len(valuation)} 檔）")
    else:
        print("無新翻貴")

    # 2026-08-26：另存一份「這次翻的清單」給 researcher_stock.py 讀（同一批本機排程，
    # 跑在這支之後）。不跟上面的 flips 判斷混在一起是因為這裡要固定寫（含空清單），
    # 上面的 Telegram 推播只在有內容時才送。
    os.makedirs("state", exist_ok=True)
    Path("state/valuation_flips_today.json").write_text(
        json.dumps([{"ticker": tk, "price": price, "expensive": exp} for tk, price, exp in flips],
                   ensure_ascii=False), encoding="utf-8")

    STATE_PATH.parent.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_state = {tk: {**v, "updated_at": stamp} for tk, v in valuation.items()}
    STATE_PATH.write_text(json.dumps(out_state, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
