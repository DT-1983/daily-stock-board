# -*- coding: utf-8 -*-
"""GitHub Actions 排程看門狗（2026-08-27）。

背景：GitHub 的 schedule 是「盡力而為」，8/26-8/27 連兩天整批沒觸發
（tw-board 00:15/00:19、market-home 07:10 都沒跑）——晨報沒發、首頁停在前一天。
這支在本機檢查「今天該跑的 workflow 真的跑了嗎」，沒跑就用 workflow_dispatch 補觸發，
可選擇等它跑完（下游要吃它產出時用 --wait，例如 researcher_stock_sync 要拉
st_flips_today.json）。

用法:
    python actions_watchdog.py tw-board.yml --wait     # 沒跑就補觸發並等完成
    python actions_watchdog.py market-home.yml         # 沒跑就補觸發，不等
需要本機 gh CLI 已登入（排程環境已具備）。
"""
import io
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = "DT-1983/daily-stock-board"


def _gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    return r.returncode, r.stdout


def ran_today(workflow: str) -> bool:
    """今天（UTC日期，跟cron同基準）有沒有任何一次成功/進行中的執行。
    schedule 或 dispatch 都算——已經有人補觸發過就不用再補。"""
    code, out = _gh("run", "list", "--repo", REPO, "--workflow", workflow,
                    "--limit", "5", "--json", "status,conclusion,createdAt,event")
    if code != 0:
        print(f"  gh run list 失敗（先當作有跑，避免重複觸發）")
        return True
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for r in json.loads(out or "[]"):
        if r.get("createdAt", "").startswith(today_utc) and \
           r.get("conclusion") != "failure":
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("--wait", action="store_true", help="補觸發後等它跑完（最多12分鐘）")
    args = ap.parse_args()

    if ran_today(args.workflow):
        print(f"✅ {args.workflow} 今天已執行過，不用補")
        return 0

    print(f"⚠️ {args.workflow} 今天沒被 GitHub 排程觸發（連續發生中），補 dispatch…")
    code, _ = _gh("workflow", "run", args.workflow, "--repo", REPO)
    if code != 0:
        print("  補觸發失敗")
        return 1
    if not args.wait:
        print("  已補觸發（不等待完成）")
        return 0

    for i in range(24):                       # 24 × 30s = 最多 12 分鐘
        time.sleep(30)
        code, out = _gh("run", "list", "--repo", REPO, "--workflow", args.workflow,
                        "--limit", "1", "--json", "status,conclusion")
        if code != 0:
            continue
        rows = json.loads(out or "[]")
        if rows and rows[0].get("status") == "completed":
            print(f"  補跑完成：{rows[0].get('conclusion')}")
            return 0 if rows[0].get("conclusion") == "success" else 1
    print("  等待逾時（12分鐘），下游先繼續用現有資料")
    return 1


if __name__ == "__main__":
    sys.exit(main())
