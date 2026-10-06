# -*- coding: utf-8 -*-
"""把燈號戰情室（本機 /room）開成獨立視窗：無網址列、工作列有自己的圖示（2026-10-07，Leo 要桌面捷徑）。
優先 pywebview（有裝才用），否則 Edge／Chrome 的 --app 模式。key 每次現讀 .env、不寫進任何檔案；
連本機 127.0.0.1:8030，不經 Cloudflare 通道（比手機走通道少一趟來回）。
機器人（discord_bot，8030）沒在跑就跳提示。用 pythonw 執行不會跳黑色視窗。"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8030


def _url():
    try:
        from dotenv import dotenv_values
        tok = (dotenv_values(os.path.join(HERE, ".env")) or {}).get("LOOKUP_TOKEN", "") or ""
    except Exception:                                        # noqa: BLE001
        tok = ""
    return f"http://127.0.0.1:{PORT}/room" + (f"?key={tok}" if tok else "")


def _alive():
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=3).read()
        return True
    except Exception:                                        # noqa: BLE001
        return False


def main():
    if not _alive():
        msg = "戰情室服務（discord_bot，8030）沒有在跑。請先啟動它，或等健檢自動重啟。"
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "戰情室", 0x10)
        except Exception:                                    # noqa: BLE001
            print(msg)
        return 1
    url = _url()
    try:
        import webview
        webview.create_window("燈號戰情室", url, width=1500, height=900, min_size=(600, 500))
        webview.start()
        return 0
    except ImportError:
        pass
    for exe in (shutil.which("msedge"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", shutil.which("chrome"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if exe and os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1500,900"])
            return 0
    import webbrowser
    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
