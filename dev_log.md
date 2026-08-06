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
2. ~~新增指數擇時倉~~ → **同日依用戶指示移除**（`market_is_green()` 函式保留備用，未接任何倉）
3. **Bitcoin→AI 限重 10%**（`BTC_MAX_WEIGHT`，跨鏈主倉皆套用，`_capped_weights` 超額按比例分配）
4. 太陽能**不動**——輸 SPY 是有倖存者偏差的回測結果，無結構性理由不砍（避免追回測過擬合）

**原則**：模擬倉是實驗器材，只改「有結構性證據」的（訊號雜訊、風險集中），不追回測報酬。

### 同日修正（依用戶指示）
- **產業鏈精選 → 產業鏈全**：`chain_select_union()` 改回七鏈完整守備清單聯集，**13 檔 → 48 檔**。
  依據正是本次回測發現「每鏈取前 2」過度集中（MDD −55.9%，比單一鏈 −36~−39% 還差）。
  單一股權重 **25% → 2.2%**。`_btc_caps` 同步改用整條鏈成員（Bitcoin 實際權重 6.2% < 10% 上限）。
- **移除指數擇時倉**：用戶不採用；`market_is_green()` 保留備用。
- 守備清單維持 **8+8**（`screen.py TOPN=8` 不動）。

---

## 2026-07-31 — 巴菲特清單：補回洪瑞泰缺的三條件

### 起因
用戶拿洪瑞泰七條原則來核對系統實作：GDP高點減碼／GDP低點進場／俗買貴賣／
行業地位穩固／ROE穩定／盈再率<80%／配息率>40%。

### 核對結果（改之前）

| 條件 | 原狀 |
|---|---|
| 俗買貴賣 | ✅ EPS×12 / ×30 |
| 盈再率 < 80% | ✅ 硬關卡 |
| ROE 穩定 | ⚠️ 有算 `roe_pass_years` 但訊號只看當年 |
| 行業地位穩固 | ⚠️ 龍頭#N 只當頁面標籤，不篩 |
| 配息率 > 40% | ❌ `payout_ratio` 有抓進 DB，**零行程式用它** |
| GDP 高/低點 | ❌ 看板 repo 完全沒有 |

**GDP 更正**：GDP 模組在 **TradingBot**（`gdp.py`：World Bank + Philly Fed SPF + 中經院），
但**純資訊面** —— `/gdp` 指令 + `gdp_line` 貼在報告抬頭 + 每季提醒，
**沒有接到任何買賣訊號或部位調整**。「GDP 給你看，但系統不照它動作」。

### 實作（commit f052a8d）

1. **配息率 ≥ 40% 納入品質關**（`PAYOUT_MIN = 0.40`）
   - `payout` 有數字 → 照門檻；無數字但有配息 → 放行（資料缺）；完全不配息 → 擋
2. **ROE 穩定改硬條件**：`roe_pass_years >= ROE_YEARS(3)`，近 4 年至少 3 年 ROE≥15%
3. **拿掉合理價**（用戶先前已指示「不需要合理價 都可以直接拿掉」，當時只改了頁面沒改邏輯）
   - WATCH 上界 `fair_price(EPS×20)` → `exp_price(EPS×30)`，`HOLD` 訊號移除
   - **連帶**：`buffett_sp500.py` Stage1 預篩 PE 門檻同步 20→30，
     否則 PE 20~30 的標的永遠進不了 Stage2，改動等於空轉
   - 頁面說明（🟡觀望＝俗價~貴價）與程式邏輯**這下才一致**
4. 頁面新增：**配息率欄**、ROE 欄後方 **n/4 達標年數**、品質關說明列

### ⚠️ 配息率門檻的已知副作用（用戶知情下選擇 A：忠於原方法）

拿改前的 203 檔美股實測 → **只剩 87 檔（43%）通過**。
被刷掉的含 GOOGL(4.3%)、NVDA(0.6%)、AAPL(12.6%)、HON(36%)、PDD(0%)。

**這是結構性誤殺不是公司變差**：美國公司用**庫藏股買回**還錢給股東，
yfinance `payoutRatio` **只算現金股利不算買回**（蘋果 2025 買回 >$900億，配息率仍 12.6%）。
洪瑞泰這條是**為台股設計**（台灣公司少做買回，現金股利是唯一證據）。

提了三案：A 照原規則 / B 美股改「股東回報率＝(股利+買回)/淨利」/ C 台股套美股不套。
**用戶選 A** —— 忠於洪瑞泰原方法，接受美股清單瘦身、偏向金融/公用/傳產。
（若日後想改，B 案的實作點在 `buffett_screener.py` 的 `payout_ok`）

