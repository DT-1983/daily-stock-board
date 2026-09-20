# -*- coding: utf-8 -*-
"""券商名稱去識別化（2026-09-20 Leo：「不要寫是哪一家，只要寫是券商」）。

公開的產業鏈深度報告可以吸收投顧／券商研究的觀點，但**不能點名是哪一家**。
這一層由程式擋（不靠 prompt 叫 AI 別寫）：render 時把所有已知券商名稱換成「券商」，
並印出每一處替換，讓人看得到。

名單＝內建常用名（一律帶「投顧／證券」或用英文全名，避免誤傷「元大金」「富邦金」這類公司名）
＋ state/advisor_reports.json 裡實際出現過的券商名（新增券商時自動涵蓋）。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ADVISOR = os.path.join(REPO, "state", "advisor_reports.json")

# 中文名：用子字串比對（長的先換）
ZH = [
    "統一證券投資顧問", "統一投顧", "統一證券", "中國信託投顧", "中信投顧", "中信證券", "元大投顧", "元大證券",
    "康和投顧", "康和證券", "宏遠投顧", "宏遠證券", "第一金投顧", "第一金證券", "富邦投顧", "富邦證券",
    "凱基投顧", "凱基證券", "群益投顧", "群益證券", "國泰投顧", "國泰證券", "兆豐證券", "永豐投顧", "永豐證券",
    "玉山證券", "台新證券", "華南永昌證券", "華南投顧", "福邦證券", "日盛證券", "大展證券", "元富證券",
    "高盛", "瑞銀證券", "瑞銀", "摩根士丹利", "摩根大通", "花旗", "美林", "野村證券", "野村", "大和證券",
    "麥格理", "巴克萊", "德意志", "法巴", "里昂證券", "匯豐證券", "瑞信", "美銀證券", "SMBC日興",
]
# 英文名：要求前後不是英文字母（避免命中單字內部）
EN = [
    "Goldman Sachs", "Goldman", "SMBC Nikko", "Nikko", "Morgan Stanley", "J.P. Morgan", "JPMorgan", "Citigroup",
    "Merrill Lynch", "Nomura", "Daiwa", "Macquarie", "Barclays", "Deutsche Bank", "BNP Paribas", "CLSA",
    "HSBC", "Credit Suisse", "Bank of America", "BofA", "Jefferies", "Bernstein", "Wedbush", "UBS",
]
NOT_A_BROKER = {"", None, "Leo自行彙整"}


def _dataset_names():
    try:
        d = json.load(open(ADVISOR, encoding="utf-8"))
    except Exception:
        return []
    return sorted({v.get("broker") for v in d.values() if v.get("broker") not in NOT_A_BROKER})


def _compile():
    zh = sorted(set(ZH) | set(_dataset_names()), key=len, reverse=True)
    en = sorted(EN, key=len, reverse=True)
    zh_re = re.compile("|".join(re.escape(x) for x in zh)) if zh else None
    en_re = re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(x) for x in en) + r")(?![A-Za-z])")
    return zh_re, en_re


_ZH_RE, _EN_RE = _compile()


def scrub(text):
    """回 (清乾淨的字串, [被換掉的名稱])。"""
    hits = []

    def sub(m):
        hits.append(m.group(0))
        return "券商"
    out = text
    if _ZH_RE:
        out = _ZH_RE.sub(sub, out)
    out = _EN_RE.sub(sub, out)
    return out, hits


def scrub_deep(obj, path="", log=None):
    """遞迴處理 dict/list/str。log 收集 (路徑, 名稱)。"""
    if log is None:
        log = []
    if isinstance(obj, str):
        new, hits = scrub(obj)
        for h in hits:
            log.append((path, h))
        return new, log
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj):
            nv, _ = scrub_deep(v, f"{path}[{i}]", log)
            out.append(nv)
        return out, log
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nv, _ = scrub_deep(v, f"{path}/{k}", log)
            out[k] = nv
        return out, log
    return obj, log
