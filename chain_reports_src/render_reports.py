# -*- coding: utf-8 -*-
"""把各鏈研究 JSON（chains_data.json）渲染成 .rpt HTML 片段，
合併進 daily_stock_analysis/chain_reports.json（保留既有 AI 伺服器 bespoke 版）。
用法：python render_reports.py
"""
import json, os, glob, html

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                      # chain_reports_src 的上層 = repo 根
DATADIR = os.path.join(HERE, "reports_data")     # 每鏈一個 *.json（含 _chain 鍵）
OUT = os.path.join(REPO, "chain_reports.json")


def _unesc(x):
    """遞迴把 &lt;b&gt; 等實體還原成 <b>，讓粗體生效。"""
    if isinstance(x, str):
        return html.unescape(x)
    if isinstance(x, list):
        return [_unesc(i) for i in x]
    if isinstance(x, dict):
        return {k: _unesc(v) for k, v in x.items()}
    return x


def _stocks_table(rows):
    body = []
    for s in rows:
        code = s.get("code", ""); name = s.get("name", "")
        role = s.get("role", ""); note = s.get("note", "")
        bull = (s.get("bull") or "").strip(); bear = (s.get("bear") or "").strip()
        mm = ""
        if bull:
            mm += f'<div class="ln"><span class="b up">多</span>{bull}</div>'
        if bear:
            mm += f'<div class="ln"><span class="b dn">空</span>{bear}</div>'
        nm = f'<b>{code}</b>' + (f'<br>{name}' if name else '')
        body.append(
            f'<tr><td data-label="代號">{nm}</td>'
            f'<td data-label="角色">{role}</td>'
            f'<td data-label="近況">{note}</td>'
            f'<td data-label="多空">{mm}</td></tr>')
    return ('<div class="tw"><table><thead><tr><th>代號</th><th>角色</th>'
            '<th>近況／財務</th><th>多空一句</th></tr></thead><tbody>'
            + "".join(body) + '</tbody></table></div>')


