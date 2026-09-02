"""客觀守備清單篩選器：市值 + 成長 + 進場（法人/動能），每鏈取 top N。不含 CANSLIM。

美股候選池 = 各鏈 ETF 成分股（top holdings 合併）
台股候選池 = 各鏈產業鏈龍頭池
三因子各自排名正規化加總 → 每鏈取最強 N 檔
輸出:screen_result.json
用法:python screen.py
"""
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
import requests
import yfinance as yf
import tw_symbol

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 印 emoji 會炸

FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOPN = 8

US_ETFS = {
    "AI 伺服器": ["SMH", "SOXX", "DTCR", "SKYY"],
    "矽光子/光通訊": ["XSD", "IGN"],
    "低軌衛星": ["UFO", "ARKX", "ROKT"],
    "太陽能": ["TAN", "ICLN"],
    "Bitcoin→AI 機房": ["WGMI", "MNRS"],
    "AI 電力/核能": ["URA", "NLR", "GRID"],
    "機器人": ["BOTZ", "KOID", "ROBO"],
}
# 第 8 條鏈（2026-08-05）：玻璃基板/TGV。題材驗證期、無對應 ETF → 手選池。
# 第 9 條鏈（2026-08-17）：關鍵金屬/原物料。AI資料中心銅銀鈾需求是「AI基建吃資源」
# 故事，沒有單一ETF覆蓋這個組合 → 手選池（用戶明確要求只放原物料，不放記憶體）。
# 跟AI電力/核能鏈的鈾曝險(US_ETFS用URA)有重疊是刻意的，鈾本來就橫跨「發電」跟
# 「關鍵金屬」兩個敘事。台股沒有夠格的礦業/原物料標的可放，這條鏈只有美股池。
# 逐鏈獨立取 top N，所以不會跟 AI 伺服器鏈的巨頭比。賽馬模擬倉明確排除（paper_portfolio）。
US_MANUAL = {
    "玻璃基板/TGV": ["GLW", "INTC", "AMAT", "ONTO", "CAMT", "KLIC"],
    "關鍵金屬/原物料": ["FCX", "SCCO", "CCJ", "PAAS"],
    # 第 10、11 條鏈（2026-09-03，老墨三段時程報告行動 2）。美股沒有剛好對應的 ETF，手選：
    # 材料＝MU（HBM/DRAM）；電源散熱＝VRT（機櫃電源/液冷）、ETN（800V 基礎設施）、
    # MPWR（電源 IC）、NVTS（NVIDIA 800V 選用的 GaN/SiC）。
    "AI 材料/被動元件": ["MU"],
    "AI 電源/散熱": ["VRT", "ETN", "MPWR", "NVTS"],
}
TW_POOL = {
    "AI 伺服器": ["2330", "2317", "2382", "6669", "3231", "3017", "3324", "2376",
                "2356", "2308", "2368", "3037", "8046", "3533"],
    "矽光子/光通訊": ["4979", "3450", "4908", "3105", "3081", "3363", "3163", "2345",
                    "3008", "6442"],   # 2026-09-03 老墨 2028+ CPO/光學路線：大立光、光聖（上詮已在）
    "機器人": ["2049", "1536", "6188", "2359", "4576", "1504", "3023", "1597", "4540"],
    "低軌衛星": ["3491", "6285", "2314", "3105", "2454", "6271"],
    "太陽能": ["6443", "5483", "6182", "3576"],
    "AI 電力/核能": ["1513", "1503", "1504", "1519", "1605"],
    # 2026-09-03 行動 3：補面板廠轉玻璃芯路線（TSMC CoPoS 與群創合作；友達、TPK 同一條路）。
    # 群創 3481、群翊 6664 本來就在。山太士查無代號，Leo 給了再補。
    "玻璃基板/TGV": ["3037", "8046", "3189", "3149", "8027", "6664", "1595",
                   "3055", "3481", "4768", "3580", "8064", "2409", "3673",
                   "3595"],   # 山太士 3595.TWO（Leo 9/3 補代號）
    # 第 10 條鏈（2026-09-03）：AI 材料/被動元件——老墨三段時程「2026-27 供給瓶頸」的主體。
    # DRAM 南亞科/華邦電；CCL 台光電/聯茂/台燿（DIGITIMES、TrendForce 點名的三雄）；
    # 銅箔 金居；玻纖布 富喬（M9 CCL 真正瓶頸在玻纖布）；MLCC 國巨/華新科；功率 強茂；
    # 矽片再生 昇陽半（老墨 2027-28 點名，性質是材料）。
    "AI 材料/被動元件": ["2408", "2344", "2383", "6213", "6274", "8358", "1815",
                     "2327", "2492", "2481", "8028"],
    # 第 11 條鏈（2026-09-03）：AI 電源/散熱——800V HVDC（3Q26 首批出貨）＋微流道散熱。
    # 台達電/光寶科（TrendForce 點名 HVDC 供應商）、貿聯（連接/線束）、健策（微流道蓋板）、
    # 奇鋐/雙鴻（液冷，也在 AI 伺服器鏈；鏈是題材分類，重疊是刻意的，見 screen.py 檔頭）。
    "AI 電源/散熱": ["2308", "2301", "3665", "3653", "3017", "3324"],
}
NAME = {}  # code → name 快取


def us_pool():
    pool = {}
    for chain, etfs in US_ETFS.items():
        s = set()
        for e in etfs:
            try:
                df = yf.Ticker(e).funds_data.top_holdings
                for sym in df.index:
                    if isinstance(sym, str) and sym.replace("-", "").isalpha() and len(sym) <= 5:
                        s.add(sym)
                        NAME[sym] = df.loc[sym].get("Name", sym)
            except Exception:
                pass
            time.sleep(0.5)
        pool[chain] = sorted(s)
    for chain, syms in US_MANUAL.items():   # 無 ETF 的鏈用手選池
        pool[chain] = sorted(set(pool.get(chain, [])) | set(syms))
    return pool


