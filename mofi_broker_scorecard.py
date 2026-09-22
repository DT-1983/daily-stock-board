# -*- coding: utf-8 -*-
"""券商目標價可信度計分卡（2026-09-22，Leo 給連結：mofiinvestment.com/AI-RESEARCH/broker-report.html）。

## 這是什麼

老墨自己整理的研究站，用 19,919 份歷史報告（53 家券商、1,183 檔台股、2021-2026）
回測「跟單這份報告的『買進』建議抱一年，達成率／等待天數／套牢深度／期望值」，
算出 26 家主力券商（樣本數夠大的）的可信度排名。這正是 `broker_credibility.py`
檔頭寫「中信的報告不附調整史，無法回溯它過去準不準」時缺的那份資料——現在有了。

## 資料怎麼拿到的

頁面是純靜態 HTML，資料以 `<script id="data" type="application/json">` 內嵌在頁面裡
（不是 API，沒有登入門檻），欄位：
  `scorecard`：26 家主力券商，每家 {broker, n, n_buy, cred_score(可信度分數),
    rank(排名), rate_close(達成率), days_close(等待天數), mdd_close(套牢深度),
    ev(期望值), lights(rate/mdd/time/calib 四燈號)}；
  `reference`：樣本數不足以進主榜的其餘券商（`康和證券` 這種），只給粗略數字；
  `meta`：n_reports/n_brokers/n_stocks/date_max（頁面資料涵蓋到哪天）。

## 定位：跟我們自己的 base_rate/thesis_check 是兩件事

`analyst_track_record`（base_rate.py）量的是**公司**的 EPS 意外方向（分析師共識對
這家公司是偏保守還是偏樂觀）；這支量的是**券商本身**歷史上喊「買進」的目標價，
抱一年達成率高不高——兩個維度不重疊，都要看。

## ⚠️ 這是老墨自己的方法論，不是我們驗證出來的

頁面上寫「不是買賣信號、也不是任何操作依據」。他的「達成率」怎麼定義（`rate_close`
是什麼時間窗、`ev` 期望值怎麼算）我們沒有查證方法論本身，只是**引用他的結論**，跟
`broker_credibility.py` 對中信/高盛/統一的處理是同一個保守原則：標明來源、
讓讀的人自己折價，不要包裝成我們自己驗證過的東西。

用法:
    python mofi_broker_scorecard.py fetch     # 抓最新頁面，存快取
    python mofi_broker_scorecard.py list      # 列出快取裡的 26 家排名
"""
import io
import os
import re
import sys
import json
import argparse
import datetime as dt

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE_URL = "https://mofiinvestment.com/AI-RESEARCH/broker-report.html"
STORE = "state/mofi_broker_scorecard.json"

# 我們解析出來的券商名稱（advisor_reports.json 實際出現過的寫法）→ 計分卡的官方名稱。
# 同 broker_credibility.py 的規則：只放**不會撞名**的別名，中文優先，不要用短縮寫。
ALIASES = {
    "中國信託綜合證券": ("中信投顧", "中信", "中國信託", "ctbc"),
    "統一證券": ("統一投顧", "統一"),
    "Goldman Sachs": ("高盛", "goldman"),
    "宏遠證券": ("宏遠投顧", "宏遠"),
    "第一金證券": ("第一金投顧", "第一金"),
    "摩根士丹利證券": ("摩根士丹利", "morgan stanley"),
    "摩根大通證券": ("摩根大通", "jp morgan", "jpmorgan"),
    "花旗美邦證券": ("花旗",),
    "元富證券投顧": ("元富",),
    "康和證券": ("康和投顧", "康和"),
    "福邦投顧": ("福邦證券", "福邦"),
}


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return d


