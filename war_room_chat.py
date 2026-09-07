# -*- coding: utf-8 -*-
"""軍師對話的記憶層：續談 session ＋ 對話記錄（2026-09-07）。

Leo：「軍師也希望可以上線，然後把對話記下來，之後問到可以同步（discord 也同步）」
     「需要跨天，可以會翻回之前的討論」

## 這一層在做什麼

`war_room.py` 只負責「組材料、問一次、回一段話」，它是無狀態的。
續談與記錄本來散在 `lamp_room._SESSIONS`（一個記憶體 dict，重啟就沒），
Discord 那邊則**完全沒有**——同一位軍師在網頁跟 Discord 是兩條互不相干的線。
這個模組把兩者收成同一份：

  · `state/war_room_sessions.json`  —— 續談用的 session id（誰、哪一檔、談到哪）
  · `state/war_room_chats.jsonl`    —— 每一輪問答的全文（可以翻回去看）

網頁與 Discord 都走這裡的 `ask()`，所以**在 Discord 問完，回網頁點同一檔會接著談**，
反過來也是。

## 🔴 跨天續談：材料會過期，所以要主動換掉

原本刻意不給跨天，理由是燈號每天重掃，昨天的價格/風報比接著談就是拿舊數字回答今天。
Leo 要跨天，所以改成**把新材料補進去**而不是禁止：偵測到「上次談的資料日 ≠ 今天的資料日」，
就在問題最前面塞一段「先前對話的數字全部作廢，以這一輪材料為準」。

⭐ 這跟 2026-09-04「問高力答 HIG」的修法是同一個原則：
   **材料缺一塊，模型就會自己補一塊，而且補得很自然**——
   要補的是材料，不是再寫一條「不要用舊數字」的 prompt 規則。
   （見記憶 war_room_advisors、comment_is_not_code。）

## 🔴 這兩個檔案不進公開 repo

裡面是 Leo 的持股、成本、他實際在煩惱什麼——比燈號本身敏感得多。
已加進 .gitignore；**新增任何欄位前先想一次會不會把私人資訊寫進公開的地方**
（見記憶 code_is_data_privacy：「輸出不公開」≠「程式可以寫死私人資訊」）。
"""
import datetime as dt
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SESS_PATH = os.path.join(HERE, "state", "war_room_sessions.json")
CHAT_PATH = os.path.join(HERE, "state", "war_room_chats.jsonl")
RESULT_PATH = os.path.join(HERE, "state", "combo_result.json")

# 一檔一位軍師最多留幾輪在「翻回去看」的清單裡（jsonl 本身不刪，只是不全部端出來）
HISTORY_LIMIT = 40


# ── 資料日：判斷「上次談的材料是不是今天的」 ──────────────────────
def current_asof():
    """今天材料的資料日。用 combo_result 的日期——燈號、風報比、距停損全來自它。

    ⚠️ 不要用 `date.today()`：週末與收盤前跑，掃描結果的資料日跟今天不一樣，
    那樣會每天都判定成「材料換了」，天天多塞一段沒必要的提醒。
    """
    try:
        d = json.load(io.open(RESULT_PATH, encoding="utf-8"))
        return str(d.get("date") or (d.get("rows") or [{}])[0].get("asof") or "")
    except Exception:                                       # noqa: BLE001
        return ""


