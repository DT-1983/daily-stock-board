# -*- coding: utf-8 -*-
"""投資長判斷是不是已經過期（2026-10-07，交接 INVESTMENT_AUDIT_FIX 項目 4）

原本判斷產生後，正文就一直當「現況」顯示——MRVL 9/3 的出場判斷在 10/6 技術面早已翻回 4 燈全亮還照樣擺著，
2882 的 RS 破線也只在文末記一行。這裡用**資料**找過期證據，不靠檔案修改時間：
  ① 失效條件登錄簿（state/thesis_conditions.json）status=triggered——判斷當初寫下的失效條件已成立；
  ② 判斷之後才觸發的券商報告失效條件（state/advisor_reports_today.json 的 fire_first > 判斷日）；
  ③ 趨勢角度的方向跟現在燈號牴觸（判斷說出場、現在 SuperTrend 多方且 ≥3 燈；判斷說續抱、現在已翻空）；
  ④ 判斷當時報價跟現在差 ≥15%（或判斷已超過 10 天且差 ≥8%）。
只標「過期、待更新」，**不重算、不改寫**判斷內容（要新判斷得重新呼叫投資長）。
被三處用：個股整合報告（stock_brief）、軍師資料庫 Markdown（advisor_db_export）、索引頁。
"""
import datetime as _dt
import io
import json
import re


def _load(path, default=None):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return default


def _norm(tk):
    t = str(tk or "").upper().strip()
    return re.sub(r"\.(TWO?|US)$", "", t)


def reasons(ticker, v, px_now=None):
    """回 [過期原因, ...]；空＝沒有證據過期。ticker 任何寫法都行，v 是 advisor_verdicts 的一筆。"""
    if not v:
        return []
    why = []
    ts = str(v.get("ts") or "")[:10]
    tk = _norm(ticker)

    try:
        for r in (_load("state/advisor_reports_today.json", {}) or {}).get("rows", []):
            if _norm(r.get("ticker")) != tk:
                continue
            for f in (r.get("fired") or []):
                ff = str(f.get("fire_first") or "")
                if ts and ff and ff > ts:
                    why.append(f"{ff} 觸發失效條件：{str(f.get('desc') or '')[:40]}")
                    break
    except Exception:                                       # noqa: BLE001
        pass

    try:
        for k, ent in (_load("state/thesis_conditions.json", {}) or {}).items():
            if _norm(k) != tk:
                continue
            for c in (ent.get("conditions") or []):
                if c.get("status") == "triggered":
                    td = c.get("triggered_date")
                    why.append(f"失效條件已觸發：{str(c.get('desc') or '')[:40]}" + (f"（{td}）" if td else ""))
            break
    except Exception:                                       # noqa: BLE001
        pass

    crow = None
    try:
        crow = next((r for r in (_load("state/combo_result.json", {}) or {}).get("rows", [])
                     if _norm(r.get("ticker")) == tk), None)
        tj = str((v.get("trend_angle") or {}).get("judgment") or "")
        # 只有「技術面資料日比判斷用的資料日更新」才算牴觸：同一天的資料，判斷本來就是看過這個技術面才下的
        # （2026-10-08 重判 31 檔持股時發現：剛產生的新判斷被誤標過期——趨勢角度的出場理由可以來自 RS 等，不只 SuperTrend）。
        newer = bool(crow) and str(crow.get("asof") or "") > str(v.get("price_asof") or v.get("ts") or "")
        if crow and newer:
            if "出場" in tj and crow.get("bull") and (crow.get("lit") or 0) >= 3:
                why.append(f"技術面已翻多（{crow.get('asof')}：SuperTrend 多方、{crow.get('lit')}/4 燈），與判斷「{tj}」牴觸")
            elif tj.startswith("續抱") and crow.get("bull") is False:
                why.append(f"技術面已翻空（{crow.get('asof')}：SuperTrend 空方），與判斷「{tj}」牴觸")
    except Exception:                                       # noqa: BLE001
        pass

    try:
        px_then = v.get("price")
        px = px_now if px_now is not None else (crow or {}).get("price")
        age = (_dt.date.today() - _dt.date.fromisoformat(ts)).days if ts else 0
        mv = (float(px) / float(px_then) - 1) if (px_then and px) else None
        if mv is not None and (abs(mv) >= 0.15 or (age >= 10 and abs(mv) >= 0.08)):
            why.append(f"報價 {float(px_then):,.2f}（{v.get('price_asof')}）→ {float(px):,.2f}，已變動 {mv:+.0%}"
                       + (f"，距判斷已 {age} 天" if age >= 10 else ""))
    except Exception:                                       # noqa: BLE001
        pass
    return why
