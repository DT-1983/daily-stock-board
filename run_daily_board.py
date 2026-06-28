"""一鍵美股晨會看板:跑分析 → 轉繁中台灣用語 → 存進 obis AI Report/Investment

排程呼叫這支即可(Windows 工作排程器 / 或工具內建 SCHEDULE_ENABLED)。
用法:.venv\\Scripts\\python.exe run_daily_board.py
"""
import subprocess
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def main():
    # 1. 跑分析(用 .env 的 STOCK_LIST,含市場複盤,不推原生通知)
    print("▶ 跑美股分析...")
    subprocess.run([PY, "main.py", "--no-notify", "--force-run"],
                   cwd=HERE, env=ENV, check=False)

    # 2. 找最新報告
    reports = sorted(glob.glob(os.path.join(HERE, "reports", "report_*.md")))
    if not reports:
        print("✗ 找不到報告,中止")
        return
    latest = reports[-1]

    # 3. 轉繁中 .md + 存 obis Investment
    print(f"▶ 轉繁中存檔:{os.path.basename(latest)}")
    subprocess.run([PY, "tw_report.py", latest], cwd=HERE, env=ENV, check=False)

    # 4. 產 HTML 看板（7 鏈分區）+ 存 obis Investment
    print("▶ 產 HTML 看板...")
    subprocess.run([PY, "board_html.py", latest], cwd=HERE, env=ENV, check=False)
    print("✅ 完成")


if __name__ == "__main__":
    main()