def _save(p, o):
    os.makedirs("state", exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def fetch():
    import requests
    r = requests.get(SOURCE_URL, timeout=20)
    r.raise_for_status()
    # requests 對沒宣告 charset 的回應會退回 ISO-8859-1猜測，.text 直接用會把 UTF-8
    # 位元組拆散重編、變亂碼（中文名稱裡每個字被拆成兩三個不相干的碼位）。
    # 用 .content 自己按 UTF-8 解碼，不要相信 requests 猜的編碼。
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                  r.content.decode("utf-8"), re.S)
    if not m:
        raise RuntimeError("頁面結構變了，找不到 id=data 的內嵌 JSON——先手動確認頁面還在")
    d = json.loads(m.group(1))
    out = {"fetched_at": dt.date.today().isoformat(), "source": SOURCE_URL,
           "meta": d.get("meta"), "scorecard": d.get("scorecard"), "reference": d.get("reference")}
    _save(STORE, out)
    print(f"✅ 已存 {STORE}：{len(out['scorecard'])} 家主力券商、"
          f"{len(out.get('reference') or [])} 家次要券商（資料到 {out['meta'].get('date_max')}）")
    return out


def _tier(rank, total):
    if rank <= total * 0.25:
        return "前段班"
    if rank >= total * 0.75:
        return "後段班"
    return "中段班"


def note_for(broker):
    """回這家券商的計分卡摘要 dict，查不到回 None（找不到不等於它不可信，只是沒進主榜）。"""
    b = str(broker or "").strip()
    if not b:
        return None
    store = _load(STORE, {})
    cards = store.get("scorecard") or []
    if not cards:
        return None
    b_low = b.lower()

    def _match(official):
        if official == b:
            return True
        for al in ALIASES.get(official, ()):
            if al.lower() in b_low or b_low in al.lower():
                return True
        return False

    for row in cards:
        if _match(row["broker"]):
            total = len(cards)
            return {
                "broker": row["broker"], "matched_from": b,
                "rank": row["rank"], "total": total, "tier": _tier(row["rank"], total),
                "score": row["cred_score"], "rate_close": row["rate_close"],
                "days_close": row["days_close"], "mdd_close": row["mdd_close"],
                "ev": row["ev"], "n": row["n"], "lights": row.get("lights", {}),
                "source": SOURCE_URL, "as_of": store.get("meta", {}).get("date_max"),
            }
    # 樣本數不足以進主榜的小券商，只給粗略數字
    for row in store.get("reference") or []:
        if _match(row["broker"]):
            return {"broker": row["broker"], "matched_from": b, "rank": None, "total": None,
                    "tier": "樣本太少（未進主榜）", "rate_close": row.get("rate_close"),
                    "n": row.get("n"), "source": SOURCE_URL, "as_of": store.get("meta", {}).get("date_max")}
    return None


def line_for(broker):
    """一行文字版，給孔明材料／仲達材料用。查不到回空字串。"""
    n = note_for(broker)
    if not n:
        return ""
    if n.get("rank") is None:
        return (f"（老墨計分卡：{n['broker']} 樣本數太少未進主榜，n={n.get('n','?')}，"
               f"達成率{n['rate_close']*100:.0f}%僅供參考｜來源 {n['source']}｜{n['as_of']} 資料）")
    return (f"（老墨計分卡：{n['broker']} {n['total']}家中排第{n['rank']}（{n['tier']}），"
           f"可信度分數{n['score']:.0f}、達成率{n['rate_close']*100:.0f}%、"
           f"等待{n['days_close']:.0f}天、套牢{n['mdd_close']*100:.0f}%、期望值{n['ev']*100:+.0f}%"
           f"（n={n['n']}）｜來源 {n['source']}｜{n['as_of']} 資料，非我們驗證）")


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "list"], nargs="?", default="list")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch()
        return
    store = _load(STORE, {})
    cards = store.get("scorecard") or []
    if not cards:
        print("尚無快取，先跑：python mofi_broker_scorecard.py fetch")
        return
    print(f"資料到 {store.get('meta', {}).get('date_max')}（{store.get('fetched_at')} 抓的），"
          f"{len(cards)} 家主力券商：\n")
    for row in sorted(cards, key=lambda x: x["rank"]):
        print(f"  {row['rank']:3d}  {row['broker']:16s} 分數{row['cred_score']:5.1f}  "
              f"達成率{row['rate_close']*100:5.1f}%  等待{row['days_close']:5.1f}天  "
              f"套牢{row['mdd_close']*100:6.1f}%  期望值{row['ev']*100:6.1f}%  n={row['n']}")


if __name__ == "__main__":
    _main()
