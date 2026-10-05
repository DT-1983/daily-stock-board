# -*- coding: utf-8 -*-
"""PCB／載板／CCL 與大封測 深入研究 HTML 報告（2026-10-05，Leo：「做成 html 吧」）。

資料：量化對照來自 pcb_pkg_screen.py 的結果（state/pcb_pkg_screen.json：價格 yfinance、月營收與財報 FinMind、共識 EPS yfinance）；
質化展望來自財經媒體整理（沒有公司官方簡報／公開資訊觀測站原文），並標明管理層說法（M）與法人預估（A）。
只描述，不是買賣訊號；共識 EPS 與目標價是賣方預估，歷史上偏樂觀。內容為公開媒體資訊整理，非機密，這支腳本不進 .gitignore。
用法: python pcb_pkg_report.py
"""
import io
import json
import os
import re
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                  # noqa: E402

TITLE = "PCB／載板與大封測深入研究"
CHECK_DATE = "2026-10-05"
GRP_COLOR = {"載板": "var(--warn)", "PCB": "var(--accent)", "CCL": "#F472B6", "封測": "var(--up)", "設備": "#C084FC"}
GRP_ORDER = ["載板", "PCB", "CCL", "封測", "設備"]
SHORT = {"臻鼎-KY": "臻鼎", "日月光投控": "日月光", "京元電子": "京元", "定穎投控": "定穎"}

CSS = """
.rpt-sec{margin:24px 0}
.rpt-sec h2{font-size:16px;font-weight:800;color:#93C5FD;margin-bottom:10px}
.rpt-sec h3{font-size:13.5px;font-weight:800;color:var(--ink);margin:16px 0 6px}
.rpt-sec p{font-size:13.5px;line-height:1.9;color:var(--ink);margin:0 0 10px}
.rpt-sec ul{margin:0 0 10px 18px;font-size:13.5px;line-height:1.85;color:var(--ink)}
.rpt-sec li{margin-bottom:8px}
.rpt-sec b{color:#F5B841}
.rpt-tldr{background:var(--card);border:1px solid var(--accent);border-radius:12px;padding:16px 18px;margin:18px 0 26px}
.rpt-tldr .lbl{font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--accent);margin-bottom:8px}
.rpt-tldr ol{margin:0 0 0 18px;padding:0;font-size:13.5px;line-height:1.9;color:var(--ink)}
.rpt-tldr li{margin-bottom:6px}.rpt-tldr b{color:#F5B841}
.rpt-note{font-size:12px;color:var(--dim);border-top:1px solid var(--line);padding-top:10px;margin-top:22px;line-height:1.7}
.rpt-chart{margin:12px 0 6px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 12px 8px}
.rpt-chart svg{width:100%;height:auto;display:block}
.rpt-chart .cap{font-size:11.5px;color:var(--dim);margin-top:6px;line-height:1.6}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin:6px 2px 0;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
.tbl-wrap{overflow-x:auto;margin:10px 0;border:1px solid var(--line);border-radius:10px}
table.t{border-collapse:collapse;width:100%;font-size:12.5px;min-width:1250px}
table.t th{color:var(--dim);font-weight:600;text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap;background:var(--surface);position:sticky;top:0}
table.t td{padding:6px 9px;border-bottom:1px solid var(--line2);color:var(--ink);white-space:nowrap}
table.t td.n{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums;text-align:right}
table.t td.up{color:var(--up)}table.t td.dn{color:var(--down)}table.t td.w{color:var(--warn)}
table.t tr.gsep td{border-top:2px solid var(--line)}
.w{color:var(--warn)}
.chip{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:9px;color:#06101c;font-weight:700}
.stk-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.stk-card .h{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin-bottom:6px}
.stk-card b{font-size:14.5px;color:#93C5FD}
.stk-card .tag{font-size:11px;color:var(--dim);background:var(--card);padding:2px 8px;border-radius:6px}
.stk-card .d{font-size:12.5px;line-height:1.8;color:var(--muted);margin-top:4px}
.stk-card .d b{font-size:12.5px;color:var(--ink)}
.stk-card .warn{color:var(--warn)}
details.sec{margin:10px 0}
details.sec summary{cursor:pointer;font-size:13.5px;font-weight:700;color:var(--ink);padding:8px 2px}
.kv2{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:10px 0}
.kv2 .c{background:var(--card);border-radius:8px;padding:9px 11px}
.kv2 .k{font-size:10.5px;color:var(--dim)}.kv2 .v{font-size:13px;font-weight:700;color:var(--ink);margin-top:2px}
"""

