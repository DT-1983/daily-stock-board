# -*- coding: utf-8 -*-
"""回歸測試（交接 INVESTMENT_AUDIT_FIX，2882）：PBR（每股淨值）基準的報告，上檔拆解不得拿 BVPS 當 EPS。
執行：python test_report_factcheck_pbr.py
"""
import report_factcheck as rf

PBR = {"ticker": "2882", "target": 117.0, "valuation_kind": "PBR", "valuation_multiple": 1.1,
       "valuation_eps": 106.37, "valuation_eps_label": "2027年底每股淨值",
       "forecast": [{"year": "2026F", "eps": 8.27}, {"year": "2027F", "eps": 8.61}]}
PE = {"ticker": "2330", "target": 3000.0, "valuation_kind": "PE", "valuation_multiple": 20,
      "valuation_eps": 150.0, "valuation_eps_label": "2027年EPS",
      "forecast": [{"year": "2026F", "eps": 100.0}, {"year": "2027F", "eps": 150.0}]}


def _rows(rep, price):
    return [r for r in rf.check(rep, price=price) if str(r.get("kind", "")).startswith("上檔空間")]


def test_pbr_not_eps_decomposition():
    rows = _rows(PBR, 112.0)
    assert len(rows) == 1, rows
    t = rows[0]["ours"] + rows[0]["note"]
    assert "1186" not in t and "盈餘成長貢獻" not in t, t
    assert "1.053" in t and "PBR" in t, t          # 112/106.37 = 1.0529
    assert "不是本益比擴張" in t or "不是 EPS" in t


def test_pe_still_decomposed():
    rows = _rows(PE, 2000.0)
    assert len(rows) == 1 and "盈餘成長貢獻" in rows[0]["ours"], rows


if __name__ == "__main__":
    test_pbr_not_eps_decomposition()
    test_pe_still_decomposed()
    print("OK 2 tests passed")
