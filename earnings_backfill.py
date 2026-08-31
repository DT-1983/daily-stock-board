# -*- coding: utf-8 -*-
"""7-8 月漏推財報的一次性回補 → Discord #財報（2026-08-31）

**為什麼需要這支**：8/31 稽核發現 30 檔追蹤清單裡**只有 2 檔曾經推播過**
（NVDA 8/26、富邦金 8/31），其餘 7-8 月公布的 15 檔從頭到尾沒進過 Discord。
三個原因疊在一起（都已在 earnings_watch.py 修掉）：
  1 T-7 登錄只在季度重掃當天發生 → 8/8~8/18 公布的整批落在兩次掃描的縫裡
  2 AFTER_DAYS 在 8/27 之前是 3 天，窗口更窄
  3 Discord 訊息把沒有卡片的股票壓成一行計數，內容整包丟掉

這支**只做回補這一件事**，不改 state、不影響每日流程：純讀已產好的卡片
（docs/earnings_*.html）組摘要發一次。跑完就可以留著當歷史，不排進排程。

⚠️ 不重跑 AI：卡片裡的敘事本來就是 AI 寫的、數字是 FinMind/SEC EDGAR/yfinance
的真實財報，這裡只是把已經存在的東西換個地方呈現，跟 earnings_watch.card_digest
同一個原則。

用法:
    python earnings_backfill.py --dry-run    # 只印不發
    python earnings_backfill.py              # 發 Discord
"""
import os
import io
import sys
import time
import argparse
from datetime import date

# 用 reconfigure 不用 TextIOWrapper——earnings_watch 匯入時也會包一次 stdout，
# 兩層 wrapper 會把先前那層關掉，之後 print 直接 ValueError: closed file
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import earnings_watch as EW          # noqa: E402
from earnings_watch import card_digest, PAGES, NL2, _load_env  # noqa: E402

_load_env()

# 稽核出來的名單：7-8 月公布、從沒推過 Discord 的。寫死不動態算——這是一次性
# 回補，動態算會在之後的日子產生不同結果，反而說不清楚補了什麼。
BACKFILL = [
    ("2317.TW", "鴻海",     "2026-08-12"),
    ("2884.TW", "玉山金",   "2026-08-13"),
    ("1101.TW", "台泥",     "2026-08-12"),
    ("2105.TW", "正新",     "2026-08-12"),
    ("2313.TW", "華通",     "2026-08-10"),
    ("3045.TW", "台灣大",   "2026-08-05"),
    ("2412.TW", "中華電",   "2026-08-04"),
    ("AMD",     "AMD",      "2026-08-04"),
    ("PLTR",    "Palantir", "2026-08-03"),
    ("2303.TW", "聯電",     "2026-07-29"),
    ("MSFT",    "微軟",     "2026-07-29"),
    ("GLW",     "康寧",     "2026-07-28"),
    ("INTC",    "英特爾",   "2026-07-23"),
    ("GOOG",    "Alphabet", "2026-07-22"),
    ("TSLA",    "Tesla",    "2026-07-22"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    digests, missing = [], []
    for tk, nm, ed in BACKFILL:
        base = tk.split(".")[0]
        path = f"docs/earnings_{base}.html"
        if not os.path.exists(path):
            missing.append(f"{tk} {nm}")
            continue
        url = f"{PAGES}/earnings_{base}.html"
        dg = card_digest(path, url)
        if dg:
            digests.append(dg)
        else:
            missing.append(f"{tk} {nm}（卡片解析不出摘要）")

    if not digests:
        print("沒有可回補的卡片")
        return

    head = ("# 📊 7-8 月財報回補" + NL2
            + "-# 這批財報當時公布了但沒推到 Discord（T-7 登錄只在季度重掃當天發生，"
              "8/8~8/18 公布的整批落在兩次掃描的縫裡）。原因已修，之後不會再漏。"
              "以下是各檔的完整財報分析摘要，數字都是最新一季。")
    body = NL2.join(digests)
    tail = ""
    if missing:
        tail = NL2 + f"-# 另有 {len(missing)} 檔沒有卡片可摘要：" + "、".join(missing)

    # Discord 單則 2000 字元上限，超過就分批發（不截斷內容）
    msgs, cur = [], head
    for dg in digests:
        if len(cur) + len(NL2) + len(dg) > 1900:
            msgs.append(cur)
            cur = dg
        else:
            cur += NL2 + dg
    msgs.append(cur + tail)

    print(f"回補 {len(digests)} 檔，分 {len(msgs)} 則發送"
          + (f"｜缺卡片 {len(missing)}：{missing}" if missing else ""))
    for i, m in enumerate(msgs, 1):
        print(f"\n────── 第 {i}/{len(msgs)} 則（{len(m)} 字元）──────")
        print(m[:600] + ("…" if len(m) > 600 else ""))

    if a.dry_run:
        print("\n(dry-run：沒有發送)")
        return

    from notify_discord import send_discord
    for i, m in enumerate(msgs, 1):
        ok = send_discord("earnings", m, persona="龐統")
        print(f"第 {i}/{len(msgs)} 則：{'✅ 已發' if ok else '❌ 失敗'}")
        if i < len(msgs):
            time.sleep(1.2)          # 避免 webhook 限流


if __name__ == "__main__":
    main()
