# -*- coding: utf-8 -*-
"""SEC EDGAR 美股財報（給盈再率用）

2026-08-25 建立。緣由：yfinance 的資產負債表拿不到「4 年前」那一期
（第 5 期一律 NaN，AAPL/9904 實測皆然），而盈再率的定義就是「今年 vs 四年前」，
所以美股一直只能用 CapEx÷淨利 的替代算法。

⚠️ 2026-08-25 實測訂正（訂正兩次，以這版為準）：
我先寫「CapEx 版漏長投所以低估」，再改成「系統性高估」——**兩次都講死了方向，都不對**。
CapEx 版與官方公式**沒有固定方向的偏差**，實測兩邊都出現過：
  高估：CPB +56%→+14%、WU +21%→−1%、GLPI +14%→−5%（美股）
  低估：9917 +59%→**+174%**、6581 +62%→+101%、1342 +38%→+86%（台股）
原因是兩個反向誤差同時存在——CapEx 用**毛支出**（拉高），又**漏掉長期投資**（壓低），
哪一個大取決於公司的資產結構。所以它不是官方公式的近似值，是**另一個東西**，
不能拿來當替代，只能標「資料不足、僅供參考」。

SEC 規定要帶可識別的 User-Agent，且建議 <10 req/s。
"""
import json
import ssl
import time
import urllib.request

UA = {"User-Agent": "Leo personal investment research phc1110@gmail.com"}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_CIK_MAP: dict = {}      # ticker -> zero-padded CIK
_FACTS_CACHE: dict = {}
_LAST_CALL = [0.0]

# ── 兩套分類（taxonomy）────────────────────────────────────
# 美國本土公司報 us-gaap；外國發行人（20-F）多半報 ifrs-full。
# 實測 HAFN（丹麥）、BWLP（百慕達）**一個 us-gaap 科目都沒有**，
# 只看 us-gaap 會把整批外國股當成「EDGAR 查無此公司」漏掉。
# 固資：必要。多數公司用 PropertyPlantAndEquipmentNet
PPE_TAGS = ["PropertyPlantAndEquipmentNet",
            "PropertyPlantAndEquipmentNetExcludingCapitalLeasedAssets"]
# 長投：**每家公司用的科目名不同**（實測 AAPL=MarketableSecuritiesNoncurrent、
# MSFT=LongTermInvestments、KO=EquityMethodInvestments、JNJ 一個都沒有）。
# 依序找第一個有值的；全都沒有就當 0——對很多公司來說本來就沒有長投，
# 但要標記出來，不要讓「沒這科目」跟「有但沒抓到」混在一起。
LTI_TAGS = ["LongTermInvestments", "MarketableSecuritiesNoncurrent",
            "EquityMethodInvestments", "EquitySecuritiesFvNiNoncurrent",
            "OtherLongTermInvestments"]
NI_TAGS = ["NetIncomeLoss", "ProfitLoss"]

IFRS_PPE_TAGS = ["PropertyPlantAndEquipment",
                 "PropertyPlantAndEquipmentIncludingRightofuseAssets"]
IFRS_LTI_TAGS = ["InvestmentsInAssociatesAccountedForUsingEquityMethod",
                 "InvestmentsInSubsidiariesJointVenturesAndAssociates",
                 "OtherNoncurrentFinancialAssets", "NoncurrentFinancialAssets"]
IFRS_NI_TAGS = ["ProfitLoss", "ProfitLossAttributableToOwnersOfParent"]
# 年報型別：10-K 美國本土、20-F 外國發行人、40-F 加拿大 MJDS
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def _throttle():
    """SEC 建議 <10 req/s，保守一點抓 0.2 秒。"""
    gap = time.time() - _LAST_CALL[0]
    if gap < 0.2:
        time.sleep(0.2 - gap)
    _LAST_CALL[0] = time.time()


def _get(url, timeout=45):
    _throttle()
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout, context=_CTX).read())


def _load_cik_map():
    """SEC 官方 ticker→CIK 對照表（約 1 萬多檔，一次載入行程內快取）。"""
    if _CIK_MAP:
        return _CIK_MAP
    try:
        d = _get("https://www.sec.gov/files/company_tickers.json")
        for row in d.values():
            _CIK_MAP[row["ticker"].upper()] = str(row["cik_str"]).zfill(10)
    except Exception as e:                       # noqa: BLE001
        print(f"  [edgar] 載入 CIK 對照失敗：{e}")
    return _CIK_MAP


def _facts(ticker):
    tk = ticker.upper().replace("-", "")         # BRK-B → BRKB（SEC 用無分隔寫法）
    if tk in _FACTS_CACHE:
        return _FACTS_CACHE[tk]
    cik = _load_cik_map().get(tk)
    if not cik:
        _FACTS_CACHE[tk] = None
        return None
    try:
        d = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        facts = d.get("facts", {})
    except Exception:
        facts = None
    _FACTS_CACHE[tk] = facts
    return facts


