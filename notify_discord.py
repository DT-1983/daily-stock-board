# -*- coding: utf-8 -*-
"""Discord 推播共用模組（隆中對伺服器，2026-08-27 建）。

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
    # 2026-08-27：私人頻道（只有 Leo 看得到）——持股相關內容專用。
    # 背景：#每日戰情/#財報 之後可能開放家人看，持股明細不該出現在公開頻道。
    "private": _env.get("DISCORD_WH_PRIVATE", ""),
}

# 三國軍師團（2026-08-27 Leo 定案）：伺服器=隆中對。
# 顯示名帶職稱（Leo：「名稱可以改 龐統-研究員 嗎？比較好懂」）——
# 呼叫端仍用短名（persona="孔明"），這裡自動轉顯示名。
PERSONAS = {
    "龐統": "龐統-研究員",
    "孔明": "孔明-投資長",
    "仲達": "仲達-風險官",
    "陳壽": "陳壽-復盤官",
    "戰情室": "戰情室",
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


def _url(channel):
    return CHANNELS.get(channel, channel if str(channel).startswith("https://") else "")


def send_discord(channel: str, text: str, persona: str = "戰情室", return_ids=False):
    """發到指定頻道。channel: 'daily'|'earnings'|'private'（或完整 webhook URL）。
    回 True/False；return_ids=True 時回 [訊息id,...]（之後要編輯/刪除得留著 id）。
    失敗不 raise。"""
    url = _url(channel)
    if not url:
        print(f"[discord] 頻道 {channel} 沒設 webhook，跳過")
        return [] if return_ids else False
    display = PERSONAS.get(persona, persona)
    ok, ids = True, []
    for i, chunk in enumerate(_split(text)):
        try:
            # ?wait=true 才會回傳訊息本體（含 id）——不加的話 Discord 回 204 空 body，
            # 事後就無從編輯／刪除那則訊息（2026-08-27 想改說明訊息時才發現這個坑）
            r = requests.post(url + ("?wait=true" if return_ids else ""),
                              json={"content": chunk, "username": display}, timeout=15)
            if r.status_code not in (200, 204):
                print(f"[discord] 發送失敗 {r.status_code}: {r.text[:150]}")
                ok = False
            elif return_ids and r.status_code == 200:
                try:
                    ids.append(r.json().get("id"))
                except Exception:
                    pass
            if i:               # 多則之間稍停，避免 rate limit（webhook 約 30則/分鐘）
                time.sleep(0.6)
        except Exception as e:
            print(f"[discord] 發送例外：{e}")
            ok = False
    return ids if return_ids else ok


def edit_discord(channel: str, message_id: str, text: str) -> bool:
    """編輯先前用 webhook 發出的訊息（需要當初 return_ids 拿到的 id）。"""
    url = _url(channel)
    if not (url and message_id):
        return False
    try:
        r = requests.patch(f"{url}/messages/{message_id}", json={"content": text}, timeout=15)
        if r.status_code not in (200, 204):
            print(f"[discord] 編輯失敗 {r.status_code}: {r.text[:150]}")
            return False
        return True
    except Exception as e:
        print(f"[discord] 編輯例外：{e}")
        return False


def delete_discord(channel: str, message_id: str) -> bool:
    """刪除先前用 webhook 發出的訊息。"""
    url = _url(channel)
    if not (url and message_id):
        return False
    try:
        r = requests.delete(f"{url}/messages/{message_id}", timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[discord] 刪除例外：{e}")
        return False


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    ok1 = send_discord("daily", "⚔️ **隆中對・每日戰情** 測試訊息\n三顧頻道之後，亮已在此。之後每天的戰情匯報由軍師團在這裡發佈。", persona="孔明")
    ok2 = send_discord("earnings", "📜 **財報快訊** 測試訊息\n此頻道專記各家財報：預告、實際vs預期、指引與盤後反應。", persona="龐統")
    print("daily:", ok1, "| earnings:", ok2)
