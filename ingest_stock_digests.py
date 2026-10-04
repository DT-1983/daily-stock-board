# -*- coding: utf-8 -*-
"""把 Drive「個股整合報告」裡 Ari（GPT）做好的券商／研究機構「中文重點」HTML 讀進軍師資料庫（2026-10-04，Leo 要求）。
只讀成品 HTML，不碰原文、不抓取、不產生報告（分工：Ari 抓與寫；這支只接下游）。
每份只收「一句結論＋關鍵數字」進 state/industry_notes.json（私人、已 gitignore）；完整頁面路徑留在 report_path。
冪等：同檔同主題同「原報告日」重跑只會蓋掉那一筆。取不到的欄位留空，不補、不猜。
用法：python ingest_stock_digests.py                    # 乾跑，只列會寫什麼
      python ingest_stock_digests.py --apply            # 寫入 industry_notes（之後請跑 advisor_db_export.py）
      python ingest_stock_digests.py --apply --push     # 另外把「新進來的」推到私人 Discord 與 Telegram
推播只走私人頻道（Morningstar 是付費內容，不進公開戰情頻道）；已推過的用 state/stock_digest_pushed.json 去重，重跑不重推。"""
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
    if fv:
        bits.append(f"{fv} {m[fv][0]}")
    for lab, key in (("評等", "Morningstar 評等"), ("護城河", "經濟護城河"), ("不確定性", "估值不確定性")):
        if key in m:
            bits.append(f"{lab} {m[key][0]}")
    px = m.get("報告所列收盤價")
    if px:
        bits.append(f"報告收盤價 {px[0]}（{px[1]}）")
    ratio = m.get("價格／公允價值")
    if ratio:
        bits.append(f"價格／公允價值 {ratio[0]}")
    s = d["head"] or d["subtitle"]
    return (s + "｜" if s else "") + "、".join(bits)


def _push(new):
    """new：這次新進來（沒推過）的清單。Discord private＋Telegram 各一則；兩邊分開記回執，一邊失敗下次只補那邊。"""
    from html import escape
    try:
        done = json.load(io.open(PUSHED, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        done = {}
    lines_d, lines_t = [], []
    for d in new:
        m = d["metrics"]
        fv = _fv_key(m)
        fvs = f"公允價值 {m[fv][0]}" if fv else "公允價值 —"
        star = m.get("Morningstar 評等", ("—",))[0]
        ratio = m.get("價格／公允價值", ("—",))[0]
        d_ = d["date"][5:].replace("-", "/")
        one = d["head"] or d["subtitle"]
        lines_d.append(f'**{d["ticker"]} {d["name"]}**　{fvs}｜{star}｜價格／公允價值 {ratio}　-# 原報告 {d_}\n-# {one}')
        lines_t.append(f'<b>{escape(d["ticker"])} {escape(d["name"])}</b>　{escape(fvs)}｜{escape(star)}｜價格／公允價值 {escape(ratio)}（原報告 {d_}）\n{escape(one)}')
    head = f"📑 Morningstar 新研報已進軍師資料庫（{len(new)} 份）"
    keys = [f'{d["ticker"]}|{d["source"]}|{d["date"]}' for d in new]
    if not all(done.get(k, {}).get("discord") for k in keys):
        from notify_discord import send_discord
        ok = send_discord("private", head + "\n" + "\n".join(lines_d)
                          + "\n-# 來源：Ari 整理的中文重點；公允價值不是 12 個月目標價；描述性資訊、不是買賣訊號", persona="戰情室")
        for k in keys:
            done.setdefault(k, {})["discord"] = bool(ok)
        print("Discord private：", "成功" if ok else "失敗")
    if not all(done.get(k, {}).get("telegram") for k in keys):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import notify_tg
        rc = notify_tg.send(head + "\n\n" + "\n\n".join(lines_t) + "\n\n公允價值不是 12 個月目標價；描述性資訊、不是買賣訊號")
        for k in keys:
            done.setdefault(k, {})["telegram"] = (rc == 0)
        print("Telegram：", "成功" if rc == 0 else "失敗")
    os.makedirs("state", exist_ok=True)
    io.open(PUSHED, "w", encoding="utf-8").write(json.dumps(done, ensure_ascii=False, indent=2))


def main(apply=False, push=False):
    rows = []
    for sub, pat, src in PATTERNS:
        for f in sorted(glob.glob(os.path.join(BASE, sub, pat))):
            d = parse(f)
            d["source"] = src
            rows.append(d)
    import industry_notes
    try:
        pushed = json.load(io.open(PUSHED, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        pushed = {}
    new = []
    for d in rows:
        if not d["ticker"] or not d["date"] or (not d["head"] and not d["subtitle"]):
            print(f"⚠️ 略過（欄位不全）：{os.path.basename(d['path'])}  代號={d['ticker']!r} 日期={d['date']!r}")
            continue
        s = summary(d)
        print(f"{d['ticker']:6s} {d['name']:10s} {d['date']}  {s}")
        if apply:
            industry_notes.record(d["ticker"], d["name"], f"{d['source']} 個股報告", s,
                                  source=f"{d['source']} 研報（Ari 整理、原報告 {d['date']}）",
                                  report_path=d["path"], date=d["date"])
        k = f'{d["ticker"]}|{d["source"]}|{d["date"]}'
        if not (pushed.get(k, {}).get("discord") and pushed.get(k, {}).get("telegram")):
            new.append(d)
    print(f"\n{'已寫入' if apply else '乾跑（未寫入）'}：{len(rows)} 份；尚未推播：{len(new)} 份")
    if apply and push and new:
        _push(new)
    return rows


if __name__ == "__main__":
    main("--apply" in sys.argv, "--push" in sys.argv)
