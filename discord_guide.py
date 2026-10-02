# -*- coding: utf-8 -*-
"""Discord 推播總覽說明文件 → 發到 #每日戰情 供 Leo 釘選（2026-08-31）

**為什麼要有這支而不是手打**：這份說明每次系統改動都要更新，手打會漏。
寫成程式的好處是**內容跟實際排程綁在一起**，改了排程就重跑這支重貼。

⚠️ 它**不會**自己去讀排程檔反推內容——那樣看起來自動但其實更危險（.cmd 裡有
註解、有失敗分支，反推出來的描述會失真）。這裡是人工維護的清單，但集中在一個
檔案，改動時只改這裡，避免同一份說明散在多個地方各自過期。

用法:
    python discord_guide.py --dry-run     # 只印
    python discord_guide.py               # 發到 #每日戰情
"""
import os
import io
import sys
import json
import time
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATE = "state/discord_pinned.json"
NL = chr(10)

SECTIONS = [
    ("# 📋 Discord 推播總覽",
     [
         "-# 最後更新 2026-09-28。每次系統改動會重貼一份，舊的可以取消釘選。",
         "-# 分工：**急件**（當天 ST 轉向、RS 破 60、突破貴價）推 Telegram；**完整資訊**在 Discord。",
     ]),

    ("## 📊 #每日戰情（公開，不含持股）",
     [
         "**每日戰情**　平日 08:45～09:00　**一則**（戰情室）",
         "",
         "> ① 大盤／總經（美台指數、非農實際值（BLS，公布後 5 天內）、台指電子盤前一晚收盤、電金比體溫計、產業輪動最強最弱、近期排定）",
         "> ② 今日訊號異動（守備清單 SuperTrend 翻面、AI 轉買賣、🚦燈號倉動作）",
         "> ③ 投資長進場機會（非持股評估）",
         "> 🔄 剛轉進領先象限的類股",
         "> ⭐⭐ 四燈＋風報比 ≥ 1（進場候選，附距停損 %）",
         "> ⚡ 全市場接力（RS 創新高＋EC 翻正；數字＝距 60 日平均成本 🔴🟡🟢）",
         "> ④ 研究員筆記　⑤ 近日要看（總經行事曆、財報、📌驗證日程）　⑥ 觀察名單失效條件",
         "",
         "-# 沒內容的段落整段不出，不再有「今日無新訊號」佔位句",
         "",
         "**巴菲特到價＋雙確認**　每週六 08:00",
     ]),

    ("## 🔒 #持股密報（私人）",
     [
         "**🚨 持股警示**　週一～六 08:19　持股 SuperTrend 翻空／RS60 跌破**立刻**發、並 @你",
         "",
         "**持股密報**　平日 08:45～09:00　**一則**（戰情室）",
         "> ② 今日新變化（持股出場訊號依去向分組：新達成ST空＋RS破／新轉弱／解除；💰翻貴）＋存量一行計數，完整名單與成本損益開 <https://assets.talentxtrend.com/exit-review>（要密碼）",
         "> ⭐⭐ 持股四燈＋風報比　③ 持股判斷（沒事也會寫一行「今日持股無新事件」）",
         "> ⚡ 持股出現接力訊號　④ 持股新聞　🆕 今日報告更新（券商報告／目標價）",
         "> ⑤ 失效條件日檢（逼近失效線、監控涵蓋率；出場訊號已搬到 ②）",
         "",
         "**預估前提檢查・持股**　每週一（有變化才發）",
         "**對帳提醒／Mike 交叉比對**　每月／每季",
     ]),

    ("## 📈 #財報",
     [
         "**財報快訊**　平日 06:00 批次（有財報才發，T-7 預告）",
         "> EPS 實際 vs 預期、下季共識、指引、盤後反應，附財報懶人包連結",
         "",
         "**總經週報**（孔明判讀）　每週一",
         "**預估前提檢查・觀察名單**　每週一（有變化才發）",
     ]),

    ("## 🤖 Bot（隆中對伺服器任一頻道，打 / 會跳出）",
     [
         "**/查 代號:2454**　四燈／風報比／RS60／**距 60 日成本**／類股象限／投信買賣，附圖表版連結",
         "**/龐統 /孔明 /仲達 /陳壽**　單獨問一位軍師　　**/軍議**　依序問四位",
         "**/加自選 /移除自選 /自選清單**　進出燈號的自訂觀察清單",
         "**/上傳報告**　券商報告 PDF 或目標價截圖",
     ]),

    ("## 🌐 網頁",
     [
         "投資站　<https://dt-1983.github.io/daily-stock-board/>",
         "> 首頁｜產業輪動｜進出燈號｜籌碼異動｜策略賽馬｜產業鏈看板｜財報分析｜GDP｜ARK｜巴菲特",
         "燈號戰情室（本機，已授權裝置）　<https://stock.talentxtrend.com/room>",
         "> 每天 06:00～07:00 本機更新；技術圖：真蠟燭（雙重颱風三色）、SuperTrend 紫多黃空、平均成本按鈕",
     ]),

    ("## 📱 Telegram（急件）",
     [
         "> 08:19 投資晨報：持股 ST 轉向／RS60 跌破、守備清單 ST 翻面（沒急件發「今日無急件」）",
         "> 約 06:00 持股翻貴　06:00 巴菲特俗貴翻轉　07:30 市場情緒（有變化才發）　12:00 盈再表新討論",
     ]),
]

