# -*- coding: utf-8 -*-
"""把戰情室入口開成獨立視窗（無網址列、像桌面 App）。2026-10-06。

優先用 pywebview（跟老墨那種 WebView 桌面版同一類）；沒裝就退回 Edge／Chrome 的 --app 模式（同樣無網址列、獨立視窗、
工作列有自己的圖示）。**不需要安裝任何東西就能用**；要裝 pywebview：pip install pywebview。
連本機 127.0.0.1:8030（discord_bot 常駐的那個服務）；key 現讀 .env，不寫進任何檔案。
用法：pythonw hub_window.py（或雙擊 hub_window.cmd；pythonw 不會跳黑色視窗）
"""
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
    return f"http://127.0.0.1:{PORT}/hub" + (f"?key={tok}" if tok else "")


def _alive():
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=3).read()
        return True
    except Exception:                                        # noqa: BLE001
        return False


def main():
    if not _alive():
        msg = "戰情室服務（discord_bot，8030）沒有在跑，先確認它已啟動。"
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "戰情室", 0x10)
        except Exception:                                    # noqa: BLE001
            print(msg)
        return 1
    url = _url()
    try:
        import webview
        webview.create_window("戰情室", url, width=1280, height=860, min_size=(420, 600))
        webview.start()
        return 0
    except ImportError:
        pass
    for exe in (shutil.which("msedge"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", shutil.which("chrome"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if exe and os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1280,860"])
            return 0
    import webbrowser
    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
