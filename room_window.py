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


def _set_window_icon(title_part="燈號戰情室", seconds=20):
    """Edge --app 視窗的工作列圖示是從網頁 favicon 縮出來的（Chromium 縮得很糊）。
    視窗出現後直接用 Win32 的 WM_SETICON 換成我們自己的多尺寸 .ico（小圖 32px／大圖 256px 各用最合適的那張），
    工作列就清楚了。找不到視窗或失敗就算了（圖示糊一點而已，不影響使用）。"""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:                                        # noqa: BLE001
        return False
    ico = os.path.join(HERE, "戰情室.ico")
    if not os.path.exists(ico):
        return False
    u = ctypes.windll.user32
    u.LoadImageW.restype = ctypes.c_void_p
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _):
        if u.IsWindowVisible(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                if title_part in buf.value:
                    found.append(hwnd)
        return True
    import time
    end = time.time() + seconds
    while time.time() < end and not found:
        u.EnumWindows(_enum, 0)
        if not found:
            time.sleep(0.5)
    if not found:
        return False
    small = u.LoadImageW(None, ico, 1, 32, 32, 0x10)       # IMAGE_ICON, LR_LOADFROMFILE
    big = u.LoadImageW(None, ico, 1, 256, 256, 0x10)
    for hwnd in found:
        if small:
            u.SendMessageW(hwnd, 0x0080, 0, small)          # WM_SETICON, ICON_SMALL
        if big:
            u.SendMessageW(hwnd, 0x0080, 1, big)            # ICON_BIG
    return bool(small and big)


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
            _set_window_icon()
            return 0
    import webbrowser
    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
