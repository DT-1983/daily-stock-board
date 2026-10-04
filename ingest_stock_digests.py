# -*- coding: utf-8 -*-
"""把 Drive「個股整合報告」裡 Ari（GPT）做好的券商／研究機構「中文重點」HTML 讀進軍師資料庫（2026-10-04，Leo 要求）。
只讀成品 HTML，不碰原文、不抓取、不產生報告（分工：Ari 抓與寫；這支只接下游）。

🔗 跟既有投顧報告管線「同一條路」（Leo：「我們其他掃描報告也有，整合在一起」）：
  · board_analyze_daily.cmd（平日 06:00）緊接在 `advisor_reports.py parse` 後面跑本檔 --apply
    ＝寫進軍師資料庫（industry_notes）＋推 Telegram（跟 advisor_reports 解析後推 Telegram 一樣）。
  · daily_warroom 08:45 私人密報的「新收到的研報」區塊用本檔 new_today_lines()，發送成功後 mark_discord()
    ＝跟「新收到的投顧報告」同一則密報、同一套「報過才標記、失敗隔天補」。
  · 兩個目的地各自記回執在 state/stock_digest_pushed.json（已 gitignore），重跑不重推。
只走私人頻道（Morningstar 是付費內容，不進公開戰情頻道）。
每份只收「一句結論＋關鍵數字」進 state/industry_notes.json（私人、已 gitignore）；完整頁面路徑留在 report_path。
冪等：同檔同主題同「原報告日」重跑只會蓋掉那一筆。取不到的欄位留空，不補、不猜。
用法：python ingest_stock_digests.py                 # 乾跑
      python ingest_stock_digests.py --apply         # 入庫＋推 Telegram（排程用）
      python ingest_stock_digests.py --apply --no-tg # 只入庫"""
import glob
import html
import io
import json
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

BASE = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment\個股整合報告"
PATTERNS = [("美股", "*_Morningstar報告_中文重點.html", "Morningstar")]
PUSHED = "state/stock_digest_pushed.json"


def _txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse(path):
    t = io.open(path, encoding="utf-8").read()
    tags = [_txt(x) for x in re.findall(r'<span class="tag">(.*?)</span>', t, re.S)]
    sub = _txt((re.search(r'<p class="subtitle">(.*?)</p>', t, re.S) or [None, ""])[1])
    h1 = _txt((re.search(r"<h1>(.*?)</h1>", t, re.S) or [None, ""])[1])
    lead = re.search(r'<div class="lead">.*?<strong>(.*?)</strong>', t, re.S)
    head = _txt(lead.group(1)) if lead else ""
    mets = {}
    for m in re.finditer(r'<div class="label">(.*?)</div><div class="value[^"]*">(.*?)</div>(?:<div class="small">(.*?)</div>)?', t, re.S):
        mets[_txt(m.group(1))] = (_txt(m.group(2)), _txt(m.group(3) or ""))
    date = None
    for g in tags:
        d = re.search(r"原報告\s*(\d{4})/(\d{2})/(\d{2})", g)
        if d:
            date = "-".join(d.groups())
    tk = (tags[0].split("·")[0].strip() if tags else "")
    name = h1.split(tk)[0].strip() if tk and tk in h1 else h1
    return {"ticker": tk, "name": name, "date": date, "subtitle": sub, "head": head, "metrics": mets, "path": path}


def _fv_key(m):
    """公允價值那一欄（BRK.B 的標籤是「B 股公允價值」，所以用包含比對；排除「上修／下修」「價格／公允價值」這類欄）。"""
    k = [x for x in m if "公允價值" in x and "修" not in x and "／" not in x]
    return k[0] if k else None


def summary(d):
    m = d["metrics"]
    bits = []
    fv = _fv_key(m)
    px = m.get("報告所列收盤價")
    if fv:
        t = f"目標價 {m[fv][0]}（公允價值，無期限）"
        try:
            f_ = float(re.search(r"[\d,]+(?:\.\d+)?", m[fv][0]).group().replace(",", ""))
            c_ = float(re.search(r"[\d,]+(?:\.\d+)?", px[0]).group().replace(",", ""))
            t += f"｜報告收盤 {px[0]}，空間 {(f_ / c_ - 1) * 100:+.0f}%"
        except (AttributeError, TypeError, ValueError, IndexError):
            if px:
                t += f"｜報告收盤 {px[0]}"
        bits.append(t)
    for lab, key in (("評等", "Morningstar 評等"), ("護城河", "經濟護城河"), ("不確定性", "估值不確定性")):
        if key in m:
            bits.append(f"{lab} {m[key][0]}")
    s = d["head"] or d["subtitle"]
    return (s + "｜" if s else "") + "、".join(bits)


def _now_price(ticker, fv_text):
    """市場現價（yfinance 最近一個收盤）與「現價／公允價值」。取不到就明講，不留空也不猜。
    公允價值文字形如「$254」；解析不出數字就只顯示現價。"""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker.replace(".", "-")).history(period="7d")["Close"].dropna()
        px, day = float(h.iloc[-1]), str(h.index[-1])[5:10].replace("-", "/")
    except Exception as e:                                   # noqa: BLE001
        print(f"[digest] {ticker} 現價取不到：{str(e)[:60]}")
        return "現價這次取不到"
    m = re.search(r"[\d,]+(?:\.\d+)?", fv_text or "")
    r = f"｜預期報酬 {(float(m.group().replace(',', '')) / px - 1) * 100:+.0f}%" if m else ""
    return f"現價 ${px:,.2f}（{day} 收）{r}"


