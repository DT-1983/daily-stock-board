"""把報告轉繁中台灣用語 → 分段推 Telegram（給 GitHub Actions 雲端用）

讀環境變數:TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
用法:python push_telegram.py reports/report_YYYYMMDD.md
"""
import sys
import os
import requests
from tw_report import convert  # 複用繁中轉換（OpenCC s2twp + 台灣金融詞典）

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
LIMIT = 3800  # Telegram 上限 4096，留 buffer


def split_chunks(text):
    chunks, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > LIMIT:
            chunks.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        chunks.append(buf)
    return chunks


def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT, "text": text, "disable_web_page_preview": True,
    }, timeout=30)
    if r.status_code != 200:
        print(f"✗ Telegram {r.status_code}: {r.text[:200]}")
    return r.status_code == 200


def main():
    if not TOKEN or not CHAT:
        print("✗ 缺 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        md_tw = convert(f.read())
    chunks = split_chunks(md_tw)
    print(f"▶ 推 Telegram，共 {len(chunks)} 段")
    ok = sum(send(c) for c in chunks)
    print(f"✅ 成功 {ok}/{len(chunks)} 段")


if __name__ == "__main__":
    main()
