# -*- coding: utf-8 -*-
"""回歸測試（交接 INVESTMENT_AUDIT_FIX 項目 4）：投資長判斷過期標記。python test_stale_verdict.py"""
import datetime as dt
import verdict_stale as sb

TODAY = dt.date.today().isoformat()


def _run(v, state, px_now):
    old_load = sb._load
    sb._load = lambda p, d=None: state.get(p, d)
    try:
        return sb.reasons("XXXX", v, px_now)
    finally:
        sb._load = old_load


def test_triggered_condition_marks_stale():
    st = {"state/thesis_conditions.json": {"XXXX": {"conditions": [{"status": "triggered", "desc": "RS跌破均線", "triggered_date": "2026-10-07"}]}}}
    r = _run({"ts": "2026-09-22", "price": 100, "trend_angle": {"judgment": "續抱/可買"}}, st, 101)
    assert any("失效條件已觸發" in x for x in r), r


def test_tech_flip_conflicts_with_judgment():
    st = {"state/combo_result.json": {"rows": [{"ticker": "XXXX", "bull": True, "lit": 4, "asof": "2026-10-06"}]}}
    r = _run({"ts": "2026-09-03", "price": 100, "trend_angle": {"judgment": "考慮出場"}}, st, 101)
    assert any("技術面已翻多" in x for x in r), r


def test_age_and_price_move():
    old = (dt.date.today() - dt.timedelta(days=12)).isoformat()
    assert _run({"ts": old, "price": 100, "trend_angle": {}}, {}, 111), "12 天且 +11% 應標過期"
    assert not _run({"ts": TODAY, "price": 100, "trend_angle": {}}, {}, 111), "今天剛判斷的不應過期"


def test_fresh_verdict_not_stale():
    assert _run({"ts": TODAY, "price": 100, "trend_angle": {"judgment": "續抱/可買"}}, {}, 102) == []


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("OK 4 tests passed")
