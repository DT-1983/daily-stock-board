"""財報守望（本機每日跑）→ Telegram 提醒 + 自動產懶人包

補上 TradingBot 那支 `earning_reviewer` 的兩個涵蓋缺口：
  1. 它只看 Firstrade 巴菲特持倉（美股），**看不到台股實際持股與七鏈守備清單**
  2. 它只在每週一推，財報通常週二~週五公布 →「已經公布了」最多延遲 6 天才知道

本支每日跑（接在 board_analyze_daily 後面），兩種事件：
  📅 **T-7 ~ T-1 即將公布**：預告，每檔每季只提醒一次
  📊 **T ~ T+3 剛公布**：自動產財報懶人包 HTML → 推 Telegram 連結

用法：
    python earnings_watch.py                  # 正常跑（推 Telegram）
    python earnings_watch.py --dry-run        # 只印不推、不產圖
    python earnings_watch.py --universe personal   # 只看實際持股
"""
import os
import io
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import logging
import yfinance as yf

# ETF 沒有財報，yfinance 每檔都會 log 一行 "No earnings dates found"，
# 那是預期行為不是錯誤 → 壓成 CRITICAL 以免 log 被雜訊蓋掉。
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _load_env(path=".env"):
    """讀 .env 補進 os.environ（不覆蓋已存在的）。排程執行時沒有 shell 的環境變數，
    DISCORD_WH_EARNINGS 要從這裡拿（2026-08-28 TG 精簡後這支只發 Discord）。
    .env 已在 .gitignore，不會進版控。"""
    try:
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


_load_env()

TW = timezone(timedelta(hours=8))
STATE = "state/earnings_seen.json"
PAGES = "https://dt-1983.github.io/daily-stock-board"
HOLDINGS = r"C:\Users\Mophy\AI\assets-dashboard\data\holdings.json"

AHEAD_DAYS = 7      # 提前幾天預告
NL2 = chr(10) * 2
AFTER_DAYS = 7      # 公布後幾天內仍算「剛公布」（2026-08-27 從3放寬到7：窗口太窄+
                    # 季度閘門的組合讓8月25檔裡24檔的「公布後更新」全漏掉，見 daily_followup）

# ── 執行節奏：每季一次，不是每天 ──────────────────────────────────
# 2026-08-03 用戶指示「財報不用每天跑、每季做一次就可以」。
# 洪瑞泰是長期投資法（先挑好公司再等便宜），財報每季才更新一次，
# 天天輪詢 yfinance 只是浪費，也會讓提醒失去份量。
#
# 日期對齊「台股財報申報截止日」之後幾天（多數公司已公布）：
#   Q4/年報 3/31 → 4/5    Q1 5/15 → 5/20
#   Q2 8/14 → 8/19        Q3 11/14 → 11/19
# 美股多在 1/4/7/10 月下旬公布，這 4 個時點也都涵蓋得到。
QUARTER_DAYS = [(4, 5), (5, 20), (8, 19), (11, 19)]
GRACE_DAYS = 3      # 排定日當天沒開機 → 之後 3 天內補跑仍算數


# ────────────────────────────── universe ──────────────────────────────

# 2026-08-03 用戶指定：美股只追這 4 檔（原本 49 檔守備清單全追太雜）
US_WATCH = {"TSLA": "Tesla", "NVDA": "NVIDIA", "AMD": "AMD", "MRVL": "Marvell",
            "MU": "美光科技", "AVGO": "博通", "PLTR": "Palantir"}  # 2026-08-04 用戶加 3 檔


