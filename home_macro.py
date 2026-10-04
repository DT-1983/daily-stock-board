# -*- coding: utf-8 -*-
"""投資首頁「總經指標」區（2026-10-04 Leo：「這幾個新增的指標投資首頁也可以加？」）。
四張卡：美債 10 年殖利率＋與標普連動、非農、CPI、台指電子盤。全是免費公開資料（yfinance／BLS／期交所），零 AI。
在 GitHub Actions 上跑（market-home.yml）：每次現抓，不依賴本機快取；任何一張取不到就顯示「這次取不到」，不讓整區消失。
只描述、不是買賣訊號。"""
import datetime as dt
from html import escape as esc


def _card(nm, px, sub, cls="flat"):
    return (f'<div class="idx"><div class="nm">{esc(nm)}</div><div class="px num {cls}">{px}</div>'
            f'<div class="chg flat" style="font-weight:400;line-height:1.6">{sub}</div></div>')


def _fail(nm, why):
    return _card(nm, "—", f"這次取不到：{esc(why)[:60]}")


def _rel_note(ym, dates, today=None):
    """依官方行事曆（macro_calendar）回「10/02 公布」或偏舊警示。
    ym＝資料月份 'YYYY-MM'；該月資料應在次月的某個公布日出來。
    - 行事曆上最近一個已到期的公布日，其資料月份＝ym → 寫公布日。
    - 已到期的公布日比資料新（例如 10/2 已過但資料還是 8 月）→ 紅字警示（容許公布當天 1 天延遲）。
    - 行事曆查不到 → 不猜，寫「公布日未知」。"""
    import macro_calendar as mc                                      # noqa: F401
    t = today or dt.date.today()
    ds = sorted(dt.date.fromisoformat(x) for x in dates)
    due = [d for d in ds if d <= t]
    if not due:
        return "公布日未知"
    last = due[-1]
    want = (last.year, last.month - 1) if last.month > 1 else (last.year - 1, 12)
    if f"{want[0]}-{want[1]:02d}" == ym:
        return f"{last:%m/%d} 公布"
    if (t - last).days >= 1:
        return (f'<span class="neg">⚠️ {last:%m/%d} 應已公布 {want[0]}-{want[1]:02d} 數據，'
                f'目前仍是 {esc(ym)}，資料偏舊</span>')
    return f"{last:%m/%d} 應公布，資料尚未更新（{esc(ym)}）"


def _dates(kind):
    import macro_calendar as mc
    return list(mc.NFP_2026_CONFIRMED) if kind == "NFP" else list(mc.CPI_2026)


def _yield():
    try:
        import yield_link
        d = yield_link.data(force=True)
        if not d:
            return _fail("美債 10 年殖利率", "yfinance 無回應")
        cls = "pos" if d["chg_bp"] > 0 else ("neg" if d["chg_bp"] < 0 else "flat")
        w = yield_link._word(d["r3"])
        late = (dt.date.today() - dt.date.fromisoformat(d["asof"])).days
        stale = f' <span class="neg">⚠️ 落後 {late} 天</span>' if late > 4 else ""
        sub = (f'{d["chg_bp"]:+.1f} bp · {esc(d["asof"][5:])} 收{stale}<br>'
               f'近 6 月高點 {d["high6"]:.2f}%'
               + (f' · 一個月前 {d["ago"]:.2f}%' if d["ago"] is not None else "")
               + f'<br>與標普連動 3 個月 {d["r3"] + 0.0:+.2f}（{w}）· 24 個月 {d["r24"] + 0.0:+.2f}')
        return _card("美債 10 年殖利率", f'{d["level"]:.2f}%', sub, cls)
    except Exception as e:                                   # noqa: BLE001
        return _fail("美債 10 年殖利率", str(e))


def _nfp():
    try:
        import bls_fetch
        d = bls_fetch.latest(force=True)
        if not d:
            return _fail("非農就業", "BLS 無回應")
        ch = d["nfp_change_k"] / 10.0
        pv = d["prev_change_k"] / 10.0
        return _card("非農就業", f'{ch:+.1f} 萬',
                     f'{esc(d["ym"])} 數據（{_rel_note(d["ym"], _dates("NFP"))}） · 失業率 {d["unemp"]}%（前月 {d["unemp_prev"]}%）<br>'
                     f'前月 {pv:+.1f} 萬（含修正）· 比前月 {ch - pv:+.1f} 萬 · BLS 官方', "pos" if ch > 0 else "neg")
    except Exception as e:                                   # noqa: BLE001
        return _fail("非農就業", str(e))


def _cpi():
    try:
        import bls_fetch
        d = bls_fetch.cpi_latest(force=True)
        if not d:
            return _fail("美國 CPI", "BLS 無回應")
        py = d.get("prev_yoy")
        pc = d.get("prev_core_yoy")
        pv = f'前月 {py:.1f}%' if py is not None else '前月 —'
        pcv = f'（前月 {pc:.1f}%）' if pc is not None else ''
        return _card("美國 CPI（年增）", f'{d["yoy"]:.1f}%',
                     f'{esc(d["ym"])} 數據（{_rel_note(d["ym"], _dates("CPI"))}） · {pv} · 月增 {d["mom_sa"]:+.1f}%<br>'
                     f'核心年增 {d["core_yoy"]:.1f}%{pcv} · BLS 官方', "flat")
    except Exception as e:                                   # noqa: BLE001
        return _fail("美國 CPI", str(e))


def _night():
    try:
        import night_session
        why = []
        s = night_session.fetch(why)
        if not s:
            return _fail("台指電子盤", why[0] if why else "原因不明")
        d = dt.datetime.strptime(s["date"], "%Y%m%d").date()
        end = d + dt.timedelta(days=1)
        pct = s.get("pct")
        cls = "flat" if pct is None else ("pos" if pct > 0 else ("neg" if pct < 0 else "flat"))
        late = (dt.date.today() - d).days
        stale = f' <span class="neg">⚠️ 落後 {late} 天</span>' if late > 4 else ""
        chg = "" if pct is None else f'{s["change"]:+,.0f}（{pct:+.2f}%）<br>'
        return _card("台指電子盤", f'{s["last"]:,.0f}',
                     f'{chg}{d:%m/%d} 15:00～{end:%m/%d} 05:00 夜盤 · 期交所彙整、非即時{stale}', cls)
    except Exception as e:                                   # noqa: BLE001
        return _fail("台指電子盤", str(e))


def cards_html():
    return "".join(f() for f in (_yield, _nfp, _cpi, _night))