PCB_CARDS = [
    ("2368", "金像電", "伺服器 PCB（AI 板、泰國擴產）",
     "管理層：下半年伺服器與網通較 Q2 成長；伺服器占 Q2 營收 78%；資本支出已公告約 190 億；泰國廠成長 5～6 倍、稼動率滿載。法人（高盛）：AI 占比 2025 年 40% → 2026 年 70%。中壢新廠 138 億。",
     "AI 占比有「4～5 成（上半年實績）」與「70%（高盛全年預估）」兩種口徑；資本支出有 72／104／170／190 億多個版本；ASIC 混壓良率 6 月曾引發股價修正逾 50%。"),
    ("3044", "健鼎", "多層板（伺服器＋記憶體）",
     "管理層原話未讀到；法人預估 Q3 季增約 15%、湖北四廠下半年完成、越南廠 Q4 試產。伺服器 42.2% ＋ 記憶體 23.1% ＝ 65%。",
     "記憶體景氣是主要驅動；GPU 板占比查不到。"),
    ("2383", "台光電", "CCL（高階銅箔基板）",
     "3 月法說（管理層）：2026 資本支出 150～230 億、M8 為主、M9 下半年出貨 2027 放量、1.6T 交換器相關產品 Q1 起出貨；全產全銷延續一年；2027 年底產能 945 萬張／月。Q2 毛利率 33.9%、EPS 27.55。",
     "8～9 月最新法說內容沒找到，法說日有 7/29、8/21、9/4 三種說法；EPS 92.6（2026）／187（2027）是法人預估。"),
    ("6274", "台燿", "CCL（高頻高速）",
     "管理層：新增月產能 195 萬張（中山 120 萬、泰國二期 75 萬）、規劃 100 億可轉債；泰國 7 月貢獻、Q4 目標滿載；低階產品漲幅較大。產能 2026／27／28 為 260／380／530 萬張。M7／M8 以上占 39%。",
     "Q2 營收以 143 億為準（FinMind 毛利率 29.7%、EPS 8.02 對得上，另一個「45 億」版本是單月或轉述錯）；AI 占比查不到；泰國設備延遲約兩個月。"),
    ("4958", "臻鼎-KY", "軟硬板、載板、光模塊",
     "管理層：相關業務逐季增強；光模塊客戶已預訂 2027 年產能；2026 資本支出超過 800 億；2030 目標 AI 相關占比 45～50%。AI 相關（伺服器、光模塊、載板）目前 21.6%。",
     "毛利率僅 23.1% 而資本支出很重；高階競爭與認證前置期長。"),
    ("2313", "華通", "HDI、衛星、光模塊",
     "管理層：今年逐季走揚；資料中心年增 225%（Q1）；2028 年營收目標逾 1,000 億（光模塊與衛星各占 20～30%）；mSAP 光模塊專用產能擴充。",
     "毛利率與 EPS 都沒動（18.0→18.5%、1.26→1.24）、月營收增速下滑；AI 伺服器板占比查不到，主軸是光模塊與衛星。"),
    ("3715", "定穎投控", "HDI／多層板（泰國 AI 板）",
     "管理層：6～7 月已調價；泰國 AI 高階板量產由 Q3 延到 Q4；泰國稼動率約 60%、2027Q1 滿載；2027 AI 占比目標 40%。",
     "仍虧損（EPS −0.81）、毛利率 16.1→14.0%（原物料）；資本支出 184 億或 383 億衝突待核對；分析師僅 2 位，倍數無參考性。"),
]

