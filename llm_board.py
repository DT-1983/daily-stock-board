"""看板判讀層的 LLM 轉接器。

2026-07-31 起預設走 **本機 Claude Code headless**（Max plan，零 API 費用），
Gemini 退為備援。原因見 dev_log「看板判讀層搬本機」。

用法：
    from llm_board import ask_json
    rows = ask_json(prompt)          # 回 list/dict（自動剝 ```json 圍籬）

環境變數：
    BOARD_LLM=claude|gemini   指定後端（預設 claude；claude 不可用時自動退 gemini）
    CLAUDE_BIN                claude CLI 路徑（預設 %APPDATA%\\npm\\claude.cmd）
    GEMINI_API_KEY            備援用
"""
import os
import re
import json
import shutil
import subprocess

BACKEND = os.environ.get("BOARD_LLM", "claude").lower()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("TW_LLM_MODEL", "gemini/gemini-3-flash-preview")
TIMEOUT = int(os.environ.get("BOARD_LLM_TIMEOUT", "600"))


# ── 簡體字偵測（2026-08-31）。Leo 硬規則禁簡體，但 8/31 實測 MRVL 的財報快訊與
# 整張財報卡片都是簡體——**prompt 裡寫「用繁體中文」不等於做到**，餵進去的查核
# 資料是簡中新聞時模型會跟著漂過去。放這裡是因為所有走 LLM 的產出都該驗收。
#
# 作法：OpenCC 轉一次，跟原文比對，有差異的字＝簡體。OpenCC 是本機純文字轉換
# 函式庫（不連網、不吃憑證、無帳號），已在環境裡。比自己維護字表可靠——第一版
# 手寫字表漏了「晶圆」的 圆，MRVL 那則因此漏網。
#
# ⚠️ 設定必須用 **s2tw（台灣標準）不是 s2t**：s2t 會把 峰→峯、群→羣、為→爲，
# 那是中國的繁體用字習慣，會把正常台灣中文誤判成簡體。實測 s2t 誤動 5 字、
# s2tw 只誤動 3 字（台/干/采）。
#
# ⚠️ AMBIGUOUS：即使用了 s2tw，仍有一批字**在繁體中文本來就合法**、同時又是
# 別字的簡化形（台/臺、后/後、准/準、佣/傭、范/範…），這些要扣掉否則「台積電」
# 「批准」「佣金」「范姜」全變簡體。清單是實測 s2tw 會改動的候選字再人工複核，
# 砍掉 摆荡复牵（純簡體字）與 几万与党种并云（現代財經文裡幾乎只會是簡體）。
# ⚠️ OpenCC 是**詞組級**轉換，同一個字在不同詞裡結果不同：「發布日期」不變，
# 「公布財報／布局」卻會 布→佈。所以白名單是字級的，涵蓋所有詞境。
# 實測進榜的：布（公布/布局→佈）、表（手表→錶）、污（污染→汙）。
AMBIGUOUS = set("台后里干采咸划丑涂范郁准岳佣占游布表污注升系周回恒")

# OpenCC 匯入不到時的退路（功能降級不炸）。只列繁體不會出現的字。
SIMPLIFIED = set("营产报涨电币会万亿达应权关联发优势场单价业计记说语证论议观见"
                 "开区个们时长东车轮华图书专务实现级标题问给经过还这样从"
                 "净现资总额购销费约层构圆员团园国图")

try:
    import opencc as _opencc
    _S2TW = _opencc.OpenCC("s2tw")
except Exception:
    _S2TW = None


def simplified_chars(txt):
    """回 txt 裡的簡體字集合（已扣掉一對多歧義字）。空集合＝乾淨。"""
    txt = txt or ""
    if _S2TW is not None:
        conv = _S2TW.convert(txt)
        if len(conv) == len(txt):        # 逐字對齊才比得起來
            return {a for a, b in zip(txt, conv) if a != b} - AMBIGUOUS
        # 長度不一致（少數一對多轉換）就退回字表，不硬猜對位
    return (SIMPLIFIED & set(txt)) - AMBIGUOUS


def has_simplified(txt):
    """回 True 代表 txt 裡有簡體字。"""
    return bool(simplified_chars(txt))


