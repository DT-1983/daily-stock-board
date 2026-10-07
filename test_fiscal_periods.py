# -*- coding: utf-8 -*-
"""回歸測試（交接 INVESTMENT_AUDIT_FIX，景碩／MRVL）：已公布的季／年度不得再被當「預估」。python test_fiscal_periods.py"""
import fiscal_periods as FP
import report_factcheck as rf

# 景碩 3189：2026Q2 已公布（FinMind 基本 EPS 2.57）；3Q26 還沒有
FP._TW_CACHE["3189"] = {"2026-06-30": {"EPS": 2.57}, "2025-12-31": {"EPS": 10.0}}
R3189 = {"ticker": "3189", "target": 1205, "eps_quarterly": [{"q": "2Q26", "value": 2.49}, {"q": "3Q26E", "value": 3.79}],
         "forecast": [{"year": "2026E", "eps": 12.0}, {"year": "2027E", "eps": 27.42}]}


def test_published_quarter_compared():
    rows = rf.check(R3189, price=1070.0)
    pub = [r for r in rows if r["kind"] == "季度 EPS（該季已公布）"]
    assert len(pub) == 1 and "2.57" in pub[0]["ours"] and pub[0]["verdict"] == "warn", pub
    assert "口徑待核" in pub[0]["note"]
    wait = [r for r in rows if r["kind"] == "季度 EPS 預估"]
    assert len(wait) == 1 and "3Q26E" in wait[0]["claim"] and "2Q26" not in wait[0]["claim"], wait


def test_within_3pct_ok():
    FP._TW_CACHE["9999"] = {"2026-06-30": {"EPS": 2.50}}
    rows = rf.check({"ticker": "9999", "eps_quarterly": [{"q": "2Q26", "value": 2.49}]}, price=None)
    r = [x for x in rows if x["kind"] == "季度 EPS（該季已公布）"][0]
    assert r["verdict"] == "ok", r


def test_parse_quarter():
    assert FP.parse_quarter("2Q26") == (2026, 2) and FP.parse_quarter("Q3 2026") == (2026, 3)
    assert FP.parse_quarter("2026Q4") == (2026, 4) and FP.parse_quarter("3Q26E") == (2026, 3)
    assert FP.parse_quarter("FY26") is None


def test_flat_year_published_is_actual():
    # MRVL：2025 年全年已公布，EPS 年增 +4% 是實績不是未來空白年
    FP.year_published = lambda t, y: True if str(y).startswith("2025") else False
    rep = {"ticker": "MRVL", "forecast": [{"year": "2024", "eps": 1.51}, {"year": "2025", "eps": 1.57}, {"year": "2026", "eps": 2.84}]}
    kinds = [r["kind"] for r in rf.check(rep, price=None)]
    assert "有沒有空白年（已公布實績）" in kinds and "有沒有空白年" not in kinds, kinds


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("OK 4 tests passed")
