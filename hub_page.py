# -*- coding: utf-8 -*-
"""戰情室總入口 /hub ＋「立即更新」（2026-10-06，Leo：「兩個都做」——當場算＋單一入口）。

掛在 discord_bot.py 常駐的 aiohttp server（127.0.0.1:8030，經 Cloudflare Tunnel 對外），跟 /lookup、/room、/trades
同一道 token 門檻（lookup_page.gate）。電腦開了才有；關機時只剩 GitHub Pages 上的每日靜態頁（hub 會標明）。

## 「立即更新」到底更新了什麼（照實寫，不誇大）
只**重新產生頁面**——用磁碟上「已經算好的最新資料」重畫，**不重抓全市場價格、不重掃**：
  · exit  ＝ exit_review.py（出場檢視表，約 20 秒）→ state/live/exit.html
  · combo ＝ combo_html.py（進出燈號，含圖約 80 秒、檔案約 10MB）→ state/live/combo.html
每日 06:00 的排程仍負責重抓與重掃。要「當下價格」請用 /lookup（那頁本來就是現場算）。
輸出一律寫 state/live/（已 gitignore），**不寫 docs/**——docs 是整包 git add 上公開站，持股相關頁不能走那條路。
一次只跑一個、同一個任務不重複排隊；子行程有逾時；失敗會顯示原因，不靜默。

## 入口怎麼用
· 電腦：瀏覽器開，或用 hub_window.py 開成獨立視窗（WebView；沒裝 pywebview 時退回 Edge app 模式，同樣無網址列）。
· 手機：開一次 /hub?key=…（或從 Sonia 的卡片進來，Sonia 會補 key）→ 加入主畫面。
  iOS 主畫面 App 的 cookie 是獨立容器——第一次從主畫面開若被擋，從 Sonia 點進來即可（見記憶 sonia_login_faceid）。
"""
import html as _html
import io
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_DIR = os.path.join(HERE, "state", "live")
PUBLIC = "https://dt-1983.github.io/daily-stock-board"

# 任務白名單：name → (顯示名, 指令, 輸出檔, 逾時秒, 說明)
JOBS = {
    "exit": ("持股出場檢視表", ["exit_review.py", "-o", os.path.join(LIVE_DIR, "exit.html")], "exit.html", 240,
             "用最新訊號資料重畫，約 20 秒"),
    "combo": ("進出燈號", ["combo_html.py", "-o", os.path.join(LIVE_DIR, "combo.html"), "--no-obis"], "combo.html", 600,
              "用最新掃描結果重畫（含圖），約 80 秒、檔案約 10MB"),
}
_LOCK = threading.Lock()
_STATE = {k: {"status": "idle", "started": None, "finished": None, "rc": None, "tail": ""} for k in JOBS}
_RUNNING = {"name": None}


def _fmt_age(path):
    if not os.path.exists(path):
        return "還沒產生過", None
    t = os.path.getmtime(path)
    sec = time.time() - t
    if sec < 90:
        a = "剛剛"
    elif sec < 3600:
        a = f"{int(sec // 60)} 分鐘前"
    elif sec < 86400:
        a = f"{int(sec // 3600)} 小時前"
    else:
        a = f"{int(sec // 86400)} 天前"
    return f"{datetime.fromtimestamp(t):%m/%d %H:%M}（{a}）", t


def _run(name):
    label, cmd, out, timeout, _ = JOBS[name]
    os.makedirs(LIVE_DIR, exist_ok=True)
    s = _STATE[name]
    s.update({"status": "running", "started": time.time(), "finished": None, "rc": None, "tail": ""})
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable] + cmd, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        s["rc"] = r.returncode
        s["tail"] = ((r.stdout or "") + (r.stderr or "")).strip()[-400:]
        s["status"] = "done" if r.returncode == 0 and os.path.exists(os.path.join(LIVE_DIR, out)) else "failed"
    except subprocess.TimeoutExpired:
        s["status"], s["tail"] = "failed", f"逾時（超過 {timeout} 秒）已中止"
    except Exception as e:                                   # noqa: BLE001
        s["status"], s["tail"] = "failed", str(e)[:300]
    finally:
        s["finished"] = time.time()
        with _LOCK:
            _RUNNING["name"] = None
        print(f"[hub] {name} → {s['status']} rc={s['rc']}", flush=True)


def start(name):
    """啟動背景更新。回 (ok, 訊息)。同時只跑一個；同一任務執行中不重複啟動。"""
    if name not in JOBS:
        return False, "未知任務"
    with _LOCK:
        if _RUNNING["name"]:
            who = JOBS[_RUNNING["name"]][0]
            return False, f"「{who}」正在更新中，等它跑完"
        _RUNNING["name"] = name
    threading.Thread(target=_run, args=(name,), daemon=True).start()
    return True, f"已開始更新「{JOBS[name][0]}」"


