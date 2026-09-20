# -*- coding: utf-8 -*-
"""把投顧／券商研究整理成「不具名」的每鏈摘要，給 refresh-chain-reports 的研究 Agent 讀（2026-09-20）。

Leo：「只讀投顧資料就好；不要寫是哪一家，只要寫是券商」。
資料來源：state/advisor_reports.json（本機、已 gitignore；由 Leo 丟進 Documents\\Investment\\投顧報告 的 PDF 解析而來）。
輸出：chain_reports_src/broker_digest/<slug>.md（已 gitignore，每次跑重產，不進公開 repo）。

摘要只放：家數、評等分布、目標價區間／中位數、論點與風險（去掉券商名稱）。
Agent 拿到後必須用自己的話改寫、不逐字引用、不點名——公開報告最後還會過 brokers.scrub 再擋一次。

用法：python chain_reports_src/broker_digest.py [--days 240]
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import statistics

import brokers

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUTDIR = os.path.join(HERE, "broker_digest")
DATADIR = os.path.join(HERE, "reports_data")


def _slugs():
    """slug ↔ 鏈名，取自各鏈研究 JSON 的 _chain。"""
    out = {}
    for fp in glob.glob(os.path.join(DATADIR, "*.json")):
        d = json.load(open(fp, encoding="utf-8"))
        if d.get("_chain"):
            out[os.path.basename(fp)[:-5]] = d["_chain"]
    return out


def _date_of(key, rec):
    if rec.get("date"):
        return rec["date"]
    m = re.match(r"(\d{4})(\d{2})(\d{2})_", key)          # 檔名開頭 YYYYMMDD
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def build(days=240):
    screen = json.load(open(os.path.join(REPO, "screen_result.json"), encoding="utf-8"))
    adv = json.load(open(os.path.join(REPO, "state", "advisor_reports.json"), encoding="utf-8"))
    today = dt.date.today()
    recs = {}                                              # ticker -> [每家最新一份]
    for key, r in adv.items():
        d = _date_of(key, r)
        if not d:
            continue
        if (today - dt.date.fromisoformat(d)).days > days:
            continue
        recs.setdefault(str(r.get("ticker")), {})
        b = r.get("broker") or key
        cur = recs[str(r["ticker"])].get(b)
        if not cur or d > cur["_d"]:
            recs[str(r["ticker"])][b] = dict(r, _d=d)
    os.makedirs(OUTDIR, exist_ok=True)
    written = {}
    for slug, chain in _slugs().items():
        codes = [x["code"] for x in screen.get("us", {}).get(chain, [])] + \
                [x["code"] for x in screen.get("tw", {}).get(chain, [])]
        lines = [f"# {chain}：券商研究摘要（不具名）", "",
                 "使用規則（必須遵守）：",
                 "1. 用自己的話改寫成「券商研究普遍認為…」「多數券商看…」這類說法；**不得點名任何券商或分析師**，只能寫「券商」。",
                 "2. **不得逐字引用**原文句子；不得貼原文段落。",
                 "3. 個別目標價只能用中位數或區間，不要寫成某一家的目標價。",
                 "4. 這些是輸入素材：還是要跟網路查證的最新資料交叉核對，衝突時以查證資料為準並註明差異。",
                 "5. `sources` 欄請加一句「券商研究報告（多家，不具名）」，不要列出券商名稱。", ""]
        n = 0
        for c in codes:
            rs = list(recs.get(str(c), {}).values())
            if not rs:
                continue
            n += 1
            ratings = {}
            for r in rs:
                ratings[r.get("rating") or "未標示"] = ratings.get(r.get("rating") or "未標示", 0) + 1
            tg = [r["target"] for r in rs if isinstance(r.get("target"), (int, float))]
            name = rs[0].get("name") or ""
            head = f"## {c} {name}｜{len(rs)} 份券商研究（{'、'.join(f'{k}×{v}' for k, v in ratings.items())}）"
            if tg:
                head += (f"｜目標價 {min(tg):,.0f}–{max(tg):,.0f}（中位數 {statistics.median(tg):,.0f}）"
                         if len(tg) > 1 else f"｜目標價 {tg[0]:,.0f}")
            lines.append(head)
            for r in rs:
                t = (r.get("thesis") or "").strip()
                if t:
                    lines.append("- 論點：" + t)
                for s in (r.get("summary") or [])[:3]:
                    lines.append("  · " + str(s))
                rk = [str(x) for x in (r.get("risks") or [])][:3]
                if rk:
                    lines.append("- 風險：" + "；".join(rk))
            lines.append("")
        if n == 0:
            lines.append("（這一鏈目前沒有對應的券商研究資料）")
        text, hits = brokers.scrub("\n".join(lines))
        open(os.path.join(OUTDIR, f"{slug}.md"), "w", encoding="utf-8").write(text)
        written[slug] = (n, len(hits))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=240)
    a = ap.parse_args()
    w = build(a.days)
    for slug, (n, h) in sorted(w.items()):
        print(f"  {slug}: {n} 檔有券商研究" + (f"（內文去識別化 {h} 處）" if h else ""))
    print(f"已寫入 {OUTDIR}")


if __name__ == "__main__":
    main()