def _key(d):
    return f'{d["ticker"]}|{d["source"]}|{d["date"]}'


def _load_pushed():
    try:
        return json.load(io.open(PUSHED, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}


def _save_pushed(done):
    os.makedirs("state", exist_ok=True)
    io.open(PUSHED, "w", encoding="utf-8").write(json.dumps(done, ensure_ascii=False, indent=2))


def scan():
    """讀資料夾裡所有符合的成品頁，回欄位齊全的 list（欄位不全的印警告略過，不補不猜）。"""
    rows = []
    for sub, pat, src in PATTERNS:
        for f in sorted(glob.glob(os.path.join(BASE, sub, pat))):
            d = parse(f)
            d["source"] = src
            if not d["ticker"] or not d["date"] or (not d["head"] and not d["subtitle"]):
                print(f"⚠️ 略過（欄位不全）：{os.path.basename(f)}  代號={d['ticker']!r} 日期={d['date']!r}")
                continue
            rows.append(d)
    return rows


def _one(d, rich=True):
    """回 (標題行, 現價行, 結論) 的文字。"""
    m = d["metrics"]
    fv = _fv_key(m)
    # 用我們系統慣用的「目標價」＋「預期報酬 %（目標價÷現價−1）」呈現（Leo 要求）。
    # ⚠️ Morningstar 的數字是「公允價值」，沒有 12 個月期限，所以括號標明，不能當成 12 個月目標價。
    fvs = f"目標價 {m[fv][0]}（公允價值，無期限）" if fv else "目標價 —"
    star = m.get("Morningstar 評等", ("—",))[0]
    now = _now_price(d["ticker"], m[fv][0] if fv else "")
    return (f'{d["ticker"]} {d["name"]}', f"{fvs}｜{star}", now,
            d["head"] or d["subtitle"], d["date"][5:].replace("-", "/"))


def pending(channel):
    """還沒推到 channel（'discord' 或 'telegram'）的 digest。"""
    done = _load_pushed()
    return [d for d in scan() if not done.get(_key(d), {}).get(channel)]


def mark(channel, rows, ok=True):
    done = _load_pushed()
    for d in rows:
        done.setdefault(_key(d), {})[channel] = bool(ok)
    _save_pushed(done)


def new_today_lines(date=None):
    """給 daily_warroom 私人密報用（跟 advisor_reports.new_today_lines 同形狀）：還沒報過 Discord 的研報，一檔兩行。"""
    fresh = sorted(pending("discord"), key=lambda d: (d["ticker"], d["date"]))
    if not fresh:
        return []
    out = [f"・📑 新收到的研報（{fresh[0]['source']}，{len(fresh)} 份；公允價值不是 12 個月目標價）："]
    for d in fresh[:10]:
        t, a, b, c, dd = _one(d)
        out.append(f"**{t}**　{a}")
        out.append(f"-# 　{b}　原報告 {dd}")
        out.append(f"-# 　{c[:70]}")
    if len(fresh) > 10:
        out.append(f"-# 　…另有 {len(fresh) - 10} 份，obis 個股整合報告資料夾可查")
    return out


def mark_discord():
    """密報發送成功後呼叫：把目前待報的標成已報（跟 advisor_reports.mark_announced 一樣的時機）。"""
    mark("discord", pending("discord"))


def _push_telegram(new):
    from html import escape
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import notify_tg
    parts = []
    for d in new:
        t, a, b, c, dd = _one(d)
        parts.append(f"<b>{escape(t)}</b>　{escape(a)}\n{escape(b)}（原報告 {dd}）\n{escape(c)}")
    rc = notify_tg.send(f"📑 {new[0]['source']} 新研報已進軍師資料庫（{len(new)} 份）\n\n" + "\n\n".join(parts)
                        + "\n\n公允價值不是 12 個月目標價；描述性資訊、不是買賣訊號")
    mark("telegram", new, rc == 0)
    print("Telegram：", "成功" if rc == 0 else "失敗")


def main(apply=False, tg=True):
    import industry_notes
    rows = scan()
    for d in rows:
        s = summary(d)
        print(f"{d['ticker']:6s} {d['name']:10s} {d['date']}  {s}")
        if apply:
            industry_notes.record(d["ticker"], d["name"], f"{d['source']} 個股報告", s,
                                  source=f"{d['source']} 研報（Ari 整理、原報告 {d['date']}）",
                                  report_path=d["path"], date=d["date"])
    new_tg = pending("telegram")
    print(f"\n{'已入庫' if apply else '乾跑（未寫入）'}：{len(rows)} 份；Telegram 待推 {len(new_tg)} 份、Discord 待報 {len(pending('discord'))} 份（密報會帶）")
    if apply and tg and new_tg:
        _push_telegram(new_tg)
    return rows


if __name__ == "__main__":
    main("--apply" in sys.argv, "--no-tg" not in sys.argv)
