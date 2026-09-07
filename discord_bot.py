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
import json
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


# ── #軍議：仲達（風險官）／陳壽（復盤官）─────────────────────────
# 路線圖第 1 項階段 3。材料組裝＋提問都在 war_room.py，這裡只負責 Discord 的殼。
#
# ⚠️ 為什麼是 slash command 不是 @提及：讀一般訊息要 message_content 這個
# **特權 intent**，得 Leo 去 Developer Portal 開；slash command 用
# Intents.default() 就夠，不用他動手。功能上沒差——一樣可以打字問問題。
#
# ⚠️ 兩位都走本機 claude（Max plan 訂閱額度，**不是付費 API**），一次問答數十秒，
# 所以跟 /查 一樣先 defer()。
def _first_ticker(q):
    """問題裡點名的第一檔，當成續談的 key。認不出就回 ""（大盤／整體那條線）。

    ⚠️ 用 war_room 自己的解析器，不要另外寫一套——網頁跟 Discord 的 key
    必須算得出一樣的值，兩套解析遲早會在同一句話上給出不同答案。
    """
    try:
        import war_room
        c = war_room._tickers_in_question(q or "")
        return (c[0][0] if c else "")
    except Exception:                                     # noqa: BLE001
        return ""


async def _ask_war_room(interaction, role, 問題):
    await interaction.response.defer(thinking=True)
    try:
        import war_room
        import war_room_chat as wc
        # 2026-09-07：Discord 也走同一份續談＋記錄，所以「在 Discord 問完、
        # 回網頁點同一檔會接著談」，反過來也是。標的從問題裡解析（跟網頁同一套）。
        tk = _first_ticker(問題)
        msg, _m, _x = await asyncio.to_thread(
            wc.ask, role, 問題, tk, False, None, "discord")
        _note = ((f'　_接續 {_x["since"][:10]} 的對話_' if _x.get('resumed') else '')
                 + ('　_材料已更新為今天_' if _x.get('refreshed') else ''))
        head = f"**{war_room.ROLES[role]['name']}**{_note}" + "\n"
        if 問題:
            head += f"> {問題}\n\n"
        msg = head + msg
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        msg = f"⚠️ {role} 出錯：{e}"
    for i in range(0, len(msg), 1900):        # Discord 單則上限 2000
        await interaction.followup.send(msg[i:i + 1900])


@tree.command(name="仲達", description="風險官：現在有什麼風險（失效條件/燈號/大盤溫度/券商異動）")
@app_commands.describe(問題="想問什麼；留空＝要一份今日風險摘要")
async def cmd_sima(interaction: discord.Interaction, 問題: str = ""):
    await _ask_war_room(interaction, "仲達", 問題)


@tree.command(name="陳壽", description="復盤官：回頭看判斷準不準、交易紀律（樣本不足會明講）")
@app_commands.describe(問題="想問什麼；留空＝要一份復盤現況")
async def cmd_chen(interaction: discord.Interaction, 問題: str = ""):
    await _ask_war_room(interaction, "陳壽", 問題)


@tree.command(name="軍議", description="依序問龐統→孔明→仲達→陳壽（沒指定個股時跳過孔明），約 3-4 分鐘")
@app_commands.describe(問題="要議什麼；指定個股→四位都問，沒指定→龐統/仲達/陳壽")
async def cmd_council(interaction: discord.Interaction, 問題: str = ""):
    # ⚠️ **一位答完就先送一則**，不要等全部跑完——一位約 40-60 秒，
    # 四位就是 3-4 分鐘，全部跑完才送的話中間完全沒有回饋，看起來像掛了。
    # 順序由 war_room.council_roles 決定（材料→判斷→風險→回顧），這裡不重排。
    await interaction.response.defer(thinking=True)
    try:
        import war_room
        roles = war_room.council_roles(問題)
        head = f"**🏛️ 軍議**　{'、'.join(roles)}"
        if 問題:
            head += f"\n> {問題}"
        await interaction.followup.send(head)
        prior = []          # 前面軍師講過的話，往下傳給 PRIOR_FOR 裡的角色
        for role in roles:
            import war_room_chat as wc
            out, _m, _x = await asyncio.to_thread(
                wc.ask, role, 問題, _first_ticker(問題), False, prior, "discord")
            prior.append((war_room.ROLES[role]['name'], out))
            msg = f"**{war_room.ROLES[role]['name']}**\n{out}"
            for i in range(0, len(msg), 1900):
                await interaction.followup.send(msg[i:i + 1900])
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        await interaction.followup.send(f"⚠️ 軍議出錯：{e}")