WHATS_NEW = (
    "## 🆕 2026-09-27～28 這次改了什麼",
    [
        "**1. 日報一個頻道一則**",
        "> 原本龐統情報、孔明判斷分兩則（平日共 4 則）→ 公開、密報各一則；空段落不出。",
        "> 「今日報告更新」只留密報（公開版原本會露出持股）。",
        "",
        "**2. 全市場 RS＋EC 接力**",
        "> 台股上市櫃全部＋美股市值 5 億美元以上，每天早上本機批次掃；9/24 跟老墨 XQ 核對 6／6 一致。",
        "",
        "**3. 平均成本（AVWAP）**",
        "> 技術圖多一列按鈕（預設只開 60 日，可點 K 棒自訂起算）；戰情室、產業輪動、/查 都有「距 60 日成本」。",
        "> 🔴 全市場最偏離前 1%、🟡 前 1～5%，門檻每天重算。只顯示偏離程度，不影響燈號。",
        "",
        "**4. Telegram 只留急件**",
        "> 守備清單 AI 訊號改只在 Discord；TradingBot 季度推播拿掉已退役的配對檢定。",
        "",
        "**5. 「停損 x%」改「距停損 x%」**",
        "> 再跌這麼多會碰到 SuperTrend 支撐線，不是已經虧損。",
    ])


def build():
    out = []
    for title, lines in SECTIONS:
        out.append(title)
        out.extend(lines)
        out.append("")
    out.append(WHATS_NEW[0])
    out.extend(WHATS_NEW[1])
    return NL.join(out).strip()


def _chunks(text, limit=1900):
    """Discord 單則 2000 字元上限。**只在段落邊界切**，不切在句子中間。"""
    parts, cur = [], ""
    for block in text.split(NL + NL):
        if cur and len(cur) + 2 + len(block) > limit:
            parts.append(cur)
            cur = block
        else:
            cur = (cur + NL + NL + block) if cur else block
    if cur:
        parts.append(cur)
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    # 2026-09-03：Leo 的「個人記錄區」是獨立頻道 #個人記錄區（不是 #每日戰情），總覽改預設發那裡；
    # DISCORD_WH_NOTES 還沒填時退回 daily，不要靜默不發。
    ap.add_argument("--channel", default="notes")
    a = ap.parse_args()

    msgs = _chunks(build())
    print(f"共 {len(msgs)} 則")
    for i, m in enumerate(msgs, 1):
        print(f"{NL}────── 第 {i}/{len(msgs)} 則（{len(m)} 字元）──────")
        print(m)
    if a.dry_run:
        print(f"{NL}(dry-run：沒發送)")
        return

    from notify_discord import send_discord, CHANNELS
    if a.channel == "notes" and not CHANNELS.get("notes"):
        print("⚠️ DISCORD_WH_NOTES 未填，改發 #每日戰情（daily）——請 Leo 在 #個人記錄區 建 webhook 後填 .env 再重跑")
        a.channel = "daily"
    ids = []
    for i, m in enumerate(msgs, 1):
        r = send_discord(a.channel, m, persona="龐統", return_ids=True)
        print(f"第 {i}/{len(msgs)} 則：{r}")
        if isinstance(r, (list, tuple)):
            ids += [str(x) for x in r]
        if i < len(msgs):
            time.sleep(1.2)
    if ids:
        try:
            st = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            st = {}
        st["guide_ids"] = ids          # 舊的 daily_help_ids 保留，方便對照要取消釘選哪則
        os.makedirs("state", exist_ok=True)
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"訊息 ID 已存 {STATE}：{ids}")


if __name__ == "__main__":
    main()
