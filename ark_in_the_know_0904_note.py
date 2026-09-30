# -*- coding: utf-8 -*-
"""ARK Invest《In The Know》2026-09-04（Cathie Wood）整理筆記。

來源：YouTube 公開影片 https://youtu.be/bjgy0BVFQx0（53 分鐘，英文自動字幕）。
公開影片＝非機密，這支程式可以進 repo；產出的 HTML 放 obis 存檔／總經與盤勢。

## 怎麼做的
- 逐字稿：yt_learn（youtube-transcript-api 抓 YouTube 自己的字幕，零成本）。
- 內容：人工讀完整份逐字稿後改寫成中文重點——不照抄原句；影片裡的圖只取她口述的數字重畫。
- 對照：她 9/4 錄影之後，用系統自己的資料（macro_weekly 利率、9/17 FOMC 筆記、ARK 追蹤頁回測）
  補一段「後來發生什麼」。這段是我們的資料，跟她的觀點分開放。

## 自動字幕的錯字（已依上下文更正，頁尾有列）
「Worsh」＝Warsh、「end of 2018」＝應為 2028、「NEO plowed」＝neocloud、「85 to 91」＝8.5%→9.1%。

用法: python ark_in_the_know_0904_note.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import obis_paths as op                                        # noqa: E402
from board_theme import BASE_CSS, header, esc                  # noqa: E402

TITLE = "Cathie Wood：科技革命下的通膨與利率"
VIDEO = "https://youtu.be/bjgy0BVFQx0"
REC_DATE = "2026-09-04"

CSS = """
.rpt-sec{margin:24px 0}
.rpt-sec h2{font-size:16px;font-weight:800;color:#93C5FD;margin-bottom:10px}
.rpt-sec h3{font-size:14px;font-weight:700;color:var(--ink);margin:14px 0 6px}
.rpt-sec p{font-size:13.5px;line-height:1.9;color:var(--ink);margin:0 0 10px}
.rpt-sec ul{margin:0 0 10px 18px;font-size:13.5px;line-height:1.85;color:var(--ink)}
.rpt-sec li{margin-bottom:7px}
.rpt-sec b{color:#F5B841}
.rpt-tldr{background:var(--card);border:1px solid var(--accent);border-radius:12px;
  padding:16px 18px;margin:18px 0 28px}
.rpt-tldr .lbl{font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--accent);margin-bottom:8px}
.rpt-tldr ul{margin:0 0 0 18px;font-size:14px;line-height:1.9;color:var(--ink)}
.rpt-tldr b{color:#F5B841}
.rpt-view{background:var(--card);border:1px solid #F5B841;border-radius:12px;padding:16px 18px;margin:24px 0}
.rpt-view h2{font-size:16px;font-weight:800;color:#F5B841;margin:0 0 10px}
.rpt-view h3{font-size:13.5px;font-weight:700;color:var(--accent);margin:12px 0 4px}
.rpt-view ul{margin:0 0 6px 18px;font-size:13.5px;line-height:1.85;color:var(--ink)}
.rpt-check{background:var(--card);border:1px solid var(--up);border-radius:12px;padding:16px 18px;margin:24px 0}
.rpt-check h2{font-size:16px;font-weight:800;color:var(--up);margin:0 0 6px}
.rpt-check .sub{font-size:12px;color:var(--dim);margin-bottom:10px;line-height:1.7}
.rpt-tbl{width:100%;border-collapse:collapse;font-size:13px}
.rpt-tbl th{text-align:left;font-size:11.5px;color:var(--dim);font-weight:600;padding:6px 8px;
  border-bottom:1px solid var(--line)}
.rpt-tbl td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top;line-height:1.7;color:var(--ink)}
.rpt-tbl td.v{white-space:nowrap}
.rpt-scroll{overflow-x:auto}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:4px;white-space:nowrap}
.tag.ok{background:rgba(34,197,94,.14);color:var(--up)}
.tag.no{background:rgba(239,68,68,.14);color:var(--down)}
.tag.mid{background:rgba(255,182,39,.14);color:var(--warn)}
.rpt-chart{margin:14px 0 18px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.rpt-chart.narrow{max-width:560px;margin-left:auto;margin-right:auto}
.rpt-chart .cap{font-size:11.5px;color:var(--dim);margin-top:8px;line-height:1.6}
.rpt-chart svg{width:100%;height:auto;display:block}
.rpt-chart-row{display:flex;gap:16px;flex-wrap:wrap;margin:14px 0 18px}
.rpt-chart-row .rpt-chart{margin:0;flex:1 1 420px;max-width:560px}
.rpt-note{font-size:12px;color:var(--dim);border-top:1px solid var(--line);padding-top:10px;margin-top:22px;line-height:1.7}
.rpt-note a{color:var(--accent)}
"""


def _svg_gdp():
    """各時期全球實質 GDP 年成長（她口述的數字重畫）。"""
    rows = [("西元前～1500 年", 0.3, "#5B6E8A", "約 0.3%*"),
            ("1500～1900 年", 0.6, "#5B6E8A", "0.6%"),
            ("工業革命後～今", 3.0, "#9DB0C8", "約 3%"),
            ("IMF 今年預估", 3.1, "#3B82F6", "3.1%"),
            ("ARK 未來 5 年", 6.0, "#22D3EE", "至少 6%"),
            ("放大 5 倍（樂觀）", 15.0, "#F5B841", "15%")]
    w, lw, top, bh, gap = 400, 142, 8, 26, 12
    plot = w - lw - 96
    h = top + len(rows) * (bh + gap)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="各時期全球實質GDP年成長">']
    for i, (lab, v, col, txt) in enumerate(rows):
        y = top + i * (bh + gap)
        bw = max(3, v / 15.0 * plot)
        out.append(f'<text x="{lw - 8}" y="{y + bh * 0.7:.1f}" text-anchor="end" font-size="15" '
                   f'style="fill:var(--ink)">{esc(lab)}</text>')
        out.append(f'<rect x="{lw}" y="{y}" width="{bw:.1f}" height="{bh}" rx="3" style="fill:{col}"/>')
        out.append(f'<text x="{lw + bw + 6:.1f}" y="{y + bh * 0.7:.1f}" font-size="15" '
                   f'style="fill:var(--muted);font-family:\'IBM Plex Mono\',monospace">{esc(txt)}</text>')
    out.append("</svg>")
    return ('<div class="rpt-chart narrow">' + "".join(out)
            + '<div class="cap">數字取自她的口述（原圖是 ARK 與學術期刊合作的超長期估算，本身就很粗略）。'
              '標 * 的「西元前～1500 年」是依她說「1500～1900 年是前 1500 年的兩倍」推回去的，不是她直接講的數字。</div></div>')


def _svg_inflation():
    """通膨指標比較：新主席盯的整體 PCE vs 其他指標（她口述的數字重畫）。"""
    rows = [("整體 PCE（主席盯）", 3.7, "#EF4444"),
            ("達拉斯截尾 PCE", 2.3, "#FFB627"),
            ("民間指標：整體", 2.4, "#FFB627"),
            ("民間指標：核心", 1.3, "#22C55E")]
    w, lw, top, bh, gap = 400, 150, 22, 28, 14
    plot = w - lw - 56
    h = top + len(rows) * (bh + gap) + 6
    x2 = lw + 2.0 / 4.0 * plot
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="通膨指標比較">',
           f'<line x1="{x2:.1f}" y1="{top - 8}" x2="{x2:.1f}" y2="{h - 4}" '
           f'style="stroke:var(--accent);stroke-width:1.5;stroke-dasharray:4 3"/>',
           f'<text x="{x2 + 5:.1f}" y="{top - 2}" font-size="14" style="fill:var(--accent)">目標 2%</text>']
    for i, (lab, v, col) in enumerate(rows):
        y = top + 6 + i * (bh + gap)
        bw = v / 4.0 * plot
        out.append(f'<text x="{lw - 8}" y="{y + bh * 0.68:.1f}" text-anchor="end" font-size="15" '
                   f'style="fill:var(--ink)">{esc(lab)}</text>')
        out.append(f'<rect x="{lw}" y="{y}" width="{bw:.1f}" height="{bh}" rx="3" style="fill:{col}"/>')
        out.append(f'<text x="{lw + bw + 6:.1f}" y="{y + bh * 0.68:.1f}" font-size="15" '
                   f'style="fill:var(--muted);font-family:\'IBM Plex Mono\',monospace;'
                   f'paint-order:stroke;stroke:var(--surface);stroke-width:5px">{v:.1f}%</text>')
    out.append("</svg>")
    return ('<div class="rpt-chart narrow">' + "".join(out)
            + '<div class="cap">她的重點：只有整體 PCE 離 2% 遠，其他三個指標都已經接近或低於 2%。'
              '她認為整體 PCE 被伊朗戰爭推高的油價拉上去，是暫時的。</div></div>')


def build():
    b = []
    b.append('<div class="rpt-tldr"><div class="lbl">⏱ 30 秒看懂</div><ul>'
             '<li>她的主軸：<b>科技革命會讓全球實質成長加倍，同時壓低通膨</b>——跟工業革命一樣，成長快、物價卻往下。</li>'
             '<li>通膨：新任聯準會主席盯的整體 PCE 是 3.7%，但其他指標都已接近 2%；'
             '她認為油價和科技成本下降會讓通膨<b>比市場預期低很多，甚至轉負</b>。</li>'
             '<li>利率：近期長債殖利率上升，主要是<b>實質成長預期</b>推升、不是通膨；'
             '她認為殖利率曲線可能再度倒掛，但<b>不代表衰退</b>（大蕭條前多數時間都是倒掛）。</li>'
             '<li>資產：看好比特幣相對黃金走強、油價可能回到 30 美元；AI 已經有真實營收與報酬，'
             '<b>不會像 1800 年代鐵路那樣大批倒閉</b>。</li></ul></div>')

    b.append('<div class="rpt-sec"><h2>一、核心框架：拿工業革命對照現在</h2>'
             '<p>過去約 125 年，全球實質 GDP 成長大致都在 <b>3%</b> 附近，幾乎沒有人經歷過別的成長速度。'
             '她的論點是：技術革命會把成長率往上推——工業革命把年成長從 0.6% 推到 3%，約 <b>5 倍</b>。</p>'
             '<ul><li>工業革命主要是三個平台：鐵路先行，接著電話、電力、內燃機。</li>'
             '<li>現在同時有<b>五個</b>平台在發展：AI（最大的催化劑）、機器人、儲能、區塊鏈、多組學定序（生命科學）。</li>'
             '<li>IMF 預估今年全球成長 3.1%，而且一年來沒改過看法；ARK 認為未來 5 年成長<b>至少加倍</b>，而且這還算保守。'
             '她提到 Elon Musk 已經開始用 10%～15% 來想。</li></ul>'
             + _svg_gdp() + '</div>')

    b.append('<div class="rpt-sec"><h2>二、利率：上升的是實質成長預期，不是通膨</h2>'
             '<ul><li>名目 GDP 成長（＝實質成長＋通膨）跟 10 年期公債殖利率長期高度相關。'
             '10 年債從 2023 年起在一個區間盤整，已經第三年；名目 GDP 成長的 10 年移動平均看起來正在往上突破。</li>'
             '<li>她的推演：實質成長往上、通膨往下，兩者互相抵銷，利率可能繼續在這附近打底；'
             '但如果實質成長超過 7%、通膨只是微幅負值，10 年債就會往上走——「那只是市場在運作」。</li>'
             '<li>今年以來長債殖利率平均約 <b>4.4%</b>，大致回到 1971 年脫離金本位之前的水準，她認為這是回歸正常。</li>'
             '<li>股市在利率上升中仍創新高：把長債殖利率拆成通膨和實質兩部分，近期上升主要來自<b>實質成長預期</b>。</li>'
             '<li>她也批評 2008 年後長期零利率造成很多問題，事後會被認為是疫情前後混亂的原因之一。</li></ul>'
             '<h3>百年殖利率曲線：倒掛不一定是衰退訊號</h3>'
             '<ul><li>1913 年聯準會成立、走出大蕭條後，殖利率曲線大多是正斜率，只有接近衰退時才倒掛。</li>'
             '<li>但大蕭條之前、工業革命期間，倒掛反而是常態：她說<b>超過六成的時間是倒掛</b>，平均倒掛約 100 個基點。'
             '原因是新技術帶來通縮壓力，長債反映通縮，短債反映實質經濟成長。</li>'
             '<li>2023～2025 年深度倒掛卻沒有整體衰退（製造業、房市、小企業、低收入族群確實像衰退）——'
             '她認為這可能是回到「工業革命型」的第一個跡象。現在曲線又在變平、往倒掛靠近。</li></ul></div>')

    b.append('<div class="rpt-sec"><h2>三、通膨：她為什麼認為會大降</h2>'
             '<p>新任聯準會主席 Warsh 在 Jackson Hole 演講中聚焦<b>整體 PCE 通膨 3.7%</b>，目標要降到 2%。'
             '她說這讓 ARK 的想法稍微調整：如果主席真的只看這個數字，而它繼續上升，聯準會就會再緊縮。'
             '但她認為主席也在看其他指標（他在國會聽證時提過截尾 PCE，也成立了小組研究公私部門的通膨衡量）。</p>'
             + _svg_inflation()
             + '<h3>理由一：油價</h3>'
             '<ul><li>兩場戰爭（俄烏、伊朗）都沒能讓油價突破 2008 年的高點 147 美元。</li>'
             '<li>阿布達比 5 月退出 OPEC，之後產量增加 <b>78%</b>，創紀錄的每日 400 多萬桶；委內瑞拉也可能退出。</li>'
             '<li>美國每日產油 1,360 萬桶、出口超過 600 萬桶（2015 年幾乎不出口）。80～90 美元的油價是很強的增產誘因。</li>'
             '<li>她認為阿布達比已判斷石油需求見頂（運輸轉向電網，電網靠天然氣、核能、水力、太陽能、風力），'
             '會想在油價下跌前盡量變現；沙烏地不會讓阿布達比搶市占。她<b>不意外油價跌回 30 美元</b>（約過去 50 年平均）。</li></ul>'
             '<h3>理由二：科技成本</h3>'
             '<ul><li>基因定序成本：2003 年定序一個人約 27 億美元，現在不到 100 美元，可能降到 10 美元。</li>'
             '<li>AI 推論成本下降得極快；這些成本下降正進入醫療和各行各業。生產力是對抗通膨最強的力量。</li></ul>'
             '<h3>黃金</h3>'
             '<ul><li>她認為 Volcker 與 Greenspan 任內用金價當參考，通膨因此被壓下來；'
             '1990 年代末一連串危機與 Y2K 讓聯準會放鬆過頭，美元對黃金的購買力流失。</li>'
             '<li>近期金價上漲，她認為除了疫情後的通膨恐懼，更多是「怕財富被沒收」的避險需求。'
             '新主席不喜歡金價上漲，而金價在他被提名當天見頂；若美元因美國投資報酬率較高而走強，金價會下跌。</li></ul></div>')

    b.append('<div class="rpt-sec"><h2>四、財政與貨幣</h2>'
             '<ul><li>赤字最近擴大，原因是國防支出加速和企業減稅退稅（企業拿到退稅在大舉投資）——她認為兩個都不是壞理由。'
             '長期仍看赤字縮小，達到財長 Bessent 的目標：<b>赤字占 GDP 3%</b>（字幕寫 2018 年底，依上下文應為 2028 年）。</li>'
             '<li>政府債務約 40 兆美元、GDP 約 30 兆，債務占 GDP 接近歷史高點；但<b>政府債務對股票市值的比例接近歷史低點</b>'
             '（只有 1990 年代末更低），代表支撐債務的能力其實改善了。</li>'
             '<li>她強烈反對財富稅，認為會打擊創新，讓中國取得優勢。</li>'
             '<li>貨幣供給 M2 年增率略高於 5%（四年年化只有 1.7%），不是會造成通膨的增速；'
             '貨幣流通速度正在走平，她發現唯一相關的是勞動參與率——嬰兒潮退休、移民離開若持續，流通速度會繼續走平或下降。</li></ul></div>')

    b.append('<div class="rpt-sec"><h2>五、8 月經濟數據（錄影當天是就業報告日）</h2>'
             '<div class="rpt-scroll"><table class="rpt-tbl"><thead><tr><th>項目</th><th>數字</th><th>她的解讀</th></tr></thead><tbody>'
             '<tr><td>非農就業</td><td class="v">16.2 萬</td><td>預期只有 5～5.5 萬，強勁</td></tr>'
             '<tr><td>家戶調查就業</td><td class="v">45 萬以上</td><td>涵蓋更多小企業，8 月經濟很熱</td></tr>'
             '<tr><td>失業率</td><td class="v">4.1%</td><td>持平</td></tr>'
             '<tr><td>16～24 歲失業率</td><td class="v">8.5% → 9.1%</td><td>入門職缺確實在減少；鼓勵年輕人用 AI 自己創業</td></tr>'
             '<tr><td>平均時薪年增</td><td class="v">3.1%</td><td>生產力 2～3% 下，工資不會推升通膨</td></tr>'
             '</tbody></table></div>'
             '<ul style="margin-top:12px"><li>她不認為 AI 會消滅就業：企業支出平台 Ramp 的調查顯示，'
             '越積極使用 AI 的公司，員工人數成長越快。勞動力因退休和移民減少，未來可能談到缺工。</li>'
             '<li>房市：新屋待售量本來以為會繼續下降，卻又回升（建商在利率短暫下降時又開始投機性興建），新屋價格仍在下跌。</li>'
             '<li>資本支出：非國防資本財（不含飛機）在疫情後突破了 20～25 年的區間，成長速度接近 1990 年代網路革命時期；'
             '她認為從 ChatGPT 之後才剛開始，還有好幾年。</li>'
             '<li>貿易逆差擴大是美國成長比其他國家快的必然結果，會由資本流入抵銷。</li></ul></div>')

    b.append('<div class="rpt-sec"><h2>六、市場指標與資產</h2>'
             '<ul><li><b>比特幣／黃金</b>：看起來正在翻轉向上（她自己也說「但願不是名言」）；兩者相關性處於歷史低點。'
             '她看好比特幣是技術革命、新的全球貨幣體系、新資產類別三件事。</li>'
             '<li><b>S&amp;P 500／油價</b>：在 1990 年代末以來區間的頂部，若油價如她預期下跌，會大幅突破。</li>'
             '<li><b>S&amp;P 500／黃金</b>：擔心赤字的空頭預期會像 1970 年代一樣崩跌，她完全不同意，認為會往反方向走。</li>'
             '<li><b>AI 不是鐵路泡沫</b>：1800 年代有 200 家鐵路公司破產，因為當時是先蓋再等營收；'
             'AI 現在就有大量營收與很高的資本報酬——她舉例 Anthropic 同意每 GW 算力付 500 億美元，'
             '而 Musk 團隊的建置成本約在 250～290 億美元之間。</li>'
             '<li><b>創造性破壞</b>：每個產業都會有被顛覆的公司（例如押注傳統軟體的私募信貸），'
             '會出現交易對手風險——這也是她認為比特幣和黃金都有「保險」角色的原因。'
             '不過目前銀行信用違約交換和高收益債利差都很低，沒有系統性問題。</li></ul></div>')

    b.append('<div class="rpt-view"><h2>Cathie Wood 怎麼看：結論與建議</h2>'
             '<h3>為什麼是現在</h3><ul><li>科技革命進入加速期，而經濟數據開始出現共識沒預料到的變化；'
             '新任聯準會主席在 Jackson Hole 明確表態看整體 PCE。</li></ul>'
             '<h3>她的判斷（依她自己強調的程度）</h3><ul>'
             '<li>全球實質成長會大幅加速，至少加倍。</li>'
             '<li>通膨會比預期低很多、可能轉負；油價可能跌回 30 美元。</li>'
             '<li>長債殖利率可能低於短債（曲線倒掛），但那是通縮型成長、不是衰退。</li>'
             '<li>美元走強、金價回落；比特幣相對黃金走強，比特幣可以同時是避險和追求風險的資產。</li>'
             '<li>資本支出週期才剛開始，還有好幾年。</li></ul>'
             '<h3>她自己點名的風險與觀察點</h3><ul>'
             '<li>如果整體 PCE 繼續上升，聯準會會再緊縮。</li>'
             '<li>如果實質成長超過 7% 而通膨只是微幅負值，10 年債殖利率會上升。</li>'
             '<li>創造性破壞造成的交易對手風險。</li>'
             '<li>財富稅。</li>'
             '<li>勞動參與率下降會讓貨幣流通速度繼續走平。</li></ul>'
             '<h3>操作建議</h3><ul><li>節目沒有給具體買賣建議；她預告接下來幾週會發一封信談這些主題。</li></ul></div>')

    b.append('<div class="rpt-check"><h2>她錄影之後發生了什麼（隆中對自己的資料）</h2>'
             '<div class="sub">這段是我們系統的資料，不是她的觀點；日期都標在旁邊。影片是 9/4 錄的，只能看方向是否一致，不能當成她預測錯。</div>'
             '<div class="rpt-scroll"><table class="rpt-tbl"><thead><tr><th>她說的</th><th>後來的資料</th><th></th></tr></thead><tbody>'
             '<tr><td>整體 PCE 若繼續上升，聯準會會再緊縮（她列為風險）</td>'
             '<td>聯準會 9/16 升息一碼到 3.75%～4%（9/17 總經筆記已對過官方聲明）</td><td><span class="tag mid">風險成真</span></td></tr>'
             '<tr><td>今年長債殖利率平均約 4.4%，可能在這附近打底</td>'
             '<td>美 10 年債 5.17%（9/25，較前一週 +0.16）</td><td><span class="tag no">方向相反</span></td></tr>'
             '<tr><td>殖利率曲線在變平、往倒掛靠近</td>'
             '<td>10 年減 2 年 +0.32%（9/28，較前一週 +0.12），曲線在變陡</td><td><span class="tag no">方向相反</span></td></tr>'
             '<tr><td>信用市場平靜，沒有系統性問題</td>'
             '<td>系統每週判讀（9/29）美股「偏保守」：長債破 5%、信用利差走闊</td><td><span class="tag no">方向相反</span></td></tr>'
             '<tr><td>通膨會比預期低很多</td>'
             '<td>美國 CPI 年增 3.35%（8 月，較上月 +0.05）；下一次 CPI 10/14 公布</td><td><span class="tag mid">還看不出來</span></td></tr>'
             '</tbody></table></div>'
             '<p style="font-size:13px;line-height:1.8;color:var(--ink);margin:12px 0 0">'
             '另外，看她的預測可以搭配 ARK 基金自己的紀錄：隆中對 ARK 追蹤頁的 10 年回測（2016-10-03～2026-09-25）'
             'ARKK 年化 +16.1%、最大回撤 −80.9%；同期 QQQ 年化 +21.1%、最大回撤 −35.1%。'
             '同一段期間 ARKK 年化報酬比 QQQ 低 5 個百分點，最大回撤是 QQQ 的兩倍多。</p></div>')

    b.append('<div class="rpt-note">來源：ARK Invest《In The Know》，Cathie Wood，' + REC_DATE + ' 錄製（53 分鐘）'
             f'　<a href="{VIDEO}">{VIDEO}</a><br>'
             '內容依 YouTube 英文自動字幕人工整理、改寫成中文；圖表只取她口述的數字重畫。'
             '字幕錯字已依上下文更正：主席名 Warsh（字幕作 Worsh）、赤字目標年份 2028（字幕作 2018）、'
             'neocloud 業務（字幕作 NEO plowed）、年輕人失業率 8.5%→9.1%（字幕作 85 to 91）。<br>'
             '「後來發生什麼」那段取自隆中對：每週總體報告（利率、CPI、每週判讀）、9/17 總經筆記、ARK 追蹤頁（9/28 更新）。'
             '以上是她的個人觀點整理，不是投資建議。</div>')
    sub = f"ARK Invest《In The Know》・{REC_DATE} 錄製・53 分鐘"
    return ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(TITLE)}</title><style>" + BASE_CSS + CSS
            + "</style></head><body><div class=\"wrap\">"
            + header("gdp", TITLE, sub, [], eyebrow="MACRO NOTE")
            + "".join(b) + "</div></body></html>")


def main(out=None):
    html = build()
    dst = out or op.archive(f"{REC_DATE}_CathieWood_科技革命與通膨利率.html", sub="總經與盤勢")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"已存 {dst}（{len(html):,} 字）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
