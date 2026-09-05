# -*- coding: utf-8 -*-
"""券商研究報告的可信度註記（2026-09-05，Leo 上課筆記轉述老墨）。

## 🔴 為什麼**不是**加進 `target_changes.TRUSTED`

那個名單管的是**每日目標價異動表**（Leo 丟的截圖）。實查那張表出現過的 20 家
券商，**中信投顧（CTBC）從來沒出現過**——那張表上的是外資與少數本土券商
（Morningstar 15／Goldman 6／JP Morgan 6／…／SinoPac 5／KGI 3／元大 1）。

⚠️ 而且照字面把「中信」對到那張表，最接近的是 **`CITI`——那是花旗，不是中國信託**。
⭐ 這跟 `"gs"` 命中 `"mornin(gs)tar"` 是同一類錯誤，只是更難發現，因為兩個名字
真的很像。所以可信度註記獨立成這一支，**兩個名單各管各的，不互相污染**。

## 這一支只做「標註」，不做「過濾」

它不會讓任何報告消失，也不改任何門檻。只是在報告頁／整合報告／仲達材料上
多一行「這家的已知偏誤是什麼」，讓讀的人自己折價。

⚠️ **這些是老墨的經驗判斷，不是我們回測出來的。** 每一條都標明來源，
不要讓它看起來像我們自己驗證過的結論。要驗證需要累積各家的目標價達成率
——實查現況：高盛那份附了 17 筆目標價調整史、元大 3 筆、
**中信 11 份全部 0 筆**（本土投顧的報告不附調整史），所以目前**無法比較**。
"""
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE = "老墨 2026-09-05 課堂（Leo 轉述）"

# 比對用**整詞／子字串**：券商名稱在我們的解析結果裡是中文（中信投顧／高盛／元大投顧…）。
# key 用能唯一辨識的最短字串，避免像 CITI/中信 那種撞名。
# 每家可以有多個別名（解析出來的券商名不保證只有一種寫法）。
# ⚠️ 別名只放**不會撞名**的：加 "goldman" 安全，加 "gs" 不行——那正是
# 命中 "mornin(gs)tar" 的那個坑。加 "中國信託" 安全，加 "citi" 絕對不行。
ALIASES = {
    "中信": ("中信", "中國信託", "ctbc"),
    "高盛": ("高盛", "goldman"),
    "統一": ("統一", "uni-president", "president securities"),
}

NOTES = {
    "中信": {
        "tag": "★ 可信度較高",
        "level": "good",
        "note": "老墨點名可信。⚠️ 這是他的經驗判斷，我們沒有自己的驗證數據"
                "——中信的報告不附目標價調整史（11 份全部 0 筆），無從回溯它過去準不準。",
    },
    "高盛": {
        "tag": "⚠️ 期望值偏高",
        "level": "warn",
        "note": "老墨提醒高盛的期望值高。**這一條我們有數據佐證**："
                "它 2454 那份自附的 17 筆調整史顯示，2023-10 至 2026-07 目標價 +665%、"
                "同期股價 +344%——**目標價漲得比股價快**。看它的目標價時記得折價。",
    },
    "統一": {
        "tag": "📼 需搭配法說會",
        "level": "warn",
        "note": "老墨：統一的報告要搭配法說會錄音檔一起看，只讀報告不夠。"
                "⚠️ 目前我們一份統一的報告都沒有，這條先放著。",
    },
}


def note_for(broker):
    """回這家券商的註記 dict，沒有就回 None。"""
    b = str(broker or "").lower()
    if not b.strip():
        return None
    for k, v in NOTES.items():
        for al in ALIASES.get(k, (k,)):
            if al.lower() in b:
                return dict(v, broker=str(broker), key=k, source=SOURCE)
    return None


def line_for(broker):
    """一行文字版（給日報／仲達材料用）。沒有註記回空字串。"""
    n = note_for(broker)
    return f"{n['tag']}｜{n['note']}（來源：{n['source']}）" if n else ""


def _main():
    import json
    import io
    import collections
    st = json.load(io.open("state/advisor_reports.json", encoding="utf-8"))
    c = collections.Counter()
    for r in st.values():
        if not r.get("_notreport"):
            c[r.get("broker") or "?"] += 1
    print(f"目前 {sum(c.values())} 份報告，{len(c)} 家券商：\n")
    for b, n in c.most_common():
        x = note_for(b)
        print(f"  {b:10} {n:2} 份   {x['tag'] if x else '（無註記）'}")
        if x:
            print(f"             {x['note']}")
    print()
    unused = [k for k in NOTES if not any(k in (b or "") for b in c)]
    if unused:
        print(f"⚠️ 名單裡但目前沒有報告的：{', '.join(unused)}")


if __name__ == "__main__":
    _main()