def _holdings(owners=None, category=None) -> dict:
    """assets-dashboard 的實際持股。
    owners=None 代表全部人（Leo + 小孩）；category='台股' 只取台股。
    回 {ticker: (name, owner)}。"""
    out = {}
    try:
        for h in json.load(open(HOLDINGS, encoding="utf-8")):
            ow = h.get("owner")
            if owners is not None and ow not in owners:
                continue
            if category and h.get("category") != category:
                continue
            tk = h["ticker"]
            if h.get("category") == "台股" and not tk.endswith((".TW", ".TWO")):
                tk = f"{tk}.TW"
            # 同一檔多人持有 → 保留第一個 owner，顯示時再標「多人」
            if tk not in out:
                out[tk] = (h.get("name") or tk, ow)
    except Exception as e:
        print(f"  [holdings] 讀不到實際持股：{e}")
    return out


def _personal() -> dict:
    """只有 Leo 自己的持股（給 ⭐ 標記用）。"""
    return {k: v[0] for k, v in _holdings(owners={"Leo"}).items()}


def _board() -> dict:
    """七鏈守備清單（美股 + 台股）。"""
    out = {}
    try:
        d = json.load(open("screen_result.json", encoding="utf-8"))
        for x in (y for lst in d.get("us", {}).values() for y in lst):
            out[x["code"]] = x.get("name") or x["code"]
        for x in (y for lst in d.get("tw", {}).values() for y in lst):
            out[f'{x["code"]}.TW'] = x.get("name") or x["code"]
    except Exception as e:
        print(f"  [board] 讀不到守備清單：{e}")
    return out


def _buffett() -> dict:
    out = {}
    try:
        for tk, v in json.load(open("buffett_watch.json", encoding="utf-8")).items():
            out[tk] = v.get("name") or tk
    except Exception as e:
        print(f"  [buffett] 讀不到巴菲特清單：{e}")
    return out


def build_universe(which: str) -> dict:
    """回 {ticker: name}。

    holdings（預設，2026-08-03 用戶指定）：
        台股＝全部實際持股（Leo + 小孩，因為小孩的也想被提醒）
        美股＝只有 US_WATCH 那 4 檔（TSLA/NVDA/AMD/MRVL）
    board / all 保留備用，範圍較大。
    """
    if which == "holdings":
        uni = {k: v[0] for k, v in _holdings(category="台股").items()}
        uni.update(US_WATCH)
        return uni
    uni = {}
    parts = {"personal": [_personal], "board": [_personal, _board],
             "all": [_personal, _board, _buffett]}[which]
    for fn in parts:
        for k, v in fn().items():
            uni.setdefault(k, v)
    return uni


# ────────────────────────────── 財報日期 ──────────────────────────────

def earnings_info(ticker: str, tries: int = 2):
    """回 {next_date, days_to, last_date, last_eps, surprise} 或 None。

    ETF（006208/009816 這類）沒有財報，yfinance 會噴 "No earnings dates found,
    symbol may be delisted" 到 stderr。那是正常的、不是錯誤，靜音掉避免 log 誤導。
    """
    for a in range(tries):
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=12)
            break
        except Exception:
            if a == tries - 1:
                return None
            time.sleep(1.5)
    if df is None or df.empty or "Reported EPS" not in df.columns:
        return None
    today = datetime.now(TW).date()
    now = datetime.now(timezone.utc)
    rep = df[df["Reported EPS"].notna()].sort_index(ascending=False)
    upc = df[df["Reported EPS"].isna()]

    nd = dt = None
    fut = [i for i in upc.index if i >= now]
    if fut:
        nd = min(fut).date()
        dt = (nd - today).days

    last_date = last_eps = surprise = None
    if not rep.empty:
        last_date = rep.index[0].date()
        try:
            last_eps = float(rep.iloc[0]["Reported EPS"])
        except Exception:
            pass
        s = rep.iloc[0].get("Surprise(%)")
        surprise = float(s) if s == s else None      # NaN check
    return {"next_date": nd, "days_to": dt, "last_date": last_date,
            "last_eps": last_eps, "surprise": surprise}


# ────────────────────────────── state ──────────────────────────────

