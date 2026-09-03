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

# 2026-09-03：**被 .gitignore 保護的資料檔也要備份**，而且比 .py 更急——
# .py 至少還在我腦袋裡可以重寫，這幾個是累積出來的紀錄，弄丟就沒了。
#
# 這條是踩到才加的：9/3 把 `state/thesis_conditions.json` 移出版控（它帶
# held=true，等於持股清單留在公開 repo）之後，接著的 rebase/stash 流程把它從
# 磁碟上也弄掉了，只能從 git 上一版還原，**中間 28 條觸發標記永久遺失**。
# 移出版控＝失去 git 這層意外保險，那就必須補一層備份，否則等於用隱私換備份。
#
# ⚠️ 這裡刻意**列舉而不是自動掃 state/**：state/ 底下絕大多數是每天重跑就會
# 重建的快取（price_store、combo_result…），全掃會把 Drive 灌爆而且沒意義。
# 判準是「弄丟了能不能重建」，不是「是不是被 ignore」。
DATA_FILES = [
    "state/trade_journal.jsonl",       # Leo 的交易紀錄——完全無法重建，最優先
    "state/advisor_verdicts.jsonl",    # 孔明歷來所有判斷＋推理，重跑要花錢且結果不同
    "state/research_notes.jsonl",      # 龐統歷來研究筆記，同上
    "state/thesis_conditions.json",    # 失效條件登錄簿＋累積的觸發狀態
    # 2026-09-03：券商研究報告結構化結果。原始 PDF 在 Documents/Investment 不會
    # 消失，但這份是本機 claude 逐份解析的產物（每份數十秒），重跑成本高、
    # 而且是 gitignore 檔（第三方付費研究內容不進公開 repo）→ 只有備份救得回來。
    "state/advisor_reports.json",
]


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


def data_files():
    """回傳實際存在、且確實被 git 忽略的資料檔。

    **被忽略才備份**是刻意的檢查：如果哪天某個檔案不小心又進了版控，這裡會少印
    一行，而不是安靜地雙份備著讓人以為沒事——那正是 9/3 那次外洩沒被發現的原因。
    """
    out = []
    for p in DATA_FILES:
        if not os.path.exists(p):
            print(f"⚠️ {p} 不存在（是不是被誤刪了？）")
            continue
        r = subprocess.run(["git", "check-ignore", "-q", p], capture_output=True)
        if r.returncode != 0:
            print(f"⚠️ {p} **沒有被 .gitignore 擋住**——它含私人資料，請檢查 .gitignore")
        out.append(p)
    return out


def rotate(name, ext):
    """同一支檔案只留最近 KEEP_LAST 份（檔名含時間戳，字典序＝時間序）。"""
    stem = os.path.splitext(os.path.basename(name))[0]
    olds = sorted(glob.glob(os.path.join(DEST, f"{stem}.*{ext}")))
    for f in olds[:-KEEP_LAST] if len(olds) > KEEP_LAST else []:
        try:
            os.remove(f)
            print(f"  輪替刪除 {os.path.basename(f)}")
        except OSError as e:
            print(f"  輪替失敗（不影響本次備份）：{e}")


def main():
    files = ignored_sources() + data_files()
    if not files:
        print("沒有需要備份的本機專屬檔案")
        return 0
    try:
        os.makedirs(DEST, exist_ok=True)
    except OSError as e:
        print(f"⚠️ 備份目的地建不起來（Drive 沒掛載？）：{e}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ok = 0
    for name in files:
        base = os.path.basename(name)                  # state/x.json → x.json
        stem, ext = os.path.splitext(base)
        latest = os.path.join(DEST, base)              # 永遠是最新版，好找
        # 內容沒變就不新增歷史版本，免得輪替被無意義的每日副本洗掉
        same = os.path.exists(latest) and \
            open(latest, "rb").read() == open(name, "rb").read()
        try:
            shutil.copy2(name, latest)
            if not same:
                shutil.copy2(name, os.path.join(DEST, f"{stem}.{stamp}{ext}"))
                rotate(name, ext)
            ok += 1
            print(f"✅ {name} → Drive{'（內容未變，只更新最新版）' if same else f'（新增 {stamp} 版）'}")
        except OSError as e:
            print(f"⚠️ {name} 備份失敗：{e}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
