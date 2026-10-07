# -*- coding: utf-8 -*-
"""戰情室「自選」清單（2026-10-08，Leo：「自選我想加上 XQ 的自選股…給我匯入與新增功能」）

儲存：state/watchlist.json（已列入 .gitignore——自選股是個人關注清單，不進公開儲存庫）。
      {"items":[{"tk":"NVDA","added":"2026-10-08","src":"xq"}, ...]}  順序＝加入順序。
代號統一寫法（跟戰情室其他地方一致）：台股純數字（2330、6488、00981A），美股大寫字母（BRK-B 用連字號）。

匯入支援：
  · XQ 自選股匯出檔 .dsl（OLE 二進位；從裡面抽出逗號分隔的代號串，如 ",SPY.US,NDAQ.US,…"）
  · 純文字／CSV：每行或逗號分隔一個代號（XQ 匯入格式：純代號、美股加 .US；第一欄為代號，表頭自動略過）
  · 可以一次貼多個代號到「新增」框（逗號／空白／換行分隔），也可以打台股中文名（唯一符合才加，否則回傳候選）。
不支援的代號（港股 .HK、指數、期貨等）不加入，回傳清單讓使用者知道哪些被略過——不靜默丟掉。
"""
import base64
import datetime as _dt
import io
import json
import os
import re

STORE = "state/watchlist.json"
_MAX = 300


