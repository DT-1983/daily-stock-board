# -*- coding: utf-8 -*-
"""老墨三段時程的「驗證日程」（2026-09-03，報告行動 5）。

行事曆型，**不花現金**：到期前 21 天 Discord 日報第④段提醒，逾期未驗證持續提醒。
狀態：pending（未驗）/ confirmed（如期）/ slipped（延後）/ broken（前提被打破）。

## 2026-09-03 擴充（Leo：「法說會我們財報分析不是會抓資料？可以到時審核吧？」）

會，而且比代理指標直接——但原本有兩個缺口，都補了：

1. **`earnings_call.py` 抓到的「管理層展望」產完就丟**。它只回 HTML 嵌進財報卡，
   結構化項目沒存，程式沒辦法回頭查「台積電上一季對 N2 產能講了什麼」。
   → 已加 `earnings_call._persist()` 存進 `state/earnings_call_notes.json`。
2. **里程碑要看的公司不在每日財報卡母體裡**。母體是 `holdings`（31 檔），
   TSM / COHR / 2330 / 2308 / 2301 全都不在，法說會逐字稿根本不會被抓。
   → 這支自己對 `watch` 標的呼叫 `earnings_call.build()`（本機 claude，
   Max plan 走訂閱額度不是現金），**不產整張財報卡**（那要 3-8 分鐘）。

⚠️ 11 條裡有 2 條（spacex-1gw / orbit-scale）標的**非上市，沒有法說會可讀**，
到期一定要人工判斷——這在 `criteria_note` 裡標明了。

## 判定標準先訂好了（`criteria` 欄，2026-09-03）

趁還沒有部位、沒有立場先訂通過線。不然到期時一定會往「自己看好的方向」
事後合理化（見 feedback_no_self_change_criteria）。
標準是**從宣稱本身機械推出來**的；少數需要我自己抓中間線的（n2-100k 的 7 萬片）
在 `criteria_note` 裡標明「這是我訂的、不是外部來源」。

用法:
    python roadmap_milestones.py                    # 列出（含判定標準與已抓到的法說會線索）
    python roadmap_milestones.py --fetch            # 對近期到期的里程碑抓法說會展望
    python roadmap_milestones.py --fetch --days 400 # 放寬到期範圍
    python roadmap_milestones.py hvdc-3q26 confirmed "台達電 Q3 法說確認 800V 出貨"
"""
import sys
import json
import io
import os
import argparse
import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

P = "state/roadmap_milestones.json"
FETCH_WITHIN_DAYS = 150      # 只對這個天數內到期的里程碑抓法說會（一季一次就夠）


def load():
    return json.load(io.open(P, encoding="utf-8"))


def save(d):
    json.dump(d, io.open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def clues(m):
    """回這條里程碑目前抓到的法說會線索 [(ticker, quarter, item)]。

    比對只用關鍵字，**不做判定**——判定是人的事（有 criteria 可以照）。
    這裡只負責「把該看的那幾句話端到眼前」，省掉翻逐字稿。
    """
    if not m.get("watch") or not m.get("kw"):
        return []
    try:
        import earnings_call
    except Exception:                                       # noqa: BLE001
        return []
    out = []
    for tk in m["watch"]:
        out += earnings_call.guidance(ticker=tk, contains=m["kw"])
    return out


def fetch(days=FETCH_WITHIN_DAYS, only=None):
    """對近期到期、還沒驗證的里程碑，去抓它 watch 標的的法說會展望。

    ⚠️ 走本機 `claude`（Max plan 訂閱額度，不是付費 API），但每檔數十秒到數分鐘，
    所以只對 `days` 天內到期的抓，而且同一檔只抓一次（多條里程碑共用一家公司時）。
    """
    import earnings_call
    d = load()
    today = datetime.date.today()
    want = {}
    for m in d["milestones"]:
        if m.get("status") != "pending":
            continue
        if only and m["id"] != only:
            continue
        dd = (datetime.date.fromisoformat(m["due"]) - today).days
        if not only and dd > days:
            continue
        for tk in m.get("watch") or []:
            want.setdefault(tk, []).append(m["id"])
    if not want:
        print(f"{days} 天內沒有待驗證且有法說會可讀的里程碑")
        return 0
    print(f"要抓 {len(want)} 家的法說會展望：" +
          "、".join(f"{k}（{'/'.join(v)}）" for k, v in want.items()))
    ok = 0
    for tk in want:
        print(f"  {tk} …", flush=True)
        try:
            html, _txt = earnings_call.build(tk)
        except Exception as e:                              # noqa: BLE001
            print(f"    失敗：{str(e)[:100]}")
            continue
        n = len(earnings_call.guidance(ticker=tk))
        print(f"    {'抓到' if html else '沒抓到逐字稿'}，累積展望 {n} 條")
        ok += 1 if html else 0
    return ok


def listing(verbose=True):
    d = load()
    today = datetime.date.today()
    for m in d["milestones"]:
        dd = (datetime.date.fromisoformat(m["due"]) - today).days
        print(f"{m['status']:9} {m['due']}  ({dd:+5d}天)  [{m['id']}] {m['chain']}｜{m['claim']}")
        if m.get("note"):
            print(f"          ↳ {m['checked']} {m['note']}")
        if not verbose:
            continue
        c = m.get("criteria") or {}
        if c:
            print(f"          ✅ 算過：{c.get('confirmed','')}")
            print(f"          ⏳ 延後：{c.get('slipped','')}")
            print(f"          ❌ 打破：{c.get('broken','')}")
        if m.get("criteria_note"):
            print(f"          ⚠️ {m['criteria_note']}")
        for tk, q, it in clues(m)[:3]:
            print(f"          📄 {tk} {q}｜{it.get('label','')}：{str(it.get('value',''))[:90]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="?", help="里程碑 id")
    ap.add_argument("status", nargs="?", help="pending/confirmed/slipped/broken")
    ap.add_argument("note", nargs="?", default="")
    ap.add_argument("--fetch", action="store_true", help="抓近期到期里程碑的法說會展望")
    ap.add_argument("--days", type=int, default=FETCH_WITHIN_DAYS)
    ap.add_argument("--brief", action="store_true", help="只列狀態，不印判定標準")
    a = ap.parse_args()

    if a.fetch:
        fetch(a.days, only=a.id)
        return 0
    if a.id and a.status:
        assert a.status in ("pending", "confirmed", "slipped", "broken"), a.status
        d = load()
        hit = [m for m in d["milestones"] if m["id"] == a.id]
        assert hit, f"沒有這個 id：{a.id}"
        hit[0].update({"status": a.status, "note": a.note,
                       "checked": datetime.date.today().isoformat()})
        save(d)
        print("已更新：", hit[0]["id"], a.status)
        if a.status in ("slipped", "broken"):
            print(f"⚠️ 這條打到「{hit[0]['chain']}」鏈——看板 ⏱ 標籤會改，"
                  f"該鏈持股會進投資長重評名單（下次 investment_chief 執行時）")
        return 0
    listing(verbose=not a.brief)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