@tree.command(name="孔明", description="投資長：對一檔給趨勢/價值兩個獨立角度的判斷＋失效條件")
@app_commands.describe(問題="要判斷哪一檔，例：2454 / 輝達怎麼看（一定要指定股票）")
async def cmd_kongming(interaction: discord.Interaction, 問題: str):
    await _ask_war_room(interaction, "孔明", 問題)


@tree.command(name="龐統", description="研究員：查這一檔或這個主題最近的新聞（鉅亨網，只給材料不下判斷）")
@app_commands.describe(問題="要查哪一檔或什麼主題，例：2454 / HBM 最近有什麼消息")
async def cmd_pangtong(interaction: discord.Interaction, 問題: str):
    await _ask_war_room(interaction, "龐統", 問題)


async def _health(request):
    # 2026-09-03：這個 port 接上 Cloudflare Tunnel 對外開放查股頁之後，健康檢查也
    # 跟著曝光了，外面打一下就看得到 bot 名稱。健檢只有本機的 service_health_check
    # 在用，所以**經由 tunnel 進來的一律 404**——cloudflared 轉發時會帶
    # CF-Connecting-IP，本機直接打不會有這個標頭（不能用來源 IP 判斷：tunnel 也是
    # 從 127.0.0.1 連進來的）。
    if request.headers.get("CF-Connecting-IP"):
        return web.Response(text=lookup_page.BARE_404, status=404,
                            content_type="text/html", charset="utf-8")
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
    # 對外開放後的門檻：?key=<LOOKUP_TOKEN> 進來一次種 90 天 cookie。
    # 沒通過一律 404（不是 403——403 等於告訴對方這裡有東西）。詳見 lookup_page.gate。
    ok, set_cookie = lookup_page.gate(request.query.get("key", ""),
                                      request.cookies.get(lookup_page.COOKIE, ""))
    if not ok:
        print(f"[lookup] 擋下（無 key／cookie）ticker={request.query.get('ticker','')!r}",
              flush=True)
        return web.Response(text=lookup_page.not_found_html(), status=404,
                            content_type="text/html", charset="utf-8")

    tk = request.query.get("ticker", "")
    live = request.query.get("live") in ("1", "true", "yes")
    try:
        html, status = await asyncio.to_thread(lookup_page.render, tk, live)
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        return web.Response(text=f"查詢失敗：{e}", status=500,
                            content_type="text/plain", charset="utf-8")
    # 存取紀錄：9/3 Leo 回報「沒辦法用」時我完全查不到他打了什麼、被擋在哪一關
    # （aiohttp 預設不記請求）。只記代號與結果，不記 IP/UA。
    print(f"[lookup] ticker={tk!r} status={status} "
          f"{'外部' if request.headers.get('CF-Connecting-IP') else '本機'}", flush=True)
    resp = web.Response(text=html, status=status, content_type="text/html", charset="utf-8")
    if set_cookie:
        # Secure＋SameSite=Lax：只走 https（tunnel 那端本來就是 https），
        # 且不會被第三方網站帶著送出去。
        resp.set_cookie(lookup_page.COOKIE, lookup_page._token(),
                        max_age=lookup_page.COOKIE_DAYS * 86400,
                        httponly=True, samesite="Lax", secure=True)
    return resp


