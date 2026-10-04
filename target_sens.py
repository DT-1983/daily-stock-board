# -*- coding: utf-8 -*-
"""目標價敏感度（2026-10-04，Leo：「整合進去吧，也同步讓軍師讀取」）。

純算術、不連網、不呼叫 AI：只用報告自己的三個數字——目標價 T、估值倍數 M、估值基準 B（EPS 或每股淨值），T≈M×B。
回答的不是「合理價是多少」，而是「這個目標價的兩個輸入一變，價格差多少」：
  · 倍數每差 1 倍＝B 元；基準差 10%＝0.1×M×B 元；基準打 8 折（倍數不變）＝0.8×T。
  · 格子表：列＝倍數（目標倍數、×0.85、×0.7、現價隱含倍數），欄＝基準（100%／90%／80%）。
輸出是區間，不是新的目標價；不替任何人選倍數。
另附一句「賣方目標價歷史上偏樂觀」的提醒（外部研究，不是我們的回測，不自己訂折價係數）。"""

OPTIMISM = ("賣方 12 個月目標價歷史上偏樂觀：美國 2000–2009 樣本，隱含報酬平均比實際高約 15 個百分點、"
            "12 個月期末約 38% 達標（Bradshaw, Brown & Huang 2013，只讀到摘要；不是我們自己的回測）。")


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def sensitivity(r, price=None):
    """r＝advisor_reports 一筆；缺目標價／倍數／基準就回 None（不補、不猜）。"""
    T, M = _f(r.get("target")), _f(r.get("valuation_multiple"))
    B = _f(r.get("valuation_eps")) or _f(r.get("bps"))
    if not (T and M and B and T > 0 and M > 0 and B > 0):
        return None
    kind = r.get("valuation_kind") or "PE"
    base_name = "EPS" if kind == "PE" else "每股淨值"
    price = _f(price)
    out = {"T": T, "M": M, "B": B, "kind": kind, "base_name": base_name,
           "per_mult": B, "per_mult_pct": B / T,
           "per_base10": 0.1 * M * B, "base80": 0.8 * M * B,
           "derived": "回推" in str(r.get("valuation_eps_label") or ""),
           "m_now": (price / B) if price else None, "price": price}
    rows = [("目標倍數", M), ("目標倍數 ×0.85", M * 0.85), ("目標倍數 ×0.7", M * 0.7)]
    if out["m_now"]:
        rows.append(("現價隱含倍數", out["m_now"]))
    out["grid_rows"] = rows
    out["grid_cols"] = [1.0, 0.9, 0.8]
    return out


def lines(r):
    """給軍師材料／軍師資料庫的文字（價格無關，不連網）。"""
    s = sensitivity(r)
    if not s:
        return []
    kind = f"{s['M']:g} 倍{'本益比' if s['kind'] == 'PE' else '股價淨值比'}"
    out = [f"敏感度（算術、不是新目標價）：目標價 {s['T']:,.0f} ＝ {kind} × {s['base_name']} {s['B']:,.2f}"
           + ("（倍數或基準是依目標價回推的，不是報告自己寫的）" if s["derived"] else ""),
           f"倍數每差 1 倍＝{s['per_mult']:,.0f}（{s['per_mult_pct'] * 100:.1f}%）；"
           f"{s['base_name']}差 10%＝{s['per_base10']:,.0f}；{s['base_name']}只達 8 成（倍數不變）＝{s['base80']:,.0f}",
           OPTIMISM]
    return out
