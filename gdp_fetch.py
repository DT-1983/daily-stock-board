"""GDP 觀察頁資料層 → gdp_data.json

資料源（2026-08-04 驗證可用）：
- 美國實際：FRED 公開 CSV GDPC1（實質 GDP 水準）→ 自算季增年率 SAAR
- 美國預測：Philly Fed SPF median_RGDP_growth.xlsx（SAAR，口徑與實際值一致）
  （抓取邏輯移植自 TradingBot/gdp.py，含 openpyxl 炸 datetime 的 zipfile 繞法）
- 台灣實際：主計總處 nstatdb A018101010「經濟成長率(%)」（YoY，台灣慣例）
- 台灣預測：gdp_manual.json 手動維護——主計總處每季新聞稿（2/5/8/11 月）只有
  PDF 沒有 API，asof 超過 STALE_DAYS 天會推 Telegram 提醒去更新

口徑注意：美國「實際+預測」都是 SAAR、台灣「實際+預測」都是 YoY，
各自內部一致可以畫同一條線，但美台兩張圖的數字不能互比。

用法：python gdp_fetch.py [--force-notify]
"""
import io
import sys
import json
import os
import re
import zipfile
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, date

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 印 emoji 會炸

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gdp_data.json")
MANUAL = os.path.join(HERE, "gdp_manual.json")
STALE_DAYS = 120  # 主計總處每季發布，一季 92 天 + 緩衝

UA = {"User-Agent": "Mozilla/5.0"}
SPF_URL = ("https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/"
           "survey-of-professional-forecasters/data-files/files/median_RGDP_growth.xlsx")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPC1"
DGBAS_URL = ("https://nstatdb.dgbas.gov.tw/dgbasAll/webMain.aspx"
             "?sys=220&funid=A018101010&outmode=8&fldlst=111111111111111")


def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ── 美國 ────────────────────────────────────────────────────────────

def _get_text_curl_fallback(url):
    """FRED 會擋 python 的 TLS 指紋（requests/urllib 都被 reset），curl 卻通。
    先試 requests，失敗改走 subprocess curl（本機與 GitHub Actions 都有 curl）。"""
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        import subprocess
        # 不用 text=True：Windows 會拿 cp950 解 UTF-8 回應，直接炸 reader thread
        p = subprocess.run(["curl", "-sL", "--max-time", "30", url],
                           capture_output=True, timeout=40)
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError(f"curl 也失敗 rc={p.returncode}")
        return p.stdout.decode("utf-8")


def fetch_us_actual(n=12):
    """FRED GDPC1 水準值 → 季增年率 SAAR，取近 n 季"""
    rows = [ln.split(",") for ln in _get_text_curl_fallback(FRED_CSV).strip().splitlines()[1:]]
    series = [(d, float(v)) for d, v in rows if v not in (".", "")]
    out = []
    for (d0, v0), (d1, v1) in zip(series, series[1:]):
        y, m = int(d1[:4]), int(d1[5:7])
        q = (m - 1) // 3 + 1
        saar = ((v1 / v0) ** 4 - 1) * 100
        out.append({"period": f"{y}-Q{q}", "value": round(saar, 2)})
    return out[-n:]


def fetch_us_spf():
    """Philly Fed SPF 中位數預測（SAAR）。移植自 TradingBot/gdp.py。"""
    r = requests.get(SPF_URL, headers=UA, timeout=25)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
        strings = [(si.find("a:t", ns).text or "") if si.find("a:t", ns) is not None else ""
                   for si in ss.findall("a:si", ns)]
    except KeyError:
        strings = []
    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall("a:sheetData/a:row", ns):
        cells = []
        for c in row.findall("a:c", ns):
            v = c.find("a:v", ns)
            val = v.text if v is not None else None
            if c.attrib.get("t") == "s" and val is not None:
                val = strings[int(val)]
            cells.append(val)
        rows.append(cells)
    last = None
    for row in rows[1:]:
        if len(row) >= 3 and row[0] and row[1] and row[2]:
            last = row
    if not last:
        return []
    sy, sq = int(float(last[0])), int(float(last[1]))
    out = []
    for off in range(5):  # DRGDP2~DRGDP6 = 本季+0 ~ 本季+4
        i = 2 + off
        if i >= len(last) or last[i] in (None, "#N/A"):
            continue
        q = sq + off
        y = sy + (q - 1) // 4
        q = (q - 1) % 4 + 1
        try:
            out.append({"period": f"{y}-Q{q}", "value": round(float(last[i]), 2),
                        "source": "Philly Fed SPF"})
        except (TypeError, ValueError):
            continue
    return out


# ── 台灣 ────────────────────────────────────────────────────────────

