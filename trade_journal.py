# -*- coding: utf-8 -*-
"""交易記錄（decisions 表 v1，2026-09-03，Leo：「我想寫交易記錄，怎麼記比較方便」）。

設計（老墨戰情室驗證過的做法，見 memory/mofi_warroom_structure）：
  · 一筆記錄＝「當時為什麼下單」＋「系統當時怎麼看」。理由 Leo 自己講；系統快照自動抓
    （燈號/風報比/象限/投資長判斷），這是之後陳壽復盤能比對的關鍵——沒有快照，
    三個月後只剩「當時覺得不錯」。
  · executions（實際成交價量）之後從 IB／統一對帳單匯入，這裡先留 qty/price 欄位可回填。

🔒 私人資料：state/trade_journal.jsonl 在 .gitignore（跟 advisor_verdicts 同一批），
   board_analyze_daily 的 `git add state` 不帶 -f 所以不會被推上公開 repo。
   給手機看的 HTML 輸出到 obis（私人 Google Drive），不進 docs/。

用法：
    python trade_journal.py quick "IB buy MSFT | 產業鏈評分高、三燈號過、風報比"
    python trade_journal.py quick "統一 order 2454 5 | 燈號ok"          # 掛單未成交
    python trade_journal.py fill <id> --qty 10 --price 501.3                # 對帳單回填
    python trade_journal.py cancel <id>
    python trade_journal.py list [--days 30]
    python trade_journal.py html                                            # 輸出到 obis
quick 格式：<券商> <buy|sell|order> <代號> [數量] [@價格] | 理由1、理由2
  order＝掛單未成交（status=pending），成交後用 fill 補價量並轉 filled。
"""
import os
import re
import sys
import json
import uuid
import argparse
import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PATH = "state/trade_journal.jsonl"
# 2026-09-05 資料夾整理：路徑一律走 obis_paths，不再各自寫死。
from obis_paths import DAILY as OBIS
VERDICTS = "state/advisor_verdicts.jsonl"
BROKERS = {"ib": "IB", "統一": "統一", "unified": "統一", "firstrade": "Firstrade", "ft": "Firstrade"}
ACTIONS = {"buy": "buy", "買": "buy", "買入": "buy", "sell": "sell", "賣": "sell", "賣出": "sell",
           "order": "order", "掛單": "order"}


def _load():
    if not os.path.exists(PATH):
        return []
    return [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]


def _save(rows):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _snapshot(ticker):
    """系統當下對這檔的看法：燈號/風報比/象限（lamp_lookup）＋最近 3 天的投資長判斷。"""
    snap = {}
    try:
        import lamp_lookup as L
        r = L.lookup(ticker)
        if r:
            snap.update({
                "price": r.get("price"), "bull": r.get("bull"), "lit": r.get("lit"),
                "lamps_on": [k for k, v in (r.get("lamps") or {}).items() if v],
                "rr": r.get("rr"), "rs_short": r.get("rs_short"),
                "quad60": (r.get("quad") or {}).get("60"), "sector": r.get("sector_zh"),
                "asof": r.get("asof"), "src": r.get("src"),
            })
    except Exception as e:                              # noqa: BLE001
        snap["lookup_error"] = str(e)[:80]
    try:
        if os.path.exists(VERDICTS):
            today = datetime.date.today()
            base = ticker.split(".")[0].upper()
            best = None
            for l in open(VERDICTS, encoding="utf-8"):
                if not l.strip():
                    continue
                v = json.loads(l)
                if str(v.get("ticker", "")).split(".")[0].upper() != base:
                    continue
                d = datetime.date.fromisoformat(v.get("ts", "")[:10])
                if (today - d).days <= 3 and (best is None or v["ts"] > best["ts"]):
                    best = v
            if best:
                snap["chief"] = {"ts": best["ts"][:10],
                                 "trend": best["trend_angle"]["judgment"],
                                 "value": best["value_angle"]["judgment"],
                                 "brief": (best["trend_angle"].get("brief") or "")[:40]}
    except Exception as e:                              # noqa: BLE001
        snap["chief_error"] = str(e)[:80]
    return snap


def add(broker, action, ticker, qty=None, price=None, reasons=None, note=""):
    rows = _load()
    now = datetime.datetime.now()
    r = {"id": now.strftime("%y%m%d") + "-" + uuid.uuid4().hex[:4],
         "ts": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
         "broker": broker, "action": "buy" if action == "order" else action,
         "status": "pending" if action == "order" else "filled",
         "ticker": ticker.upper(), "qty": qty, "price": price,
         "reasons": reasons or [], "note": note,
         "snapshot": _snapshot(ticker)}
    rows.append(r)
    _save(rows)
    return r


def quick(text):
    """<券商> <buy|sell|order> <代號> [數量] [@價格] | 理由1、理由2"""
    head, _, tail = text.partition("|")
    toks = head.split()
    if len(toks) < 3:
        raise SystemExit("格式：<券商> <buy|sell|order> <代號> [數量] [@價格] | 理由")
    broker = BROKERS.get(toks[0].lower(), toks[0])
    action = ACTIONS.get(toks[1].lower())
    if not action:
        raise SystemExit(f"動作要是 buy/sell/order，收到：{toks[1]}")
    ticker = toks[2]
    qty = price = None
    for t in toks[3:]:
        if t.startswith("@"):
            price = float(t[1:])
        else:
            qty = float(t)
    reasons = [x.strip() for x in re.split(r"[、,，;；]", tail) if x.strip()]
    return add(broker, action, ticker, qty, price, reasons)