def walk_strings(o):
    """把巢狀 dict/list 裡的字串全攤平——LLM 回的 JSON 常是 list of dict，
    只檢查頂層 values 會漏掉最長的那幾段敘事。"""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from walk_strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from walk_strings(v)


def _claude_bin():
    p = os.environ.get("CLAUDE_BIN")
    if p and os.path.exists(p):
        return p
    p = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    if os.path.exists(p):
        return p
    return shutil.which("claude")


def claude_available():
    return bool(_claude_bin())


def _ask_claude(prompt):
    """headless claude -p。用 stdin 餵 prompt，避開命令列長度與跳脫字元地雷。"""
    exe = _claude_bin()
    if not exe:
        raise RuntimeError("找不到 claude CLI")
    r = subprocess.run(
        [exe, "-p", "--dangerously-skip-permissions"],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=TIMEOUT,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude 失敗 (exit {r.returncode}): {(r.stderr or '')[:300]}")
    out = (r.stdout or "").strip()
    if not out:
        raise RuntimeError("claude 回空字串")
    return out


def _ask_gemini(prompt):
    import litellm
    resp = litellm.completion(model=GEMINI_MODEL, api_key=GEMINI_KEY, temperature=0.3,
                              messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content


def ask(prompt):
    """回純文字。claude 為主、gemini 備援。"""
    order = ["claude", "gemini"] if BACKEND == "claude" else ["gemini", "claude"]
    errs = []
    for be in order:
        try:
            if be == "claude":
                if not claude_available():
                    raise RuntimeError("claude CLI 不存在")
                return _ask_claude(prompt)
            if not GEMINI_KEY:
                raise RuntimeError("無 GEMINI_API_KEY")
            return _ask_gemini(prompt)
        except Exception as e:
            errs.append(f"{be}: {e}")
    raise RuntimeError(" | ".join(errs))


def _strip_fence(txt):
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip(), flags=re.S).strip()
    # claude 偶爾會在 JSON 前後加一句話 → 取最外層的 [] 或 {}
    for op, cl in (("[", "]"), ("{", "}")):
        i, j = txt.find(op), txt.rfind(cl)
        if i != -1 and j > i:
            cand = txt[i:j + 1]
            try:
                json.loads(cand)
                return cand
            except Exception:
                continue
    return txt


def ask_json(prompt, retries=1):
    """回 dict/list。解析失敗會重試一次（要求只回 JSON）。"""
    last = None
    for k in range(retries + 1):
        p = prompt if k == 0 else prompt + "\n\n（上次回覆無法解析成 JSON，請只輸出 JSON 本身，前後不要任何說明文字。）"
        txt = ask(p)
        try:
            return json.loads(_strip_fence(txt))
        except Exception as e:
            last = f"{e}｜回覆開頭：{txt[:200]}"
    raise ValueError(f"JSON 解析失敗：{last}")


def ask_json_traditional(prompt, tries=3, log=print):
    """ask_json 的繁體版：回來的 JSON 若含簡化字，帶著「你用了哪幾個」重寫，
    最多 tries 次。全失敗回 None——呼叫端該當作「這次產不出來」走既有的重試佇列，
    不要為了有東西可交而把簡體字送出去（Leo 硬規則）。

    2026-08-31 抽出來的原因：這段邏輯 earnings_infographic 和 earnings_watch 都要用，
    而且寫在 narrative() 裡面時**測不到重試路徑**（narrative 要一整包財報 facts 才跑得動）。
    """
    fix = ""
    for a in range(tries):
        out = ask_json(prompt + fix)
        if not out:
            return out
        bad = sorted(simplified_chars("".join(walk_strings(out))))
        if not bad:
            return out
        log(f"    ⚠️ 出現簡體字 {''.join(bad[:10])}（第 {a+1}/{tries} 次），要求改寫")
        fix = ("\n" * 2 + "⚠️ 你上一次的回答用了簡體字（" + "".join(bad[:10])
               + "）。整份重寫，全部用繁體中文（台灣用語），一個簡體字都不能有。")
    log(f"    ⚠️ {tries} 次仍是簡體，放棄這次產出")
    return None
