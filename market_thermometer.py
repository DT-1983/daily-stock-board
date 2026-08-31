# -*- coding: utf-8 -*-
"""大盤體溫計：電金比 vs 100日均線（P2，2026-08-27）。

**電金比 = 電子工業類指數 ÷ 金融保險類指數**。邏輯：電子是台股的攻擊型資金
（風險偏好高時漲最兇），金融是防守型（避險時相對強）。比值上升＝資金敢衝（Risk-ON），
下降＝資金在撤退（Risk-OFF）——它衡量的是大盤**內部資金結構**，比只看指數漲跌更早反映風向。

公式驗證（不是猜的）：2026-08-27 證交所當日 電子工業類 2916.26 ÷ 金融保險類 3223.07
= 0.9048，對照老墨戰情室 RX bot 同期公布的「電金比 0.9054」——吻合。

資料源：證交所官方 openapi（當日）+ rwd 歷史端點（逐交易日），免登入免key。
歷史存 state/ef_ratio.json，每天 append 一筆。

⚠️ **這支只做「量測」不做「行動建議」**：老墨的「連32日轉弱→開盤全部清倉」是他自己
系統的規則，我們沒有對應的回測依據。照 Leo 的硬規則（不自行發明投資判定門檻），
這裡只誠實報告狀態（比值、均線、連續幾日在均線下），行動規則等 Leo 拍板或做完回測再加。

用法:
    python market_thermometer.py --backfill 150   # 一次補歷史（首次執行必跑）
    python market_thermometer.py                  # 每日跑：抓當日 + 算狀態
"""
import os
import sys
import json
import time
import argparse
import datetime as dt

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HIST_PATH = "state/ef_ratio.json"
MA_DAYS = 100
ELEC = "電子工業類指數"
FIN = "金融保險類指數"


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def fetch_day(date_str):
    """抓某一交易日的電子/金融類指數。date_str: YYYYMMDD。

    回 (狀態, 資料)，**「非交易日」和「被擋掉」一定要分開**——兩者都回 None 的話
    會變成靜默失敗：被限流的日子會被永久當成「那天沒開盤」跳過，再也不會補回來，
    而 A 方案（每日累積湊 100 日均線）漏一天就永久少一天。狀態：
        "ok"      有資料
        "closed"  證交所正常回應但無該日指數 → 非交易日，記進 closed 名單不再重試
        "blocked" 被證交所限流擋掉（HTTP 307 安全性頁）→ 留著缺口，下次再補
    """
    import requests
    try:
        r = requests.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                         params={"date": date_str, "type": "IND", "response": "json"},
                         timeout=25)
        if "json" not in (r.headers.get("content-type") or ""):
            return "blocked", None      # 證交所限流頁，不是 JSON
        d = r.json()
    except Exception as e:
        print(f"  {date_str} 抓取失敗：{str(e)[:60]}")
        return "blocked", None
    for t in d.get("tables") or []:
        if "價格指數" not in (t.get("title") or ""):
            continue
        rows = {row[0]: row[1] for row in (t.get("data") or []) if len(row) >= 2}
        e, f = _num(rows.get(ELEC)), _num(rows.get(FIN))
        if e and f:
            return "ok", {"elec": e, "fin": f, "ratio": round(e / f, 6)}
    return "closed", None


def load_hist():
    if not os.path.exists(HIST_PATH):
        return {}
    try:
        return json.load(open(HIST_PATH, encoding="utf-8"))
    except Exception:
        return {}