PKG_CARDS = [
    ("2330", "台積電", "先進封裝（CoWoS／SoIC）",
     "管理層（7/16 法說）：Q3 營收指引 446～458 億美元、毛利率 65～67%；全年美元營收成長略高於 40%；資本支出上修到 600～640 億美元（先進封裝、測試與光罩占 10～20%）；先進封裝供需缺口依然非常巨大；CPU 因 Agentic AI 復甦。",
     "CoWoS 月產能管理層沒給數字；法人 2027 年底預估 14／18／28 萬片互相矛盾，原因可能是口徑（含 WMCM 與否），不確定。"),
    ("3711", "日月光投控", "封測龍頭",
     "管理層（7/30 法說）：Q3 合併營收季增 21～22%、ATM 毛利率 28～29%、Q4 ATM 毛利率有機會突破 30%；LEAP 先進封測 2026 年超過原目標 35 億美元、2027 年較今年翻倍；風險在廠房、設備、良率與爬坡，不是需求。2026 資本支出 105 億美元（原 85）。",
     "AI 占比只有「運算應用 30%」；LEAP 的 CoWoS 子項與測試營收金額查不到；稼動率 80～85%、排除未投運設備接近滿載。"),
    ("2449", "京元電子", "測試代工",
     "法人預估 Q3 與全年雙位數成長；先進測試新產能明年上半年量產；2026 資本支出上修到 500 億元（媒體，公司說法沒讀到）。",
     "AI 占比有 25～30%／35～40%／七成以上多種說法互相矛盾，官方查不到。"),
    ("6239", "力成", "記憶體封測、FOPLP",
     "管理層：Q3 季增個位數、毛利率與 EPS 續升、Q4 優於 Q3；全年有機會超越 2022 年 839 億高點；FOPLP 與 AMD 2027 年中前量產；Broadcom 新加坡合資 4 億美元；CPO 2027 下半年出貨。",
     "FOPLP 設備交期延遲與新產品導入；2026 資本支出總額查不到。"),
    ("3264", "欣銓", "IC 測試（ASIC）",
     "法人預估 Q3 雙位數季增（9 月營收需超過 14 億）；稼動率 Q2 73%、AI ASIC 高階機台接近滿載；上半年 ASIC 相關資本支出約 70 億。",
     "自由現金流 −44.7 億、負債比 53%，現金股利配發率可能無法維持過去 9 成以上；分析師僅 2 位。"),
    ("6257", "矽格", "IC 測試",
     "管理層只有定性：AI 伺服器、ASIC、矽光子、網通、衛星需求穩健，沒有量化指引；湖口廠 7 月量產、產能被國外大客戶預訂滿。",
     "分析師僅 1 位；2026 資本支出 88 億來自舊報導（二手）。"),
    ("6187", "萬潤", "先進封裝設備（CoWoS 點膠、CPO）",
     "CPO 設備 Q4 交貨、2027Q1 放量、下半年逐季創高；合約負債 Q2 2.99 億（Q1 0.74 億）。",
     "管理層親口說法沒讀到（媒體分析）；高盛估 CPO 占營收 2026–28 年 3%／29%／69%（二手）。"),
    ("2360", "致茂", "測試設備（SLT、CPO 光電測試）",
     "下半年成長延續，驅動來自 AI／HPC／ASIC 的 SLT 與 CPO 光電測試；Q2 營收 135.29 億（年增 100%）。",
     "毛利率 62.6→60.5%；占比、訂單金額、風險查不到。"),
    ("6223", "旺矽", "探針卡",
     "管理層：產能供不應求；探針卡約占營收 7 成；2026 全年雙位數成長；AI 測試設備仍驗證階段、明年底前才明朗。法人：Insertion 3 工程驗證機 Q4 出貨、2027 上半年量產。",
     "毛利率 59.4→58.4%；60 日股價 −22%。"),
    ("6515", "穎崴", "測試座與探針卡",
     "管理層：訂單能見度提高、高雄新產能、Q3 預期季增。",
     "營收年增 +156～288%，但毛利率 43.0→38.3%、EPS 19.54→18.70：MEMS 探針卡占比稀釋、新產能成本，量增沒轉成獲利增。"),
    ("3131", "弘塑", "濕製程設備",
     "下半年大型濕製程設備進入裝機驗收、合約負債約 32.75 億（媒體）。",
     "上半年營收以 FinMind 的 33.23 億（15.96＋17.27）為準，另一篇 41.16 億不採用；EPS 16.11→11.18；60 日股價 −22%。"),
    ("3583", "辛耘", "設備、再生晶圓",
     "管理層：製造業務占比首度突破 50%；2026 毛利率優於 2025 年的 33.54%（Q2 FinMind 40.3%）；再生晶圓月產能 21→25 萬片；資本支出 17.5 億。",
     "合約負債 149.81 億為業界最高，但不宜全視為短期 CoWoS 訂單；代理業務略降；月營收年增 −3～+18% 最弱。"),
]

