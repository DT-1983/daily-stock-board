# -*- coding: utf-8 -*-
"""家人專用登入（2026-10-06，Leo：「家人要用 /room，做帳號密碼，不能用軍師」）。

跟 Leo 自己的 key／cookie（lookup_page.gate）是**兩套獨立的權限**：
  · Leo：帶 ?key= 或有 lk cookie → 全部功能（含軍師、全部持股、交易紀錄）。
  · 家人：帳號＋密碼登入 → fk cookie（90 天）→ **只能**看 /room 的燈號與個股圖表、/lookup 查股。
    看不到：軍師（不能問、對話紀錄也看不到）、全部持股、/trades。這些在伺服器端一律擋，不只是把按鈕藏起來。
帳密放 .env 的 FAMILY_USER／FAMILY_PASS（沒設＝家人登入整個關閉）。cookie 值是用密碼衍生的簽章，
換密碼＝所有家人裝置自動登出。登入失敗同一個來源 10 分鐘內錯 5 次就鎖 15 分鐘（記憶體內，重啟歸零）。
"""
import hashlib
import hmac
import os
import time

from dotenv import dotenv_values

HERE = os.path.dirname(os.path.abspath(__file__))
COOKIE = "fk"
COOKIE_DAYS = 90
_FAILS = {}            # ip -> [時間戳...]
_LOCK_UNTIL = {}       # ip -> 解鎖時間


def _env():
    return dotenv_values(os.path.join(HERE, ".env")) or {}


def enabled():
    e = _env()
    return bool(e.get("FAMILY_USER") and e.get("FAMILY_PASS"))


def cookie_value():
    """簽章 cookie：密碼沒變就一直有效；換密碼立即全部失效。"""
    e = _env()
    return hmac.new((e.get("FAMILY_PASS", "") + "|family-session-v1").encode(),
                    (e.get("FAMILY_USER", "") + "|fk").encode(), hashlib.sha256).hexdigest()


def is_family(cookie_val):
    return enabled() and bool(cookie_val) and hmac.compare_digest(cookie_val, cookie_value())


def leo_enabled():
    """Leo 本人帳密（2026-10-08）：登入成功＝拿到跟 ?key= 一樣的 lk cookie（全部功能含軍師）。
    為什麼要有：手機的 App 內建瀏覽器每個容器 cookie 各自一份，要一直重貼帶 key 的網址；帳密可用鑰匙圈自動填。
    帳密放 .env 的 LEO_USER／LEO_PASS（沒設＝關閉）；跟家人帳密完全分開，家人帳號登不進本人權限。"""
    e = _env()
    return bool(e.get("LEO_USER") and e.get("LEO_PASS"))


def login_enabled():
    return enabled() or leo_enabled()


def locked(ip):
    return _LOCK_UNTIL.get(ip, 0) > time.time()


def check(user, pw, ip="-"):
    """回 (ok, 訊息)。比對用固定時間比較；錯太多就鎖。"""
    if not enabled():
        return False, "家人登入尚未開啟"
    if locked(ip):
        return False, "嘗試太多次，請 15 分鐘後再試"
    e = _env()
    ok = (hmac.compare_digest(user.encode(), e["FAMILY_USER"].encode())
          & hmac.compare_digest(pw.encode(), e["FAMILY_PASS"].encode()))
    now = time.time()
    if ok:
        _FAILS.pop(ip, None)
        return True, ""
    fl = [t for t in _FAILS.get(ip, []) if now - t < 600] + [now]
    _FAILS[ip] = fl
    if len(fl) >= 5:
        _LOCK_UNTIL[ip] = now + 900
        _FAILS.pop(ip, None)
    return False, "帳號或密碼不對"


def check_any(user, pw, ip="-"):
    """回 (角色, 訊息)：角色 "leo"／"family"／None。共用同一個來源的錯誤次數鎖。"""
    if not login_enabled():
        return None, "登入尚未開啟"
    if locked(ip):
        return None, "嘗試太多次，請 15 分鐘後再試"
    e = _env()
    role = None
    if leo_enabled() and (hmac.compare_digest(user.encode(), e["LEO_USER"].encode())
                          & hmac.compare_digest(pw.encode(), e["LEO_PASS"].encode())):
        role = "leo"
    elif enabled() and (hmac.compare_digest(user.encode(), e["FAMILY_USER"].encode())
                        & hmac.compare_digest(pw.encode(), e["FAMILY_PASS"].encode())):
        role = "family"
    now = time.time()
    if role:
        _FAILS.pop(ip, None)
        return role, ""
    fl = [t for t in _FAILS.get(ip, []) if now - t < 600] + [now]
    _FAILS[ip] = fl
    if len(fl) >= 5:
        _LOCK_UNTIL[ip] = now + 900
        _FAILS.pop(ip, None)
    return None, "帳號或密碼不對"


def safe_next(n):
    """登入後只准回到這幾個頁面，不做開放轉址。"""
    return n if n in ("/room", "/lookup") else "/room"


def login_html(msg="", nxt="/room"):
    from html import escape
    m = f'<div class="err">{escape(msg)}</div>' if msg else ""
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>登入</title>
<style>body{{margin:0;background:#04070E;color:#E6EDF7;font:16px/1.6 system-ui,"Noto Sans TC","PingFang TC",sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}}
.box{{width:100%;max-width:360px;background:#0C1524;border:1px solid #1E2B42;border-radius:12px;padding:22px}}
h1{{font-size:18px;margin:0 0 4px}}.sub{{color:#8FA8C8;font-size:13px;margin-bottom:14px}}
label{{display:block;font-size:13px;color:#8FA8C8;margin:10px 0 4px}}
input{{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:1px solid #1E2B42;background:#04070E;color:#E6EDF7;font-size:16px}}
button{{width:100%;margin-top:16px;padding:13px;border:0;border-radius:8px;background:#22D3EE;color:#04202a;font-weight:700;font-size:16px}}
.err{{background:#3b1215;border:1px solid #7f1d1d;color:#fca5a5;padding:8px 10px;border-radius:8px;font-size:13px;margin-bottom:10px}}</style>
</head><body><form class="box" method="post" action="/login">
<h1>燈號戰情室</h1><div class="sub">登入（家人：燈號與個股圖表；本人：含軍師）</div>{m}
<input type="hidden" name="next" value="{escape(safe_next(nxt))}">
<label for="u">帳號</label><input id="u" name="user" autocomplete="username" autocapitalize="none" required>
<label for="p">密碼</label><input id="p" name="pw" type="password" autocomplete="current-password" required>
<button type="submit">登入</button></form></body></html>"""