def _fmt(r):
    s = r.get("snapshot") or {}
    lamp = f"{s.get('lit')}燈" if s.get("lit") is not None else "—"
    rr = f"RR{s['rr']:.1f}" if s.get("rr") is not None else "無目標價"
    q = {"leading": "領先", "improving": "改善", "weakening": "弱化", "lagging": "落後"}.get(s.get("quad60"), "—")
    chief = s.get("chief")
    ch = f"　投資長：{chief['trend']}/{chief['value']}（{chief['ts']}）" if chief else ""
    qp = " ".join(x for x in (f"{r['qty']:g}股" if r.get("qty") else "", f"@{r['price']}" if r.get("price") else "") if x)
    st = "⏳掛單" if r["status"] == "pending" else ("✅" if r["status"] == "filled" else "✖")
    return (f"{r['ts']}  {st} {r['broker']} {r['action']} {r['ticker']} {qp}\n"
            f"    理由：{'、'.join(r['reasons']) or '（無）'}\n"
            f"    系統：{lamp} {rr} 象限{q} RS60 {s.get('rs_short')}{ch}")


def html():
    rows = _load()
    Q = {"leading": ("領先", "#3987e5"), "improving": ("改善", "#2fbf71"),
         "weakening": ("弱化", "#eda100"), "lagging": ("落後", "#e5484d")}
    tr = []
    for r in reversed(rows):
        s = r.get("snapshot") or {}
        q = Q.get(s.get("quad60"))
        qh = f'<span style="background:{q[1]};color:#fff;padding:1px 6px;border-radius:4px">{q[0]}</span>' if q else "—"
        chief = s.get("chief")
        ch = f"{chief['trend']}／{chief['value']}<br><small>{chief['ts']}</small>" if chief else "—"
        st = {"pending": "⏳ 掛單", "filled": "✅ 成交", "cancelled": "✖ 取消"}.get(r["status"], r["status"])
        qp = " ".join(x for x in (f"{r['qty']:g} 股" if r.get("qty") else "", f"@{r['price']}" if r.get("price") else "") if x) or "—"
        tr.append(f"<tr><td>{r['ts']}</td><td>{r['broker']}</td><td>{r['action']}</td><td><b>{r['ticker']}</b></td>"
                  f"<td>{qp}</td><td>{st}</td><td>{'、'.join(r['reasons'])}</td>"
                  f"<td>{s.get('lit', '—')}燈 {('RR%.1f' % s['rr']) if s.get('rr') is not None else ''}</td>"
                  f"<td>{qh}</td><td>{ch}</td><td class=dim>{r['id']}</td></tr>")
    page = ("<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>交易紀錄</title><style>body{background:#0B1220;color:#e8eaed;font-family:-apple-system,'Microsoft JhengHei',sans-serif;padding:14px}"
            "h1{font-size:18px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 8px;border-bottom:1px solid #1E293B;text-align:left;vertical-align:top}"
            "th{color:#94A3B8;font-size:12px}.dim{color:#475569;font-size:10px}small{color:#64748B}.n{color:#64748B;font-size:12px;margin:8px 0 14px}</style></head><body>"
            f"<h1>📒 交易紀錄</h1><div class=n>{len(rows)} 筆 · 產生 {datetime.datetime.now():%Y-%m-%d %H:%M} · 私人檔案，不在公開網站</div>"
            "<div style='overflow-x:auto'><table><tr><th>時間</th><th>券商</th><th>動作</th><th>代號</th><th>量／價</th><th>狀態</th>"
            "<th>理由</th><th>燈號</th><th>象限</th><th>投資長</th><th>id</th></tr>" + "".join(tr) + "</table></div></body></html>")
    os.makedirs(OBIS, exist_ok=True)
    out = os.path.join(OBIS, "交易紀錄.html")
    open(out, "w", encoding="utf-8").write(page)
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    q = sub.add_parser("quick"); q.add_argument("text")
    f = sub.add_parser("fill"); f.add_argument("id"); f.add_argument("--qty", type=float); f.add_argument("--price", type=float)
    c = sub.add_parser("cancel"); c.add_argument("id")
    l = sub.add_parser("list"); l.add_argument("--days", type=int, default=30)
    sub.add_parser("html")
    a = ap.parse_args()
    if a.cmd == "quick":
        r = quick(a.text)
        print("已記錄：\n" + _fmt(r))
    elif a.cmd in ("fill", "cancel"):
        rows = _load()
        hit = [r for r in rows if r["id"] == a.id]
        if not hit:
            raise SystemExit(f"沒有這筆：{a.id}")
        if a.cmd == "fill":
            if a.qty is not None: hit[0]["qty"] = a.qty
            if a.price is not None: hit[0]["price"] = a.price
            hit[0]["status"] = "filled"
        else:
            hit[0]["status"] = "cancelled"
        _save(rows)
        print("已更新：\n" + _fmt(hit[0]))
    elif a.cmd == "html":
        print("已輸出：", html())
    else:
        cutoff = (datetime.date.today() - datetime.timedelta(days=a.days)).isoformat()
        rows = [r for r in _load() if r["date"] >= cutoff]
        print(f"最近 {a.days} 天 {len(rows)} 筆")
        for r in rows:
            print(_fmt(r))
    if a.cmd in ("quick", "fill", "cancel"):
        html()


if __name__ == "__main__":
    main()
