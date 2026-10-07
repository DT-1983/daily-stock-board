# -*- coding: utf-8 -*-
"""回歸測試（交接 INVESTMENT_AUDIT_FIX，MRVL／NVDA）：法說摘要期間核對。執行：python test_earnings_call_period.py"""
import earnings_call as ec
import earnings_infographic as ei
import datetime as dt

TOTAL = lambda v, lab="本季總營收": [{"type": "metric", "label": lab, "value": v}]


def test_wrong_quarter_rejected():                   # MRVL：FY26Q3 筆記 vs FY27Q2 營收 2.7393B
    assert ec.period_mismatch(TOTAL("20.75億美元，季增3%、年增37%"), 2.7393e9)
    assert ec.period_mismatch(TOTAL("570億美元，年增62%"), 96.22e9)          # NVDA


def test_right_quarter_accepted():
    assert ec.period_mismatch(TOTAL("27.39億美元"), 2.7393e9) is None
    assert ec.period_mismatch(TOTAL("4,146 億美元級紀錄之外的實際數字為 414.6 億美元，較上季 238.6 億美元"), 41.46e9) is None


def test_segment_and_currency_not_compared():
    assert ec.period_mismatch(TOTAL("108億美元", "AI半導體本季營收"), 29.59e9) is None   # 事業別不是總額
    assert ec.period_mismatch(TOTAL("美元計價營收達402億美元"), 1270.38e9, currency="TWD") is None   # 幣別不同不硬比
    assert ec.period_mismatch(TOTAL("很大"), 1e9) is None                                      # 無金額不核對


def test_fiscal_label():
    ts = lambda s: dt.datetime.fromisoformat(s).timestamp()
    assert ei.fiscal_label(ts("2026-01-31"), "2026-08-01") == "FY2027Q2"     # MRVL
    assert ei.fiscal_label(ts("2026-09-03"), "2026-09-03") == "FY2026Q4"     # MU
    assert ei.fiscal_label(ts("2026-01-25"), "2026-07-26") == "FY2027Q2"     # NVDA
    assert ei.fiscal_label(ts("2026-06-30"), "2026-09-30") == "FY2027Q1"     # MSFT
    assert ei.fiscal_label(None, "2026-09-30") == ""


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("OK 4 tests passed")
