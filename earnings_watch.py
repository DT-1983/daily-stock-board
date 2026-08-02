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

import requests
import yfinance as yf


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
AFTER_DAYS = 3      # 公布後幾天內仍算「剛公布」


# ────────────────────────────── universe ──────────────────────────────

def _personal() -> dict:
    """實際持股（assets-dashboard，只取 owner=Leo）。這是最該提醒的一群。"""
    out = {}
    try:
        for h in json.load(open(HOLDINGS, encoding="utf-8")):
            if h.get("owner") != "Leo":
                continue
            tk = h["ticker"]
            if h.get("category") == "台股" and not tk.endswith((".TW", ".TWO")):
                tk = f"{tk}.TW"          # TWSE；上櫃股在 assets-dashboard 目前沒區分
            out[tk] = h.get("name") or tk
    except Exception as e:
        print(f"  [personal] 讀不到實際持股：{e}")
    return out


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
    """回 {ticker: name}。優先順序：實際持股 > 守備清單 > 巴菲特清單（名稱不覆蓋）。"""
    uni = {}
    parts = {"personal": [_personal], "board": [_personal, _board],
             "all": [_personal, _board, _buffett]}[which]
    for fn in parts:
        for k, v in fn().items():
            uni.setdefault(k, v)
    return uni


# ────────────────────────────── 財報日期 ──────────────────────────────

def earnings_info(ticker: str, tries: int = 2):
    """回 {next_date, days_to, last_date, last_eps, surprise} 或 None。"""
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

def load_state() -> dict:
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"upcoming": {}, "reported": {}}


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
    if not tok or not chat:
        print("  ⚠️ 無 TELEGRAM_BOT_TOKEN / CHAT_ID，跳過推播")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                                "disable_web_page_preview": "true"}, timeout=20)
        return r.ok
    except Exception as e:
        print(f"  ⚠️ 推播失敗：{e}")
        return False


# ────────────────────────────── main ──────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="board", choices=["personal", "board", "all"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-infographics", type=int, default=3,
                    help="單次最多產幾份懶人包（每份要跑 LLM，避免一次爆量）")
    args = ap.parse_args()

    uni = build_universe(args.universe)
    print(f"追蹤 {len(uni)} 檔（universe={args.universe}）")
    personal = set(_personal())
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
                upcoming.append((tk, nm, info, tk in personal))
                st["upcoming"][key] = "sent"

        # B. 剛公布（同一個財報日只處理一次）
        ld = info["last_date"]
        if ld and 0 <= (today - ld).days <= AFTER_DAYS:
            key = f"{tk}@{ld}"
            if st["reported"].get(key) != "sent":
                reported.append((tk, nm, info, tk in personal))
                st["reported"][key] = "sent"

    print(f"  即將公布 {len(upcoming)} 檔　剛公布 {len(reported)} 檔")

    lines = []
    if upcoming:
        upcoming.sort(key=lambda r: (not r[3], r[2]["days_to"]))
        lines.append(f"📅 <b>未來 {AHEAD_DAYS} 天要出財報</b>")
        for tk, nm, info, own in upcoming:
            when = "今天" if info["days_to"] == 0 else f'{info["days_to"]} 天後'
            star = "⭐ " if own else "　"
            lines.append(f'{star}<b>{tk}</b> {nm}　{info["next_date"]}（{when}）')

    if reported:
        reported.sort(key=lambda r: not r[3])
        lines.append(f"\n📊 <b>剛公布財報</b>")
        made = 0
        for tk, nm, info, own in reported:
            eps = f'　EPS {info["last_eps"]:.2f}' if info["last_eps"] is not None else ""
            sp = ""
            if info["surprise"] is not None:
                ic = "🟢" if info["surprise"] >= 0 else "🔴"
                sp = f'　{ic} 意外 {info["surprise"]:+.1f}%'
            star = "⭐ " if own else "　"
            link = ""
            # 只幫「實際持股」自動產懶人包，守備清單太多會爆量
            if own and made < args.max_infographics and not args.dry_run:
                print(f"  產懶人包 {tk} …")
                p = make_infographic(tk)
                if p:
                    made += 1
                    link = f'\n　　📄 <a href="{PAGES}/{os.path.basename(p)}">財報懶人包</a>'
            lines.append(f'{star}<b>{tk}</b> {nm}　{info["last_date"]}{eps}{sp}{link}')

    if not lines:
        print("✅ 今天沒有要提醒的財報")
        if not args.dry_run:
            save_state(st)
        return

    lines.append("\n<i>⭐＝你的實際持股</i>")
    msg = "\n".join(lines)
    print("\n" + "─" * 50)
    print(msg.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    print("─" * 50)

    if args.dry_run:
        print("\n(dry-run：沒有推播，也沒有寫入 state)")
        return
    if push(msg):
        print("✅ 已推 Telegram")
    save_state(st)


if __name__ == "__main__":
    main()
