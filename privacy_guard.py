# -*- coding: utf-8 -*-
"""commit 前的私人資訊檢查（2026-09-30，Leo：「請記下來，不要出現外流，不能再犯」）。

這個 repo 是**公開**的。2026-09-29～30 兩次把家人／自己的持股金額寫進 `dev_log.md` 推上去，
更早還有把個別持股的成本、帳戶檔數、家人名字寫進程式註解與 commit 訊息——都是「寫的人記得這是公開 repo」才擋得住的東西，
而那正是靠不住的部分。所以改成程式擋：**這次要提交的新增內容**出現下列樣式就拒絕 commit。

`dev_log.md` 同日起**不再進版控**（.gitignore），因為工作紀錄逐行清不乾淨；這支檢查擋的是
程式註解與其他文字檔。

只檢查人寫的文字檔（.py／.md／.cmd／.ps1／.yml／.txt），不檢查 `state/`、`docs/`、`reports/`
（那些是程式產出的公開資料，每天自動提交，量大而且有各自的把關）。

樣式分兩層：
  ・通用樣式寫在這支程式裡（不含任何人名）。
  ・家人名字、券商帳戶名這類**本身就不能公開的字**放在 `.git/info/privacy_patterns.txt`
    （一行一個正規表示式；`.git/` 底下的東西永遠不會被提交）。

用法：
    python privacy_guard.py            # 檢查已 git add 的內容（pre-commit hook 呼叫這個）
    python privacy_guard.py --all      # 掃整個工作目錄裡進版控的文字檔（盤點用）
誤判時：把那一行改寫成不含金額／名字的說法。確定是誤判才用
    set PRIVACY_GUARD_ALLOW=1          # 只對下一個指令有效；⚠️ 要 Leo 同意，不是自己決定
"""
import os
import re
import subprocess
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXTS = (".py", ".md", ".cmd", ".ps1", ".yml", ".yaml", ".txt")
SKIP_DIRS = ("state/", "docs/", "reports/")
MONEY = r"[0-9][0-9,]*(?:\.[0-9]+)?\s*萬"
OWN = r"(?:持股|庫存|總資產|總市值|股票市值|帳上|帳戶|部位|家人|媽媽|爸爸|小孩|照做賣出|釋出現金)"
GENERIC = [
    (rf"{OWN}.{{0,40}}{MONEY}", "持股／資產相關字眼旁邊有「N 萬」金額"),
    (rf"{MONEY}.{{0,20}}{OWN}", "「N 萬」金額旁邊有持股／資產相關字眼"),
    (r"[0-9]+\s*檔[、，,／/]\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*萬", "「N 檔、N 萬」＝某人的持股規模"),
    (rf"(?:總資產|持股市值|股票市值).{{0,25}}[0-9]{{1,3}},[0-9]{{3}},[0-9]{{3}}", "總資產／市值的完整金額"),
    (r"平均成本\s*[0-9]", "個別持股的平均成本"),
    (r"成本\s*[0-9]+\.[0-9]{2}.{0,20}現價", "個別持股的成本與現價"),
    (r"\$ ?[0-9]{1,3}(?:,[0-9]{3}){2,}", "完整金額（七位數以上）"),
    (r"[0-9.]+ ?股 ?@ ?[0-9]", "實際成交（股數＠價格）"),
    (r"(?:Firstrade|IBKR).{0,24}[0-9]+ ?(?:檔|筆)", "券商帳戶的持股檔數"),
]
# 這些是公司／市場層級的數字，不是誰的持股：整行放行
# ⚠️ 不能放「成交」——「賣出 N 股 @ 某價格 成交」這種實際交易會被整行放行（要擋的正是它）
ALLOW = re.compile(r"市值\s*[0-9,]+\s*億|營收|發行|股本|成交量|成交值|方舟|萬股|萬美元")


def _local_patterns():
    try:
        top = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, text=True).stdout.strip()
        p = os.path.join(top, "info", "privacy_patterns.txt")
        with open(p, encoding="utf-8") as f:
            return [(ln.strip(), "本機清單裡的字（家人名字／帳戶名）") for ln in f
                    if ln.strip() and not ln.startswith("#")]
    except OSError:
        return []


def _added_lines():
    """已 git add 的新增行：[(檔名, 行文字)]。"""
    out = subprocess.run(["git", "diff", "--cached", "-U0", "--no-color", "--diff-filter=AM"],
                         capture_output=True).stdout.decode("utf-8", "replace")
    cur, rows = None, []
    for ln in out.splitlines():
        if ln.startswith("+++ "):
            cur = ln[6:] if ln.startswith("+++ b/") else None
        elif ln.startswith("+") and not ln.startswith("+++") and cur:
            rows.append((cur, ln[1:]))
    return rows


def _all_lines():
    files = subprocess.run(["git", "ls-files", "-z"], capture_output=True).stdout.decode("utf-8", "replace").split("\0")
    rows = []
    for f in files:
        if not f.endswith(EXTS) or f.startswith(SKIP_DIRS):
            continue
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                rows += [(f, ln.rstrip("\n")) for ln in fh]
        except OSError:
            pass
    return rows


def main():
    rows = _all_lines() if "--all" in sys.argv else _added_lines()
    pats = [(re.compile(p), why) for p, why in GENERIC + _local_patterns()]
    hits = []
    for f, ln in rows:
        if not f.endswith(EXTS) or f.startswith(SKIP_DIRS) or f == "privacy_guard.py":
            continue
        for rx, why in pats:
            m = rx.search(ln)
            if m and not ALLOW.search(ln):
                hits.append((f, why, ln.strip()[:110]))
                break
    if not hits:
        return 0
    print("🔴 privacy_guard：這次要提交的內容疑似含私人資訊（這個 repo 是公開的）")
    for f, why, ln in hits[:30]:
        print(f"  {f}｜{why}\n     {ln}")
    if len(hits) > 30:
        print(f"  …還有 {len(hits) - 30} 行")
    if "--all" in sys.argv:
        return 1
    if os.environ.get("PRIVACY_GUARD_ALLOW") == "1":
        print("⚠️ PRIVACY_GUARD_ALLOW=1：照樣提交（要確定是誤判，而且 Leo 同意）")
        return 0
    print("→ 已擋下這次 commit。把金額／檔數／名字改成「對得上」「一致」這類說法再提交。")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:                                  # noqa: BLE001
        # 檢查本身壞掉時放行並印警告——排程每天自動 commit，不能因為這支出錯整個停擺
        print(f"⚠️ privacy_guard 執行失敗（未檢查，照樣提交）：{str(e)[:100]}")
        raise SystemExit(0)
