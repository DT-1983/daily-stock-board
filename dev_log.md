# daily-stock-board 開發日誌

> 產業鏈看板（remote `board`=DT-1983/daily-stock-board、GitHub Pages）。記錄自建功能的重大變更；歷史細節見 git log。

## 2026-07-17 · 七鏈產業深度解讀系統 + 每月本機自動

**看板守備清單 top 6→8**
- `screen.py` TOPN=8、`chain_themes.py` TOP_N=8：每鏈守備清單多顯示 2 檔（tw-board 的 STOCK_LIST 帶動每日分析涵蓋到第 7、8 檔）。

**Gemini 一段題材（每週自動）**
- `chain_themes.py` 一句 →三欄 dict（catalyst/risk/watch），`board_html._theme_html` 做成可展開；weekly-screen 產出、board_html 渲染，舊字串相容。

**七鏈「📖 產業深度解讀」全螢幕彈窗（本日主軸）**
- 內容管線：`chain_reports_src/reports_data/<slug>.json`（研究資料）→ `chain_reports_src/render_reports.py`（可攜、unescape `&lt;b&gt;`）→ repo 根 `chain_reports.json`（保留未更新鏈舊內容）。
- UI：`board_html.py` 每鏈注入 `<button class="rptbtn">` + `.rptmodal` 全螢幕彈窗；CSS 前綴 `.rpt` 不碰既有樣式；手機表格「標籤左欄 absolute + 內容右欄」（避免 flex 把 `<b>` 拆成偽欄位）；多空用綠`多`/紅`空`色塊各一行。
- 內容：TL;DR/產業規模/競爭格局市佔/價值鏈/催化劑/多空 bull-bear/風險/觀察/8+8 檔個股獨立解讀。
- 六鏈（矽光子·機器人·低軌·電力核能·太陽能·Bitcoin）由平行 general-purpose Agent 上網查證 2026 資料 → 結構化 JSON → 統一模板；AI 伺服器維持人工 bespoke（多雲端 capex 表）。
- 報告另存 obis `04_AI Report/Investment/產業鏈深度報告/`。

**每月自動更新（本機、Claude 品質）**
- 用戶要求不犧牲品質 → 不走 Gemini 自動版；改本機排程叫 headless Claude（同早報機制 ClaudeMorningBriefing）。
- Windows 排程 `RefreshChainReports`：每月 1 號 09:23 跑 `C:\Users\Mophy\AI\refresh_reports_monthly.cmd`（headless `claude -p "重跑產業深度報告"`）。
- 指令＝全域 skill `refresh-chain-reports`（研究→渲染→部署→驗證；互動用背景 Agent、headless 用同步）。
- `monthly-report-reminder.yml`：每月 1 號 09:07 Telegram 提醒（+ 電腦沒開的手動備援）。

**踩坑**：tw-board 結尾 `git push || echo 略過` 吞掉 push 失敗 → 部署途中若我 push，發佈 index.html 被拒卻顯示 success、線上靜默不更新。**部署期間絕不 push**。

## 2026-07-18 · 巴菲特價值清單加台股分頁 + 俗貴價核對

**台股分頁（美/台 toggle）**
- `data_tv.get_buffett_snapshot_taiwan`（TV taiwan、TWSE+TPEX、市值 TWD、ticker 帶 .TW）；stage2 的 yfinance `fetch_fundamentals` 逐檔重抓 → 台股完全重用評估邏輯、下游零改。
- `buffett_scan --markets us,tw`：併掃標 market；FinMind TaiwanStockInfo 補中文名。台股門檻 50億（180 檔過關取 76 檔 BUY/WATCH）。
- `buffett_html`：美/台 toggle 分頁（同主看板 UX）、台股去 .TW 顯示代號+中文名+TWD。
- weekly-screen 巴菲特步驟加 FINMIND_TOKEN + `--tw-max-candidates 200`。

**排序：EPS估降殿後** — 洪瑞泰「EPS 變差＝俗價假便宜」，✅體質過關浮上、⚠️EPS估降沉底。

