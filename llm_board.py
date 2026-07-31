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