def status():
    out = {}
    for k, (label, _, f, _, desc) in JOBS.items():
        s = dict(_STATE[k])
        s["label"] = label
        s["built"], _ = _fmt_age(os.path.join(LIVE_DIR, f))
        if s["status"] == "running" and s["started"]:
            s["elapsed"] = int(time.time() - s["started"])
        out[k] = s
    return out


def live_file(name):
    """/live/<name> 要送的檔；沒產生過回 None。"""
    if name not in JOBS:
        return None
    p = os.path.join(LIVE_DIR, JOBS[name][2])
    return p if os.path.exists(p) else None


# ───────────────────────────── 頁面 ─────────────────────────────

def _esc(s):
    return _html.escape(str(s), quote=True)


def _site_nav():
    try:
        from board_theme import NAV
        return [(label, (PUBLIC + "/" + href.lstrip("./")) if href not in ("./", ".") else PUBLIC + "/") for _k, _i, label, href in NAV]
    except Exception:                                        # noqa: BLE001
        return [("投資站首頁", PUBLIC + "/")]


def _daily_freshness():
    """靜態頁的資料日：讀本機最新一份報告檔名；讀不到就不顯示。"""
    try:
        import glob
        f = sorted(glob.glob(os.path.join(HERE, "reports", "report_*.md")))[-1]
        d = os.path.basename(f)[7:-3]
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    except Exception:                                        # noqa: BLE001
        return None