def _annual(node_map, tags, want_cur=None):
    """回 ({年: 值}, tag, 幣別)。只取年報（10-K/20-F/40-F）。找不到回 ({}, None, None)。

    IFRS 申報常用當地幣（實測 CIG/ITUB 報 BRL），所以幣別不能寫死 USD。
    盈再率是比值，分子分母同幣就好——但**必須是同一種**，
    否則會拿巴西幣的固資去除美金的淨利，算出來的數字完全沒意義卻不會報錯。
    """
    for tag in tags:
        node = node_map.get(tag) if node_map else None
        if not node:
            continue
        units = node.get("units", {})
        curs = [want_cur] if want_cur and want_cur in units else                sorted(units, key=lambda c: -len(units[c]))
        for cur in curs:
            out = _pick_annual(units.get(cur, []))
            if out:
                return out, tag, cur
    return {}, None, None


def _pick_annual(units):
    """從一堆 XBRL 事實裡挑出年報數字。

    20-F/40-F 是外國發行人的年報（實測 CIG/ITUB 巴西、HAFN/TRMD 丹麥、
    BWLP 百慕達都走 20-F）。只收 10-K 會把這些整批漏掉，
    表面上看起來像「EDGAR 沒這家公司」，其實只是報表型別不同。
    """
    out = {}
    for unit in units:
        if unit.get("form") not in ANNUAL_FORMS or unit.get("fp") != "FY":
            continue
        y = unit["end"][:4]
        # 同一年可能有多筆（原始申報＋後續重編），取最後揭露的
        if y not in out or unit.get("filed", "") >= out[y][1]:
            out[y] = (unit["val"], unit.get("filed", ""))
    return {y: v[0] for y, v in out.items()}


def _compute(node_map, ppe_tags, lti_tags, ni_tags):
    """單一分類（us-gaap 或 ifrs-full）內算盈再率。算不出回 None。"""
    ppe, _, cur = _annual(node_map, ppe_tags)
    if not ppe:
        return None, None
    # 淨利必須跟固資同幣別，否則是拿巴西幣除美金
    ni, _, ni_cur = _annual(node_map, ni_tags, want_cur=cur)
    if not ni or ni_cur != cur:
        return None, None
    lti, lti_tag, lti_cur = _annual(node_map, lti_tags, want_cur=cur)
    if lti_cur != cur:                           # 幣別對不上就當沒有，不硬混
        lti, lti_tag = {}, None

    # 期末年度不能直接抓「最新」。實測 BSM 固資到 2025 但淨利只到 2024、
    # NVO 固資從 2020 才有但算式要 2019——各公司申報進度不一致，
    # 原本硬用最新年度當期末，只要有一格對不上就整檔作廢（3 檔白白漏掉）。
    # 改成從新到舊找第一個「期末固資＋期初固資＋四年淨利」全齊的年度。
    # 最多往回 3 年；再舊就太不即時，寧可標資料不足。
    years = sorted(ppe)
    if len(years) < 5:
        return None, None

    end_y = ni_sum = None
    for cand in sorted(years, reverse=True)[:4]:
        start = str(int(cand) - 4)
        if start not in ppe:
            continue
        vals = [ni.get(str(k)) for k in range(int(cand) - 3, int(cand) + 1)]
        if any(v is None for v in vals):
            continue                             # 四年淨利缺任一年就換下一個年度試
        total = sum(vals)
        if total <= 0:
            continue
        end_y, start_y, ni_sum = cand, start, total
        break
    if end_y is None:
        return None, None

    def base(y):
        return ppe[y] + lti.get(y, 0)            # 長投缺視為 0（很多公司本來就沒有）

    ratio = (base(end_y) - base(start_y)) / ni_sum
    # 標記有沒有真的抓到長投，方便事後判斷「這檔是沒有長投，還是我們沒抓到」
    return round(float(ratio), 4), bool(lti_tag)


def reinvest_us(ticker):
    """美股盈再率（洪瑞泰公式）。回 (值, 方法字串)；算不出來回 (None, None)。

    公式：(期末固資+長投 − 期初固資+長投) ÷ 近 4 年稅後淨利
    期末＝最新年報，期初＝4 年前年報。任一必要項缺就不算，不用 0 硬湊。
    """
    facts = _facts(ticker)
    if not facts:
        return None, None                        # 查無此公司/抓不到 → 交回呼叫端退 fallback

    for tax, ppe_t, lti_t, ni_t, tag in (
            ("us-gaap", PPE_TAGS, LTI_TAGS, NI_TAGS, "official_us"),
            ("ifrs-full", IFRS_PPE_TAGS, IFRS_LTI_TAGS, IFRS_NI_TAGS, "official_us_ifrs")):
        node_map = facts.get(tax)
        if not node_map:
            continue
        ratio, has_lti = _compute(node_map, ppe_t, lti_t, ni_t)
        if ratio is not None:
            return ratio, tag if has_lti else tag + "_nolti"
    return None, None


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    for t in (sys.argv[1:] or ["AAPL", "MSFT", "JNJ", "KO", "NVDA"]):
        v, m = reinvest_us(t)
        print(f"{t:8} {f'{v*100:+7.0f}%' if v is not None else '    n/a'}  {m}")
