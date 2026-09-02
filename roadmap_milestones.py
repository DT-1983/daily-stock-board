# -*- coding: utf-8 -*-
"""老墨三段時程的「驗證日程」（2026-09-03，報告行動 5）。

行事曆型，零成本：到期前 21 天 Discord 日報第⑤段會提醒，逾期未驗證會一直提醒。
**不自動上網查證**——那是付費呼叫；驗證在對談裡做完，用這支把結果記回去。
狀態：pending（未驗）/ confirmed（如期）/ slipped（延後）/ broken（前提被打破）。

用法：
    python roadmap_milestones.py                      # 列出
    python roadmap_milestones.py hvdc-3q26 confirmed "台達電 Q3 法說確認 800V 出貨"
"""
import sys, json, io, datetime
P = "state/roadmap_milestones.json"

def main():
    d = json.load(io.open(P, encoding="utf-8"))
    ms = d["milestones"]
    if len(sys.argv) >= 3:
        mid, st = sys.argv[1], sys.argv[2]
        note = sys.argv[3] if len(sys.argv) > 3 else ""
        assert st in ("pending", "confirmed", "slipped", "broken"), st
        hit = [m for m in ms if m["id"] == mid]
        assert hit, f"沒有這個 id：{mid}"
        hit[0].update({"status": st, "note": note, "checked": datetime.date.today().isoformat()})
        json.dump(d, io.open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已更新：", hit[0]["id"], st)
        return
    today = datetime.date.today()
    for m in ms:
        dd = (datetime.date.fromisoformat(m["due"]) - today).days
        print(f"{m['status']:9} {m['due']}  ({dd:+5d}天)  [{m['id']}] {m['chain']}｜{m['claim']}")
        if m.get("note"): print(f"          ↳ {m['checked']} {m['note']}")

if __name__ == "__main__":
    main()
