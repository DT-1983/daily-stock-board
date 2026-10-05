# -*- coding: utf-8 -*-
"""PCB／載板／CCL 與大封測（先進封裝、測試、設備）個股量化對照表（2026-10-05，Leo：「深入研究 PCB、大封測相關個股」）。

只把「已公布／可查」的數字放在一起，不選倍數、不下買賣結論：
  價格與 5／20／60 日漲幅（yfinance）｜最近三個月月營收年增（FinMind）｜最近兩季毛利率、營益率、EPS（FinMind）
  ｜業外是否大於本業｜共識 EPS 與現價÷2026E／2027E（forward_eps，yfinance）｜預估前提檢查（base_rate：要求的營收成長 vs 這檔歷史上限）
  ｜軍師最新判斷（趨勢／價值）。代號先用官方名稱核對，對不上就標出來。
用法：python pcb_pkg_screen.py            # 印表並存 JSON 到 state/pcb_pkg_screen.json
"""
import json
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

GROUPS = {
    "ABF 載板": [("3037", "欣興"), ("8046", "南電"), ("3189", "景碩")],
    "PCB／CCL": [("2368", "金像電"), ("3044", "健鼎"), ("2383", "台光電"), ("6274", "台燿"), ("6213", "聯茂"),
               ("4958", "臻鼎-KY"), ("2313", "華通"), ("3715", "定穎投控")],
    "封測": [("2330", "台積電"), ("3711", "日月光投控"), ("2449", "京元電子"), ("6239", "力成"), ("3264", "欣銓"), ("6257", "矽格")],
    "設備／測試介面": [("6187", "萬潤"), ("2360", "致茂"), ("6223", "旺矽"), ("6515", "穎崴"), ("3131", "弘塑"), ("3583", "辛耘")],
}


def one(code, want):
    import yfinance as yf
    import tw_symbol
    import daily_warroom as dw
    from fundamentals_reality import _tw_monthly, _tw_quarterly
    import forward_eps
    out = {"code": code, "want": want}
    out["name"] = dw.tkname(code)
    out["name_ok"] = bool(out["name"]) and (want in out["name"] or out["name"] in want or want.replace("-KY", "") in out["name"])
    h = yf.Ticker(tw_symbol.resolve(code)).history(period="6mo")["Close"].dropna()
    p = float(h.iloc[-1])
    out["px"] = p
    for n, k in ((5, "r5"), (20, "r20"), (60, "r60")):
        out[k] = (p / float(h.iloc[-1 - n]) - 1) * 100 if len(h) > n else None
    try:
        m = _tw_monthly(code, n=3)
        out["mon"] = [(x.get("period"), x.get("yoy")) for x in m]
    except Exception:                                        # noqa: BLE001
        out["mon"] = []
    try:
        q = [x for x in _tw_quarterly(code, n=3) if x.get("eps") is not None]
        out["q"] = [{"p": x["period"], "gm": x.get("gross_margin"), "om": x.get("op_margin"), "eps": x["eps"],
                     "nonop_dom": x.get("non_op_dominant")} for x in q]
    except Exception:                                        # noqa: BLE001
        out["q"] = []
    try:
        d = forward_eps.derived(forward_eps.get(code))
        if d:
            out["fe"] = {"e0": d["a0"]["avg"], "e1": d["a1"]["avg"], "pe0": d["pe0"], "pe1": d["pe1"], "g": d["g"],
                         "n": d["n1"], "lo": d["a1"]["low"], "hi": d["a1"]["high"], "x_run": d.get("x_run")}
    except Exception:                                        # noqa: BLE001
        pass
    try:
        import base_rate
        r = base_rate.implied_requirement_tw(code)
        if r:
            out["req"] = {"tier": r["tier"], "need": r["need_yoy"] * 100, "max": r["yoy_max"] * 100, "med": r["yoy_med"] * 100}
    except Exception:                                        # noqa: BLE001
        pass
    return out


def verdicts():
    try:
        import advisor_db_export as ex
        v = ex._latest_verdicts()
        res = {}
        for k, x in v.items():
            res[str(k).split("_")[0].split(".")[0]] = x
        return res
    except Exception:                                        # noqa: BLE001
        return {}


def main():
    rows = []
    for g, lst in GROUPS.items():
        for code, want in lst:
            try:
                r = one(code, want)
            except Exception as e:                           # noqa: BLE001
                r = {"code": code, "want": want, "err": str(e)[:80]}
            r["group"] = g
            rows.append(r)
            print(f"[{g}] {code} {r.get('name') or want} ok", flush=True)
            time.sleep(0.2)
    os.makedirs("state", exist_ok=True)
    io.open("state/pcb_pkg_screen.json", "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False, indent=1))
    print("done", len(rows))


if __name__ == "__main__":
    main()
