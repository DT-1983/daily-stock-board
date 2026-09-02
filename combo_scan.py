# -*- coding: utf-8 -*-
"""COMBO 連鎖反應：四燈共振 + 風報比（2026-09-01 建，抄老墨 XQ 的判定）

老墨的規則（Leo 2026-09-01 提供截圖）：
    燈1 SUPER TREND 多方
    燈2 動能 > 0
    燈3 雙重颱風不為綠
    燈4 RS 60日乖離 > +3%
    COMBO 門檻 = 亮 3 燈以上
    打點成立 = 亮 3 燈以上「且」風報比 ≥ 1 —— 兩個條件要一起看

⭐ 為什麼兩個條件要一起：燈號給的是**勝率**（技術面共振），風報比給的是**賠率**。
只有一半沒意義——勝率高但每次賺一點賠一大筆，長期還是虧。而風報比會自動偏好
「剛起漲」、排除「漲過頭」（同一檔燈號沒變、價格漲了，風報比就掉下來），
所以它篩的是**進場時機**不是標的好壞。

⚠️ 四個指標我們本來就有（technical_indicators.py 當初就是照老墨 XQ 說明頁移植的），
這支不重造輪子，只做三件事：把四個指標收斂成燈號、補風報比、偵測狀態變化。

⚠️ RS 窗口必須用 60 日：technical_indicators 的預設是短30/長1年（當初為了對齊
財報卡而定），**不是老墨的 60/240**。用預設會讓燈4 算錯，這裡明確傳 60/240。

實測對照（8996 高力 @ 2026-08-26，對老墨截圖）：
    這波走了 15 根（截圖 15）✅　收盤 1195.00（截圖 1195.00）✅
    四燈判定 3/4，與截圖完全一致 ✅
    線的絕對值差約 1.6%（推測是除權息還原方式不同，未證實）
"""
import argparse
import io
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NL = chr(10)
WATCHLIST_PATH = "state/combo_watchlist.json"
TARGETS_CACHE = "state/price_targets.json"
STATE_PATH = "state/combo_state.json"
RESULT_PATH = "state/combo_result.json"

RS_SHORT, RS_LONG = 60, 240      # 老墨的預設，不是我們財報卡的 30/1年
RS_BIAS_MIN = 3.0                # 燈4 門檻：RS 60日乖離 > +3%
COMBO_MIN = 3                    # 亮幾燈算成立
TARGET_CACHE_DAYS = 7            # 目標價變動慢（券商幾週才改一次），每天抓 180 檔是浪費


def _load(path, default):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    io.open(path, "w", encoding="utf-8", newline=NL).write(
        json.dumps(obj, ensure_ascii=False, indent=2))


# ── 母體：守備清單 + 持股 + 自訂觀察清單 ────────────────────────────
def universe():
    """回 {ticker: {"name":…, "src":set(...)}}。Leo 2026-09-01 指定＝守備清單＋持股，
    另加自訂觀察清單（朋友推薦這種，不在任何自動母體裡的）。"""
    uni = {}

    def add(tk, name, src):
        tk = str(tk).strip()
        if not tk:
            return
        e = uni.setdefault(tk, {"name": name or tk, "src": set()})
        e["src"].add(src)
        if name and (not e["name"] or e["name"] == tk):
            e["name"] = name

    scr = _load("screen_result.json", {})
    for mkt in ("us", "tw"):
        for chain, rows in (scr.get(mkt) or {}).items():
            for r in rows or []:
                add(r.get("code"), r.get("name"), "守備清單")
    try:
        from trade_plan import monitored_holdings
        for tk, owner, name in monitored_holdings():
            add(tk, name, "持股")
    except Exception as e:                             # noqa: BLE001
        print(f"  [warn] 讀不到持股：{str(e)[:70]}")
    for row in _load(WATCHLIST_PATH, []):
        add(row.get("ticker"), row.get("name"), "自訂")
    return uni