def _load():
    try:
        d = json.load(io.open(STORE, encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("items"), list) else {"items": []}
    except Exception:                                       # noqa: BLE001
        return {"items": []}


def _save(d):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def normalize(tok):
    """任何寫法 → 戰情室代號；認不得回 None。"""
    t = str(tok or "").strip().strip("'\"").upper()
    if not t or t.startswith("^"):
        return None
    for suf in (".US", ".TWO", ".TW"):
        if t.endswith(suf):
            t = t[: -len(suf)]
            break
    else:
        if re.search(r"\.(HK|SS|SZ|T|L|KS|KQ|SI|AX|F|DE|PA)$", t):    # 其他市場：不支援
            return None
    if re.fullmatch(r"\d{4,6}[A-Z]?", t):
        return t
    t = t.replace(".", "-")
    if re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", t):
        return t
    return None


def _tokens_from_text(text):
    out = []
    for line in re.split(r"[\r\n]+", text):
        if not line.strip():
            continue
        for part in re.split(r"[,;\t ，、]+", line.strip()):
            if part:
                out.append(part)
    return out


def _tokens_from_dsl(raw):
    """XQ .dsl（OLE）：抽出所有可見 ASCII 字串，取「逗號分隔、且大多像代號」的那一串。"""
    best = []
    for m in re.finditer(rb"[\x20-\x7e]{4,}", raw):
        s = m.group(0).decode("ascii", "ignore")
        if "," not in s:
            continue
        toks = [x.strip() for x in s.split(",") if x.strip()]
        ok = [x for x in toks if re.fullmatch(r"[A-Za-z0-9.\-^]{1,12}", x)]
        if len(ok) >= 2 and len(ok) >= 0.8 * len(toks) and len(ok) > len(best):
            best = ok
    return best


def parse_import(filename, data):
    """回 (代號清單（已去重、已正規化）, 被略過的原字串清單)。"""
    name = str(filename or "").lower()
    if name.endswith(".dsl") or data[:4] == b"\xd0\xcf\x11\xe0":
        toks = _tokens_from_dsl(data)
    else:
        text = None
        for enc in ("utf-8-sig", "cp950", "utf-16"):
            try:
                text = data.decode(enc)
                break
            except Exception:                               # noqa: BLE001
                continue
        toks = _tokens_from_text(text or "")
        # CSV 的表頭（代號／Symbol／股票代號…）不是代號
        toks = [t for t in toks if t.upper() not in ("代號", "股票代號", "SYMBOL", "TICKER", "CODE", "NAME", "名稱")]
    ok, skipped, seen = [], [], set()
    for t in toks:
        n = normalize(t)
        if n is None:
            skipped.append(t)
        elif n not in seen:
            seen.add(n)
            ok.append(n)
    return ok, skipped


def _tw_names():
    try:
        import combo_scan
        return combo_scan._tw_names() or {}
    except Exception:                                       # noqa: BLE001
        return {}


def resolve_query(q):
    """使用者在「新增」框打的字 → (代號清單, 略過, 候選{原字串: [代號...]})。
    中文名只在「唯一符合」時才加；多個符合回候選讓使用者挑，不替他猜。"""
    ok, skipped, cands, seen = [], [], {}, set()
    names = None
    for tok in _tokens_from_text(str(q or "")):
        n = normalize(tok)
        if n:
            if n not in seen:
                seen.add(n)
                ok.append(n)
            continue
        if re.search(r"[一-鿿]", tok):
            names = names if names is not None else _tw_names()
            hit = [c for c, nm in names.items() if tok in str(nm)]
            exact = [c for c in hit if str(names[c]) == tok]
            pick = exact if len(exact) == 1 else (hit if len(hit) == 1 else [])
            if len(pick) == 1:
                if pick[0] not in seen:
                    seen.add(pick[0])
                    ok.append(pick[0])
            elif hit:
                cands[tok] = hit[:8]
            else:
                skipped.append(tok)
        else:
            skipped.append(tok)
    return ok, skipped, cands


def add(tickers, src="manual"):
    d = _load()
    have = {x["tk"] for x in d["items"]}
    added = []
    today = _dt.date.today().isoformat()
    for t in tickers:
        if t in have or len(d["items"]) >= _MAX:
            continue
        d["items"].append({"tk": t, "added": today, "src": src})
        have.add(t)
        added.append(t)
    if added:
        _save(d)
    return added


def reorder(order):
    """依傳入順序重排；沒列到的（例如被市場篩選藏起來的）維持原本相對順序、排在後面。"""
    d = _load()
    by = {x["tk"]: x for x in d["items"]}
    seen, new = set(), []
    for t in order or []:
        t = str(t).upper()
        if t in by and t not in seen:
            new.append(by[t])
            seen.add(t)
    new += [x for x in d["items"] if x["tk"] not in seen]
    if [x["tk"] for x in new] != [x["tk"] for x in d["items"]]:
        d["items"] = new
        _save(d)
        return True
    return False


def remove(tk):
    d = _load()
    n = len(d["items"])
    d["items"] = [x for x in d["items"] if x["tk"] != tk]
    if len(d["items"]) != n:
        _save(d)
        return True
    return False


def import_bytes(filename, data):
    ok, skipped = parse_import(filename, data)
    have = {x["tk"] for x in _load()["items"]}
    added = add(ok, src="xq" if str(filename).lower().endswith((".dsl", ".csv", ".txt")) else "import")
    return {"added": added, "already": [t for t in ok if t in have], "skipped": skipped, "total": len(_load()["items"])}


def listing():
    """自選清單＋每檔的燈號資訊（來自今天的掃描 state/combo_result.json；不在掃描母體的只有代號）。"""
    d = _load()
    meta = {}
    try:
        res = json.load(io.open("state/combo_result.json", encoding="utf-8"))
        for r in res.get("rows", []):
            meta[str(r.get("ticker"))] = r
    except Exception:                                       # noqa: BLE001
        pass
    names = None
    out = []
    for x in d["items"]:
        tk = x["tk"]
        r = meta.get(tk) or {}
        is_tw = bool(re.fullmatch(r"\d{4,6}[A-Z]?", tk))
        nm = r.get("name")
        if not nm and is_tw:
            names = names if names is not None else _tw_names()
            nm = names.get(tk)
        out.append({"tk": tk, "name": nm or "", "mkt": "tw" if is_tw else "us", "src": x.get("src"),
                    "lit": r.get("lit"), "bull": r.get("bull"), "px": r.get("price"),
                    "target": r.get("target"), "asof": r.get("asof"), "in_scan": bool(r)})
    return out


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else ""
    if p and os.path.exists(p):
        print(parse_import(p, open(p, "rb").read()))
