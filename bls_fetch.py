# -*- coding: utf-8 -*-
"""美國非農＋失業率實際值（BLS 官方公開 API，免費、免金鑰、零 AI）。

2026-10-02 Leo：「這個有在我們監查嗎」（貼文：9 月非農 +2.9 萬、失業率 4.2%）——查出總經研究員
只在「事件前後各 1 天」才叫 AI 查實際值，而每日批次週一～週五才跑，**落在週五的事件永遠查不到**
（非農一年 9 次、CPI 3 次）。實際值本來就是官方公布的數字，直接讀 BLS，不用 AI、不用網搜、不花額度。

API：api.bls.gov/publicAPI/v1（無金鑰版，每日 25 次查詢上限；我們每次只發 1 個請求含兩個序列）
  CES0000000001＝非農就業總人數（千人，季調）　LNS14000000＝失業率（%）
⚠️ 「新增人數」＝本月水準 − 上月水準，**上月水準是現值（可能已被修正）**，所以前月新增不等於當初公布值。
⚠️ 資料月份必須對得上公布日：公布日當天 BLS 資料可能還沒更新，這時 latest() 的月份會是上一個月，
   summary_line 會明講「尚未更新」，不能把上個月當成這個月講。
"""
import json
import os
import sys
import time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CACHE = "state/bls_latest.json"
URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
TTL = 6 * 3600
_MON = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, "July": 7,
        "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}


def _fetch():
    import requests
    yr = dt.date.today().year
    r = requests.post(URL, json={"seriesid": ["CES0000000001", "LNS14000000"],
                                 "startyear": str(yr - 1), "endyear": str(yr)}, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS 回應異常：{d.get('status')} {d.get('message')}")
    out = {}
    for s in d["Results"]["series"]:
        rows = []
        for x in s["data"]:
            if x["period"].startswith("M") and x["period"] != "M13":
                try:
                    v = float(x["value"])
                except ValueError:                           # BLS 缺資料的月份值是「-」（例：2025-10 停擺）
                    continue
                rows.append(((int(x["year"]), int(x["period"][1:])), v,
                             any(f.get("code") == "P" for f in (x.get("footnotes") or []))))
        rows.sort(reverse=True)
        out[s["seriesID"]] = rows
    return out


def latest(force=False):
    """回 {ym:'2026-09', nfp_change_k, prev_change_k, unemp, unemp_prev, preliminary, fetched}；失敗回 None。"""
    try:
        c = json.load(open(CACHE, encoding="utf-8"))
        if not force and time.time() - c.get("_t", 0) < TTL:
            return c
    except Exception:                                        # noqa: BLE001
        c = None
    try:
        d = _fetch()
        nfp, un = d["CES0000000001"], d["LNS14000000"]
        def _prev(ym):
            return (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)

        def _chg(i):
            """第 i 筆相對「前一個日曆月」的變動；前一個月沒資料（月份不連續）就回 None，不跨月硬減。"""
            if i + 1 >= len(nfp) or nfp[i + 1][0] != _prev(nfp[i][0]):
                return None
            return round(nfp[i][1] - nfp[i + 1][1])
        (y, m), lv, pre = nfp[0]
        uprev = un[1][1] if len(un) > 1 and un[1][0] == _prev(un[0][0]) else None
        res = {"ym": f"{y}-{m:02d}", "nfp_level_k": lv,
               "nfp_change_k": _chg(0), "prev_change_k": _chg(1),
               "preliminary": pre,
               "unemp": un[0][1], "unemp_prev": uprev, "unemp_ym": f"{un[0][0][0]}-{un[0][0][1]:02d}",
               "fetched": time.strftime("%Y-%m-%d %H:%M"), "_t": time.time()}
        os.makedirs("state", exist_ok=True)
        json.dump(res, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        return res
    except Exception as e:                                   # noqa: BLE001
        print(f"[bls] 取得失敗：{str(e)[:80]}（沿用舊快取：{'有' if c else '無'}）")
        return c


def _wan(k):
    """千人 → 萬人字串，帶正負號（+2.9 萬）。"""
    return f"{k / 10:+.1f} 萬"


def recent_nfp_date(today=None, within=5):
    """行事曆上最近一次（含今天）已到期的非農公布日；超過 within 天回 None。"""
    import macro_calendar as mc
    t = dt.date.fromisoformat(today) if today else dt.date.today()
    ds = [dt.date.fromisoformat(x) for x in mc.NFP_2026_CONFIRMED if dt.date.fromisoformat(x) <= t]
    if not ds:
        return None
    d = max(ds)
    return d if (t - d).days <= within else None


def summary_line(today=None):
    """給戰情 ① 用的一行；最近 5 天內沒有非農公布就回空字串。"""
    rel = recent_nfp_date(today)
    if not rel:
        return ""
    b = latest()
    want = (rel.year, rel.month - 1) if rel.month > 1 else (rel.year - 1, 12)
    want_s = f"{want[0]}-{want[1]:02d}"
    if not b or b["ym"] != want_s:
        return (f"⚠️ 美國非農（{rel:%m/%d} 公布）：BLS 官方資料還沒更新到 {want_s}"
                f"{'（目前最新 ' + b['ym'] + '）' if b else '（取不到）'}，數字未確認")
    if b["nfp_change_k"] is None:
        return f"⚠️ 美國非農（{rel:%m/%d} 公布）：BLS 前一個月沒有資料，算不出新增人數"
    un = ""
    if b["unemp_ym"] == want_s:
        un = f"　失業率 {b['unemp']:.1f}%" + (f"（前月 {b['unemp_prev']:.1f}%）" if b["unemp_prev"] is not None else "")
    prev = f"　-# 前月現值 {_wan(b['prev_change_k'])}（含修正）" if b["prev_change_k"] is not None else ""
    return f"🇺🇸 **非農**（BLS，{rel:%m/%d} 公布，{want[1]} 月）{_wan(b['nfp_change_k'])}{un}{prev}"


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    print(latest(force=True))
    print(summary_line("2026-10-02"))
    print(summary_line("2026-10-05"))
    print(repr(summary_line("2026-10-20")))