# ── 目標價（yfinance 市場共識，非投顧報告）────────────────────────
def price_targets(tickers, force=False):
    """回 {ticker: {mean, low, high, n, asof}}。快取 7 天。

    ⚠️ 這是**市場共識**（yfinance analyst_price_targets），不是單一投顧報告的目標價。
    實測交叉驗證：8996 的區間低點 1320 正是富邦投顧那份的目標價，證明這個欄位
    確實收台灣券商，不是只有外資。
    ⚠️ 上櫃小型股常常查無（實測 1580.TWO 沒有）——查無就不給風報比，只給距停損%，
    不要為了湊欄位塞一個假目標價。
    ⚠️ 這個欄位只有**現在**的快照、沒有歷史（同 RRG 資金規模、sharesOutstanding
    的坑）。要做歷史比較就得從今天開始存。
    """
    import yfinance as yf
    cache = _load(TARGETS_CACHE, {})
    today = time.strftime("%Y-%m-%d")
    fresh_before = time.time() - TARGET_CACHE_DAYS * 86400
    need = []
    for tk in tickers:
        c = cache.get(tk)
        if force or not c or c.get("ts", 0) < fresh_before:
            need.append(tk)
    if need:
        print(f"  目標價：快取命中 {len(tickers)-len(need)}/{len(tickers)}，需更新 {len(need)} 檔…")
        import tw_symbol
        for i, tk in enumerate(need, 1):
            sym = tw_symbol.resolve(tk)
            try:
                d = yf.Ticker(sym).analyst_price_targets or {}
                mean = d.get("mean")
                cache[tk] = {"mean": mean, "low": d.get("low"), "high": d.get("high"),
                             "asof": today, "ts": time.time()}
            except Exception:                          # noqa: BLE001
                # 抓失敗不寫快取，避免一次逾時被永久記成「沒有目標價」
                pass
            if i % 40 == 0:
                print(f"    …{i}/{len(need)}")
        _save(TARGETS_CACHE, cache)
    return cache


# ── 燈號 ────────────────────────────────────────────────────────
def scan_one(tk, sym, df, bench_closes):
    """回單檔的四燈 + 價位。資料不足回 None。"""
    import technical_indicators as ti
    from board_html_legacy import supertrend
    df = df.dropna()
    if len(df) < RS_LONG + 20:
        return None
    H = df["High"].round(2).tolist()
    L = df["Low"].round(2).tolist()
    C = df["Close"].round(2).tolist()
    # ⚠️ 顯示層一律用 **SMA 版 ATR**（＝ double_typhoon 那條線），因為老墨的
    # 「SUPER TREND PRO MAX」實測就是 SMA 版：
    #   3037 @ 2026-09-02 他顯示空方壓力 1223.7 → 我們 SMA 版 1223.7（分毫不差）、
    #   Wilder 版 964.2 而且方向相反；9939 @ 08-26 他 141.40 → SMA 141.40 / Wilder 141.66。
    #   （他的方法說明寫「SUPER TREND 採 Wilder's RMA」，與實際數字矛盾，採信數字。）
    # ⚠️ **策略層不動**：trade_plan.supertrend_invalidation / st_alert / paper_portfolio
    #   仍用 Wilder——Leo 的出場規則是拿 Wilder 版回測出來的。
    #   實測兩版長期特性接近（3037 三年翻轉 23 vs 24 次、平均段長 31.3 vs 30.0 根），
    #   差別在個別訊號的時點，不是策略的統計特性。
    st_w = supertrend(H, L, C)          # Wilder 版：保留備查，不進顯示
    st = ti.double_typhoon(H, L, C)     # SMA 版＝老墨的 SUPER TREND
    if not st or st["dir"][-1] is None:
        return None
    dt = st
    vols_k = [None if v is None else (v / 1000 if _is_tw(tk) else v)
              for v in df["Volume"].tolist()]
    ty_state = ti.typhoon_state(C, vols_k, dt["dir"][-1]) if dt else None
    sq = ti.squeeze_momentum(H, L, C)
    rs = ti.mansfield_rs(C, bench_closes, short=RS_SHORT, long=RS_LONG) or {}

    px = float(C[-1])
    st_line = st["st"][-1]
    mom = sq["momentum"][-1]
    rs_s = rs.get("short")

    # ⚠️ 一律用 bool() 包起來：這些比較的左邊是 numpy 值，回的是 numpy.bool_，
    # 看起來是 True/False 但 json.dumps 會直接 TypeError。
    # （今天下午才在 trade_plan.supertrend_invalidation 修過同一個坑，這裡又犯一次——
    #  凡是 numpy 出來的值要進 JSON，都要先轉回 Python 原生型別。）
    lamps = {
        "L1 SuperTrend 多方": bool(st["dir"][-1] == 1),
        "L2 動能 > 0": bool(mom is not None and mom > 0),
        # 官方定義：紅=偏多、綠=偏空、黃=不明；「不為綠」＝不是偏空，紅與黃都算亮。
        # 原本只有 dir==1（多）才亮 → 把「黃(不明)」誤判成滅，會系統性少算一燈。
        # ⚠️ 三態的第二道關卡是逆向推導的，見 technical_indicators.typhoon_state。
        "L3 雙重颱風不為綠": bool(ty_state != -1) if ty_state is not None else False,
        f"L4 RS{RS_SHORT}日乖離 > +{RS_BIAS_MIN:g}%": bool(rs_s is not None and rs_s > RS_BIAS_MIN),
    }
    lit = sum(1 for v in lamps.values() if v)
    # ⚠️ 空方時那條線不是「停損」是「壓力」——語意完全不同。
    # 老墨的處理：SuperTrend 空方時不算風報比，改顯示「站上 X 才翻多（還要 +Y%）」。
    # 我們照做：bull=False 時 gap_pct 代表「離翻多還要漲多少」，頁面要分開講。
    bull = bool(st["dir"][-1] == 1)
    return {"ticker": tk, "symbol": sym, "price": round(px, 2), "bull": bull,
            "st_line": round(float(st_line), 2) if st_line else None,
            "gap_pct": round((px - st_line) / px * 100, 2) if st_line else None,
            "momentum": round(float(mom), 2) if mom is not None else None,
            "rs_short": round(float(rs_s), 2) if rs_s is not None else None,
            "rs_long": round(float(rs.get("long")), 2) if rs.get("long") is not None else None,
            "lamps": lamps, "lit": int(lit), "combo": bool(lit >= COMBO_MIN),
            "typhoon": ty_state,
            "asof": str(df.index[-1])[:10]}