**俗貴價核對（對第一手講稿）** — 詳見記憶 hongruitai_method：
- 爬 mikeon88 官方 blog 確認：俗價 EPS×12（買）、貴價 EPS×30（賣）＝洪瑞泰官方，跟我們一致。
- 合理價 ×20 是我們自補中點、洪瑞泰無官方定義 → **拿掉合理價**，只留買/賣兩線（🟢買進/🟡觀望/🔴太貴）。

## 2026-07-28 · 績效總體檢 + 模擬倉調整（依回測，非短期績效）

**一、實盤 4 週（6/30–7/26）**：巴菲特 +6.7%（唯一正）｜SPY −1.1%｜七鏈 −2.9~−13.4%｜趨勢倉 −20.9%｜Pairs 爆倉。

**二、Pairs 根因＝程式 bug 不是虧損**：pre-v7 sizing 用「股數×HR」而非名目金額拆分（`qty1=qty2*hr`），
對 AVGO_HYG(hr=4.08) 造成 3–7 倍槓桿 → 虛擬帳戶 10,000 → −15,124（虧 251%，數學上不可能）。
v7 已改正確拆分，但負現金讓 alloc_cap 也變負 → 報酬率正負號翻轉。已加護欄 + `/pairs_reset`（待用戶執行）。

**三、SuperTrend 診斷（關鍵）**
- 日線 32 次賣出有 **24 次(75%)賣完股價續漲**（+8.2%/10日）；買進訊號正常（+10.4%/20日）→ **問題單獨在賣出**
- 同池同期：日線 **65 次**訊號 vs 週線 **10 次**，多出來的是雜訊（AI 股日內波動 > ATR10×3 軌道寬）
- 2026 YTD 回測（13 檔池）：買進持有 +78.6%/MDD−14.3% ｜ 週線 +71.1%/−16.1%/8次 ｜ 日線+2天確認 +36.4%/−20.2% ｜ 日線 +17.9%/−28.9%/47次

**四、5.5 年回測（含 2022 空頭）—— 更正先前「dominated」的說法**
- QQQ（零選股偏差）：買進持有 +128.3%/MDD−35.1% ｜ 週線 +73.5%/−17.6%/9次 ｜ 日線 +70.8%/−15.5%/44次
  · **2022：買進持有 −32.6% vs 週線 −11.7%** → 趨勢規則在指數上確實有效，是「多頭少賺換空頭少賠」的取捨，非 dominated
- **同規則放到 13 檔高波動個股：MDD 反而更大**（日線 −76.6%、週線 −65.9% vs 買進持有 −59.1%）
  → **結論：SuperTrend 對指數有效、對高波動個股無效**
- 七鏈（現時持股回推，有倖存者偏差，只看行為特徵）：巴菲特 MDD **−20.0%**、2022 **+7.5%**（唯一全天候）；
  AI 電力/核能 2022 **+25.4%**（更正「七鏈都是同一個 AI 賭注」的說法）；Bitcoin→AI MDD **−94%**；
  太陽能 5.5 年輸 SPY 且回撤兩倍；產業鏈精選 MDD −55.9%（比單一鏈更差＝過度集中）

**五、實作調整**
1. 趨勢倉 → **週線** SuperTrend（`TREND_WEEKLY`，公式參數不動，只換 K 棒週期）；確認天數 2→1
2. 新增 **指數擇時倉**（`rebalance-timing`）：QQQ 週線綠燈持有精選、紅燈全現金；接入 tw-board 每日排程
3. **Bitcoin→AI 限重 10%**（`BTC_MAX_WEIGHT`，跨鏈主倉皆套用，`_capped_weights` 超額按比例分配）
4. 太陽能**不動**——輸 SPY 是有倖存者偏差的回測結果，無結構性理由不砍（避免追回測過擬合）

**原則**：模擬倉是實驗器材，只改「有結構性證據」的（訊號雜訊、風險集中），不追回測報酬。
