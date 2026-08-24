# -*- coding: utf-8 -*-
"""等 FinMind 每小時額度恢復後自動重掃，並把磁碟快取灌滿。

2026-08-25 建立。緣由：一小時內跑了三次全市場掃描（每次約 400 次請求），
免費額度用完 → 台股官方盈再率從 41 檔掉回 11 檔。
額度是每小時重置，與其人工猜時間，不如探到通了再跑。
掃描本身會把每筆成功結果寫進 .fm_cache/，之後重跑就不再消耗額度。
"""
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
DEADLINE = time.time() + 2 * 3600          # 最多等兩小時，等不到就明講，不要無限掛著

while True:
    import importlib
    import buffett_screener as B
    importlib.reload(B)                     # 重載才能清掉上一輪的限流旗標
    data = B._fm("TaiwanStockBalanceSheet", "2330")
    if data:
        print(f"[{time.strftime('%H:%M')}] 額度已恢復（台積電 {len(data)} 筆），開始重掃")
        break
    if time.time() > DEADLINE:
        print(f"[{time.strftime('%H:%M')}] 等了兩小時仍被限流，放棄。"
              f"買進清單維持現狀（部分台股標 capex_fallback），不要當成公司資料不足。")
        sys.exit(1)
    print(f"[{time.strftime('%H:%M')}] 仍被限流，5 分鐘後再試")
    time.sleep(300)

r = subprocess.run([sys.executable, "buffett_scan.py",
                    "--max-candidates", "200", "--tw-max-candidates", "200"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[-3000:] if r.stdout else "")
if r.stderr:
    print("STDERR:", r.stderr[-1500:])
sys.exit(r.returncode)
