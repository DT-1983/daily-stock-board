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
         "-# 最後更新 2026-08-31。每次系統改動會重貼一份，舊的可以取消釘選。",
     ]),

    ("## 📊 #每日戰情（公開）",
     [
         "**每日戰情**　平日 08:45　六段：①產業輪動一句話 ②大盤體溫計 "
         "③進場機會（非持股評估）④籌碼異動 ⑤觀察名單失效條件 ⑥今日重點",
         "**本文件**　系統改動時重貼",
     ]),

    ("## 🔒 持股密報（私人）",
     [
         "**持股密報**　平日 08:45　①持股判斷（趨勢/價值兩角度獨立不合併）"
         "②失效條件日檢 ③今日事件",
         "**預估前提檢查・持股**　每週一 08:45　分析師預估要求的成長，"
         "這家公司自己做過嗎",
     ]),

    ("## 📈 #財報",
     [
         "**財報快訊**　每日 08:45（有財報才發）",
         "-# T-7 預告一行；公布後推四段：①EPS實際/意外 ②下季分析師共識 "
         "③指引vs共識（AI查證）④盤後反應＋一句白話，附財報懶人包連結",
         "-# 追蹤 30 檔＝台股全部持股 19 檔＋美股 11 檔"
         "（TSLA/NVDA/AMD/MRVL/MU/AVGO/PLTR/GLW/GOOG/MSFT/INTC）",
         "**預估前提檢查・觀察名單**　每週一 08:45",
         "-# 每月中推完整清單，其他週一只推燈號有變的",
     ]),

    ("## 🌐 網頁（GitHub Pages）",
     [
         "投資站 <https://dt-1983.github.io/daily-stock-board/>",
         "-# 財報分析 earnings.html｜籌碼異動 chip.html｜產業輪動 rotation.html"
         "｜巴菲特清單 buffett.html",
     ]),
]

WHATS_NEW = (
    "## 🆕 2026-08-31 這次改了什麼",
    [
        "**1. 財報不再漏推**",
        "-# 稽核發現 30 檔追蹤清單裡只有 2 檔曾經推播過。三個原因："
        "①T-7 登錄只在季度重掃當天發生，8/8~8/18 公布的整批落在兩次掃描的縫裡 "
        "②公布後的認列窗口原本只有 3 天 ③沒有懶人包的股票被壓成一行計數、內容整包丟掉。"
        "現在改成每天掃全清單、有卡片發卡片摘要、沒卡片發四段快訊。",
        "",
        "**2. 美股財報分析快 4 天以上**",
        "-# 原本等 yfinance 的完整三表（MRVL 公布後第 4 天還是上一季、NVDA 第 5 天也是）。"
        "改成優先讀 SEC EDGAR 官方申報——MRVL 8/27 公布、8/28 就送件。"
        "抓不到時自動退回 yfinance，兩邊失敗的公司不一樣，疊起來覆蓋率更高。",
        "",
        "**3. 失效條件分成趨勢／價值兩組**",
        "-# 原本 83 條裡有 39 條寫的是俗貴價，趨勢角度形同沒有失效條件。"
        "現在強制兩個角度各給條件，並新增每天算得出來的兩種："
        "SuperTrend 翻空、RS 跌破 60 日均線（本來就不必等財報）。"
        "訊息上會標 📉趨勢 / 💰價值。",
        "",
        "**4. 預估前提檢查加「毛利率位階」**（週一開始看得到）",
        "-# 原本只量「市場期待 vs 這檔自己的歷史成長率」，量不到「現在的獲利能力"
        "在自己歷史的哪個位置」。美光就是會誤判的例子：綠燈（只要求成長 22%、"
        "自己做過 75%）看起來寬鬆，但它現在毛利率 84.6% 是 24 季最高，"
        "3 年前還是 -32.7%——那個綠燈是建立在循環頂點的基期上。",
        "-# 新增兩個數字：**位階**＝現在賺的錢跟自己過去 6 年比有多高（100%＝史上最高）；"
        "**擺盪**＝最會賺跟最不會賺差多少。兩個要一起看——美光和 AVC 都是位階 100%，"
        "但美光擺盪 117pp（雲霄飛車頂端）、AVC 只有 17pp（樓梯頂端），風險差一個數量級。",
        "-# 鴻海、廣達這種毛利率不擺盪的代工廠會直接標「無鑑別力」，不給假訊號。",
        "",
        "**5. 全面禁簡體字**",
        "-# 發現財報卡片和投資長判斷都出現過簡體（AI 查到簡中新聞就跟著寫）。"
        "現在所有 AI 產出都會驗收，有簡體就要求改寫，改不掉就不發。",
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
    ap.add_argument("--channel", default="daily")
    a = ap.parse_args()

    msgs = _chunks(build())
    print(f"共 {len(msgs)} 則")
    for i, m in enumerate(msgs, 1):
        print(f"{NL}────── 第 {i}/{len(msgs)} 則（{len(m)} 字元）──────")
        print(m)
    if a.dry_run:
        print(f"{NL}(dry-run：沒發送)")
        return

    from notify_discord import send_discord
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