LAMPS = {}
ABF_NOTE = "ABF 載板（欣興、南電、景碩）與聯茂我們前面已另外查過，這裡只放進對照表當基準。"


def _nm(r):
    n = re.sub(r"^\d+\s*", "", r["name"])
    return SHORT.get(n, n)


def _grp(r):
    g = r["group"]
    if g == "PCB／CCL":
        return "CCL" if r["code"] in ("2383", "6274", "6213") else "PCB"
    if g == "ABF 載板":
        return "載板"
    return "封測" if g == "封測" else "設備"


def _lamp(code):
    """四燈／SuperTrend／共識目標價／風報比（lamp_lookup；每列帶資料日）。取不到回 {}。"""
    try:
        import lamp_lookup
        return lamp_lookup.lookup(code, live=False) or {}
    except Exception:                                        # noqa: BLE001
        return {}


def _fmt_pct(v, nd=0):
    return "—" if v is None else f"{v:+.{nd}f}%"


def scatter(rows):
    pts = []
    for r in rows:
        fe = r.get("fe")
        if not fe or r["code"] == "3715":
            continue
        pts.append({"name": _nm(r), "x": fe["pe1"], "y": fe["g"], "g": _grp(r)})
    W, H = 640, 380
    L, R, T, B = 66, 18, 16, 46
    xmin, xmax, ymin, ymax = 10, 44, 10, 170
    px = lambda v: L + (v - xmin) / (xmax - xmin) * (W - L - R)
    py = lambda v: T + (1 - (v - ymin) / (ymax - ymin)) * (H - T - B)
    parts = []
    for xv in (15, 20, 25, 30, 35, 40):
        parts.append(f'<line x1="{px(xv):.0f}" y1="{T}" x2="{px(xv):.0f}" y2="{H - B}" stroke="var(--line2)" stroke-width="1"/>')
        parts.append(f'<text x="{px(xv):.0f}" y="{H - B + 16}" text-anchor="middle" font-size="10.5" fill="var(--muted)">{xv}x</text>')
    for yv in (25, 50, 75, 100, 125, 150):
        parts.append(f'<line x1="{L}" y1="{py(yv):.0f}" x2="{W - R}" y2="{py(yv):.0f}" stroke="var(--line2)" stroke-width="1"/>')
        parts.append(f'<text x="{L - 6}" y="{py(yv) + 4:.0f}" text-anchor="end" font-size="10.5" fill="var(--muted)">+{yv}%</text>')
    parts.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="var(--line)"/>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="var(--line)"/>')
    parts.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 8}" text-anchor="middle" font-size="11" fill="var(--dim)">現價 ÷ 共識 2027E EPS（倍）</text>')
    parts.append(f'<text x="17" y="{(T + H - B) / 2:.0f}" text-anchor="middle" font-size="11" fill="var(--dim)" transform="rotate(-90 17 {(T + H - B) / 2:.0f})">2027E 比 2026E 要再成長</text>')
    parts.append(f'<text x="{L + 8}" y="{H - B - 8}" font-size="10.5" fill="var(--up)">倍數低、要求輕</text>')
    parts.append(f'<text x="{W - R - 8}" y="{T + 14}" text-anchor="end" font-size="10.5" fill="var(--down)">倍數高、要求重</text>')
    placed = [(px(p["x"]) - 6, py(p["y"]) - 6, 12, 12) for p in pts]   # 先把所有圓點當障礙物

    def rect_for(x, y, name, pos):
        w = 10.5 * (len(name) + 0.4) + 2
        h = 12
        if pos == "r":
            return (x + 7, y - 6, w, h), "start", x + 7, y + 4
        if pos == "l":
            return (x - 7 - w, y - 6, w, h), "end", x - 7, y + 4
        if pos == "t":
            return (x - w / 2, y - 7 - h, w, h), "middle", x, y - 9
        if pos == "tr":
            return (x + 5, y - 5 - h, w, h), "start", x + 5, y - 7
        if pos == "br":
            return (x + 5, y + 5, w, h), "start", x + 5, y + 15
        if pos == "tl":
            return (x - 5 - w, y - 5 - h, w, h), "end", x - 5, y - 7
        if pos == "bl":
            return (x - 5 - w, y + 5, w, h), "end", x - 5, y + 15
        return (x - w / 2, y + 7, w, h), "middle", x, y + 17

    def hit(a, b):
        return not (a[0] + a[2] < b[0] or b[0] + b[2] < a[0] or a[1] + a[3] < b[1] or b[1] + b[3] < a[1])

    pts.sort(key=lambda p: (p["y"], p["x"]))
    for p in pts:
        x, y = px(p["x"]), py(p["y"])
        col = GRP_COLOR[p["g"]]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" fill="{col}" stroke="var(--bg)" stroke-width="1"/>')
        own = (px(p["x"]) - 6, py(p["y"]) - 6, 12, 12)
        chosen = None
        for pos in ("r", "l", "t", "b", "tr", "br", "tl", "bl"):
            rc, anc, tx, ty = rect_for(x, y, p["name"], pos)
            if rc[0] < L - 2 or rc[0] + rc[2] > W - 2 or rc[1] < T - 2 or rc[1] + rc[3] > H - B + 2:
                continue
            if any(hit(rc, q) for q in placed if q is not own):
                continue
            chosen = (rc, anc, tx, ty)
            break
        if chosen is None:
            chosen = rect_for(x, y, p["name"], "r")
        placed.append(chosen[0])
        parts.append(f'<text x="{chosen[2]:.1f}" y="{chosen[3]:.1f}" text-anchor="{chosen[1]}" font-size="10.5" fill="var(--ink)">{esc(p["name"])}</text>')
    legend = "".join(f'<span><i style="background:{GRP_COLOR[g]}"></i>{g}</span>' for g in GRP_ORDER)
    return ('<div class="rpt-chart"><svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">%s</svg>'
            '<div class="legend">%s</div>'
            '<div class="cap">橫軸：現價是共識 2027E EPS 的幾倍（越右越貴）；縱軸：2027E 比 2026E 要再成長多少（越上要求越高）。'
            '左下是「倍數低、要求輕」，右上是「倍數高、要求重」。共識是賣方預估，歷史上偏樂觀；定穎（虧損、分析師僅 2 位）不畫。</div></div>'
            % (W, H, "".join(parts), legend))