### 沒做的

- **GDP 擇時**：用戶先前已明確「不用指數擇時」，GDP 擇時本質同一件事，
  且 GDP 是落後指標（季度、還會修正）。維持只顯示不動作。
- **行業地位當硬條件**：龍頭排名是「同 sector 市值前 3」的粗糙代理，
  當硬門檻會誤殺中型股（台股尤甚，候選才剛放寬到 200 檔）。留著當標籤。

### 同日：全掃描實測 + 挖出上櫃代號 bug

**第一輪（A 案三關全開）**：美 **203 → 16 檔**（我先前只套配息率估 87，低估了三關疊加）。
剩下的 16 檔：外國 ADR（NVO/PBR/ITUB/UGP/CIG）、航運（BWLP/HAFN/TRMD）、
資管+MLP（APAM/TROW/MPLX/BSM），**一般美企只剩 ACN/DOX/WU/CPB 四檔，科技股全滅**。
→ 這頁的實際定位已變成「台股清單 + 美股附帶」，用戶知情。

**🔴 挖出 bug：上櫃股(TPEX)代號後綴錯了**（commit d6f8eb4）
- log 裡 11 個 404 全是台股 → 查到 `data_tv.py` 對 853 檔台股**一律掛 `.TW`**
- 實際：TWSE 596 檔用 `.TW` ✅、**TPEX 257 檔要用 `.TWO`** ❌ → yfinance 全 404
- **靜默失敗**：404 被 except 吞掉印個 SKIP，外觀等同「基本面不合格」。從台股功能上線就存在。
- 修法：`df['exchange'].map({'TWSE':'.TW','TPEX':'.TWO'})`；
  連帶 `buffett_scan` / `buffett_html` 剝後綴改 `rsplit('.',1)`

**第二輪（修完）**：美 16 / 台 **45 → 76**（新進 31 檔全是上櫃），404 歸零。
新進榜含 **鈊象3293（ROE 99.2%／盈再 8.4%／配息 73%）**、元太8069、
巨漢6903（盈再 1.5%）、瑞穎8083、普萊德6263 —— 教科書級洪瑞泰標的，
**先前全部被靜默丟掉**。

**教訓**：外部 API 的 404/例外若只印 SKIP，會偽裝成正常的業務結果。
台股 TWSE/TPEX 後綴不同是 yfinance 常見坑。

---

## 2026-07-31 — 看板判讀層搬回本機（Max plan），Actions 不再呼叫 LLM

### 起因：先查帳單，不憑印象

用戶問「看板每日產業評論具體是什麼？可以改 Max plan 嗎？」
我先答「Flash 很便宜，搬家不划算」，用戶要求**查真實花費** —— 結果打臉兩次。

**查法（可重用）**：BigQuery billing export
`data-collector-489107.billing_export.gcp_billing_export_v1_01A5A5_21B1E4_017086`，
`bq` 已登入可直接查。按 `project.name` + `sku.description` + 日期分組。

**歸因鐵證**：`gemini 3 flash` 花費在 **7/20、7/26、7/27 歸零**，
那正好是週日/週一 —— cron 是 `2-6`（週二~週六）。不是統計相關，是完全對應。

| 日 | 星期 | 看板 |
|---|---|---|
| 7/23 | 四 | NT$23.40 |
| 7/26 | **日** | **NT$0.68** |
| 7/27 | **一** | **NT$0.00** |
| 7/28 | 二 | NT$25.15 |

→ **每運行日 NT$24 × 21 日 ≈ NT$500/月**

### 🔴 我犯的兩個錯

1. **幣值**：帳單 `currency` 欄位是 **TWD**，我當成 USD 又乘 32.3，
   把 NT$500/月 講成 **NT$16,000/月**，並基於錯的數字給了「搬家省 19 萬」的建議。
   舊記憶 `gemini_cost_spike_2026-07` 同一個錯誤（寫「$2,027.86 USD ≈ NT$66,000」）
   已沿用兩週，一併更正。
2. **7/18 的省錢預測錯 170 倍**：當時用牌價推算「Flash 便宜 33 倍 → NT$3/月」，
   實測只省 **3.7 倍**（NT$89/日 → NT$24/日）。實付單價 **NT$95.6/百萬 output token**，
   遠高於牌價 $0.30。原因是 `main.py` 的 agent pipeline 每檔股票跑好幾輪，
   10 天燒 170 萬 output token。**換模型省多少要事後查帳單，不能用牌價推算。**