# ── session（續談） ────────────────────────────────────────────────
def _load_sessions():
    try:
        return json.load(io.open(SESS_PATH, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}


def _save_sessions(d):
    os.makedirs(os.path.dirname(SESS_PATH), exist_ok=True)
    tmp = SESS_PATH + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(
        json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, SESS_PATH)


def _key(role, ticker):
    """key = 角色｜標的。

    🔴 **一定要綁標的**。續談表示這一輪建立在上一輪的材料上；看完 6442 換去
    2454 再問「那它呢」，軍師手上還是 6442 的材料——那正是「問高力答 HIG」
    那一類錯換個入口回來。換標的就換 key ＝ 自動重開，材料不會串味。
    沒指定標的（大盤、整體風險）自成一條線，key 的標的部分是空字串。
    """
    return f"{role}|{str(ticker or '').upper()}"


def get_session(role, ticker):
    """回 (session_id, 上次談的資料日, 上次時間)。沒談過回 (None, "", "")。"""
    r = _load_sessions().get(_key(role, ticker)) or {}
    return r.get("sid"), r.get("asof") or "", r.get("ts") or ""


def put_session(role, ticker, sid, asof):
    if not sid:
        return
    d = _load_sessions()
    k = _key(role, ticker)
    prev = d.get(k) or {}
    d[k] = {"sid": sid, "asof": asof or "",
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "turns": int(prev.get("turns") or 0) + 1}
    _save_sessions(d)


def drop_session(role, ticker):
    d = _load_sessions()
    if d.pop(_key(role, ticker), None) is not None:
        _save_sessions(d)


# ── 跨天：把新材料的優先權講白 ─────────────────────────────────────
def refresh_block(old_asof, new_asof):
    """續談跨過資料日時，加在問題最前面的一段。

    ⚠️ 這段一定要放在**問題**裡而不是材料裡：材料每次都是重新組的（本來就是新的），
    模型要被告知的是「你記得的那些數字已經不算數了」——那是關於**對話**的事，
    不是關於材料的事。
    """
    return (f"【⚠️ 材料已更新：我們上次談是 {old_asof} 的數字，這一輪是 {new_asof}】\n"
            "你在先前對話裡看到的價格、燈號、風報比、距停損**全部作廢**，"
            "一律以這一輪材料裡的數字為準。\n"
            "如果要沿用前面談過的結論，請先用新數字確認它還成不成立；"
            "已經不成立的要直接講「前次的看法已經不適用，因為 …」。\n\n")


# ── 對話記錄 ──────────────────────────────────────────────────────
def log_turn(role, ticker, question, answer, src="room",
             asof="", resumed=False, refreshed=False, meta=None):
    """寫一輪問答。**append-only**，不覆蓋、不刪除。"""
    meta = meta or {}
    rec = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "src": src,                       # room / discord
        "role": role,
        "ticker": str(ticker or "").upper(),
        "asof": asof,
        "resumed": bool(resumed),         # 是否接著上一輪談
        "refreshed": bool(refreshed),     # 是否跨天、有塞材料更新提示
        "q": question or "",
        "a": answer or "",
        "cost_usd": float(meta.get("cost_usd") or 0),
        "session_id": meta.get("session_id") or "",
    }
    try:
        os.makedirs(os.path.dirname(CHAT_PATH), exist_ok=True)
        with io.open(CHAT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:                                  # noqa: BLE001
        print(f"[war_room_chat] 寫記錄失敗：{str(e)[:80]}", flush=True)
    return rec


def history(ticker=None, role=None, limit=HISTORY_LIMIT):
    """翻回之前的討論。給 ticker 就只看那一檔；都不給＝全部（最近的在最後）。

    ⚠️ 從檔尾往回讀，不要整份載進來——這個檔會一直長。
    """
    if not os.path.exists(CHAT_PATH):
        return []
    tk = str(ticker or "").upper()
    out = []
    try:
        lines = io.open(CHAT_PATH, encoding="utf-8").read().splitlines()
    except Exception:                                       # noqa: BLE001
        return []
    for ln in reversed(lines):
        if len(out) >= limit:
            break
        try:
            r = json.loads(ln)
        except Exception:                                   # noqa: BLE001
            continue
        if ticker is not None and r.get("ticker", "") != tk:
            continue
        if role and r.get("role") != role:
            continue
        out.append(r)
    out.reverse()
    return out


def stats():
    """給收尾/健檢用：總輪數、幾檔、幾條續談線。"""
    h = history(ticker=None, limit=10 ** 9)
    return {"turns": len(h),
            "tickers": len({r.get("ticker") for r in h if r.get("ticker")}),
            "sessions": len(_load_sessions())}


# ── 統一入口：網頁與 Discord 都走這裡 ──────────────────────────────
def ask(role, question, ticker=None, fresh=False, prior=None, src="room"):
    """問一位軍師，自動處理續談、跨天換材料、寫記錄。

    回 (回答文字, meta, 資訊dict)。資訊 dict：
      resumed   接著上一輪談
      refreshed 跨天，已塞材料更新提示
      since     上一輪是什麼時候（給前端顯示「接續 9/5 的對話」）

    ⚠️ **不重寫任何判斷邏輯**，材料組裝與 prompt 全部還是 war_room 的。
       這裡只管「記得上次談到哪」。
    """
    import war_room
    tk = str(ticker or "").upper()
    asof = current_asof()
    sid, old_asof, old_ts = (None, "", "") if fresh else get_session(role, tk)

    q = question or ""
    refreshed = False
    if sid and old_asof and asof and old_asof != asof:
        q = refresh_block(old_asof, asof) + q
        refreshed = True

    txt, meta = war_room.ask_meta(role, q, prior=prior, resume=sid)
    if meta.get("session_id"):
        put_session(role, tk, meta["session_id"], asof)
    log_turn(role, tk, question or "", txt, src=src, asof=asof,
             resumed=bool(sid), refreshed=refreshed, meta=meta)
    return txt, meta, {"resumed": bool(sid), "refreshed": refreshed,
                       "since": old_ts}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="軍師對話記錄")
    ap.add_argument("--ticker", default=None, help="只看這一檔（不給＝全部）")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--sessions", action="store_true", help="列出續談中的線")
    a = ap.parse_args()
    if a.sessions:
        for k, v in sorted(_load_sessions().items()):
            print(f"{k:24} {v.get('asof','')}  {v.get('ts','')}  "
                  f"{v.get('turns',0)} 輪")
        return 0
    for r in history(a.ticker, limit=a.n):
        flag = ("　續談" if r["resumed"] else "　新開") + ("　跨天換材料" if r["refreshed"] else "")
        print(f"── {r['ts']}　{r['role']}　{r['ticker'] or '（無標的）'}"
              f"　[{r['src']}]{flag}")
        print(f"   Q {r['q'][:120]}")
        print(f"   A {r['a'][:200]}\n")
    s = stats()
    print(f"共 {s['turns']} 輪／{s['tickers']} 檔／{s['sessions']} 條續談線")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