def table(rows):
    head = ("<tr><th>族群</th><th>股票</th><th>現價</th><th>5日</th><th>20日</th><th>60日</th><th>四燈／趨勢</th><th>距線</th><th>共識目標價（距現價）</th><th>風報比</th><th>月營收年增（近三月）</th>"
            "<th>毛利率 Q1→Q2</th><th>EPS Q1→Q2</th><th>共識 EPS 26E／27E</th><th>現價÷26E</th><th>現價÷27E</th><th>27E 比 26E</th><th>分析師</th></tr>")
    body = []
    last = None
    cls = lambda v: "up" if (v is not None and v >= 0) else "dn"
    for r in sorted(rows, key=lambda r: (GRP_ORDER.index(_grp(r)), -(r.get("r60") or 0))):
        g = _grp(r)
        mon = "／".join(f"{(y or 0):+.0f}%" for p, y in r["mon"])
        q = r["q"]
        q1, q2 = q[-2], q[-1]
        flag = ' <span class="w">⚠業外&gt;本業</span>' if q2.get("nonop_dom") else ""
        fe = r.get("fe")
        sep = ' class="gsep"' if g != last else ""
        last = g
        eps_cls = "dn" if q2["eps"] < q1["eps"] else ""
        gm_cls = "dn" if (q1.get("gm") is not None and q2.get("gm") is not None and q2["gm"] < q1["gm"]) else ""
        name = _nm(r)
        lp = LAMPS.get(r["code"]) or {}
        lit, bull, gap, rr = lp.get("lit"), lp.get("bull"), lp.get("gap_pct"), lp.get("rr")
        tgt, tpct = lp.get("target"), lp.get("target_pct")
        lamp_cell = (f'<td class="n {"up" if (lit or 0) >= 3 else ("dn" if (lit or 0) <= 1 else "")}">{lit}／4 {"多" if bull else "空"}</td>'
                     if lit is not None else '<td class="n">—</td>')
        gap_cell = (f'<td class="n {"up" if gap >= 0 else "dn"}">{gap:+.0f}%</td>' if gap is not None else '<td class="n">—</td>')
        tgt_cell = (f'<td class="n">{tgt:,.0f}（{tpct:+.0f}%）</td>' if tgt and tpct is not None else '<td class="n">—</td>')
        if rr is None:
            rr_cell = '<td class="n">不適用</td>' if lit is not None else '<td class="n">—</td>'
        else:
            small = gap is not None and 0 <= gap < 5
            rr_cell = f'<td class="n {"up" if rr >= 1 else "dn"}">{rr:.1f}{"⚠" if small else ""}</td>'
        body.append(
            f'<tr{sep}><td><span class="chip" style="background:{GRP_COLOR[g]}">{g}</span></td><td>{r["code"]} {esc(name)}</td>'
            f'<td class="n">{r["px"]:,.0f}</td><td class="n {cls(r["r5"])}">{_fmt_pct(r["r5"])}</td><td class="n {cls(r["r20"])}">{_fmt_pct(r["r20"])}</td>'
            f'<td class="n {cls(r["r60"])}">{_fmt_pct(r["r60"])}</td>{lamp_cell}{gap_cell}{tgt_cell}{rr_cell}<td class="n">{mon}</td>'
            f'<td class="n {gm_cls}">{q1["gm"]:.1f}→{q2["gm"]:.1f}</td><td class="n {eps_cls}">{q1["eps"]}→{q2["eps"]}{flag}</td>'
            + (f'<td class="n">{fe["e0"]:.1f}／{fe["e1"]:.1f}</td><td class="n">{fe["pe0"]:.0f}x</td><td class="n">{fe["pe1"]:.0f}x</td>'
               f'<td class="n">+{fe["g"]:.0f}%</td><td class="n">{fe["n"]}</td></tr>' if fe else
               '<td class="n">—</td><td class="n">—</td><td class="n">—</td><td class="n">—</td><td class="n">—</td></tr>'))
    return f'<div class="tbl-wrap"><table class="t">{head}{"".join(body)}</table></div>'