def due_today(st: dict):
    """今天該不該跑（每季一次）。回 (該跑?, 說明字串)。

    排定日當天沒開機的話，GRACE_DAYS 天內補跑仍算數（跟排程的 StartWhenAvailable 同精神），
    但同一季只會跑一次（用 state 記錄 last_quarter_run）。
    """
    today = datetime.now(TW).date()
    for m, dd in QUARTER_DAYS:
        try:
            sched = today.replace(month=m, day=dd)
        except ValueError:
            continue
        delta = (today - sched).days
        if 0 <= delta <= GRACE_DAYS:
            key = f"{today.year}-{m:02d}"
            if st.get("last_quarter_run") == key:
                return False, f"本季（{key}）已經跑過了"
            return True, f"本季排定日 {sched}（今天 +{delta} 天）"
    nxt = min((today.replace(month=m, day=dd) for m, dd in QUARTER_DAYS
               if today.replace(month=m, day=dd) > today),
              default=None)
    return False, f"今天不是季度排定日，下次 {nxt or f'{today.year+1}-04-05'}"


def _mark(tk, personal, kids):
    """⭐ 自己持股 / 👦 小孩持股 / 全形空白 只是觀察清單。"""
    return "⭐ " if tk in personal else ("👦 " if tk in kids else "　")


def _rank(mark):
    return {"⭐ ": 0, "👦 ": 1}.get(mark, 2)


def load_state() -> dict:
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"upcoming": {}, "reported": {}, "last_quarter_run": None}


def save_state(s: dict):
    os.makedirs(os.path.dirname(STATE) or ".", exist_ok=True)
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ────────────────────────────── 懶人包 ──────────────────────────────

