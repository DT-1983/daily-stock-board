# -*- coding: utf-8 -*-
"""產業筆記登錄簿（2026-09-16，Leo：「這類一次性產業筆記查到的個股數字，要不要
也寫進軍師資料庫」→「每次都寫進去」）。

跟 `advisor_reports.py`（券商目標價）／`revenue_report.py`（月營收）同一層級：
**查過的事實，不用等投資長 AI 判斷**。差別是這份是給「一次性產業筆記」
（`industry-note-intake` skill 那套流程——社群貼文/券商影音整理出來的個股筆記）
用的登錄簿，每檔可以累積多筆（同一檔股票可能在不同主題的筆記裡各出現一次），
不像月營收只留最新一筆快照。

⚠️ 只收「這次筆記查到的關鍵事實／發現」，不是整篇報告內容搬過來——軍師資料庫
濃度優先，`report_path` 已經指到完整報告，需要細節的人自己去開。

用法:
    import industry_notes
    industry_notes.record("3680", "家登", "12吋光罩/High NA EUV",
        "8月營收年增49.9%，Q2 EPS較Q1翻倍，漲停有基本面支撐",
        source="IG TechNews科技新報 High NA EUV光罩系列圖卡",
        report_path=r"...\\12吋光罩HighNA_EUV產業筆記.html")
"""
import datetime
import io
import json
import os

from investment_chief import norm_ticker

STORE = "state/industry_notes.json"


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    io.open(path, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=2))


def record(ticker, name, topic, summary, source, report_path, date=None):
    """加一筆（同一檔同一主題同一天重跑，直接蓋掉那一筆，不會累積重複）。"""
    date = date or datetime.date.today().isoformat()
    store = _load(STORE, {})
    tk = norm_ticker(ticker)
    entries = store.setdefault(tk, [])
    entries[:] = [e for e in entries
                 if not (e.get("topic") == topic and e.get("date") == date)]
    entries.append({"date": date, "name": name, "topic": topic, "summary": summary,
                    "source": source, "report_path": report_path})
    _save(STORE, store)


def by_ticker():
    """{正規化代號: [entry,...]}，跟 advisor_db_export.py 其他來源同一個形狀。"""
    store = _load(STORE, {})
    out = {}
    for tk, entries in store.items():
        out.setdefault(norm_ticker(tk), []).extend(entries)
    return out


def new_today_lines(date=None):
    """今天新增的（給 investment_chief.today_tickers() 的觸發事件用，跟
    advisor_reports.new_today_lines() 同一個形狀）。回 [(ticker, 一句話), ...]。"""
    date = date or datetime.date.today().isoformat()
    store = _load(STORE, {})
    out = []
    for tk, entries in store.items():
        for e in entries:
            if e.get("date") == date:
                out.append((tk, f"新增產業筆記（{e.get('topic','')}）"))
    return out