def page_html(is_external=False):
    st = status()
    fresh = _daily_freshness()
    rows = []
    for k, (label, _cmd, f, _t, desc) in JOBS.items():
        s = st[k]
        rows.append(
            f'<div class="card" data-job="{k}">'
            f'<div class="h"><a class="t" href="/live/{k}">{_esc(label)}</a>'
            f'<span class="tag">即時版</span></div>'
            f'<div class="d">{_esc(desc)}</div>'
            f'<div class="d">上次更新：<b class="built">{_esc(s["built"])}</b></div>'
            f'<div class="d st">{_esc(_status_line(s))}</div>'
            f'<div class="row"><button class="btn" onclick="refreshJob(\'{k}\')">立即更新</button>'
            f'<a class="btn ghost" href="/live/{k}">開啟</a></div></div>')
    live_pages = [("查任意股票", "/lookup", "現場抓三年資料算指標，永遠是當下"),
                  ("軍議（龐統／孔明／仲達／陳壽）", "/room", "問軍師、看個股明細"),
                  ("交易紀錄", "/trades", "實際成交與理由")]
    for label, href, desc in live_pages:
        rows.append(f'<div class="card"><div class="h"><a class="t" href="{href}">{_esc(label)}</a>'
                    f'<span class="tag live">現場算</span></div><div class="d">{_esc(desc)}</div>'
                    f'<div class="row"><a class="btn ghost" href="{href}">開啟</a></div></div>')
    site = "".join(f'<a class="chip" href="{_esc(u)}" target="_blank" rel="noopener">{_esc(l)}</a>' for l, u in _site_nav())
    priv = "".join(f'<a class="chip" href="{_esc(u)}" target="_blank" rel="noopener">{_esc(l)}</a>' for l, u in (
        ("出場檢視表（每日版，要密碼）", "https://assets.talentxtrend.com/exit-review"),
        ("資產中控台", "https://assets.talentxtrend.com/"),
        ("Sonia", "https://sonia.talentxtrend.com/")))
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><title>戰情室入口</title>
<link rel="manifest" href="/hub.webmanifest"><link rel="apple-touch-icon" href="/hub-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="戰情室">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="theme-color" content="#04070E">
<style>
:root{{--bg:#04070E;--card:#0C1524;--line:#1E2B42;--ink:#E6EDF7;--muted:#8FA8C8;--dim:#5B7192;--accent:#22D3EE;--ok:#22C55E;--bad:#EF4444;--warn:#F59E0B}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,"Noto Sans TC","PingFang TC",sans-serif;
padding:max(16px,env(safe-area-inset-top)) 16px 40px}}
.wrap{{max-width:900px;margin:0 auto}}h1{{font-size:20px;margin:8px 0 2px}}h2{{font-size:13px;color:var(--accent);letter-spacing:.06em;margin:24px 0 8px}}
.sub{{color:var(--muted);font-size:12.5px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.h{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.t{{font-weight:700;color:var(--ink);text-decoration:none}}
.tag{{font-size:10.5px;color:var(--dim);border:1px solid var(--line);border-radius:6px;padding:1px 7px}}.tag.live{{color:var(--ok);border-color:#166534}}
.d{{font-size:12.5px;color:var(--muted);margin-top:4px}}.row{{display:flex;gap:8px;margin-top:10px}}
.btn{{background:var(--accent);color:#04202a;border:0;border-radius:8px;padding:9px 14px;font-weight:700;font-size:14px;text-decoration:none;cursor:pointer;min-height:40px;display:inline-flex;align-items:center}}
.btn.ghost{{background:transparent;color:var(--accent);border:1px solid var(--line)}}.btn:disabled{{opacity:.5;cursor:wait}}
.chips{{display:flex;flex-wrap:wrap;gap:8px}}.chip{{border:1px solid var(--line);border-radius:18px;padding:7px 13px;color:var(--ink);text-decoration:none;font-size:13px;background:var(--card)}}
.st.run{{color:var(--warn)}}.st.fail{{color:var(--bad)}}.st.ok{{color:var(--ok)}}
.note{{font-size:12px;color:var(--dim);border-top:1px solid var(--line);margin-top:26px;padding-top:10px;line-height:1.8}}
</style></head><body><div class="wrap">
<h1>戰情室入口</h1>
<div class="sub">{'經 Cloudflare 通道連到 Leo 的電腦' if is_external else '本機'}｜每日排程資料日：{_esc(fresh or '—')}</div>
<h2>即時（跑在這台電腦上）</h2><div class="grid" id="live">{''.join(rows)}</div>
<h2>投資站（每日自動更新；電腦關機也看得到）</h2><div class="chips">{site}</div>
<h2>其他私人頁（要登入）</h2><div class="chips">{priv}</div>
<div class="note"><b>「立即更新」只重畫頁面</b>：用磁碟上已算好的最新資料重新產生，不重抓全市場價格、不重掃；每日 06:00 排程才負責重抓與重掃。
要當下價格請用「查任意股票」。更新時一次只跑一個，跑的時候可以先去做別的，回來重新整理即可。<br>
手機：用 Safari／Chrome 開這頁 →「加入主畫面」就是一個 App（iOS 主畫面是獨立容器，第一次被擋就從 Sonia 的卡片點進來）。
這台電腦關機時，上面「即時」那區連不上，下面「投資站」仍可用。</div></div>
<script>
function fmt(s){{if(s.status==='running')return '更新中… 已 '+(s.elapsed||0)+' 秒';if(s.status==='failed')return '上次更新失敗：'+(s.tail||'').slice(-160);if(s.status==='done')return '更新完成';return '';}}
async function poll(){{try{{const r=await fetch('/hub/status',{{cache:'no-store'}});if(!r.ok)return;const j=await r.json();let busy=false;
 for(const k in j){{const c=document.querySelector('[data-job="'+k+'"]');if(!c)continue;c.querySelector('.built').textContent=j[k].built;
  const e=c.querySelector('.st');e.textContent=fmt(j[k]);e.className='d st '+({{running:'run',failed:'fail',done:'ok'}}[j[k].status]||'');
  if(j[k].status==='running')busy=true;}}
 document.querySelectorAll('.btn[onclick]').forEach(b=>b.disabled=busy);if(busy)setTimeout(poll,2500);}}catch(e){{}}}}
async function refreshJob(k){{const r=await fetch('/hub/refresh?job='+k,{{method:'POST'}});const j=await r.json();
 const e=document.querySelector('[data-job="'+k+'"] .st');e.textContent=j.msg;poll();}}
poll();
</script></body></html>"""


def _status_line(s):
    if s["status"] == "running":
        return f"更新中… 已 {s.get('elapsed', 0)} 秒"
    if s["status"] == "failed":
        return "上次更新失敗：" + (s.get("tail") or "")[-160:]
    if s["status"] == "done":
        return "更新完成"
    return ""


MANIFEST = {"name": "戰情室入口", "short_name": "戰情室", "start_url": "/hub", "scope": "/", "display": "standalone",
            "background_color": "#04070E", "theme_color": "#04070E",
            "icons": [{"src": "/hub-icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}


def icon_png():
    """簡單的圖示（深底、青色方塊與折線），程式現畫，不引用任何外部圖。"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (512, 512), (4, 7, 14))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((70, 70, 442, 442), radius=48, outline=(34, 211, 238), width=14)
    pts = [(120, 340), (200, 270), (270, 310), (340, 200), (400, 170)]
    d.line(pts, fill=(34, 211, 238), width=18, joint="curve")
    for p in pts:
        d.ellipse((p[0] - 14, p[1] - 14, p[0] + 14, p[1] + 14), fill=(245, 184, 65))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()
