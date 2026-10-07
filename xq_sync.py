# -*- coding: utf-8 -*-
"""與 XQ 全球贏家的自選股同步（2026-10-08，Leo：「有辦法跟 XQ 自選同步嗎」）

XQ 把自選股清單存在本機：C:\\SysJust\\XQLite\\User\\<帳號>\\Data\\SymbolList.xml（Big5 的 XML）。
每個 <List Name='台股' Value='2330.TW,2303.TW,…'/> 是一份清單；Value 裡 "ETF:" 這種結尾冒號的是分組標籤、
"TSE.TW" 是指數、".TF" 是期貨，都不是股票 → watchlist.normalize() 會略過（回報被略過的數量，不靜默丟）。

方向：**只有 XQ → 戰情室**。對 XQ 的檔案只讀不寫（XQ 開著、還會自己跟雲端同步，寫了可能弄壞它的清單）。
反方向（戰情室 → XQ）給「匯出給 XQ」的純文字，由使用者在 XQ 手動匯入（格式見 export_for_xq）。

同步語意（鏡像，但只管「XQ 來的」）：
  · 選定清單裡有的 → 加進自選（src 標 xq:清單名）；XQ 那邊拿掉的 → 自選也拿掉。
  · 自己手動新增的（src manual／import）永遠不動；戰情室裡拖曳調過的順序不動（只在最後追加新的）。
  · 預設只同步「美股」「台股」；「美股-Leo」「美股-媽媽」這類是持股清單，要使用者自己勾才會同步。
設定存 state/xq_sync.json（已列 .gitignore）。
"""
import datetime as _dt
import glob
import io
import json
import os
import re

import watchlist as wl

XQ_ROOT = r"C:\SysJust\XQLite\User"
CONF = "state/xq_sync.json"
DEFAULT_LISTS = ["美股", "台股"]


def xq_file():
    c = sorted(glob.glob(os.path.join(XQ_ROOT, "*", "Data", "SymbolList.xml")), key=os.path.getmtime, reverse=True)
    return c[0] if c else None


def lists():
    """XQ 的所有清單：[{"name","tickers"(已正規化、去重、保持 XQ 順序),"raw_count","skipped"}]；沒有 XQ 檔回 None。"""
    f = xq_file()
    if not f:
        return None
    raw = open(f, "rb").read()
    txt = None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            txt = raw.decode(enc)
            break
        except Exception:                                   # noqa: BLE001
            continue
    if txt is None:
        return None
    out = []
    for m in re.finditer(r"<List\b([^>]*?)/?>", txt):
        attrs = dict(re.findall(r"(\w+)='([^']*)'", m.group(1)))
        name, val = attrs.get("Name"), attrs.get("Value", "")
        if not name:
            continue
        toks = [t for t in val.split(",") if t.strip()]
        seen, tk, group_of, order, cur = set(), [], {}, [], ""
        for t in toks:
            t = t.strip()
            if t.endswith(":") or t.endswith("："):         # XQ 的分組標籤（"晶圓:"）＝接下來的股票都屬於這一組
                cur = t.rstrip(":：").strip()
                if cur and cur not in order:
                    order.append(cur)
                continue
            n = wl.normalize(t)
            if n and n not in seen:
                seen.add(n)
                tk.append(n)
                group_of[n] = cur
        out.append({"name": name, "tickers": tk, "raw_count": len(toks), "skipped": len(toks) - len(tk),
                    "group_of": group_of, "group_order": order})
    return out


def conf():
    try:
        c = json.load(io.open(CONF, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        c = {}
    c.setdefault("lists", list(DEFAULT_LISTS))
    c.setdefault("auto", True)
    return c


def _write(c):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump(c, io.open(CONF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def save_conf(sel=None, auto=None):
    c = conf()
    if sel is not None:
        c["lists"] = [str(x) for x in sel]
    if auto is not None:
        c["auto"] = bool(auto)
    _write(c)
    return c


def status():
    ls = lists()
    c = conf()
    return {"available": ls is not None, "auto": c["auto"], "selected": c["lists"], "last": c.get("last"),
            "lists": [{"name": x["name"], "count": len(x["tickers"]), "skipped": x["skipped"]} for x in (ls or [])]}


def sync(force_lists=None):
    """鏡像同步。回 {"added","removed","total","lists","missing"}；沒有 XQ 檔回 {"error":…}，不動自選。"""
    ls = lists()
    if ls is None:
        return {"error": "找不到 XQ 的自選股檔（" + XQ_ROOT + r"\…\Data\SymbolList.xml）"}
    sel = list(force_lists) if force_lists is not None else conf()["lists"]
    by = {x["name"]: x for x in ls}
    missing = [n for n in sel if n not in by]
    desired, src_of, grp_of, gorder = [], {}, {}, []
    for n in sel:
        for g in (by[n]["group_order"] if n in by else []):
            if g not in gorder:
                gorder.append(g)
        for t in (by[n]["tickers"] if n in by else []):
            if t not in src_of:
                src_of[t] = "xq:" + n
                desired.append(t)
                grp_of[t] = by[n]["group_of"].get(t, "")
    d = wl._load()
    today = _dt.date.today().isoformat()
    keep, removed = [], []
    for x in d["items"]:
        if str(x.get("src", "")).startswith("xq") and x["tk"] not in src_of:
            removed.append(x["tk"])
        else:
            keep.append(x)
    have = {x["tk"] for x in keep}
    added = []
    for t in desired:
        if t not in have and len(keep) < wl._MAX:
            keep.append({"tk": t, "added": today, "src": src_of[t], "group": grp_of.get(t, "")})
            have.add(t)
            added.append(t)
    regrouped = 0
    for x in keep:                                  # 在 XQ 清單裡的（含手動加的）都跟著 XQ 的分類；不在的保持原樣
        if x["tk"] in grp_of and x.get("group") != grp_of[x["tk"]]:
            x["group"] = grp_of[x["tk"]]
            regrouped += 1
    if added or removed or regrouped:
        d["items"] = keep
        wl._save(d)
    c = conf()
    c["group_order"] = gorder
    c["last"] = {"time": _dt.datetime.now().strftime("%m-%d %H:%M"), "added": len(added), "removed": len(removed)}
    _write(c)
    return {"added": added, "removed": removed, "regrouped": regrouped, "groups": gorder, "total": len(d["items"]), "lists": sel, "missing": missing}


def export_for_xq():
    """給 XQ 匯入的純文字（XQ 匯入格式：純代號、無表頭、美股加 .US、一行一檔、CRLF——少了 CRLF XQ 會靜默匯不進去）。"""
    lines = []
    for x in wl._load()["items"]:
        tk = x["tk"]
        lines.append(tk if re.fullmatch(r"\d{4,6}[A-Z]?", tk) else tk.replace("-", ".") + ".US")
    return "\r\n".join(lines) + "\r\n"