def save_hist(h):
    os.makedirs("state", exist_ok=True)
    json.dump(h, open(HIST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


CLOSED_PATH = "state/ef_ratio_closed.json"


def load_closed():
    """確認過是非交易日（國定假日/颱風假）的清單，不再浪費請求重試。"""
    if not os.path.exists(CLOSED_PATH):
        return set()
    try:
        return set(json.load(open(CLOSED_PATH, encoding="utf-8")))
    except Exception:
        return set()


def save_closed(s):
    os.makedirs("state", exist_ok=True)
    json.dump(sorted(s), open(CLOSED_PATH, "w", encoding="utf-8"), ensure_ascii=False)


PUBLISH_HOUR = 13
PUBLISH_MIN = 35


def _published(d, now=None):
    """證交所類指數是否已公布。收盤 13:30 後才有，這裡抓 13:35 留 5 分鐘緩衝。

    ⚠️ 2026-08-31 修：少了這道判斷 = 資料永久遺失。排程 08:45 跑時證交所對「今天」
    會回一個正常 JSON 但沒有價格指數表，fetch_day 判成 "closed"（非交易日）寫進
    黑名單，而黑名單設計上**永不重試**——於是每一天都在自己那天早上被判死，隔天
    也不會回頭補。8/28 和 8/31 就是這樣掉的，累積數會永遠卡在 53 天，100MA 永遠
    算不出來。未公布的日期要**完全跳過**（不打請求也不寫黑名單），留給明天早上補。
    """
    now = now or dt.datetime.now()
    if d < now.date():
        return True
    if d > now.date():
        return False
    return (now.hour, now.minute) >= (PUBLISH_HOUR, PUBLISH_MIN)


def _fill(dates, h, closed, pause=0.4):
    """補指定日期清單。回 (新增數, 被擋數)。"""
    got = blocked = 0
    for d in dates:
        key = d.isoformat()
        if key in h or key in closed:
            continue
        if not _published(d):
            continue
        st, r = fetch_day(d.strftime("%Y%m%d"))
        if st == "ok":
            h[key] = r
            got += 1
            if got % 20 == 0:
                save_hist(h)
                print(f"  已補 {got} 個交易日…")
        elif st == "closed":
            closed.add(key)
        else:
            blocked += 1
        time.sleep(pause)
    save_hist(h)
    save_closed(closed)
    return got, blocked


def backfill(days):
    """往回補 N 個日曆日。首次執行用。"""
    h, closed = load_hist(), load_closed()
    today = dt.date.today()
    ds = [today - dt.timedelta(days=i) for i in range(days)]
    ds = [d for d in ds if d.weekday() < 5]     # 週末不用打，省一半請求
    got, blocked = _fill(ds, h, closed)
    print(f"✅ 補到 {got} 個交易日，歷史共 {len(h)} 筆"
          + (f"（{blocked} 天被證交所限流擋掉，之後會自動重補）" if blocked else ""))
    return h


def status():
    """回目前狀態 dict；資料不足回 None（不硬算半套均線）。"""
    h = load_hist()
    if not h:
        return None
    days = sorted(h)
    ratios = [h[d]["ratio"] for d in days]
    if len(ratios) < MA_DAYS:
        return {"insufficient": True, "have": len(ratios), "need": MA_DAYS,
                "latest_date": days[-1], "ratio": ratios[-1]}
    ma = sum(ratios[-MA_DAYS:]) / MA_DAYS
    below = ratios[-1] < ma
    # 連續幾天在均線同一側
    streak = 0
    for i in range(len(ratios) - 1, MA_DAYS - 2, -1):
        m = sum(ratios[i - MA_DAYS + 1:i + 1]) / MA_DAYS
        if (ratios[i] < m) == below:
            streak += 1
        else:
            break
    return {"latest_date": days[-1], "ratio": round(ratios[-1], 4),
            "ma": round(ma, 4), "ma_days": MA_DAYS, "below": below, "streak": streak,
            "elec": h[days[-1]]["elec"], "fin": h[days[-1]]["fin"]}


def summary_line(st=None):
    """給日報①段用的一行。不下行動指令——只報狀態（見檔頭說明）。"""
    st = st or status()
    if not st:
        return None
    if st.get("insufficient"):
        return (f"🌡️ 大盤體溫計：電金比 {st['ratio']:.4f}"
                f"（歷史累積 {st['have']}/{st['need']} 日，還算不出{st['need']}MA）")
    icon = "🔴" if st["below"] else "🟢"
    side = "低於" if st["below"] else "高於"
    return (f"🌡️ 大盤體溫計：電金比 {st['ratio']:.4f}｜{st['ma_days']}MA {st['ma']:.4f}"
            f"　{icon} {side}均線連 {st['streak']} 日"
            f"（電子 {st['elec']:,.0f} / 金融 {st['fin']:,.0f}）")


def run(window=14):
    """每日跑：補最近 window 天的缺口（不是只抓「今天」）。

    ⚠️ 這個 window 是必要的不是保險：排程在早上 08:45 跑，但證交所類指數要
    **收盤後（13:30+）才公布**——早上抓「今天」必然是空的，隔天又換成新日期，
    只抓當天的寫法會永遠存不進任何一筆。改成回頭補缺口後，今天的資料明天早上補上，
    同時也自癒「電腦關機漏跑」「證交所當下掛掉」這兩種情況。

    A 方案（Leo 2026-08-27 拍板）是靠每日累積湊滿 100 日均線，**漏一天就永久少一天**，
    所以這裡寧可每次多打幾個已存在的日期（會被 `key in h` 擋掉，零成本）。"""
    h, closed = load_hist(), load_closed()
    today = dt.date.today()
    ds = [today - dt.timedelta(days=i) for i in range(window) if (today - dt.timedelta(days=i)).weekday() < 5]
    # 加上歷史區間裡還沒補到的舊缺口（被限流擋掉的那幾天）。已存在/已知非交易日
    # 會被 _fill 跳過，所以正常情況這裡是零請求；有缺口時才會慢慢補回來。
    if h:
        a, b = dt.date.fromisoformat(min(h)), today
        ds += [a + dt.timedelta(days=i) for i in range((b - a).days + 1)
               if (a + dt.timedelta(days=i)).weekday() < 5]
    got, blocked = _fill(ds, h, closed)
    if got:
        print(f"已補 {got} 筆，歷史共 {len(h)} 筆")
    if blocked:
        print(f"⚠️ {blocked} 天被證交所限流擋掉，下次執行會再試")
    st = status()
    print(summary_line(st) or "（尚無資料）")
    return st


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="往回補幾個日曆日")
    a = ap.parse_args()
    if a.backfill:
        backfill(a.backfill)
    run()
