"""Daily Telegram receipt, shared by serialized tw-board Actions runs.

Only the date and success flag are public. Never store message/recipient/token.
The workflow MUST use a single concurrency group (including dispatch runs).
Read the live main branch, not the potentially stale checkout of a queued run.
"""
import base64
import json
import os
from datetime import datetime, timedelta, timezone

import requests

TAIPEI = timezone(timedelta(hours=8))


def taipei_day(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(TAIPEI).date().isoformat()


def send_morning(text, send, day=None):
    """Send once per Taiwan day; explicit Telegram failures remain retryable.

    No automatic retry of an ambiguous Telegram timeout: it may have delivered.
    Receipt persistence failure after delivery requires operator investigation.
    """
    day = day or taipei_day()
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise RuntimeError("Morning receipt requires GitHub credentials; not sent")
    url = f"https://api.github.com/repos/{repo}/contents/state/morning_telegram/{day}.json"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    try:
        response = requests.get(url, headers=headers, params={"ref": "main"}, timeout=30)
        if response.status_code == 200:
            receipt = json.loads(base64.b64decode(response.json()["content"]))
            if receipt != {"date": day, "sent": True}:
                raise ValueError("Invalid receipt")
            print(f"Morning Telegram already sent for {day}; signals still updated")
            return False
        if response.status_code != 404:
            raise ValueError("Receipt read failed")
    except Exception:
        # Do not include request exceptions (may contain authorization context).
        raise RuntimeError("Cannot verify morning receipt; not sent") from None

    send(text)  # must raise unless Telegram explicitly confirms ok=true
    payload = base64.b64encode(json.dumps({"date": day, "sent": True}).encode()).decode()
    try:
        response = requests.put(url, headers=headers, json={
            "message": f"chore: morning Telegram receipt {day} [skip ci]",
            "content": payload, "branch": "main"}, timeout=30)
        if response.status_code not in (200, 201):
            raise ValueError("Receipt write failed")
    except Exception:
        raise RuntimeError("Telegram sent but receipt not confirmed; inspect before rerun") from None
    print(f"Morning Telegram receipt saved for {day}")
    return True