# ── 燈號戰情室 /room（2026-09-07，見 lamp_room.py 檔頭）──────────────
def _room_gate(request):
    """跟 /lookup 同一道門檻。**不另外發明第二套驗證**——兩套遲早會有一套漏改。"""
    return lookup_page.gate(request.query.get("key", ""),
                            request.cookies.get(lookup_page.COOKIE, ""))


def _room_404():
    return web.Response(text=lookup_page.not_found_html(), status=404,
                        content_type="text/html", charset="utf-8")


async def _room_page(request):
    ok, set_cookie = _room_gate(request)
    if not ok:
        print("[room] 擋下（無 key／cookie）", flush=True)
        return _room_404()
    import lamp_room
    # to_thread 的理由同 /lookup：讀 312 檔的收盤快取是同步 IO，
    # 直接在事件迴圈裡跑會把整個 bot（含 Discord 心跳）卡住。
    html = await asyncio.to_thread(lamp_room.page_html)
    print(f"[room] 開頁 {'外部' if request.headers.get('CF-Connecting-IP') else '本機'}",
          flush=True)
    resp = web.Response(text=html, content_type="text/html", charset="utf-8")
    if set_cookie:
        resp.set_cookie(lookup_page.COOKIE, lookup_page._token(),
                        max_age=lookup_page.COOKIE_DAYS * 86400,
                        httponly=True, samesite="Lax", secure=True)
    return resp


async def _trades_page(request):
    """交易紀錄 /trades（2026-09-07，Sonia 那張卡連這裡）。

    ⚠️ 這頁有實際交易紀錄（券商、股數、價格、理由），跟 /lookup 同一道 token 門檻，
    沒過一律 404。內容跟 obis 的「交易紀錄.html」是同一個產生器，不會有兩套。
    """
    ok, set_cookie = _room_gate(request)
    if not ok:
        print("[trades] 擋下（無 key／cookie）", flush=True)
        return _room_404()
    import trade_journal
    html = await asyncio.to_thread(trade_journal.page)
    resp = web.Response(text=html, content_type="text/html", charset="utf-8")
    if set_cookie:
        resp.set_cookie(lookup_page.COOKIE, lookup_page._token(),
                        max_age=lookup_page.COOKIE_DAYS * 86400,
                        httponly=True, samesite="Lax", secure=True)
    return resp


