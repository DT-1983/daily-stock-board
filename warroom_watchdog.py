# -*- coding: utf-8 -*-
"""看門狗：檢查今天的 Discord 日報有沒有真的發出去，沒有就重跑。

2026-09-09 Leo：「有辦法自己檢查有沒有跑成功嗎？如果沒有可以重跑嗎？」

## 為什麼需要（今天發生的事）

08:45 的 `researcher_stock_sync.cmd` 在第 135 行被中斷，
而發 Discord 的 `daily_warroom.py` 在第 177 行——**整天零 Discord**。

更糟的是：那支腳本**其實有失敗通知**，文案還寫著
「This is why no Discord report today」——但它在第 220 行。
🔴 **被中途砍死的腳本，跑不到自己的死亡通知。**
所以 Leo 不但沒收到日報，連「今天沒有日報」都沒人告訴他。

⭐ 監看必須來自**外部**。跟被監控對象死在同一個程序裡的檢查，等於沒有檢查。

## 檢查什麼

**查產出物，不查 exit code。**今天主排程 exit 0，Discord 一樣沒發——
因為根本沒跑到那一步。唯一可信的證據是 `state/daily_warroom_sent.json`
裡有沒有今天的日期。

沒有那個檔＝沒跑到；有檔但 ok=False＝跑到了但 webhook 失敗（重跑也沒用，要人看）。

## 用法

    python warroom_watchdog.py            # 檢查，需要時重跑
    python warroom_watchdog.py --check    # 只檢查不重跑
"""
import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = os.path.join(HERE, "state", "daily_warroom_sent.json")
ATTEMPT = os.path.join(HERE, "state", "warroom_watchdog_attempts.json")
SYNC = r"C:\Users\Mophy\AI\researcher_stock_sync.cmd"

EXPECT_AFTER = 9        # 08:45 的批次正常會在 9 點前發完，之前不算異常
MAX_RETRY = 2           # 一天最多自動重跑幾次——避免壞掉的東西被無限重試


def _load(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def already_running():
    """已經有一支在跑就不要再開一支（重跑同時跑會互相踩 state 檔）。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name like '%cmd.exe%'\" |"
             " Where-Object { $_.CommandLine -like '*researcher_stock_s*' } |"
             " Measure-Object).Count"],
            capture_output=True, text=True, timeout=60)
        return int((r.stdout or "0").strip() or 0) > 0
    except Exception:                                       # noqa: BLE001
        return False


def notify(title, body):
    """走既有的 Telegram 通知——**不要在這裡發 Discord**：
    Discord 正是壞掉的那條路，用它報告自己壞了是沒有意義的。"""
    try:
        subprocess.run([sys.executable, r"C:\Users\Mophy\AI\notify_tg.py",
                        title, body], timeout=120)
    except Exception as e:                                  # noqa: BLE001
        print(f"  [warn] Telegram 通知失敗：{str(e)[:80]}")


def main():
    ap = argparse.ArgumentParser(description="檢查 Discord 日報有沒有發出去")
    ap.add_argument("--check", action="store_true", help="只檢查，不重跑")
    a = ap.parse_args()

    now = dt.datetime.now()
    today = now.date().isoformat()

    if now.weekday() >= 5:
        print(f"{today} 是週末，日報本來就不發，跳過")
        return 0
    if now.hour < EXPECT_AFTER:
        print(f"現在 {now:%H:%M}，還沒到 {EXPECT_AFTER}:00，太早不判定")
        return 0

    mark = _load(MARK, {})
    if mark.get("date") == today:
        if mark.get("ok"):
            print(f"✅ 今天的日報已發（{mark.get('ts')}，"
                  f"成功 {len(mark.get('sent') or [])} 則）")
            return 0
        # 跑到了但一則都沒成功 → 重跑也不會好（webhook／網路問題），要人看
        print(f"⚠️ 今天有跑到發送步驟，但一則都沒成功：{mark.get('failed')}")
        notify("Discord daily report: all sends failed",
               f"daily_warroom ran at {mark.get('ts')} but every send failed. "
               f"Re-running will not help - check webhook config / network.")
        return 1

    print(f"🔴 找不到今天（{today}）的發送紀錄 → 08:45 的批次沒跑到 daily_warroom")

    att = _load(ATTEMPT, {})
    n = att.get(today, 0)
    if a.check:
        print("  （--check 模式，不重跑）")
        return 1
    if n >= MAX_RETRY:
        print(f"  今天已自動重跑 {n} 次，不再重試")
        notify("Discord daily report still missing",
               f"Watchdog retried {n} times today and the report is still "
               f"not sent. Needs a human. See board_analyze.log.")
        return 1
    if already_running():
        print("  已經有一支 researcher_stock_sync 在跑，這次不重複啟動")
        return 0

    print(f"  → 重跑 researcher_stock_sync.cmd（今天第 {n + 1} 次）")
    att[today] = n + 1
    os.makedirs(os.path.dirname(ATTEMPT), exist_ok=True)
    io.open(ATTEMPT, "w", encoding="utf-8").write(
        json.dumps(att, ensure_ascii=False, indent=1))
    subprocess.Popen(["cmd.exe", "/c", SYNC], cwd=os.path.dirname(SYNC),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    notify("Discord daily report missing - auto re-running",
           f"No daily_warroom send record for {today}. "
           f"Watchdog started researcher_stock_sync.cmd (attempt {n + 1}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