def lamp_section(rows):
    """把燈號與風報比跟「現價÷2027E」放在一起看（分組由資料決定，不手寫名單）。"""
    def item(r):
        lp, fe = LAMPS.get(r["code"]) or {}, r.get("fe") or {}
        return lp, fe
    A, B, C, D = [], [], [], []
    for r in rows:
        lp, fe = item(r)
        if lp.get("lit") is None:
            continue
        nm = f'{_nm(r)}'
        pe = f'{fe["pe1"]:.0f}x' if fe.get("pe1") else "—"
        if not lp.get("bull"):
            B.append(f'{nm}（共識目標距現價 {lp["target_pct"]:+.0f}%、距線 {lp["gap_pct"]:+.0f}%、2027E {pe}）')
        elif lp.get("rr") is not None and lp["rr"] < 1 and lp["lit"] >= 3:
            A.append(f'{nm}（風報比 {lp["rr"]:.1f}、距線 {lp["gap_pct"]:+.0f}%、2027E {pe}）')
        elif lp.get("rr") is not None and lp["rr"] >= 1 and lp["gap_pct"] >= 5 and lp["lit"] >= 3:
            C.append(f'{nm}（四燈 {lp["lit"]}／4、風報比 {lp["rr"]:.1f}、2027E {pe}）')
        elif lp.get("rr") is not None and lp["rr"] >= 1:
            why = (f'距線僅 {lp["gap_pct"]:+.1f}%（分母小，風報比被放大）' if lp["gap_pct"] < 5 else f'四燈只有 {lp["lit"]}／4')
            D.append(f'{nm}（風報比 {lp["rr"]:.1f}，但{why}、2027E {pe}）')
    li = lambda xs: "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in xs) + "</ul>" if xs else "<p>（無）</p>"
    return ('<div class="rpt-sec"><h2>燈號與風報比：趨勢跟價位對不對得上</h2>'
            '<p style="font-size:12.5px;color:var(--muted)">四燈＝系統每日燈號掃描亮幾盞；趨勢＝SuperTrend 多／空；距線＝現價高於 SuperTrend 線多少％（失效線）；'
            '風報比＝（共識目標價 − 現價）÷（現價 − SuperTrend 線），<b>用的是賣方共識目標價，歷史上偏樂觀</b>，且趨勢轉空時不適用；'
            '距線很小時（⚠，&lt;5%）分母小，風報比會被放大。燈號資料日以快取為準（多數是 10/02，少數是 10/05）。</p>'
            '<h3>趨勢多頭，但價位不划算（風報比 &lt; 1）</h3>' + li(A) +
            '<h3>趨勢與風報比都過關（四燈 ≥ 3、風報比 ≥ 1、距線 ≥ 5%）</h3>' + li(C) +
            '<h3>風報比 ≥ 1，但訊號打折（距線很近＝分母小，或四燈不足）</h3>' + li(D) +
            '<h3>SuperTrend 空方（趨勢已轉弱；共識目標價上檔空間大，但這是賣方預估）</h3>' + li(B) +
            '<p style="font-size:12.5px;color:var(--muted)">這是把系統訊號跟前面的估值倍數並排，不是買賣建議；趨勢是價格訊號，倍數與成長要求是基本面前提，兩者不一致時要自己判斷哪個更重要。</p></div>')


