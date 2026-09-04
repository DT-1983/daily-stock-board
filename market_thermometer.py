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


def backfill(days, pause=0.4):
    """往回補 N 個日曆日。首次執行用。

    ⚠️ `pause` 是**避開證交所限流**的節流間隔。2026-09-03 實測：0.4 秒打 1200 天
    時補到第 45 天就被擋，**528 天全部拿不到**（回 HTTP 307 安全性頁不是 JSON）。
    要補深歷史就把 pause 調大（1.5 秒約 13 分鐘補 500 天），慢但拿得到。
    """
    h, closed = load_hist(), load_closed()
    today = dt.date.today()
    ds = [today - dt.timedelta(days=i) for i in range(days)]
    ds = [d for d in ds if d.weekday() < 5]     # 週末不用打，省一半請求
    got, blocked = _fill(ds, h, closed, pause=pause)
    print(f"✅ 補到 {got} 個交易日，歷史共 {len(h)} 筆"
          + (f"（{blocked} 天被證交所限流擋掉）" if blocked else ""))
    if blocked:
        # ⚠️ 這裡原本寫「之後會自動重補」——**那是假的**：每日 run() 只掃最近
        # window=14 天，2026-02~07 那種舊缺口永遠不在窗口內，再等一年也補不到。
        # 訊息寫得像會自己好，實際上不會（2026-09-04 查出）。
        print("   ⚠️ 每日排程只掃最近 14 天，**舊缺口不會自己補**——"
              "用 `--fill-gaps` 一次補幾天，慢慢磨掉")
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
    line = (f"🌡️ 大盤體溫計：電金比 {st['ratio']:.4f}｜{st['ma_days']}MA {st['ma']:.4f}"
            f"　{icon} {side}均線連 {st['streak']} 日"
            f"（電子 {st['elec']:,.0f} / 金融 {st['fin']:,.0f}）")
    w = drawdown_warning(st)
    return line + ("\n" + w if w else "")


# ── 回檔警示（2026-09-04，Leo 選了「改用小 N」）─────────────────────
#
# 這**不是出場指令**，是回檔警示。差別很重要：
#   出場指令 = 「賣」          ← 我們沒有做，也不會做
#   回檔警示 = 「歷史上這種狀態伴隨較大的回檔」← 我們做這個
#
# 依據＝2026-09-04 的回測（433 個連續交易日、N=1~40 全掃，見 ef_backtest.py）：
#
#   N     總報酬     買抱      策略MDD    買抱MDD
#   1-7   85~104%   103.2%   **-10.4%**  -26.7%
#   32    75.9%     103.2%     -26.7%    -26.7%   ← 老墨用的，保護等於零
#
# ⭐ 唯一有結構的發現：**小 N 把最大回檔砍掉 61%**（-26.7% → -10.4%），報酬幾乎不變。
#   大 N 反應慢，等訊號確認時已經跌完，保護沒有意義。
#
# ⚠️ **2026-09-04 Leo 改回 32（老墨的版本）**，理由：「7 天很可能是在震盪」。
#
# 這跟回測結果相反，但**回測反駁不了他的理由**——我們的樣本只有 433 個交易日、
# 不含完整空頭循環，也不含長期橫盤震盪的行情。N=7 在這段樣本只進出 5 次沒被巴到，
# 但那是**這一段剛好沒有震盪盤**，不是 N=7 抗震盪。他擔心的是樣本裡沒有的情境。
#
# 🔴 **但要誠實講清楚代價**：N=32 在我們這段樣本
#   · 總報酬 +75.9% vs 買抱 +103.2%（輸 27 個百分點）
#   · 最大回檔 -26.7% ＝**跟什麼都不做完全一樣，等於沒有保護效果**
#   關鍵在 2025-04：N=32 在加權 19,529 清倉、5/14 在 21,783 回補
#   ——**賣在低點買在高點，一來一回虧 15%**，而且是永久的（後面漲幅用少 15% 的本金賺）。
#   N=7 在 22,872 就出場（才跌 3%），同一天回補，幾乎沒有代價。
#
# 所以 N=32 的警示**目前沒有回測證據支持它能減少回檔**——警示文案必須照實說，
# 不能拿 N=7 的數字（-10.4%）去背書 N=32 的門檻。
#
# 改這個數字前先看 `python ef_backtest.py --n <N>` 的進出明細，不要只看總報酬。
# ⚠️ 這是投資判定門檻，**只有 Leo 能改**，我不自己動。
WARN_N = 32