def make_infographic(ticker: str) -> str | None:
    """呼叫 earnings_infographic.py 產 HTML，回相對路徑（失敗回 None）。"""
    safe = ticker.replace(".", "_")
    out = f"docs/earnings_{safe}.html"
    try:
        r = subprocess.run([sys.executable, "earnings_infographic.py", ticker, "-o", out],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
        if r.returncode != 0:
            print(f"    ⚠️ 產圖失敗：{(r.stderr or '')[-200:]}")
            return None
        return out
    except Exception as e:
        print(f"    ⚠️ 產圖例外：{e}")
        return None


# ────────────────────────────── Discord ──────────────────────────────

def push(msg: str, discord_msg: str = None) -> bool:
    """發 Discord #財報。

    2026-08-28 Leo：TG 精簡，財報這條只留 Discord——原本 TG+Discord 雙發同一段短
    快訊，內容重複；而且 #財報 現在有卡片摘要（card_digest），比 TG 短訊資訊量更完整，
    沒有理由兩邊都留。TELEGRAM_BOT_TOKEN 相關程式碼整段拿掉（不是保留但不呼叫——
    半死不活的分支比直接刪掉更容易誤導後人）。

    discord_msg 有值（財報卡片摘要）就發它，沒有才退回發 msg（原本給 TG 的短快訊格式，
    轉成 markdown）。#財報 之後可能開放家人看：把 ⭐(你的持股)/👦(小孩持股) 標記拿掉，
    不然從星號就能反推 Leo 的持倉。"""
    import re as _re
    from notify_discord import send_discord, tg_html_to_md
    ok = False
    try:
        if discord_msg:
            ok = send_discord("earnings", discord_msg, persona="龐統")
        else:
            msg_d = msg.replace("⭐", "").replace("👦", "")
            msg_d = _re.sub(r"<i>.*?持股才會自動產懶人包</i>", "", msg_d)
            ok = send_discord("earnings", tg_html_to_md(msg_d), persona="龐統")
    except Exception as e:
        print(f"  discord 發送失敗：{e}")
    return ok


# ────────────────────────────── main ──────────────────────────────

# ──────────────── 每日跟催：發過預告的財報，公布後補做（2026-08-27）────────────────
# 背景：8/3 用戶指示「財報不用每天跑、每季一次就可以」→ 加了季度閘門。副作用：
# 「剛公布」分支幾乎永遠等不到執行（本季 8/19 掃過就鎖，NVDA 8/26 公布直接漏掉；
# 盤點 25 檔發過預告的有 24 檔公布後沒更新）。8/27 Leo：「我以為提醒完之後就會做了」
# ——預期是公布後會自動補做。兩邊都保留：季度重掃（預告的份量感）照舊；這裡加一條
# 每日輕量跟催——**只檢查 state.upcoming 裡「已發過預告、財報日落在近 AFTER_DAYS 天內、
# 還沒處理過」的那幾檔**（平常 0~3 檔），不是天天重掃全清單，不違背 8/3 的本意。

def _next_q_consensus(tk):
    """下季分析師共識（免費，yfinance）。財報公布後 0q 會滾動成「下一季」。
    抓不到回 None——美股大多有、台股常缺，呼叫端要處理。"""
    try:
        t = yf.Ticker(tk)
        ee, re_ = t.earnings_estimate, t.revenue_estimate
        eps = float(ee.loc["0q", "avg"]) if ee is not None and "0q" in ee.index else None
        rev = float(re_.loc["0q", "avg"]) if re_ is not None and "0q" in re_.index else None
        n = int(ee.loc["0q", "numberOfAnalysts"]) if eps is not None else 0
        if eps is None and rev is None:
            return None
        return {"eps": eps, "revenue": rev, "analysts": n}
    except Exception:
        return None


def _ai_flash(tk, nm, info, consensus):
    """老墨式財報即時解讀（一次 AI+WebSearch 呼叫，跟 researcher_macro 查證模式同款）：
    ②公司下季指引 vs 共識（指引數字要查新聞稿，yfinance沒有）③盤後股價反應解讀
    ④一句白話+供應鏈連動。已知的結構化數字餵進去當事實，AI 只補查+解讀，
    查不到就要老實說。失敗回 None，不擋主要推播。"""
    import subprocess
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from llm_board import _claude_bin
        exe = _claude_bin()
        if not exe:
            return None
        schema = {"type": "object", "properties": {
            "guidance_vs_consensus": {"type": "string", "maxLength": 200},
            "market_reaction": {"type": "string", "maxLength": 150},
            "takeaway": {"type": "string", "maxLength": 200},
        }, "required": ["guidance_vs_consensus", "market_reaction", "takeaway"]}
        cons_txt = ""
        if consensus:
            rev_s = f"{consensus['revenue']/1e9:.1f}B" if consensus.get("revenue") else "—"
            cons_txt = f"下季分析師共識：EPS {consensus['eps']}、營收 {rev_s}（{consensus['analysts']}位分析師）"
        prompt = f"""你是財報快訊研究員。{tk}（{nm}）在 {info['last_date']} 公布財報。
已知事實（yfinance結構化資料，不用重查）：實際EPS {info['last_eps']}，
意外幅度 {info['surprise']:+.1f}%。{cons_txt}

任務（用WebSearch查證，多源交叉確認，查不到就老實說查不到，不要編數字）：
1. guidance_vs_consensus：公司這次給的下季營收/EPS指引是多少？跟上面的分析師共識比
   高還是低？有什麼含金量細節（例如排除某地區收入）？
2. market_reaction：盤後/隔日股價怎麼反應？是慶祝行情還是賣事實？
3. takeaway：一句白話總結，包含對台股供應鏈（若相關）的連動意義。
每段都是完整的中文句子，重要數字附上。"""
        r = subprocess.run(
            [exe, "-p", "--dangerously-skip-permissions",
             "--output-format", "json", "--json-schema", json.dumps(schema, ensure_ascii=False)],
            input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300)
        if r.returncode != 0:
            return None
        out = json.loads(r.stdout)
        return out.get("structured_output")
    except Exception as e:
        print(f"  [{tk}] AI快訊失敗（不擋主要推播）：{e}")
        return None


def card_digest(path, url):
    """把已產生的財報懶人包 HTML 摘要成一則 Discord 貼文（2026-08-27 Leo 指定：
    「摘要網站裡的財報分析就可以了，然後附上連結」）。

    純解析已產生的卡片，**不重跑 yfinance、不再叫一次 AI**——卡片裡的敘事本來就是
    AI 寫的、數字本來就是 yfinance 真實財報，這裡只是換個地方呈現＋給連結。
    抓不到就回 None（呼叫端退回原本的簡短快訊，不硬湊）。"""
    import re as _re
    try:
        h = io.open(path, encoding="utf-8").read()
    except Exception:
        return None

    def one(pat, d=""):
        m = _re.search(pat, h, _re.S)
        return m.group(1).strip() if m else d

    name = one(r"<h1>([^<]*)</h1>")
    quarter = one(r'<div class="sub">([^·]*?)財報懶人包')
    bottom = _re.sub(r"<[^>]+>", "", one(r'<div class="c">(.*?)</div>'))
    consensus = one(r'class="bg" style="color:[^"]*">([^<]*)</div>')

    # 財務數據表：項目/本季/YoY
    rows = _re.findall(r"<tr><td>([^<]+)</td><td>([^<]+)</td>"
                       r'<td class="(up|down)">([^<]+)</td></tr>', h)
    want = {"營收", "淨利", "自由現金流"}
    fin = [f"{k} {v}（{'🔺' if d == 'up' else '🔻'}{y}）"
           for k, v, d, y in rows if k in want]

    pos = _re.findall(r'<span class="m">✓</span><span>([^<]+)</span>', h)[:2]
    neg = _re.findall(r'<span class="m">✕</span><span>([^<]+)</span>', h)[:2]

    lines = [f"📊 **{name}** {quarter} 財報分析"]
    if fin:
        lines.append("　" + "｜".join(fin))
    if consensus:
        lines.append(f"　分析師共識：**{consensus}**")
    if bottom:
        lines.append(f"　💡 {bottom}")
    for p in pos:
        lines.append(f"　✓ {p}")
    for n_ in neg:
        lines.append(f"　✕ {n_}")
    lines.append(f"　🔗 [完整財報分析]({url})")
    return "\n".join(lines)


def _card_period_end(path):
    """讀已產生卡片的『會計期間截至』日期。讀不到回 None。"""
    import re as _re
    try:
        h = io.open(path, encoding="utf-8").read()
    except Exception:
        return None
    m = _re.search(r"會計期間截至\s*([\d-]+)", h)
    return m.group(1) if m else None


def _infographic_is_fresh(path, ed):
    """卡片的『會計期間截至』離公告日 ed 是否合理接近（財報通常公告日在期末後
    3-6 週）。2026-08-28 修：NVDA 8/26 已公布，get_earnings_dates 抓得到 EPS，
    但 yfinance 的 quarterly_income_stmt（完整三表）還沒跟上，還停在上一季
    （2026-04-30 而不是 2026-07-31）——fetch() 沒有這層檢查，會照樣產出一張
    數字全部落後一季的卡片，而且 daily_followup 不管新不新都把 state 標成
    'sent'，之後永遠不會重試，這張卡片就永遠是舊的。
    這裡抓：期末日離公告日超過 75 天就判定太舊。門檻校準自實測（2026-08-28）：
    AAPL/MSFT/TSLA/AMD 正常差距 22~35 天；NVDA 卡在舊季別時差距是 118 天
    （幾乎整整一季）。75 天留了約 2 倍安全邊際給正常但報得慢的公司，同時
    遠低於一季(~91天)，不會誤把「差一整季」判成新鮮。"""
    pe = _card_period_end(path)
    if not pe:
        return False           # 讀不到日期，保守當作沒準備好
    try:
        from datetime import date as _date
        gap = (ed - _date.fromisoformat(pe)).days
    except Exception:
        return False
    return 0 <= gap <= 75


def daily_followup(args):
    """每日輕量跟催。只看 state.upcoming 已發過預告的（tk, 財報日），
    財報日在 [today-AFTER_DAYS, today] 且 reported 沒記過 → 確認真的公布了
    （Reported EPS 有值）→ 產懶人包 + 老墨式四段推播。

    2026-08-28 加：懶人包卡片單獨補跑（infographic_pending）。原本 `st["reported"]`
    一旦標成 "sent" 就永遠不會再檢查那檔——但 make_infographic() 沒有「資料新不新」
    的把關，quarterly_income_stmt（完整三表）常常比 get_earnings_dates（EPS 數字）
    晚更新好幾天。實測 NVDA：8/26 公布，EPS/意外都推對了，但完整三表 8/28 當下
    還停在上一季，卡片被悄悄產成舊季別、state 卻標記完成——之後永遠不會補。
    現在拆成兩層：EPS 快訊該推的照舊只推一次；卡片沒跟上就記進
    infographic_pending，之後每天輕量重試，直到 yfinance 資料跟上為止。
    """
    st = load_state()
    st.setdefault("infographic_pending", {})
    today = datetime.now(TW).date()
    personal = set(_personal())
    kids = {k for k, v in _holdings().items() if v[1] != "Leo"} - personal
    held = personal | kids

    cands = []
    for key in st.get("upcoming", {}):
        tk, ds = key.rsplit("@", 1)
        try:
            ed = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (today - ed).days <= AFTER_DAYS and st["reported"].get(key) != "sent":
            cands.append((tk, ed, key, "new"))
    # 卡片還沒跟上、但 EPS 快訊已經推過的——只補卡片，不重推 EPS/共識（避免每天洗版）。
    # 30 天還沒跟上就放棄重試（資料源長期缺漏，不是延遲問題，繼續試沒意義）。
    for key, ds in list(st["infographic_pending"].items()):
        tk = key.rsplit("@", 1)[0]
        try:
            ed = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            del st["infographic_pending"][key]
            continue
        if (today - ed).days > 30:
            print(f"  {tk} 懶人包補跑超過30天仍未跟上，放棄")
            del st["infographic_pending"][key]
            continue
        cands.append((tk, ed, key, "pending"))
    if not cands:
        print("每日跟催：沒有「已預告、近日公布、還沒處理」的財報")
        return

    print(f"每日跟催：{len(cands)} 檔候選 {[c[0] for c in cands]}")
    blocks, made, discord_digests = [], 0, []
    for tk, ed, key, kind in cands:
        if kind == "pending":
            # 只補卡片：不重抓 EPS/意外/共識（那些已經推過），成功才發輕量訊息。
            if made >= args.max_infographics or args.dry_run:
                continue
            print(f"  補跑懶人包 {tk} …")
            p = make_infographic(tk)
            if not p or not _infographic_is_fresh(p, ed):
                print(f"  {tk} 三表仍未跟上，留在 pending 明天再試")
                continue
            made += 1
            del st["infographic_pending"][key]
            url = f"{PAGES}/{os.path.basename(p)}"
            dg = card_digest(p, url)
            blocks.append(f"📄 <b>{tk}</b> 財報懶人包補上了（{ed} 財報，資料延遲跟上）")
            if dg:
                discord_digests.append(dg)
            continue

        info = earnings_info(tk)
        time.sleep(0.35)
        if not info or not info.get("last_date") or info["last_date"] < ed:
            print(f"  {tk} 財報數字還沒出現在 yfinance（可能剛公布資料未更新），明天再試")
            continue                        # 不寫 state，明天重試
        nm = _holdings().get(tk, (tk,))[0] if tk in _holdings() else US_WATCH.get(tk, tk)
        mk = _mark(tk, personal, kids)
        eps = f"{info['last_eps']:.2f}" if info["last_eps"] is not None else "—"
        sp = f"{info['surprise']:+.1f}%" if info["surprise"] is not None else "—"
        ic = "🟢" if (info["surprise"] or 0) >= 0 else "🔴"
        b = [f"{mk}<b>{tk}</b> {nm}　{info['last_date']} 已公布",
             f"　① EPS 實際 {eps}｜意外 {ic}{sp}"]
        consensus = _next_q_consensus(tk)
        if consensus:
            rev_t = f"營收 {consensus['revenue']/1e9:.1f}B" if consensus.get("revenue") else ""
            eps_t = f"EPS {consensus['eps']:.2f}" if consensus.get("eps") is not None else ""
            b.append(f"　② 下季共識：{'、'.join(x for x in (eps_t, rev_t) if x)}（{consensus['analysts']}位分析師）")
        if tk in held and made < args.max_infographics and not args.dry_run:
            print(f"  產懶人包 {tk} …")
            p = make_infographic(tk)
            if p and _infographic_is_fresh(p, ed):
                made += 1
                url = f"{PAGES}/{os.path.basename(p)}"
                b.append(f'　📄 <a href="{url}">財報懶人包（已更新）</a>')
                # 2026-08-27 Leo：「摘要網站裡的財報分析就可以了，然後附上連結」——
                # Discord #財報 改發卡片摘要（純解析已產生的卡片，不再叫一次AI）。
                # Telegram 維持原本的簡短快訊（即時通知不需要長摘要）。
                dg = card_digest(p, url)
                if dg:
                    discord_digests.append(dg)
            elif p:
                # 卡片產出來了，但財報三表資料還沒跟上（見本函式檔頭說明）——
                # 不算完成，記進 infographic_pending 之後每天輕量重試。
                print(f"  {tk} 卡片產出但三表未跟上（仍是舊季別），排入補跑佇列")
                b.append("　📄 財報懶人包：資料源三表尚未更新，補跑中（明天起會自動重試）")
                st["infographic_pending"][key] = ed.isoformat()
            flash = _ai_flash(tk, nm, info, consensus)
            if flash:
                b.append(f"　③ 指引vs共識：{flash['guidance_vs_consensus']}")
                b.append(f"　④ 盤後反應：{flash['market_reaction']}")
                b.append(f"　💡 {flash['takeaway']}")
        blocks.append("\n".join(b))
        if not args.dry_run:
            st["reported"][key] = "sent"

    if not blocks:
        if not args.dry_run:
            save_state(st)          # infographic_pending 的增減也要存
        return
    msg = "📊 <b>財報快訊（公布後跟催）</b>\n\n" + "\n\n".join(blocks)
    print("\n" + msg.replace("<b>", "").replace("</b>", ""))
    if args.dry_run:
        print("(dry-run：沒推播、沒寫state)")
        return
    # Discord #財報 收「財報卡片摘要」（含數字表、分析師共識、優缺點、懶人包連結），
    # Telegram 維持短快訊——這是 8/27 定的分工，之前 digests 組好卻沒發出去。
    # 沒有懶人包可摘要時（非持股、或超過 max-infographics）就退回發短快訊。
    d_msg = None
    if discord_digests:
        d_msg = "# 📊 財報快訊" + NL2 + NL2.join(discord_digests)
        if len(blocks) > len(discord_digests):
            d_msg += NL2 + f"-# 另有 {len(blocks)-len(discord_digests)} 檔已公布但沒有懶人包（非持股或超過本次產出上限）"
    if push(msg, discord_msg=d_msg):
        print("✅ 已發 Discord")
    print(f"　Discord #財報：{'卡片摘要 %d 檔' % len(discord_digests) if d_msg else '短快訊（無懶人包可摘要）'}")
    save_state(st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="holdings",
                    choices=["holdings", "personal", "board", "all"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="忽略「每季一次」的節奏限制，立刻跑一次")
    ap.add_argument("--max-infographics", type=int, default=3,
                    help="單次最多產幾份懶人包（每份要跑 LLM，避免一次爆量）")
    args = ap.parse_args()

    st_pre = load_state()
    ok, why = due_today(st_pre)
    if not ok and not args.force:
        print(f"⏭️ 季度掃描跳過：{why}　→ 改跑每日跟催")
        daily_followup(args)
        return

    uni = build_universe(args.universe)
    print(f"追蹤 {len(uni)} 檔（universe={args.universe}）　{why}")
    personal = set(_personal())                       # Leo 自己 → ⭐
    kids = {k for k, v in _holdings().items() if v[1] != "Leo"} - personal   # 小孩 → 👦
    held = personal | kids                            # 有實際持有的才自動產懶人包
    st = load_state()
    today = datetime.now(TW).date()
    today_s = today.isoformat()

    upcoming, reported = [], []
    for i, (tk, nm) in enumerate(sorted(uni.items()), 1):
        if i % 25 == 0:
            print(f"  …{i}/{len(uni)}")
        info = earnings_info(tk)
        time.sleep(0.35)
        if not info:
            continue

        # A. 即將公布（同一個財報日只提醒一次）
        dt_ = info["days_to"]
        if dt_ is not None and 0 <= dt_ <= AHEAD_DAYS:
            key = f'{tk}@{info["next_date"]}'
            if st["upcoming"].get(key) != "sent":
                upcoming.append((tk, nm, info, _mark(tk, personal, kids)))
                st["upcoming"][key] = "sent"

        # B. 剛公布（同一個財報日只處理一次）
        ld = info["last_date"]
        if ld and 0 <= (today - ld).days <= AFTER_DAYS:
            key = f"{tk}@{ld}"
            if st["reported"].get(key) != "sent":
                reported.append((tk, nm, info, _mark(tk, personal, kids)))
                st["reported"][key] = "sent"

    print(f"  即將公布 {len(upcoming)} 檔　剛公布 {len(reported)} 檔")

    lines = []
    if upcoming:
        upcoming.sort(key=lambda r: (_rank(r[3]), r[2]["days_to"]))
        lines.append(f"📅 <b>未來 {AHEAD_DAYS} 天要出財報</b>")
        for tk, nm, info, mk in upcoming:
            when = "今天" if info["days_to"] == 0 else f'{info["days_to"]} 天後'
            star = mk
            lines.append(f'{star}<b>{tk}</b> {nm}　{info["next_date"]}（{when}）')

    if reported:
        reported.sort(key=lambda r: _rank(r[3]))
        lines.append(f"\n📊 <b>剛公布財報</b>")
        made = 0
        for tk, nm, info, mk in reported:
            eps = f'　EPS {info["last_eps"]:.2f}' if info["last_eps"] is not None else ""
            sp = ""
            if info["surprise"] is not None:
                ic = "🟢" if info["surprise"] >= 0 else "🔴"
                sp = f'　{ic} 意外 {info["surprise"]:+.1f}%'
            star = mk
            link = ""
            # 只幫「實際持股」自動產懶人包，守備清單太多會爆量
            if tk in held and made < args.max_infographics and not args.dry_run:
                print(f"  產懶人包 {tk} …")
                p = make_infographic(tk)
                if p:
                    made += 1
                    link = f'\n　　📄 <a href="{PAGES}/{os.path.basename(p)}">財報懶人包</a>'
            lines.append(f'{star}<b>{tk}</b> {nm}　{info["last_date"]}{eps}{sp}{link}')

    if not lines:
        print("✅ 這一季沒有要提醒的財報")
        if not args.dry_run:
            st["last_quarter_run"] = f"{datetime.now(TW):%Y-%m}"
            save_state(st)
        return

    lines.append("\n<i>⭐＝你的持股　👦＝小孩持股　·　持股才會自動產懶人包</i>")
    msg = "\n".join(lines)
    print("\n" + "─" * 50)
    print(msg.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    print("─" * 50)

    if args.dry_run:
        print("\n(dry-run：沒有推播，也沒有寫入 state)")
        return
    if push(msg):
        print("✅ 已發 Discord")
    st["last_quarter_run"] = f"{datetime.now(TW):%Y-%m}"
    save_state(st)


if __name__ == "__main__":
    main()