用戶在知道實際只有 NT$500/月 後，仍決定搬。

### 實作

```
本機 08:30（接在 ClaudeMorningBriefing 之後，週二~週六）
  briefing.ps1 → 推完早報 → board_analyze_daily.cmd
      us_analyze.py  49 檔 → 依鏈分批 7 次 claude → reports/report_*.md
      tw_analyze.py  37 檔 → 依鏈分批 7 次 claude → tw_analysis.json
      git push board
Actions 09:00（cron 0 0 → 0 1）
  只讀報告 → board_html.py → 發佈 Pages（不再呼叫任何 LLM）
```

- **新增 `llm_board.py`**：判讀層轉接器。prompt **走 stdin** 不走命令列參數
  （避開長度上限與跳脫字元地雷）。`BOARD_LLM=claude|gemini` 可切，Gemini 留備援。
- **新增 `us_analyze.py`** 取代 `main.py`：yfinance 算均線/乖離率/趨勢強度/量比（免費），
  判讀依鏈分批。輸出必須符合 `board_html.parse_report()` 契約 —— 已實測驗證：
  摘要 49 筆評分抓到、56 個個股區塊、CHAIN_MAP 49/49 對得到。
- **改 `tw_analyze.py`**：`analyze()` 拆成 `collect()` + `analyze_chain()`，
  呼叫數 **86 次/日 → 14 次/日**。
- **改 `tw-board.yml`**：移除美股/台股兩個 LLM step（含 GEMINI_API_KEY / TAVILY_API_KEYS），
  改為檢查本機產出是否存在；報告逾 3 天未更新發 `::warning::`。
- **改 `briefing.ps1`**：附加呼叫，放在 Telegram 推送**之後**，兩者失敗互不影響。
  附加時用 `UTF8Encoding($false)` + `AppendAllText`，避免 PS5.1 的 `Add-Content`
  在檔案中間再插一個 BOM（檔首既有 BOM 已驗證未破壞）。

### 踩到的坑

- **跨鏈重複**：NVDA/AMD/MU/AMZN/ANET/TER 同時屬於多條鏈，
  49 個代號會產出 **56 個 `##` 區塊** → 看板同一檔渲染兩張卡。已按評分取高者去重。

### 取捨（用戶知情）

- 放棄 Tavily 新聞層（輿情情緒/風險警報/利好催化/最新動態），
  改為精簡的「結論 + 理由 + 觀察條件 + 風險 + 空手者/持有者建議」。
- **電腦沒開機就沒有當日判讀**；Actions 沿用前一日報告並發 warning。

## 2026-08-04 · 投資資訊首頁改版 + GDP 觀察頁 + 修今日看板 workflow 失敗

### 改版（用戶拍板三決定：儀表板當首頁／加 14:05 排程／新聞用鉅亨）

```
首頁 index.html（新：大盤行情 + 鉅亨頭條10條 + 分頁入口動態摘要）
├── board.html      產業鏈看板（原 index.html 搬家）
├── buffett.html    巴菲特清單
├── portfolios.html 策略賽馬
├── earnings.html   財報分析
└── gdp.html        GDP 觀察（新）
```

- **NAV 中心化**：六頁導覽統一定義在 `board_theme.NAV`，各頁不再自維護
  （board_html 原本硬編 4 連結、buffett/portfolio 各一份 NAV，全數收攏）。
- **新增 `gdp_fetch.py` → gdp_data.json**：
  美國實際＝FRED CSV（GDPC1 自算 SAAR）、預測＝Philly Fed SPF（移植 TradingBot/gdp.py）；
  台灣實際＝主計總處 nstatdb API（自動）、預測＝`gdp_manual.json` 手動維護，
  asof 超過 120 天自動推 TG 提醒（主計總處每季 2/5/8/11 月發新聞稿，只有 PDF）。
- **新增 `gdp_html.py` → docs/gdp.html**：洪瑞泰「GDP 高點賣股票、不買股票」提醒燈，
  高點判定＝近 8 季實際＋預測取最大：未來=尚未到頂(綠)/最新季=接近高點(黃)/過去=已過高點(紅)。
  維持既有定案：只顯示不接買賣訊號。首跑結果：美國已過高點(2025-Q3)、台灣接近高點(2026-Q1 14.55%)。
- **新增 `market_fetch.py` + `home_html.py`**：指數 7 檔（美 4+加權+VIX+美元/台幣）走 yfinance；
  頭條走鉅亨 JSON API（`api.cnyes.com/media/api/v1/newslist/category/{tw_stock,wd_stock}`）各 5 條。