def obv_strength(closes, vols, n=20):
    """OBV(能量潮)近 n 日淨流入，相對成交量正規化（size-neutral）。
    >0 = 資金淨流入(量增買進)，<0 = 淨流出(出貨)。"""
    if len(closes) < n + 1:
        return 0.0
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - vols[i])
        else:
            obv.append(obv[-1])
    avg = sum(vols[-n:]) / n
    return (obv[-1] - obv[-1 - n]) / (avg * n) if avg else 0.0


def us_metrics(tk):
    try:
        t = yf.Ticker(tk)
        info = t.info
        mc = info.get("marketCap") or 0
        g = info.get("revenueGrowth") or 0
        NAME.setdefault(tk, info.get("shortName", tk))
        h = t.history(period="3mo")
        if len(h) < 21:
            return {"mktcap": mc, "growth": g, "inflow": 0}
        # 進場 = OBV 量能流入（取代純漲幅，看資金是否真的在買）
        inflow = obv_strength(h["Close"].tolist(), h["Volume"].tolist())
        return {"mktcap": mc, "growth": g, "inflow": inflow}
    except Exception:
        return None


def fm(ds, sid, start):
    try:
        return requests.get(FINMIND, params={"dataset": ds, "data_id": sid,
                            "start_date": start}, timeout=15).json().get("data", [])
    except Exception:
        return []


def tw_metrics(code):
    try:
        # 2026-08-31 修：原本硬掛 .TW，上櫃股（如 3105 穩懋）的 marketCap 回 None，
        # 被下面的 except 吞掉變 mc=0。而市值是 rank_score 三因子之一，等於這些股票
        # 的市值分數永遠墊底——不是它們小，是後綴給錯抓不到。
        info = yf.Ticker(tw_symbol.resolve(code)).info
        mc = info.get("marketCap") or 0
        NAME.setdefault(code, info.get("shortName", code))
    except Exception:
        mc = 0
    rev = fm("TaiwanStockMonthRevenue", code, (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    g = 0
    if len(rev) >= 13 and rev[-13].get("revenue"):
        g = rev[-1]["revenue"] / rev[-13]["revenue"] - 1
    inst = fm("TaiwanStockInstitutionalInvestorsBuySell", code,
              (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    # 法人(外資+投信)淨買超股數
    fnet = sum(d["buy"] - d["sell"] for d in inst
               if d["name"] in ("Foreign_Investor", "Investment_Trust"))
    # 進場 = 法人買超 ÷ 近20日均量（相對值，小型股才不被大型股輾壓）
    price = fm("TaiwanStockPrice", code, (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"))
    avgvol = sum(d["Trading_Volume"] for d in price[-20:]) / 20 if len(price) >= 20 else 0
    inflow = fnet / (avgvol * 20) if avgvol else 0
    return {"mktcap": mc, "growth": g, "inflow": inflow}


def composite(metrics):
    """三因子各自排名正規化(0-1)加總。metrics: {code: {mktcap,growth,inflow}}"""
    scores = {k: 0.0 for k in metrics}
    for key in ("mktcap", "growth", "inflow"):
        vals = sorted(metrics.items(), key=lambda kv: kv[1].get(key, 0) or 0)
        n = len(vals)
        for rank, (k, _) in enumerate(vals):
            scores[k] += rank / (n - 1) if n > 1 else 0.5
    return scores


def screen(pool, metric_fn, label):
    result = {}
    for chain, codes in pool.items():
        print(f"[{label}] {chain}: {len(codes)} 候選...")
        metrics = {}
        for c in codes:
            m = metric_fn(c)
            if m:
                metrics[c] = m
            time.sleep(0.3)
        if not metrics:
            result[chain] = []
            continue
        sc = composite(metrics)
        top = sorted(sc, key=lambda k: sc[k], reverse=True)[:TOPN]
        result[chain] = [{"code": c, "name": NAME.get(c, c), **metrics[c],
                          "score": round(sc[c], 2)} for c in top]
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "tw", "both"], default="both",
                    help="2026-08-10：美股/台股各自收盤時間、資料源不同，"
                         "拆成兩個獨立 workflow 互不拖累失敗；預設 both 保留給手動整份重跑用")
    ap.add_argument("-o", "--output", default="screen_result.json",
                    help="拆開跑時通常指定各自的暫存檔（如 screen_us.json），"
                         "由外層 merge 成正式的 screen_result.json，避免兩個 job 互相覆蓋對方市場的資料")
    args = ap.parse_args()

    us, tw = {}, {}
    if args.market in ("us", "both"):
        print("=== 美股候選池(ETF 成分股)===")
        upool = us_pool()
        for c, l in upool.items():
            print(f"  {c}: {len(l)} 檔")
        us = screen(upool, us_metrics, "US")
    if args.market in ("tw", "both"):
        tw = screen(TW_POOL, tw_metrics, "TW")

    out = {"date": datetime.now().strftime("%Y-%m-%d")}
    if args.market == "both":
        out["us"], out["tw"] = us, tw
    elif args.market == "us":
        out["us"] = us
    else:
        out["tw"] = tw
    json.dump(out, open(args.output, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 印出守備清單
    print("\n===== 篩選結果 =====")
    for mkt, data in [("美股", us), ("台股", tw)]:
        if not data:
            continue
        print(f"\n【{mkt}】")
        for chain, lst in data.items():
            print(f"  {chain}: " + ", ".join(f"{x['code']}({x['name'][:6]})" for x in lst))
    print(f"\n✅ → {args.output}")


if __name__ == "__main__":
    main()