def cards(lst):
    out = []
    for code, name, role, mgmt, note in lst:
        out.append(f'<div class="stk-card"><div class="h"><b>{esc(name)}</b><span class="tag">{code}</span>'
                   f'<span class="tag">{esc(role)}</span></div><div class="d"><b>展望與擴產</b>　{esc(mgmt)}</div>'
                   f'<div class="d warn"><b>注意</b>　{esc(note)}</div></div>')
    return "".join(out)


def build():
    rows = json.load(io.open("state/pcb_pkg_screen.json", encoding="utf-8"))
    global LAMPS
    LAMPS = {r["code"]: _lamp(r["code"]) for r in rows}
    body = []
    body.append(
        '<div class="rpt-tldr"><div class="lbl">30秒看懂</div><ol>'
        '<li><b>基本面整個族群都在往上，但強弱差很大</b>：最強是上游材料與設備（台光電、台燿月營收年增 +108～130%；穎崴、致茂、萬潤 +73～288%），封測最溫和（+21～46%）。</li>'
        '<li><b>要求最輕的一端</b>：封測、健鼎、金像電、台積電，現價是 2027 年共識 EPS 的 14～21 倍，2027 年只需比 2026 再成長約 25～62%。'
        '<b>要求最重的一端</b>：載板三家與旺矽、穎崴、致茂、萬潤，31～41 倍，需要獲利再翻一倍以上。</li>'
        '<li><b>CCL 漲價的受益與被擠壓很分明</b>：台光電、台燿毛利率明顯走高；板廠分化（健鼎走高、金像電與華通持平、定穎被原物料壓到 14.0%）。</li>'
        '<li><b>量增沒轉成獲利的兩檔</b>：穎崴（營收 +233% 但毛利率 43.0→38.3%）、弘塑（EPS 16.1→11.2）；旺矽、弘塑、穎崴 60 日股價是跌的，而聯茂 +95%、欣興 +51%、萬潤 +44% 已經先漲。</li>'
        '<li><b>擴產都很大</b>（台積電資本支出 600～640 億美元、日月光 105 億美元、臻鼎 800 億元以上）：是需求能見度的證據，也是日後折舊與供給壓力的來源（觀察，不是結論）。</li>'
        '</ol></div>')
    body.append('<div class="rpt-sec"><h2>誰的要求輕、誰的要求重</h2>' + scatter(rows) + '</div>')
    body.append('<div class="rpt-sec"><h2>26 檔量化對照</h2>'
                '<p style="font-size:12.5px;color:var(--muted)">價格與漲幅為 2026-10-05 最新價；月營收為最近三個月年增；毛利率與 EPS 為 2026 Q1→Q2（紅字＝下滑）；'
                '共識 EPS 來自 yfinance（賣方預估）。表可左右捲動。' + esc(ABF_NOTE) + '</p>' + table(rows) + '</div>')
    body.append(lamp_section(rows))
    body.append('<div class="rpt-sec"><h2>PCB／CCL：公司展望</h2>'
                '<p>產業：TPCA 估 2026 年台灣 PCB 產值 1.1366 兆（+24.2%），載板 +36.7%、HDI +28.4%、多層板 +47.6%、軟板 +1.3%；供應限制預期延續到 2027 年。'
                'CCL 價格：建滔 4/28 全產品線再漲 10%（今年第四次）、南亞電材 3 月中漲 15%；玻纖布吃緊（量化缺口只有搜尋摘要，不採用）。'
                '中國同業：滬電上半年營收 +61%、毛利率 40.5%，生益預告淨利 +117～131%（人民幣口徑）。TPCA 展 10/20～22 南港展覽館。</p>'
                + cards(PCB_CARDS) + '</div>')
    body.append('<div class="rpt-sec"><h2>大封測：公司展望</h2>'
                '<p>產業：台積電把部分 CoWoS oS 訂單釋出給專業封測廠，法人評估日月光 CoWoS 類產能 2026 年倍增（「CoW 大規模委外」是韓媒傳聞，日期有疑問）；'
                'CoPoS 2026 驗證、2027 試產、2028 下半年量產（TrendForce，另一份法人寫 2029～2030 才大量，時程有分歧）；玻璃基板量產在 2030 年後（僅一家法人）；'
                'AI 晶片測試時間拉長帶動測試單價。</p>' + cards(PKG_CARDS) + '</div>')
    body.append(
        '<div class="rpt-sec"><h2>衝突數字與查不到的</h2>'
        '<details class="sec" open><summary>互相衝突、不要直接當模型輸入</summary><ul>'
        '<li>金像電：資本支出 72／104／170／190 億；AI 占比 4～5 成 vs 70%（口徑不同）。</li>'
        '<li>定穎：資本支出 184 億或 383 億，需核對公開資訊觀測站。</li>'
        '<li>台光電法說日：7/29、8/21、9/4 三種說法。</li>'
        '<li>京元 AI 占比：25～30%、35～40%、七成以上。</li>'
        '<li>台積電 CoWoS 2027 年底月產能：14／18／28 萬片（口徑可能不同）。</li></ul></details>'
        '<details class="sec"><summary>已用 FinMind 解決的</summary><ul>'
        '<li>台燿 Q2 營收以 143 億為準（毛利率 29.7%、EPS 8.02 與 FinMind 對上）。</li>'
        '<li>弘塑上半年營收以 33.23 億為準（15.96＋17.27），另一篇 41.16 億不採用。</li>'
        '<li>旺矽 58.4%、萬潤 54.8%、辛耘 40.3% 的 Q2 毛利率，助手查不到，由 FinMind 補上。</li></ul></details>'
        '<details class="sec"><summary>查不到</summary><ul>'
        '<li>所有公司官方簡報與公開資訊觀測站原文（質化內容全來自財經媒體整理，抓取工具回傳摘要）。</li>'
        '<li>台光電 Q3 具體指引；台燿、華通、健鼎的 AI 伺服器板占比；矽格 Q3 量化指引。</li>'
        '<li>力成、致茂、旺矽、穎崴的資本支出；台積電 CoWoS 管理層片數；Vera CPU 對封測訂單的量化影響；T-glass／Q-glass 缺口量化。</li></ul></details></div>')
    body.append('<div class="rpt-note">來源：財經媒體整理（工商時報、經濟日報、優分析、富果、MoneyWeekly、TechNews 等），'
                '財報數字 FinMind、價格與共識 EPS yfinance，查證日 ' + CHECK_DATE + '。質化內容為媒體轉述，管理層說法與法人預估已分開標示，未區分的標「媒體」。'
                '共識 EPS 與目標價是賣方預估，歷史上偏樂觀。本頁只做描述，不是買賣訊號，不替任何人選倍數。</div>')
    return ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS + "</style></head><body><div class=\"wrap\">"
            + header("rotation", TITLE, f"26 檔量化對照＋公司展望（財經媒體整理）｜{CHECK_DATE}", [], eyebrow="INDUSTRY RESEARCH")
            + "".join(body) + "</div></body></html>")


def main():
    html = build()
    dst = op.archive("2026-10-05_PCB與大封測深入研究.html", sub="研究與回測")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")


if __name__ == "__main__":
    main()