- **新增 `market-home.yml`**：週一~五 14:05（UTC 06:05）台股收盤後重建首頁，純 yfinance 零 LLM。

### 修今日 09:00 workflow 失敗（用戶轉來 GH 失敗信）

1. **ImportError CHAIN_ICON/TW_NAME**：昨天 v2 扶正成 board_html.py 時漏了
   alert_telegram.py 還從它 import 這兩個名字 → 已在 board_html.py re-export。
2. **`ls -t` 挑報告失準**：checkout 後所有檔 mtime 相同，今天實挑到 6/24 舊報告。
   檔名帶日期 → 改 `ls | sort | tail -1`；逾期警告同步改由檔名取日期（原 mtime 算法在
   Actions 上永遠是 checkout 時間，等於從未生效過）。

### 踩到的坑

- FRED/主計總處都會擋 python 的 TLS（前者 reset 連線、後者憑證缺 SKI 被 3.13 拒收），
  curl 卻都通 → `_get_text_curl_fallback()`：requests 失敗改走 subprocess curl。
  curl 回傳**不可用 text=True**（Windows 會拿 cp950 解 UTF-8，reader thread 直接炸）。
- 主計總處 2026-05-29 新聞稿的 Q3/Q4 逐季預測網路查不到（在 PDF 表格內），
  gdp_manual.json 只填了查證過的 Q2 10.83% 與全年 9.64%，不瞎編；8 月中新版發布時提醒會叫人補。
- cp950 印 emoji 炸 print：board/portfolio/buffett/gdp/market/home 全部補
  `sys.stdout.reconfigure(encoding="utf-8")`。

### 同日迭代（用戶看圖回饋）

- GDP 頁季度數字改**橫向排列**（跟 X 軸同方向，一季一格、預測黃虛框，手機橫滑）。
- 首頁行情定版 **2 排 × 4**：美股 S&P/那斯達克/道瓊/費半｜台股加權/三大法人買賣超/美元台幣/美債10Y殖利率。
  - 法人＝證交所 `BFI82U` API（單位元→億；合計+外資+投信）；**約 15:00 才公布當日值**，
    下午排程 14:05 → 15:10 順延。VIX 由美債殖利率取代（用戶授權我建議第 8 格）。
  - ⚠️ yfinance 的 `^TNX` **直接報 %**（4.74=4.74%），不是傳統 10 倍報價，別除以 10。

### 接回新聞層（零成本版）+ 財報加 3 檔（2026-08-04 下午）

- 用戶質疑判讀理由「都是 MA5>MA10」——正確：7/31 砍 Tavily 後 LLM 只剩技術面+一個營收數字，
  reason 四個詞其實同一條收盤價序列講四遍。
- 接回新聞層，**零成本**（vs Tavily 方案約 NT$950/月）：
  - 美股：`yf.Ticker(code).news` 近 7 天取 3 條（us_analyze._news）
  - 台股：鉅亨 ESS 關鍵字搜尋 `ess.api.cnyes.com/ess/api/v1/news/keyword` 近 5 天 3 條，
    標題要清 `<mark>` 標籤（tw_analyze._news）
  - prompt 加規則：有新聞須納入判斷、與技術面矛盾要指出不硬湊；沒附新聞不准提新聞
  - 端到端驗證過：NVDA 判讀有引用估值重評新聞並點出「多空矛盾訊號」
- 財報追蹤 US_WATCH 加 MU（美光）/AVGO（博通）/PLTR（Palantir），共 7 檔；
  三張圖卡已產出、earnings 索引頁 7 份。

### 七鏈深度報告 8 月更（同日晚間，回應「8月有跑嗎?」）

- **8/1 排程其實沒跑成**：Task Scheduler 回報成功(0)，但 log 只有一行 `end (exit 3)`、
  連 start 都沒寫，chain_reports.json 從 7/17 上線至今沒動過。根因＝
  `refresh_reports_monthly.cmd` 含中文（同 8/1 board_analyze_daily.cmd 的坑，當時漏了這支）。
- 修法：.cmd 全英文、prompt 改 ASCII 斜線指令 `/refresh-chain-reports`；乾跑驗證 start/end 都有寫。
  **教訓：所有給 Task Scheduler 跑的 .cmd 一律全英文，一支都不能漏。**
