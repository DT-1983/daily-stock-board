# -*- coding: utf-8 -*-
"""美債 10 年殖利率水準＋與標普的連動（2026-10-04，Leo 看 alphatier 貼文問「利率與股票的關係」→「好」）。
只呈現、不下判斷：水準、近 6 個月高點、一個月前，以及「殖利率日變動 vs 標普日報酬」的相關係數（近 3 個月／近 24 個月）。
連動係數只是描述過去，窗口不同結果不同（實測近 6 個月 −0.50、近 24 個月 0.00），所以短長兩個一起列。
資料 yfinance（^TNX、^GSPC），不是即時；快取 6 小時；取不到時戰情明講，不靜默消失。"""
import json
import os
import sys
import time

CACHE = "state/yield_link.json"
TTL = 6 * 3600


def _compute():
    import pandas as pd
    import yfinance as yf

    def ser(sym):
        s = yf.Ticker(sym).history(period="2y")["Close"].dropna()
        s.index = pd.to_datetime([str(i)[:10] for i in s.index])
        return s
    y, s = ser("^TNX"), ser("^GSPC")
    df = pd.concat([y.diff().rename("y"), s.pct_change().rename("s")], axis=1).dropna()
    end = df.index.max()

    def corr(days):
        d = df[df.index >= end - pd.Timedelta(days=days)]
        return round(float(d["y"].corr(d["s"])), 2) + 0.0, len(d)
    h6 = y[y.index >= y.index.max() - pd.Timedelta(days=183)]
    ago = y[y.index <= y.index.max() - pd.Timedelta(days=30)]
    r3, n3 = corr(92)
    r24, n24 = corr(730)
    return {"asof": str(y.index.max())[:10], "level": round(float(y.iloc[-1]), 2),
            "chg_bp": round(float(y.diff().iloc[-1]) * 100, 1),
            "high6": round(float(h6.max()), 2), "high6_date": str(h6.idxmax())[:10],
            "ago": round(float(ago.iloc[-1]), 2) if len(ago) else None,
            "r3": r3, "n3": n3, "r24": r24, "n24": n24, "_t": time.time()}


def data(force=False):
    try:
        c = json.load(open(CACHE, encoding="utf-8"))
        if not force and time.time() - c.get("_t", 0) < TTL:
            return c
    except Exception:                                        # noqa: BLE001
        c = None
    try:
        d = _compute()
        os.makedirs("state", exist_ok=True)
        json.dump(d, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        return d
    except Exception as e:                                   # noqa: BLE001
        print(f"[yield] 取得失敗：{str(e)[:80]}（沿用舊快取：{'有' if c else '無'}）")
        return c


def _word(r):
    if r <= -0.3:
        return "升→股偏跌"
    if r >= 0.3:
        return "升→股偏漲"
    return "目前幾乎無關"


def lines():
    """回 list[str]（已含全形縮排與 Discord 小字前綴）；取不到回空 list，由呼叫端明講。"""
    d = data()
    if not d:
        return []
    mmdd = d["high6_date"][5:].replace("-", "/").lstrip("0").replace("/0", "/")
    arrow = "🔺" if d["chg_bp"] > 0 else ("🔻" if d["chg_bp"] < 0 else "▪️")
    out = [f"　美債 10 年殖利率 {d['level']:.2f}%　{arrow}{d['chg_bp']:+.1f}bp"]
    sub1 = f"近 6 個月高點 {d['high6']:.2f}%（{mmdd}）"
    if d["ago"] is not None:
        sub1 += f"｜一個月前 {d['ago']:.2f}%"
    out.append("-# 　" + sub1)
    out.append(f"-# 　與標普連動：近 3 個月 {d['r3']:+.2f}（{_word(d['r3'])}）｜近 24 個月 {d['r24'] + 0.0:+.2f}")
    return out


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    print("\n".join(lines()) or "（取不到）")