async def _room_detail(request):
    """中欄片段。⚠️ 這裡會抓 2 年資料算指標，是最慢的一段（數秒）。"""
    ok, _ = _room_gate(request)
    if not ok:
        return web.Response(text="", status=404)
    import lamp_room
    tk = request.query.get("ticker", "")
    try:
        html = await asyncio.to_thread(lamp_room.detail_html, tk)
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        html = f'<div class="warn">{tk} 產生失敗：{str(e)[:160]}</div>'
    print(f"[room] detail {tk!r}", flush=True)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def _room_ask_stream(request):
    """串流版的軍師（SSE）。用 GET 是因為 EventSource 只能 GET。

    事件：
      stage  進度（正在讀什麼／正在查網路）——**照實回報**，不是假進度條
      delta  一段文字
      reset  前面串的作廢（重寫那一輪），畫面要清掉重來
      done   結束，帶 meta

    ⚠️ war_room 是同步的，跑在 to_thread；callback 從那條 thread 呼叫，
       所以要用 call_soon_threadsafe 把事件丟回事件圈，不能直接 await。
    """
    ok, _ = _room_gate(request)
    if not ok:
        return web.Response(text="", status=404)
    role = str(request.query.get("role") or "軍議")
    question = str(request.query.get("question") or "")[:500]
    ticker = str(request.query.get("ticker") or "")[:20]
    fresh = request.query.get("fresh") in ("1", "true")

    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",      # 別讓中間層把 SSE 緩衝起來
    })
    await resp.prepare(request)
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()

    def emit(kind, data):
        loop.call_soon_threadsafe(q.put_nowait, (kind, data))

    async def pump():
        while True:
            kind, data = await q.get()
            if kind is None:
                return
            payload = json.dumps(data, ensure_ascii=False)
            await resp.write(f"event: {kind}\ndata: {payload}\n\n".encode("utf-8"))

    async def work():
        import war_room
        import war_room_chat as wc
        try:
            roles = (war_room.council_roles(question) if role == "軍議"
                     else [role])
            prior, total = [], 0.0
            for r in roles:
                if r not in war_room.ROLES:
                    emit("delta", {"name": r, "text": f"沒有這位軍師：{r}"})
                    continue
                emit("start", {"name": war_room.ROLES[r]["name"]})
                txt, meta, x = await asyncio.to_thread(
                    wc.ask, r, question, ticker, fresh,
                    (prior if r in war_room.PRIOR_FOR else None), "room",
                    lambda m, _r=r: emit("stage", {"name": war_room.ROLES[_r]["name"],
                                                   "text": m}),
                    lambda t, _r=r: emit("delta", {"name": war_room.ROLES[_r]["name"],
                                                   "text": t}))
                prior.append((war_room.ROLES[r]["name"], txt))
                total += float(meta.get("cost_usd") or 0)
                emit("end", {"name": war_room.ROLES[r]["name"], "text": txt,
                             "resumed": x.get("resumed"),
                             "refreshed": x.get("refreshed"),
                             "since": x.get("since"), "cost": total})
            emit("done", {"cost": total, "turns": len(roles)})
        except Exception as e:                              # noqa: BLE001
            traceback.print_exc()
            emit("error", {"text": f"軍師出錯：{str(e)[:200]}"})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, (None, None))

    pumper = asyncio.ensure_future(pump())
    await work()
    await pumper
    await resp.write_eof()
    return resp


async def _room_history(request):
    """右欄的「之前談過」。純讀檔，很快，不用丟 thread。"""
    ok, _ = _room_gate(request)
    if not ok:
        return web.Response(text="", status=404)
    import lamp_room
    try:
        html = lamp_room.chat_html(request.query.get("ticker", ""))
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        html = ""
        print(f"[room] history 失敗：{str(e)[:80]}", flush=True)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def _room_ask(request):
    """右欄軍師。**一次一問，不排隊**——本機 claude 同時跑兩輪會互相搶資源，
    而且使用者也看不出哪個回答對應哪個問題。前端送出後把按鈕鎖起來。"""
    ok, _ = _room_gate(request)
    if not ok:
        return web.json_response({"error": "not found"}, status=404)
    try:
        body = await request.json()
    except Exception:                                     # noqa: BLE001
        return web.json_response({"error": "壞掉的請求"}, status=400)
    role = str(body.get("role") or "軍議")
    question = str(body.get("question") or "")[:500]
    ticker = str(body.get("ticker") or "")[:20]
    fresh = bool(body.get("fresh"))
    print(f"[room] ask role={role!r} tk={ticker!r} fresh={fresh} q={question[:40]!r}",
          flush=True)
    try:
        import lamp_room
        answers, info = await asyncio.to_thread(
            lamp_room.ask, role, question, ticker, fresh)
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        return web.json_response({"error": f"軍師出錯：{str(e)[:200]}"})
    print(f"[room] ask done resumed={info.get('resumed')} "
          f"等值 US${info.get('cost', 0):.4f}", flush=True)
    return web.json_response({"answers": answers, "info": info})


async def _run():
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/lookup", _lookup_page)
    app.router.add_get("/room", _room_page)
    app.router.add_get("/room/detail", _room_detail)
    app.router.add_get("/room/history", _room_history)
    app.router.add_get("/room/ask_stream", _room_ask_stream)
    app.router.add_post("/room/ask", _room_ask)
    app.router.add_get("/trades", _trades_page)
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
