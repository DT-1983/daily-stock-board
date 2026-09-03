# -*- coding: utf-8 -*-
"""隆中對 Discord Bot——即時查任意股票的燈號＋RRG象限（2026-09-03，路線圖第1項階段2）。

只做一件事：`/查 代號:2454` → 呼叫 lamp_lookup.lookup() + format_discord()。
判定邏輯已在 lamp_lookup.py 做完並測試過（2026-09-02，跟每日燈號頁 combo_scan.py
同一套判定，不重算第二份），這支只是接上 Discord 的殼。

用法（部署後，在隆中對伺服器任一頻道）：
    /查 代號:2454
    /查 代號:COST
    /查 代號:BRK.B

前置需求（Leo 階段1，見 advisor_next_phase_roadmap 記憶「動這五項任何一項前先讀這份」）：
    1. https://discord.com/developers/applications 建立 Application + Bot
    2. Bot 頁籤「Reset Token」複製 Token，填進 .env 的 DISCORD_BOT_TOKEN
       （不需要開 MESSAGE CONTENT INTENT——這支只用 slash command，不讀一般訊息）
    3. OAuth2 → URL Generator：Scopes 勾 `bot` + `applications.commands`，
       Bot Permissions 勾 Send Messages / Use Slash Commands，
       用產生的連結邀進「隆中對」伺服器
    4. 把隆中對的伺服器 ID 填進 .env 的 DISCORD_GUILD_ID（伺服器圖示右鍵→複製伺服器
       ID，需先在 Discord 設定開發者模式）——填了指令幾秒內生效；不填則走全域註冊，
       Discord 那邊最多要等 1 小時才會出現，僅建議測試期間先填

部署（2026-09-03 Leo 定案）：本機常駐（`start_discord_bot.ps1`，工作排程器開機啟動），
不放 Zeabur——8/27 Zeabur 平台被入侵洩露過環境變數（見 security_incident_2026-08-28
記憶），本機常駐可以完全不把 Bot Token 交給第三方平台保管。跟每日 07:00 的 batch
排程是兩回事，不要掛進 board_analyze_daily.cmd。

內建一個本機 HTTP 健康檢查端點（`HEALTH_PORT`，預設 8030），只回這支自己活不活著，
不對外開放（127.0.0.1）——目的是掛進 `service_health_check.py` 的 `SERVICES` 清單，
跟 talentxtrend/資產中控台/Sonia 用同一套「掛了自動重啟＋狀態改變才通知」機制，
不然這支 Discord 連線斷了會沒人知道（跟其他三個本機服務一樣的靜默失效風險）。
"""
import os
import sys
import asyncio
import traceback
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

import discord
from discord import app_commands
from aiohttp import web
from dotenv import dotenv_values

import lamp_lookup
import lookup_page

_env = {**dotenv_values(Path(__file__).parent / ".env"), **os.environ}
TOKEN = _env.get("DISCORD_BOT_TOKEN", "")
GUILD_ID = _env.get("DISCORD_GUILD_ID", "")
HEALTH_PORT = int(_env.get("DISCORD_BOT_HEALTH_PORT", "8030"))

# 只需要 slash command，不讀一般訊息內容 → 用預設 intents 就夠，
# 不用申請 MESSAGE CONTENT 這個 privileged intent（Leo 階段1可以少做一步）。
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    print(f"[discord_bot] 登入為 {client.user}（id={client.user.id}）", flush=True)
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            # 指令是用 @tree.command()（無 guild=）宣告的全域指令，只呼叫
            # sync(guild=) 不會生效——那只同步「本來就綁定這個 guild」的指令，
            # 全域指令要先 copy_global_to() 複製一份進這個 guild 才會被 sync 到。
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            print(f"[discord_bot] 指令已同步到伺服器 {GUILD_ID}：{len(synced)} 個", flush=True)
        else:
            synced = await tree.sync()
            print(f"[discord_bot] 指令已全域同步（Discord 那邊最多要等 1 小時才會出現）：{len(synced)} 個", flush=True)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()


@tree.command(name="查", description="查任意股票的即時燈號＋RRG象限（隆中對）")
@app_commands.describe(代號="股票代號，例：2454 / COST / BRK.B")
async def cmd_lookup(interaction: discord.Interaction, 代號: str):
    # lamp_lookup 文件明講：即時抓算約 3-8 秒，不能當同步指令直接等——
    # defer() 給 Discord 15 分鐘的 followup 窗口，比 Discord 互動預設的 3 秒逾時寬裕很多。
    await interaction.response.defer(thinking=True)
    try:
        row = await asyncio.to_thread(lamp_lookup.lookup, 代號)
        msg = lamp_lookup.format_discord(row)
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        msg = f"⚠️ 查詢失敗：{e}"
    await interaction.followup.send(msg)


async def _health(request):
    ready = client.is_ready()
    return web.json_response({"ok": ready, "user": str(client.user) if ready else None},
                              status=200 if ready else 503)


async def _lookup_page(request):
    """視覺化查股頁 `/lookup?ticker=2454`（2026-09-03）。

    跟 `/查` 同一個資料來源（lamp_lookup），只是把結果畫成網頁＋技術面四張圖。
    頁面產生邏輯全在 `lookup_page.py`，這裡只負責掛路由。

    ⚠️ 用 `to_thread`：`lookup_page.render()` 內部會抓 3 年 OHLC＋算指標，是同步的
    CPU/IO 工作，直接在事件迴圈裡跑會**把整個 bot 卡住**（連 Discord 心跳都停），
    那會害 service_health_check 判定失聯然後重啟這支。
    """
    tk = request.query.get("ticker", "")
    try:
        html, status = await asyncio.to_thread(lookup_page.render, tk)
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        return web.Response(text=f"查詢失敗：{e}", status=500,
                            content_type="text/plain", charset="utf-8")
    return web.Response(text=html, status=status, content_type="text/html", charset="utf-8")


async def _run():
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/lookup", _lookup_page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", HEALTH_PORT)
    await site.start()
    print(f"[discord_bot] 健康檢查端點：http://127.0.0.1:{HEALTH_PORT}/", flush=True)
    await client.start(TOKEN)


def main():
    if not TOKEN:
        print("[discord_bot] 缺 DISCORD_BOT_TOKEN——請先完成階段1（見 advisor_next_phase_roadmap 記憶）")
        return 1
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