- 8 月份已在對話內補跑：7 個研究 Agent 平行（各鏈 WebSearch 查證 2026/8 資料）→
  reports_data/*.json → render → push → 線上驗證 rptbtn=7。
  AI 伺服器 bespoke 版一併換成標準模板（資料新鮮度 > 客製表格）。

## 2026-08-05 · 第 8 條產業鏈上線：玻璃基板/TGV

- **緣起**：7 月底用戶貼玻璃基板文章，當時研究完停在「要我怎麼做?」沒人拍板，
  對話壓縮後斷線。用戶追問「之前有說要做第八條為什麼沒做了」→ 補做。
  教訓：**懸而未決的提案要落成待辦，不能停在問句。**
- **設計**：獨立第 8 鏈（不併 AI 伺服器——併入會在三因子篩選輸給巨頭，永遠隱形）。
  手選池：美 6（GLW/INTC/AMAT/ONTO/CAMT/KLIC）+ 台 12；逐鏈獨立 top8 只跟自己人比。
  `screen.py` 加 `US_MANUAL`（無 ETF 的鏈用手選池）。
- **賽馬排除**：`paper_portfolio.RACE_EXCLUDE`——比賽中途不換賽制，玻璃只上看板+報告。
- **深度報告**（reports_data/glass.json）：誠實原則——每檔標實際進度
  （已試產/送樣中/僅市場歸類），點名南電/景碩是純聯想題材；晶呈是全鏈唯一有真實
  TGV 營收者（篩選器也把它排第一，交叉印證）。時間表 2026 驗證/2027 試產/2028 量產。
- **看板**：CHAIN_ORDER 8 鏈、新 TGV 面板 icon、`if not us and not tw` 跳過條件加
  「有深度報告仍露出」fallback；TW_NAME 補 11 檔中文名。skill 更新為八鏈。

### 🔴 FinMind 限流連環坑（同日）

1. screen.py + tw_analyze 同日連跑 → 撞限流，後三鏈台股全跳過。
2. **根因：`.env` 裡一直有 FINMIND_TOKEN，但 tw_analyze 從沒 `_load_env()`**，
   匿名低額度跑了一個多月沒炸只是因為每天單趟剛好夠用。已修：載入 .env。
3. 限流時 tw_analysis.json 被覆寫成殘缺版（一度只剩 1 檔）→ 加保險絲：
   **產出 < 守備清單 50% 拒絕覆寫**（git 還原救回）。
4. 玻璃鏈首跑 LLM 呼叫暫時性失敗（拿預設觀望 50）→ 單鏈重試回寫成功。
   首日判讀：玻璃台股 8 檔全觀望（33~52 分），與「驗證期」定調一致。

## 2026-08-06 · 產業鏈定位上線（BEST MATCH 拆解功能 #1）

用戶帶來一份第三方「投顧錄音查核」報告（3037 欣興 BEST MATCH），要求拆解四個功能學習導入：
產業鏈定位／財報營收實況／綜合判斷／技術面四指標。逐項評估可行性後，
本次先做**產業鏈定位**（優先順序最高：資料已備妥、複用現有 8 條鏈清單）。

- **新增 `chain_positioning.py`**：讀 `chain_reports_src/reports_data/*.json` 的 `valuechain`
  （8 條鏈 107 檔股票，環節分組），算每檔毛利率（台股 FinMind FinancialStatements／
  美股 yfinance grossMargins）+ 近60日報酬，寫 `chain_positioning_cache.json`。
  快取一天建一次，財報卡引用時純讀快取、不重打 API
  （教訓：8/5 才因為財報卡連續產出撞過 FinMind 限流，這次直接把快取設計進架構裡）。
- **踩坑**：8 條鏈的 `valuechain.stocks` 欄位格式不統一——有的純代號（`"2330"`）、
  有的代號+中文名（`"3105 穩懋"`）、有的代號+英文全名附註（`"TE（T1 Energy）"`）。
  第一版 parser 只用分隔符號切字串沒過濾格式，把「穩懋」「上銀」這些中文公司名
  當成代號去查 FinMind/yfinance，全部 404（32 檔查不到）。
  修法：先砍掉全形/半形括號內容，切完詞後用正則白名單（`^\d{4,5}$` 或 `^[A-Z][A-Z.]{0,5}$`）
  過濾，只留真代號。修完 107 檔全數命中、0 缺漏。
- **整合**：`earnings_infographic.py` 財報卡底部新增「產業鏈定位」區塊，依環節分組列出
  同鏈股票的毛利率+60日報酬，目標股票用青框標記；不在任一鏈上的持股（傳產/金融股）
  優雅跳過不顯示，不硬湊。
- 3037（欣興）實測：6 個環節、鈦昇/友威科/東捷/晶呈科技等玻璃鏈股票全部對得上，
  已上線驗證。

其餘三項（財報營收實況/綜合判斷/技術面四指標）待後續依序動工。