def fetch_tw_actual(n=12):
    """主計總處 nstatdb：經濟成長率(%)（YoY），只取「NNN年第N季」列，取近 n 季"""
    # 主計總處憑證缺 Subject Key Identifier，Python 3.13 驗證直接拒收 → 走 curl
    d = json.loads(_get_text_curl_fallback(DGBAS_URL))
    # 找「經濟成長率」欄位 index（別寫死，主計總處改欄位順序就抓錯）
    cols = d["colh"][0]
    idx = next((i for i, c in enumerate(cols) if "經濟成長率" in c), None)
    if idx is None:
        raise RuntimeError(f"找不到經濟成長率欄位：{cols}")
    vals = d["orgdata"][idx]
    out = []
    for (label, *_), v in zip(d["row"], vals):
        m = re.match(r"^(\d+)年第(\d)季$", label.strip())
        if not m or v in (None, ""):
            continue
        y = int(m.group(1)) + 1911
        out.append({"period": f"{y}-Q{m.group(2)}", "value": round(float(v), 2)})
    return out[-n:]


def load_tw_forecast():
    if not os.path.exists(MANUAL):
        return {"asof": None, "source": "主計總處", "quarters": [], "annual": {}}
    return json.load(open(MANUAL, encoding="utf-8"))


# ── 高點判定（洪瑞泰用法：GDP 高點不買股票、賣股票）─────────────────

def find_peak(actual, forecast):
    """實際近 8 季 + 預測合併找最高點。
    回傳 (peak_period, status)：
      尚未到頂＝高點在未來季　接近高點＝高點就是最新實際季　已過高點＝高點在過去
    """
    series = {a["period"]: a["value"] for a in actual[-8:]}
    latest_actual = actual[-1]["period"] if actual else None
    for f in forecast:
        series.setdefault(f["period"], f["value"])
    if not series:
        return None, "無資料"
    peak = max(series, key=series.get)
    if latest_actual is None or peak > latest_actual:
        return peak, "尚未到頂"
    if peak == latest_actual:
        return peak, "接近高點"
    return peak, "已過高點"


# ── Telegram 提醒 ───────────────────────────────────────────────────

def notify_stale(asof, force=False):
    """台灣預測 asof 過期 → 推 Telegram。回傳是否有推。"""
    if asof:
        days = (date.today() - datetime.strptime(asof, "%Y-%m-%d").date()).days
        if days < STALE_DAYS and not force:
            return False
        msg = (f"📊 <b>GDP 觀察頁：台灣預測該更新了</b>\n\n"
               f"gdp_manual.json 的主計總處預測是 {asof}（{days} 天前）。\n"
               f"主計總處每年 2/5/8/11 月發布新聞稿，請把最新季度預測填進去。")
    else:
        msg = ("📊 <b>GDP 觀察頁：台灣預測尚未建檔</b>\n\n"
               "gdp_manual.json 還沒有主計總處預測資料，請填入最新新聞稿數字。")
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("⚠️ 無 TELEGRAM_BOT_TOKEN/CHAT_ID，提醒略過")
        return False
    requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                  data={"chat_id": chat, "parse_mode": "HTML", "text": msg}, timeout=15)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-notify", action="store_true")
    args = ap.parse_args()
    _load_env()

    data = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "us": {}, "tw": {}}

    try:
        data["us"]["actual"] = fetch_us_actual()
    except Exception as e:
        print(f"⚠️ 美國實際值抓取失敗：{e}")
        data["us"]["actual"] = []
    try:
        data["us"]["forecast"] = fetch_us_spf()
    except Exception as e:
        print(f"⚠️ SPF 抓取失敗：{e}")
        data["us"]["forecast"] = []

    try:
        data["tw"]["actual"] = fetch_tw_actual()
    except Exception as e:
        print(f"⚠️ 台灣實際值抓取失敗：{e}")
        data["tw"]["actual"] = []
    twf = load_tw_forecast()
    # 概估（新聞稿比 nstatdb 資料庫早約 2 週）：接在實際值後面，標 est 供頁面標注
    last_tw = data["tw"]["actual"][-1]["period"] if data["tw"]["actual"] else ""
    for e in twf.get("actual_est", []):
        if e["period"] > last_tw:
            data["tw"]["actual"].append(
                {"period": e["period"], "value": e["value"], "est": True})
    data["tw"]["forecast"] = [
        {"period": q["period"], "value": q["value"], "source": twf.get("source", "主計總處")}
        for q in twf.get("quarters", [])]
    data["tw"]["forecast_asof"] = twf.get("asof")
    data["tw"]["annual"] = twf.get("annual", {})

    data["peak"] = {}
    for mkt in ("us", "tw"):
        # 只用最新實際季之後的預測（SPF 會含當季 nowcast，重疊季以實際值為準）
        act = data[mkt]["actual"]
        last = act[-1]["period"] if act else ""
        fut = [f for f in data[mkt]["forecast"] if f["period"] > last]
        pk, st = find_peak(act, fut)
        data["peak"][mkt] = {"peak_period": pk, "status": st}

    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已存 {OUT}")
    print(f"   美國：實際 {len(data['us']['actual'])} 季 / 預測 {len(data['us']['forecast'])} 季"
          f" → {data['peak']['us']['status']}（高點 {data['peak']['us']['peak_period']}）")
    print(f"   台灣：實際 {len(data['tw']['actual'])} 季 / 預測 {len(data['tw']['forecast'])} 季"
          f" → {data['peak']['tw']['status']}（高點 {data['peak']['tw']['peak_period']}）")

    if notify_stale(twf.get("asof"), args.force_notify):
        print("📨 已推台灣預測更新提醒")


if __name__ == "__main__":
    main()
