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
import requests
import yfinance as yf

# ETF 沒有財報，yfinance 每檔都會 log 一行 "No earnings dates found"，
# 那是預期行為不是錯誤 → 壓成 CRITICAL 以免 log 被雜訊蓋掉。
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _load_env(path=".env"):
    """讀 .env 補進 os.environ（不覆蓋已存在的）。排程執行時沒有 shell 的環境變數，
    TELEGRAM_BOT_TOKEN / CHAT_ID 要從這裡拿。.env 已在 .gitignore，不會進版控。"""
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


# ────────────────────────────── Telegram ──────────────────────────────

def push(msg: str) -> bool:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    ok = False
    if not tok or not chat:
        print("  ⚠️ 無 TELEGRAM_BOT_TOKEN / CHAT_ID，跳過推播")
    else:
        try:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              data={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}, timeout=20)
            ok = r.ok
        except Exception as e:
            print(f"  ⚠️ 推播失敗：{e}")
    # 2026-08-28 Discord 雙發（隆中對 #財報，龐統）——財報預告+快訊都走這個函式，一點接全通
    try:
        from notify_discord import send_discord, tg_html_to_md
        send_discord("earnings", tg_html_to_md(msg), persona="龐統")
    except Exception as e:
        print(f"  discord 雙發失敗（不影響 Telegram）：{e}")
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


def daily_followup(args):
    """每日輕量跟催。只看 state.upcoming 已發過預告的（tk, 財報日），
    財報日在 [today-AFTER_DAYS, today] 且 reported 沒記過 → 確認真的公布了
    （Reported EPS 有值）→ 產懶人包 + 老墨式四段推播。"""
    st = load_state()
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
            cands.append((tk, ed, key))
    if not cands:
        print("每日跟催：沒有「已預告、近日公布、還沒處理」的財報")
        return

    print(f"每日跟催：{len(cands)} 檔候選 {[c[0] for c in cands]}")
    blocks, made = [], 0
    for tk, ed, key in cands:
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
            if p:
                made += 1
                b.append(f'　📄 <a href="{PAGES}/{os.path.basename(p)}">財報懶人包（已更新）</a>')
            flash = _ai_flash(tk, nm, info, consensus)
            if flash:
                b.append(f"　③ 指引vs共識：{flash['guidance_vs_consensus']}")
                b.append(f"　④ 盤後反應：{flash['market_reaction']}")
                b.append(f"　💡 {flash['takeaway']}")
        blocks.append("\n".join(b))
        if not args.dry_run:
            st["reported"][key] = "sent"

    if not blocks:
        return
    msg = "📊 <b>財報快訊（公布後跟催）</b>\n\n" + "\n\n".join(blocks)
    print("\n" + msg.replace("<b>", "").replace("</b>", ""))
    if args.dry_run:
        print("(dry-run：沒推播、沒寫state)")
        return
    if push(msg):
        print("✅ 已推 Telegram")
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
        print("✅ 已推 Telegram")
    st["last_quarter_run"] = f"{datetime.now(TW):%Y-%m}"
    save_state(st)


if __name__ == "__main__":
    main()