def add_rr(row, tgt):
    """補風報比。沒有目標價就明確標 None——不要拿貴價之類的東西硬湊，
    那會做出一個看起來像但意義不同的數字。"""
    row["target"] = None
    row["rr"] = None
    row["target_n"] = None
    # 空方不給風報比：沒有「持有中的停損」可言，這時談賠率是無意義的
    if not row.get("bull") or not tgt or tgt.get("mean") is None or not row.get("st_line"):
        return row
    mean, px, sl = float(tgt["mean"]), row["price"], row["st_line"]
    row["target"] = round(mean, 2)
    row["target_low"] = tgt.get("low")
    row["target_high"] = tgt.get("high")
    if px > sl:
        row["rr"] = round((mean - px) / (px - sl), 2)
    return row


# ── 批次掃描 ────────────────────────────────────────────────────
def _is_tw(tk):
    import re
    return bool(re.match(r"^\d{4,6}[A-Z]?(\.TWO?)?$", str(tk)))


_TWN = None


def _tw_names():
    global _TWN
    if _TWN is None:
        try:
            from industry_rotation import _tw_chinese_names
            _TWN = _tw_chinese_names() or {}
        except Exception as e:                          # noqa: BLE001
            print(f"  [warn] 台股中文名讀不到：{str(e)[:60]}")
            _TWN = {}
    return _TWN


def scan_all(force_targets=False):
    import price_store
    import tw_symbol
    uni = universe()
    print(f"母體 {len(uni)} 檔（守備清單＋持股＋自訂）")
    # ⚠️ BRK.B 這種帶點的美股代號，yfinance 要 BRK-B（實測 BRK.B 直接 no price data）。
    # tw_symbol.resolve 只管台股後綴，不會處理這個。
    def _yf(tk):
        return tw_symbol.resolve(tk) if _is_tw(tk) else str(tk).replace(".", "-")
    sym_of = {tk: _yf(tk) for tk in uni}
    # 台美股基準不同——跟錯大盤 RS 就沒有意義（同 trade_plan.supertrend_invalidation）
    benches = price_store.get_closes(["^TWII", "^GSPC"], period="3y")
    ohlc = price_store.get_ohlc(sorted(set(sym_of.values())), period="3y")

    rows, skipped = [], []
    for tk, info in uni.items():
        sym = sym_of[tk]
        df = ohlc.get(sym)
        if df is None or df.empty:
            skipped.append((tk, "無價量"))
            continue
        b = benches.get("^TWII" if _is_tw(tk) else "^GSPC")
        if b is None or b.empty:
            skipped.append((tk, "無大盤基準"))
            continue
        try:
            r = scan_one(tk, sym, df, b.dropna().tolist())
        except Exception as e:                          # noqa: BLE001
            skipped.append((tk, str(e)[:40]))
            continue
        if not r:
            skipped.append((tk, "資料長度不足"))
            continue
        # 台股補中文名：holdings/screen_result 存的常是英文全名（NAN YA PRINTED…），
        # 重用 industry_rotation 那套證交所+櫃買官方簡稱（含快取自癒），不另外打 API。
        nm = info["name"]
        if _is_tw(tk):
            nm = _tw_names().get(str(tk).split(".")[0]) or nm
        r["name"] = nm
        r["src"] = sorted(info["src"])
        rows.append(r)

    tgt = price_targets([r["ticker"] for r in rows], force=force_targets)
    for r in rows:
        add_rr(r, tgt.get(r["ticker"]))
    rows.sort(key=lambda r: (-r["lit"], -(r["rr"] if r["rr"] is not None else -99)))
    print(f"  算出 {len(rows)} 檔，跳過 {len(skipped)} 檔")
    if skipped:
        from collections import Counter
        print("  跳過原因：", dict(Counter(x[1] for x in skipped)))
    return rows


