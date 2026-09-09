# -*- coding: utf-8 -*-
"""排程 commit 前檢查：state/ 底下有沒有「新產生、還沒被追蹤、也沒被 gitignore」的檔案。

2026-09-09。搭配 board_analyze_daily.cmd 把 `git add state` 改成 `git add -u state`。

## 為什麼需要這支

改成 `git add -u` 之後，新產生的 state 檔**不會**自動進公開 repo——這是對的。
但如果就這樣算了，它會變成另一種隱形失敗：**某個檔案該公開卻一直沒上去，
而且沒有任何地方會講。**（8/01 就踩過一次同型：reports/ 被 gitignore，
`git add reports` 變成無聲的 no-op，結果 Actions 每天找不到報告。）

⭐ 所以「不自動加入」要配上「明確講出來」，才不是把一個問題換成另一個問題。

## 這支不做什麼

**不自動加、也不自動擋。**只是把清單印進 log、必要時發 Telegram。
要不要公開一個新檔案是人的決定，不是排程的預設值。
"""
import io
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = r"C:\Users\Mophy\AI\notify_tg.py"


def new_state_files():
    """回 state/ 底下未被追蹤且未被忽略的檔案清單。"""
    r = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "state/"],
        cwd=HERE, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)
    return [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]


def main():
    try:
        fs = new_state_files()
    except Exception as e:                                  # noqa: BLE001
        print(f"[new-state] 檢查失敗（不影響本次 commit）：{str(e)[:80]}")
        return 0
    if not fs:
        print("[new-state] state/ 沒有新的未追蹤檔案")
        return 0

    print(f"[new-state] ⚠️ state/ 有 {len(fs)} 個新檔案**沒有進版控**"
          f"（git add -u 只更新已追蹤的）：")
    for f in fs[:20]:
        print(f"  · {f}")
    if len(fs) > 20:
        print(f"  … 另有 {len(fs) - 20} 個")
    print("  → 該公開的請 `git add -f <path>`；"
          "私人的請加進 .gitignore（兩者都要人決定）")

    # Telegram 只在數量不大時列檔名，避免洗版；重點是「有這件事」。
    try:
        body = (f"state/ has {len(fs)} new untracked file(s) NOT in the repo. "
                + ("First few: " + ", ".join(fs[:5]) if len(fs) <= 5
                   else "See board_analyze.log."))
        subprocess.run([sys.executable, NOTIFY,
                        "New state files not committed", body], timeout=120)
    except Exception as e:                                  # noqa: BLE001
        print(f"  [warn] Telegram 通知失敗：{str(e)[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