def drawdown_warning(st=None):
    """連續 WARN_N 日低於均線時回一行警示；否則回 None。**不下行動指令。**"""
    st = st or status()
    if not st or st.get("insufficient") or not st.get("below"):
        return None
    if st.get("streak", 0) < WARN_N:
        return None
    # ⚠️ 文案必須跟實際的 WARN_N 對得上——不能拿別的 N 的回測數字來背書。
    # N≤7 是回測裡唯一有減少回檔證據的區間；N≥8 沒有。
    if WARN_N <= 7:
        why = ("回測（433 個交易日）：這種狀態下買進持有的最大回檔是 **-26.7%**，"
               f"而連續 {WARN_N} 日內轉空手可壓到 **-10.4%**、報酬幾乎不變。")
    else:
        why = (f"⚠️ **N={WARN_N} 在我們的回測裡沒有減少回檔的證據**"
               f"（總報酬 +75.9% vs 買抱 +103.2%，最大回檔 -26.7% 跟買抱一模一樣）。"
               f"這個門檻是 Leo 指定沿用老墨的版本，理由是擔心小 N 在震盪盤被巴——"
               f"那是我們樣本（433 天、無完整空頭、無長期橫盤）驗證不到的情境。")
    return (f"　⚠️ 已連 {st['streak']} 日低於均線（≥{WARN_N} 日）。{why}"
            f"　這是**狀態警示不是出場指令**，要不要動作是你的決定。")


def fill_gaps(limit=6, pause=3.0, since=None):
    """專補**歷史舊缺口**，一次只補幾天。

    🔴 2026-09-04 加，起因是一個假訊息：`backfill` 印「⚠️ N 天被證交所限流擋掉，
    **下次執行會再試**」——但每日 `run()` 只掃最近 14 天（window=14），
    2026-02~07 那批缺口**永遠不在窗口內，再等一年也補不到**。
    訊息寫得像會自己好，實際上不會。

    設計成「一次只補幾天、間隔拉長」：證交所的限流是**短時間內請求太密**觸發的，
    實測連打 1200 天會在第 45 天被擋；一天補 6 天則幾乎不會踩到。
    掛進每日排程之後，13 天的缺口約兩三天就補完，不用一次硬幹。

    since 給日期字串就只補那天之後的缺口（例如只想補「能延長最長連續段」的那幾天）。
    """
    h, closed = load_hist(), load_closed()
    today = dt.date.today()
    start = (dt.date.fromisoformat(since) if since
             else min(dt.date.fromisoformat(k) for k in h) if h else today)
    miss = []
    cur = start
    while cur <= today:
        k = cur.isoformat()
        if cur.weekday() < 5 and k not in h and k not in closed:
            miss.append(cur)
        cur += dt.timedelta(days=1)
    if not miss:
        print("沒有歷史缺口要補")
        return h
    take = miss[:limit]
    print(f"歷史缺口共 {len(miss)} 天，這次補最舊的 {len(take)} 天："
          f"{take[0].isoformat()} ~ {take[-1].isoformat()}")
    got, blocked = _fill(take, h, closed, pause=pause)
    print(f"✅ 補到 {got} 天，{blocked} 天被擋（下次排程再試）；歷史共 {len(h)} 筆")
    print(f"   剩餘缺口 {len(miss) - got} 天")
    return h


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
    ap.add_argument("--pause", type=float, default=0.4,
                    help="每次請求間隔秒數；補深歷史用 1.5 以上避開證交所限流")
    ap.add_argument("--fill-gaps", nargs="?", type=int, const=6, default=None,
                    metavar="N", help="補歷史舊缺口，一次 N 天（預設 6）")
    ap.add_argument("--since", default="", help="--fill-gaps 只補這個日期之後的缺口")
    a = ap.parse_args()
    if a.fill_gaps is not None:
        fill_gaps(a.fill_gaps, pause=max(a.pause, 3.0), since=a.since or None)
        raise SystemExit(0)
    if a.backfill:
        backfill(a.backfill, pause=a.pause)
    run()
