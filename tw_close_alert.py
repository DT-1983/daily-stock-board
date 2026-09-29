# -*- coding: utf-8 -*-
"""台股收盤急件（2026-09-29，Leo：「台股 telegram 早點做」）。

原本台股 13:30 收盤，急件（SuperTrend 轉向、RS60 跌破）要等到隔天 08:19 的投資晨報才推，
差將近 19 小時。這支在本機平日 14:05 跑（TwCloseAlert 排程）：
  - 用**當天收盤**偵測台股持股＋台股守備清單的 SuperTrend 翻轉、台股持股的 RS60 跌破／站回
    （st_alert.detect_tw_close，演算法跟晨報／燈號掃描同一套）
  - 有觸發 → Telegram 一則＋Discord 🚨 持股警示（持股才發）；沒觸發不發，不洗版
  - 記進 state/tw_close_alerts.json 並推上 repo → 隔天 08:19（GitHub Actions）的晨報／🚨 不再重複推
    （Discord 08:45 日報②段照樣會列，那是完整彙總）
  - 拿不到當天 K 棒（台股休市或資料還沒到）就跳過，不發任何東西
⚠️ 這支**不更新** st_state.json／rs60_state.json——狀態仍由隔天 08:19 更新，兩邊比的都是同一份「上一次」。
用法：python tw_close_alert.py [--dry-run]
"""
import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import st_alert                                      # noqa: E402

LOG = "state/tw_close_alerts.json"
KEEP_DAYS = 7


def _record(today, items):
    d = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"alerts": []}
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    keep = [a for a in d.get("alerts", []) if a.get("date", "") >= cutoff and a.get("date") != today]
    keep += [{"date": today, "code": f["code"], "sig": f.get("sig", "st"), "dir": f["dir"]} for f in items]
    json.dump({"alerts": keep}, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _push():
    """推上 repo，隔天 GitHub Actions 的晨報才讀得到（讀不到就會重複推一次，不會漏）。"""
    try:
        subprocess.run(["git", "pull", "-q", "--rebase", "--autostash", "board", "main"], check=False, timeout=120)
        subprocess.run(["git", "add", LOG], check=True, timeout=60)
        r = subprocess.run(["git", "commit", "-q", "-m", "台股收盤急件紀錄"], timeout=60)
        if r.returncode == 0:
            subprocess.run(["git", "push", "-q", "board", "HEAD:main"], check=False, timeout=120)
    except Exception as e:                           # noqa: BLE001
        print(f"[tw_close] 推 repo 失敗（隔天晨報可能重複推這幾則）：{e}")


def _message(today, hold, watch):
    lines = [f"⚡ <b>台股收盤急件 {today}</b>（今天收盤算的，不用等明早）"]
    if hold:
        lines.append("💼 <b>持股</b>（SuperTrend／RS60）")
        for f in hold:
            nm = f" {f['name']}" if f.get("name") else ""
            lines.append(f"　{html.escape(f['word'])}　<b>{html.escape(str(f['code']))}</b>{html.escape(nm)}")
    if watch:
        lines.append("📈 <b>守備清單 — SuperTrend 翻面</b>")
        for f in watch:
            nm = f" {f['name']}" if f.get("name") else ""
            lines.append(f"　{html.escape(f['word'])}　<b>{html.escape(str(f['code']))}</b>{html.escape(nm)}")
    lines.append("<i>美股照舊在明早 08:19 的投資晨報</i>")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = dt.date.today().isoformat()
    if dt.date.today().weekday() >= 5:
        print("[tw_close] 週末，跳過")
        return 0
    hold, watch, ratio = st_alert.detect_tw_close(today)
    print(f"[tw_close] {today} 拿到當天收盤的比例 {ratio:.0%}；持股觸發 {len(hold)}、守備 {len(watch)}")
    if ratio < 0.5:
        print("[tw_close] 多數股票沒有今天的 K 棒（休市或資料還沒到），跳過不發")
        return 0
    if not hold and not watch:
        print("[tw_close] 今天台股沒有急件，不發")
        return 0
    msg = _message(today, hold, watch)
    if a.dry_run:
        print(msg)
        return 0
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import notify_tg
    notify_tg.send(msg)
    if hold:
        import alert_telegram
        alert_telegram._send_priority_alert(hold)
    _record(today, hold + watch)
    _push()
    return 0


if __name__ == "__main__":
    sys.exit(main())
