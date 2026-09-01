# daily-stock-board

個人投資看板：每日產出台美股訊號、財報分析、產業鏈輪動與模擬倉淨值，
發布到 GitHub Pages，並推播到 Telegram / Discord。

**網站**：https://dt-1983.github.io/daily-stock-board/

## 主要頁面

| 頁面 | 內容 |
|---|---|
| `index.html` | 首頁行情總覽 |
| `board.html` | 產業鏈看板（九鏈守備清單 + 深度解讀） |
| `earnings.html` | 財報分析（卡片式，含 AI 敘事） |
| `buffett.html` | 巴菲特價值清單（洪瑞泰方法論：常利 / 盈再率 / 俗貴價） |
| `portfolios.html` | 策略賽馬模擬倉淨值 |
| `rotation.html` | 產業輪動 RRG |
| `chip.html` | 全市場籌碼掃描 |
| `gdp.html` | GDP 觀察 |
| `ark.html` | ARK ETF 追蹤 |

## 自動化

- **GitHub Actions**：首頁行情、模擬倉淨值、每週重篩、季報提醒
- **本機排程**：判讀層（headless Claude）、巴菲特全市場掃描、研究員 / 投資長
  日報。搬到本機是因為 Yahoo Finance 會對 Actions 的雲端 IP 段限流。

## 來源說明

本專案 2026-06-27 以 [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)
（MIT License, Copyright © 2026 ZhuLinsen）為起點建立。

判讀層於 2026-07-31 改為自行實作後，上游程式碼即全面停用；
2026-09-01 已將其 908 個檔案自本 repo 移除，**目前的程式碼不再包含上游內容**。
上游專案的完整授權條款見其原始 repo。