def diff_state(rows):
    """回 (新成立, 剛失效)。只推變化——180 檔每天全推會洗版，
    這個專案一貫是「變化才推」（見 tradingbot_intel_system）。"""
    prev = _load(STATE_PATH, {})
    now = {r["ticker"]: r["combo"] for r in rows}
    new = [r for r in rows if r["combo"] and not prev.get(r["ticker"])]
    lost = [t for t, was in prev.items() if was and not now.get(t, False)]
    _save(STATE_PATH, now)
    return new, lost


def main():
    ap = argparse.ArgumentParser(description="COMBO 四燈共振掃描")
    ap.add_argument("--add", metavar="TICKER", help="加進自訂觀察清單")
    ap.add_argument("--remove", metavar="TICKER", help="從自訂觀察清單移除")
    ap.add_argument("--list", action="store_true", help="列出自訂觀察清單")
    ap.add_argument("--force-targets", action="store_true", help="強制重抓目標價（忽略7天快取）")
    ap.add_argument("--top", type=int, default=20, help="終端機顯示前幾名")
    a = ap.parse_args()

    wl = _load(WATCHLIST_PATH, [])
    if a.add:
        tk = a.add.strip()
        if any(r.get("ticker") == tk for r in wl):
            print(f"{tk} 已經在清單裡")
        else:
            import tw_symbol
            import yfinance as yf
            sym = tw_symbol.resolve(tk)
            try:
                nm = (yf.Ticker(sym).info or {}).get("longName") or tk
            except Exception:                           # noqa: BLE001
                nm = tk
            wl.append({"ticker": tk, "name": nm, "added": time.strftime("%Y-%m-%d")})
            _save(WATCHLIST_PATH, wl)
            print(f"已加入：{tk} {nm}")
        return 0
    if a.remove:
        n = len(wl)
        wl = [r for r in wl if r.get("ticker") != a.remove.strip()]
        _save(WATCHLIST_PATH, wl)
        print(f"已移除 {n - len(wl)} 筆")
        return 0
    if a.list:
        print(f"自訂觀察清單 {len(wl)} 檔：")
        for r in wl:
            print(f"  {r['ticker']:10} {r.get('name','')}　（{r.get('added','')} 加入）")
        return 0

    rows = scan_all(force_targets=a.force_targets)
    # lamps 的 key 是中文字串，直接存 JSON 給頁面讀（頁面不重算，避免兩邊邏輯漂移）
    _save(RESULT_PATH, {"date": time.strftime("%Y-%m-%d"),
                        "combo_min": COMBO_MIN, "rs_short": RS_SHORT,
                        "rs_bias_min": RS_BIAS_MIN, "rows": rows})
    ok = [r for r in rows if r["combo"]]
    print(f"{NL}COMBO 成立（≥{COMBO_MIN} 燈）：{len(ok)}/{len(rows)} 檔")
    print(f"{'代號':10}{'名稱':16}{'燈':>4}{'風報比':>8}{'距停損':>9}{'RS60':>8}  來源")
    for r in ok[:a.top]:
        rr = f"{r['rr']:.2f}" if r["rr"] is not None else "無目標價"
        print(f"{r['ticker']:10}{(r['name'] or '')[:14]:16}{r['lit']}/4{rr:>8}"
              f"{r['gap_pct']:>8.1f}%{r['rs_short']:>7.1f}%  {'/'.join(r['src'])}")
    new, lost = diff_state(rows)
    print(f"{NL}狀態變化：新成立 {len(new)} 檔　剛失效 {len(lost)} 檔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
