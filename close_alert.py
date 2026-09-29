# -*- coding: utf-8 -*-
"""收盤急件：台股、美股收盤後就推，不等 08:19 投資晨報（2026-09-29）。

Leo：「台股 telegram 早點做」→「美股也可以提早嗎? 同一個邏輯」。
- 台股：平日 14:05（13:30 收盤），排程 TwCloseAlert → `python close_alert.py --market tw`
- 美股：週二～週六 05:35（美國收盤＝台灣 04:00，11 月起 05:00），排程 UsCloseAlert → `--market us`
  Telegram **靜音送達**（清晨不吵醒 Leo，通知照樣出現）。
做的事（兩個市場同一套）：
  - 用最新收盤偵測持股＋守備清單的 SuperTrend 翻轉、持股 RS60 跌破／站回
    （st_alert.detect_close，演算法跟晨報／燈號掃描同一套）
  - 有觸發 → Telegram 一則＋Discord 🚨（持股才發）；沒觸發不發
  - 記進 state/close_alerts.json 並推上 repo → 08:19 晨報**照樣重推**並標「收盤後已推過」
    （Leo：「重覆推，怕沒看到」）；Discord 🚨 不重推（08:45 日報②段會再列）
  - 拿不到基準日 K 棒（休市或資料還沒到）就跳過
⚠️ **不更新** st_state.json／rs60_state.json——狀態仍由 08:19 更新，兩邊比的都是同一份「上一次」。
用法：python close_alert.py --market tw|us [--dry-run]
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

LOG = "state/close_alerts.json"
KEEP_DAYS = 7
LABEL = {"tw": "台股", "us": "美股"}


def _record(market, bar_date, items):
    d = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"alerts": []}
    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    keep = [a for a in d.get("alerts", []) if a.get("sent", "") >= cutoff
            and not (a.get("market") == market and a.get("bar_date") == bar_date)]
    keep += [{"sent": today.isoformat(), "market": market, "bar_date": bar_date,
              "code": f["code"], "sig": f.get("sig", "st"), "dir": f["dir"]} for f in items]
    json.dump({"alerts": keep}, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _push():
    """推上 repo，GitHub Actions 的 08:19 晨報才讀得到（讀不到只是不加「已推過」標記，不會漏）。"""
    try:
        subprocess.run(["git", "pull", "-q", "--rebase", "--autostash", "board", "main"], check=False, timeout=120)
        subprocess.run(["git", "add", LOG], check=True, timeout=60)
        r = subprocess.run(["git", "commit", "-q", "-m", "收盤急件紀錄"], timeout=60)
        if r.returncode == 0:
            subprocess.run(["git", "push", "-q", "board", "HEAD:main"], check=False, timeout=120)
    except Exception as e:                           # noqa: BLE001
        print(f"[close_alert] 推 repo 失敗（晨報不會標「已推過」）：{e}")


def _message(market, bar_date, hold, watch):
    lines = [f"⚡ <b>{LABEL[market]}收盤急件</b>（{bar_date} 收盤算的，不用等 08:19）"]
    for title, fs in (("💼 <b>持股</b>（SuperTrend／RS60）", hold),
                      ("📈 <b>守備清單 — SuperTrend 翻面</b>", watch)):
        if fs:
            lines.append(title)
            for f in fs:
                nm = f" {f['name']}" if f.get("name") else ""
                lines.append(f"　{html.escape(f['word'])}　<b>{html.escape(str(f['code']))}</b>{html.escape(nm)}")
    lines.append("<i>08:19 投資晨報會再列一次</i>")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["tw", "us"], required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = dt.date.today()
    # 台股只看平日；美股是台灣週二～週六清晨（對應美國週一～週五收盤）
    if (a.market == "tw" and today.weekday() >= 5) or (a.market == "us" and today.weekday() in (0, 6)):
        print(f"[close_alert] {a.market} 今天沒有對應的交易日，跳過")
        return 0
    # 🔴 盤中不跑：盤中抓到的是「今天還沒收的 K 棒」，拿來判斷翻轉是假訊號
    # （2026-09-29 晚上台灣時間試跑美股，美股正在交易，抓到 9/29 盤中價 → 假的 12 檔持股觸發）。
    from zoneinfo import ZoneInfo
    tz, open_, close_ = (("Asia/Taipei", (9, 0), (13, 35)) if a.market == "tw"
                         else ("America/New_York", (9, 30), (16, 15)))
    now_mkt = dt.datetime.now(ZoneInfo(tz))
    if now_mkt.weekday() < 5 and open_ <= (now_mkt.hour, now_mkt.minute) < close_:
        print(f"[close_alert] {a.market} 現在是盤中（當地 {now_mkt:%H:%M}），最新 K 棒還沒收，跳過")
        return 0
    hold, watch, ratio, bar_date = st_alert.detect_close(a.market, today.isoformat())
    print(f"[close_alert] {a.market} 基準日 {bar_date}，拿到比例 {ratio:.0%}；持股觸發 {len(hold)}、守備 {len(watch)}")
    if ratio < 0.5:
        print("[close_alert] 多數股票沒有基準日的 K 棒（休市或資料還沒到），跳過不發")
        return 0
    if not hold and not watch:
        print("[close_alert] 沒有急件，不發")
        return 0
    msg = _message(a.market, bar_date, hold, watch)
    if a.dry_run:
        print(msg)
        return 0
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import notify_tg
    notify_tg.send(msg, silent=(a.market == "us"))
    if hold:
        import alert_telegram
        alert_telegram._send_priority_alert(hold)
    _record(a.market, bar_date, hold + watch)
    _push()
    return 0


if __name__ == "__main__":
    sys.exit(main())