def render(chain, d):
    p = []
    if d.get("positioning"):
        p.append(f'<p class="pos">{d["positioning"]}</p>')
    # 守備清單一行
    us = d.get("stocks_us", []); tw = d.get("stocks_tw", [])
    su = " / ".join(s.get("name") or s.get("code") for s in us)
    st = " / ".join(s.get("name") or s.get("code") for s in tw)
    line = f'守備清單（{len(us)} 美' + (f'＋{len(tw)} 台' if tw else '') + f'）：美股 {su}'
    if tw:
        line += f'　台股 {st}'
    p.append(f'<p class="ts">資料時效 2026-07-17　·　{line}</p>')
    # TL;DR
    t = d.get("tldr", {})
    p.append(
        '<div class="tldr"><div class="lab">三行懶人包 TL;DR</div>'
        f'<div class="row r1"><span class="ic">🎯</span><span><b>結論</b>：{t.get("conclusion","")}</span></div>'
        f'<div class="row r2"><span class="ic">💡</span><span><b>最強催化劑</b>：{t.get("catalyst","")}</span></div>'
        f'<div class="row r3"><span class="ic">⚠️</span><span><b>最大風險</b>：{t.get("risk","")}</span></div></div>')
    # 一、需求引擎
    if d.get("demand"):
        p.append('<h2>一、需求引擎</h2>')
        p.append(f'<p>{d["demand"]}</p>')
    # 二、產業規模
    if d.get("scale"):
        p.append('<h2>二、產業規模與成長</h2><div class="stat">')
        for b in d["scale"]:
            p.append(f'<div class="box"><div class="n">{b.get("n","")}</div>'
                     f'<div class="t">{b.get("t","")}</div></div>')
        p.append('</div>')
        if d.get("scale_note"):
            p.append(f'<p class="note">{d["scale_note"]}</p>')
    # 三、競爭格局
    if d.get("competition"):
        p.append('<h2>三、競爭格局與市佔</h2><div class="tw"><table>'
                 '<thead><tr><th>戰場</th><th>目前態勢</th><th>趨勢</th></tr></thead><tbody>')
        for r in d["competition"]:
            p.append(f'<tr><td data-label="戰場">{r.get("field","")}</td>'
                     f'<td data-label="態勢">{r.get("now","")}</td>'
                     f'<td data-label="趨勢">{r.get("trend","")}</td></tr>')
        p.append('</tbody></table></div>')
        if d.get("comp_note"):
            p.append(f'<p class="note">{d["comp_note"]}</p>')
    # 四、價值鏈
    if d.get("valuechain"):
        p.append('<h2>四、價值鏈拆解（上游 → 下游，對應守備個股）</h2><div class="tw"><table>'
                 '<thead><tr><th>環節</th><th>在做什麼</th><th>守備個股</th><th>近況重點</th></tr></thead><tbody>')
        for r in d["valuechain"]:
            p.append(f'<tr><td data-label="環節"><b>{r.get("seg","")}</b></td>'
                     f'<td data-label="做什麼">{r.get("do","")}</td>'
                     f'<td data-label="守備股">{r.get("stocks","")}</td>'
                     f'<td data-label="近況">{r.get("note","")}</td></tr>')
        p.append('</tbody></table></div>')
        if d.get("vc_note"):
            p.append(f'<p class="note">{d["vc_note"]}</p>')
    # 五、催化劑
    if d.get("catalysts"):
        p.append('<h2>五、近期變化與催化劑</h2><ul>')
        p.extend(f'<li>{x}</li>' for x in d["catalysts"])
        p.append('</ul>')
    # 六、多空
    if d.get("bull") or d.get("bear"):
        p.append('<h2>六、多空論點對照</h2><div class="bb">')
        if d.get("bull"):
            p.append('<div class="col bull"><h4>🐂 看多 Bull case</h4><ul>'
                     + "".join(f'<li>{x}</li>' for x in d["bull"]) + '</ul></div>')
        if d.get("bear"):
            p.append('<div class="col bear"><h4>🐻 看空 Bear case</h4><ul>'
                     + "".join(f'<li>{x}</li>' for x in d["bear"]) + '</ul></div>')
        p.append('</div>')
        if d.get("bb_note"):
            p.append(f'<p class="note">{d["bb_note"]}</p>')
    # 七、風險
    if d.get("risks"):
        p.append('<h2>七、風險</h2><ol class="risk">')
        p.extend(f'<li>{x}</li>' for x in d["risks"])
        p.append('</ol>')
    # 八、觀察
    if d.get("watch"):
        p.append('<h2>八、近期觀察重點</h2><ul class="watch">')
        p.extend(f'<li>{x}</li>' for x in d["watch"])
        p.append('</ul>')
    # 九、個股
    if us or tw:
        p.append('<h2>九、守備個股獨立解讀</h2>')
        if us:
            p.append(f'<p class="note" style="margin-bottom:4px">🇺🇸 美股 {len(us)} 檔</p>')
            p.append(_stocks_table(us))
        if tw:
            p.append(f'<p class="note" style="margin:12px 0 4px">🇹🇼 台股 {len(tw)} 檔</p>')
            p.append(_stocks_table(tw))
    # 來源
    if d.get("sources"):
        p.append(f'<p class="disc">📎 <b>資料來源</b>：{d["sources"]}</p>')
    p.append('<p class="disc">本報告由 Claude 綜整公開資訊與產業知識撰寫，<b>非投資建議</b>；'
             '數字為市場預估、以各公司財報與官方公告為準。守備清單由客觀三因子自動篩出。</p>')
    return '<div class="rpt">\n' + "\n".join(p) + '\n</div>'


def main():
    reports = {}
    if os.path.exists(OUT):
        reports = json.load(open(OUT, encoding="utf-8"))   # 保留 AI 伺服器 bespoke
    for fp in sorted(glob.glob(os.path.join(DATADIR, "*.json"))):
        d = _unesc(json.load(open(fp, encoding="utf-8")))
        chain = d.get("_chain")
        if not chain:
            print(f"  ! {fp} 缺 _chain，略過"); continue
        reports[chain] = render(chain, d)
        print(f"  ✓ {chain}（{len(reports[chain])} 字元、美{len(d.get('stocks_us',[]))} 台{len(d.get('stocks_tw',[]))}）")
    json.dump(reports, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已寫 {OUT}：共 {len(reports)} 鏈")


if __name__ == "__main__":
    main()
