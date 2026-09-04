# -*- coding: utf-8 -*-
"""obis `04_AI Report/Investment` 的資料夾結構（2026-09-05，Leo：「幫我整理一下」）。

## 🔴 為什麼整理資料夾必須連程式一起改

這個路徑原本被 **11 支程式各自寫死一次**。如果只搬檔案不改程式，隔天早上
08:45 的排程會把它們**重新寫回最上層**——整理當天有效、隔天自動失效，
而且看起來會像是「Leo 自己又把檔案丟出來」，沒有人會發現是排程做的。

⭐ **同一個常數散在 N 個檔案裡，就代表之後一定會漏改其中幾個。**
（同一個形狀在這個專案踩過三次：核心公式改了只改一處、`\\b` 單位改了漏掉寫死的
52/26、失效條件登錄簿的 key 沒正規化。）

## 結構

    Investment/
    ├── 每日看板/          程式自動更新的儀表板（每天／每週被覆寫）
    ├── 個股整合報告/       索引 + 每檔一份（stock_brief.py）
    ├── 財報懶人包/         每檔每季一份（earnings_infographic.py）
    ├── 產業鏈深度報告/     每月一次的深度解讀
    └── 存檔/              一次性報告，產出後不會再更新

## 怎麼分

**看「誰會再寫它一次」**，不是看內容主題：
會被程式覆寫的進 `每日看板/`（看到舊日期就代表那支壞了），
一次性產出的進 `存檔/`（舊日期是正常的，因為本來就不會更新）。
兩者混在一起時，**「這個檔案過期了」跟「這個檔案本來就是那天的」分不出來**。
"""
import os

ROOT = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"

DAILY = os.path.join(ROOT, "每日看板")
BRIEFS = os.path.join(ROOT, "個股整合報告")
EARNINGS = os.path.join(ROOT, "財報懶人包")
CHAINS = os.path.join(ROOT, "產業鏈深度報告")
ARCHIVE = os.path.join(ROOT, "存檔")

ALL_DIRS = (DAILY, BRIEFS, EARNINGS, CHAINS, ARCHIVE)


def available():
    """obis 這台機器上在不在。

    🔴 這個判斷是必要的，不是防禦性程式碼：`portfolio_html.py`／`buffett_html.py`／
    `industry_rotation.py` **也會在 GitHub Actions 的 Linux runner 上跑**，那裡
    `C:\\Users\\...` 只是一個普通字串。原本的寫法是 `io.open(join(OBIS, name))`
    直接失敗、被呼叫端的 try/except 吞掉，沒事；但只要有人在寫檔前先 `makedirs`，
    Linux 會**真的建出一個名字裡有反斜線的資料夾**並把 6MB 的 HTML 寫進去，
    然後被 `git add` 掃進公開 repo。
    ⭐ 加「先建資料夾」這種看起來無害的一行，會把原本安全的失敗變成成功的錯誤。
    """
    return os.path.isdir(ROOT)


def ensure(d):
    """建資料夾（已存在就什麼都不做）並回傳它。

    obis 不在這台機器上時**不建任何東西**，直接回傳路徑讓後續的開檔照舊失敗——
    呼叫端本來就有 try/except，維持原本的行為。
    """
    if available():
        os.makedirs(d, exist_ok=True)
    return d


def daily(name):
    """程式每天／每週覆寫的儀表板。"""
    return os.path.join(ensure(DAILY), name)


def brief(name):
    """個股整合報告（索引也在這裡——它用相對路徑連同資料夾的個股頁）。"""
    return os.path.join(ensure(BRIEFS), name)


def earnings(name):
    """財報懶人包（每檔每季一份）。"""
    return os.path.join(ensure(EARNINGS), name)


def archive(name):
    """一次性報告：產出後不會再被任何程式覆寫。"""
    return os.path.join(ensure(ARCHIVE), name)


# 多數呼叫端是 `os.path.join(OBIS, "檔名.html")` 之後直接開檔寫入——它們不會
# 呼叫 ensure()，所以子資料夾必須在這裡就備妥，否則第一次寫入會因為「資料夾
# 不存在」而失敗（而且是被 try/except 吞掉的那種靜默失敗）。
# 只在 obis 真的存在時建，理由見 available()。
if available():
    for _d in ALL_DIRS:
        os.makedirs(_d, exist_ok=True)
