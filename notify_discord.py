# -*- coding: utf-8 -*-
"""Discord 推播共用模組（隆中對伺服器，2026-08-28 建）。

用 Webhook（單向發送，不是 bot）：每則訊息可指定發言者名字——同一頻道裡
不同 agent 用自己的三國名字發言（龐統/孔明/仲達/陳壽），不用開一堆頻道。
頻道：#每日戰情（DISCORD_WH_DAILY）、#財報（DISCORD_WH_EARNINGS）；
#軍議 留給之後的互動 bot（P4b），不走 webhook。

用法：
    from notify_discord import send_discord
    send_discord("daily", "今日判斷……", persona="孔明")

- 內容支援 Discord markdown（**粗體**、`code`…），**不是** Telegram 的 HTML——
  呼叫端如果拿現成 Telegram 訊息來發，先過 tg_html_to_md() 轉一下。
- 超過 2000 字自動切多則（Discord 單則上限），切在換行處不切在句子中間。
- webhook 缺或發送失敗只印警告不 raise——Discord 是新增的通道，
  它掛掉不該讓本來就在跑的 Telegram/排程跟著失敗（雙發過渡期的基本原則）。
"""
import os
import re
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

_env = {**dotenv_values(Path(__file__).parent / ".env"), **os.environ}

CHANNELS = {
    "daily": _env.get("DISCORD_WH_DAILY", ""),
    "earnings": _env.get("DISCORD_WH_EARNINGS", ""),
}

# 三國軍師團（2026-08-28 Leo 定案）：伺服器=隆中對
PERSONAS = {
    "龐統": "研究員（情報/獻策）",
    "孔明": "投資長（綜觀全局定策）",
    "仲達": "風險官（謹守不敗）",
    "陳壽": "復盤官（修史復盤）",
    "戰情室": "系統訊息",
}


def tg_html_to_md(text: str) -> str:
    """Telegram HTML → Discord markdown 的最小轉換（雙發過渡期用）。"""
    text = re.sub(r"</?b>", "**", text)
    text = re.sub(r"</?i>", "*", text)
    text = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"[\2](\1)", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text


def _split(text: str, limit: int = 1990):
    """切在換行處，不切在句子中間。"""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for ln in text.split("\n"):
        if len(cur) + len(ln) + 1 > limit:
            chunks.append(cur.rstrip())
            cur = ""
        cur += ln + "\n"
    if cur.strip():
        chunks.append(cur.rstrip())
    return chunks


def send_discord(channel: str, text: str, persona: str = "戰情室") -> bool:
    """發到指定頻道。channel: 'daily'|'earnings'（或直接給完整 webhook URL）。
    回 True/False，失敗不 raise。"""
    url = CHANNELS.get(channel, channel if str(channel).startswith("https://") else "")
    if not url:
        print(f"[discord] 頻道 {channel} 沒設 webhook，跳過")
        return False
    ok = True
    for i, chunk in enumerate(_split(text)):
        try:
            r = requests.post(url, json={"content": chunk, "username": persona},
                              timeout=15)
            if r.status_code not in (200, 204):
                print(f"[discord] 發送失敗 {r.status_code}: {r.text[:150]}")
                ok = False
            if i:               # 多則之間稍停，避免 rate limit（webhook 約 30則/分鐘）
                time.sleep(0.6)
        except Exception as e:
            print(f"[discord] 發送例外：{e}")
            ok = False
    return ok


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    ok1 = send_discord("daily", "⚔️ **隆中對・每日戰情** 測試訊息\n三顧頻道之後，亮已在此。之後每天的戰情匯報由軍師團在這裡發佈。", persona="孔明")
    ok2 = send_discord("earnings", "📜 **財報快訊** 測試訊息\n此頻道專記各家財報：預告、實際vs預期、指引與盤後反應。", persona="龐統")
    print("daily:", ok1, "| earnings:", ok2)
