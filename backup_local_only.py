# -*- coding: utf-8 -*-
"""把「被 .gitignore 擋掉、但其實是正式原始碼」的檔案備份到 Google Drive。

**為什麼需要**：`trade_plan.py` 被刻意排除在版控外（它寫著 Leo 的部位規則和
「台股帳戶佔總資產 80%」這類個人財務資訊，而這個 repo 走 GitHub Pages 是公開的）。
排除是對的，但代價是它**沒有任何一份備份**——2026-08-31／09-01 兩次修改都只存在
本機，換機器或被覆寫就沒了。

備到 Drive 而不是解除 ignore：不能為了備份把個資推上公開 repo。
沿用 `TradingBot/backup.py` 的做法（Drive + 輪替），差別是這台有 Drive for Desktop
掛在本機，直接複製即可，不必走 Drive API。

⚠️ 這支刻意**不寫死檔名**：從 `git check-ignore` 反推「哪些 .py 被忽略」，
所以之後再有第二支這種檔案會自動被納入。反過來說，如果哪天多出一支不該備份的，
它會出現在輸出裡讓人看見（寧可多印也不要靜靜漏掉）。

用法：python backup_local_only.py
"""
import os
import sys
import glob
import shutil
import subprocess
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

DEST = (r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區"
        r"\02_Database\AI project\daily_stock_analysis\_local_only")
KEEP_LAST = 8          # 每檔保留幾份歷史

# 這些 ignore 規則擋掉的是暫時檔，不是正式原始碼，不用備份
THROWAWAY_PREFIXES = ("test_", "verify_")


def ignored_sources():
    """回傳「被 git 忽略、但屬於正式原始碼」的 .py 清單。"""
    out = []
    for p in sorted(glob.glob("*.py")):
        if p.startswith(THROWAWAY_PREFIXES):
            continue
        r = subprocess.run(["git", "check-ignore", "-q", p], capture_output=True)
        if r.returncode == 0:          # 0 = 有被忽略
            out.append(p)
    return out


def rotate(name):
    """同一支檔案只留最近 KEEP_LAST 份（檔名含時間戳，字典序＝時間序）。"""
    stem = os.path.splitext(name)[0]
    olds = sorted(glob.glob(os.path.join(DEST, f"{stem}.*.py")))
    for f in olds[:-KEEP_LAST] if len(olds) > KEEP_LAST else []:
        try:
            os.remove(f)
            print(f"  輪替刪除 {os.path.basename(f)}")
        except OSError as e:
            print(f"  輪替失敗（不影響本次備份）：{e}")


def main():
    files = ignored_sources()
    if not files:
        print("沒有需要備份的本機專屬原始碼")
        return 0
    try:
        os.makedirs(DEST, exist_ok=True)
    except OSError as e:
        print(f"⚠️ 備份目的地建不起來（Drive 沒掛載？）：{e}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ok = 0
    for name in files:
        stem = os.path.splitext(name)[0]
        latest = os.path.join(DEST, name)              # 永遠是最新版，好找
        # 內容沒變就不新增歷史版本，免得輪替被無意義的每日副本洗掉
        same = os.path.exists(latest) and \
            open(latest, "rb").read() == open(name, "rb").read()
        try:
            shutil.copy2(name, latest)
            if not same:
                shutil.copy2(name, os.path.join(DEST, f"{stem}.{stamp}.py"))
                rotate(name)
            ok += 1
            print(f"✅ {name} → Drive{'（內容未變，只更新最新版）' if same else f'（新增 {stamp} 版）'}")
        except OSError as e:
            print(f"⚠️ {name} 備份失敗：{e}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
