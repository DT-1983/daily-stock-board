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
