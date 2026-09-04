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
         "-# 最後更新 2026-09-03。每次系統改動會重貼一份，舊的可以取消釘選。",
     ]),

    ("## 📊 #每日戰情（公開）",
     [
         "**每日戰情**　平日 08:45　龐統發情報、孔明發判斷",
         "",
         "> ① 大盤／總經",
         "> ② 今日訊號異動（SuperTrend 翻面、AI 轉買賣、🚦**進出燈號倉買賣動作**）",
         "> ③ 投資長進場機會（非持股評估）",
         "> ④ 研究員筆記（產業翻象限）",
         "> ⑤ 近日要看（總經行事曆、7 天內財報、📌**驗證日程**到期前 21 天提醒）",
         "> 附：🔍 全市場籌碼異常、⑥ 觀察名單失效條件",
         "",
         "-# 燈號倉動作與驗證日程為一天延遲（Actions 09:00 寫檔、隔天 08:45 讀）",
         "",
         "**週報**　週六加一段　　**本文件**　系統改動時重貼",
     ]),

    ("## 🔒 持股密報（私人）",
     [
         "**持股密報**　平日 08:45",
         "",
         "> ① 持股判斷（趨勢/價值兩角度獨立不合併）",
         "> ② 失效條件日檢",
         "> ③ 今日事件（沒事也會回「今日無事」心跳）",
         "",
         "**預估前提檢查・持股**　每週一 08:45",
         "> 分析師預估要求的成長，這家公司自己做過嗎",
     ]),

    ("## 📈 #財報",
     [
         "**財報快訊**　每日 08:45（有財報才發，T-7 預告一行）",
         "",
         "> ① EPS 實際/意外",
         "> ② 下季分析師共識",
         "> ③ 指引 vs 共識（AI 查證）",
         "> ④ 盤後反應＋一句白話，附財報懶人包連結",
         "",
         "-# 懶人包只自動產給持股＋固定美股名單；台股卡片 8/31–9/2 曾靜默失效，9/2 已修並全部重產",
         "",
         "**預估前提檢查・觀察名單**　每週一 08:45",
     ]),

    ("## 🤖 Bot（隆中對伺服器任一頻道，打 / 會跳出）",
     [
         "**/查 代號:2454**",
         "> 即時四燈／風報比／RS60／類股象限＋最近投資長判斷",
         "> 守備清單內秒回，其他股票約 3–8 秒",
         "",
         "-# 下一個：**/交易**　一行記一筆交易＋自動附當時系統快照（燈號/象限/投資長），"
         "跟現在的 trade_journal 同一套；交易紀錄檔案在 obis 04_AI Report/Investment/每日看板",
     ]),

    ("## 🌐 網頁（GitHub Pages）",
     [
         "投資站　<https://dt-1983.github.io/daily-stock-board/>",
         "",
         "> 導覽順序：產業輪動｜進出燈號｜籌碼異動｜策略賽馬｜產業鏈看板｜財報分析｜GDP｜ARK｜巴菲特",
         "> 每天 07:00 本機更新（看板/燈號/財報卡/籌碼/輪動）；週六守備清單重篩；09:00 賽馬模擬倉調倉",
         "> 看板每條鏈標 ⏱ 主行情落在哪一段（老墨三段時程）；9/4 起多兩條鏈：AI 材料/被動元件、AI 電源/散熱",
         "> 三頁圖表已統一：真蠟燭圖（雙重颱風三色）、SuperTrend 黃多/紫空、滾輪縮放拖曳平移四圖同步",
     ]),
]

WHATS_NEW = (
    "## 🆕 2026-09-02～03 這次改了什麼",
    [
        "**1. 模擬倉「三指標合流」換成「進出燈號」**",
        "> 三指標要三件事同天發生，8/18 起零觸發。改讀進出燈號頁同一份資料：",
        "> ≥3 燈＋風報比≥1 進場、ST 翻空賣半、RS60 跌破全出、7 天冷卻。",
        "> 9/2 首日買進 8 檔各 1/8，買賣動作從今天起進 #每日戰情 第②段。",
        "",
        "**2. 趨勢倉 ATR 改回 Wilder**",
        "> 一度全改 SMA 跟顯示層統一，重跑 5.7 年（QQQ＋守備清單×日/週線）發現週線 SMA 沒優勢，",
        "> 依「只改有結構性證據的」改回。顯示層/燈號維持 SMA 對齊老墨，兩層刻意不同。",
        "",
        "**3. 進出燈號頁加類股象限欄**",
        "> 純顯示不當門檻（燈四已是個股 RS；三週期象限常互相打架）。",
        "> TradingView 按代號查類股，跟輪動頁同源。",
        "",
        "**4. 老墨三段時程：查證＋落地**",
        "> 三段都站得住；A16 晶背供電滑到 2027、M9 瓶頸是玻纖布非銅箔、2028+ 是首批量產。",
        "> 21 條點名只 5 檔在守備清單 → 新增兩條鏈、玻璃基板補面板廠、看板時程標籤、",
        "> 11 筆驗證日程（行事曆型，到期 #每日戰情 ⑤段提醒，不自動上網查證）。",
        "> 報告與簡報 PDF 在 obis 04_AI Report/Investment/存檔/老墨三段時程。",
        "",
        "**5. 台股財報卡 8/31 起靜默失效，已修**",
        "> 8/31 改檔名時把純數字代號同時傳給抓資料的子程序，yfinance 查不到，",
        "> 每天失敗但排程不中斷。修好後 45 張卡片全部重產（含新版蠟燭圖）。",
        "",
        "**6. 產業輪動改每日＋修 52 幀上限**",
        "> 週→日後頁面只有 52 天，是切幀寫死 52（週頻遺留）。解除後幀資料壓成陣列，",
        "> 頁面維持 6MB。本機 07:00 每天跑，不再只有週六。",
        "",
        "**7. Discord Bot 上線（/查）＋交易紀錄 v1**",
        "> Bot 只用 slash command，不讀一般訊息。交易紀錄每筆自動附系統快照，私人檔不進公開 repo。",
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
