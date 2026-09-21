"""Activity digest: watch your FadeHost servers, post a daily summary.

One process does two things. A background thread asks the FadeHost API who is
online every minute and folds that into a small file per day. The web half
serves a page showing today so far, and once a day the thread posts a digest
to a Discord webhook.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify
from waitress import serve

from activity.digest import SendLog, build_embed, due, post, read_hour, window_report
from activity.fadehost import fetch_servers, is_up, parse_ids, select, snapshot
from activity.history import History, day_key, resolve_data_dir
from activity.page import render

PORT = int(os.environ.get("PORT", "8080"))
TOKEN = (os.environ.get("FADEHOST_TOKEN") or "").strip()
WEBHOOK = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
DIGEST_HOUR = read_hour(os.environ.get("DIGEST_HOUR"))
SERVER_IDS = parse_ids(os.environ.get("SERVER_IDS"))

# One sample a minute is enough to tell who played and for how long, and it is
# 1,440 requests a day, which is nothing.
POLL_SECONDS = 60

if not TOKEN:
    print(
        "[config] FADEHOST_TOKEN is not set. Create a token with the read scope under Profile, AI Access "
        "(https://laplace.fadehost.com/profile/ai-access), add it as an environment variable and restart.",
        file=sys.stderr,
    )
    raise SystemExit(1)

if not WEBHOOK:
    print("[config] DISCORD_WEBHOOK_URL is not set, so no digest will be posted. The page still works.", flush=True)

DATA_DIR = resolve_data_dir()
history = History(DATA_DIR, sample_minutes=POLL_SECONDS / 60)
send_log = SendLog(DATA_DIR)

print(f"[activity] history in {DATA_DIR}/history", flush=True)
print(f"[activity] digest at {DIGEST_HOUR:02d}:00 UTC", flush=True)

# What the last poll saw, for the page and the health route.
state = {"live": {}, "polledAt": None, "error": None}


def poll_once(now: datetime | None = None) -> None:
    """One round: ask FadeHost, write it down, post the digest when it is due."""
    now = now or datetime.now(timezone.utc)

    try:
        servers = select(fetch_servers(TOKEN), SERVER_IDS)
    except Exception as error:  # noqa: BLE001 - a poll must never kill the thread
        state["error"] = str(error)
        print(f"[poll] {error}", flush=True)
        return

    snapshots = []
    live = {}

    for server in servers:
        snap = snapshot(server)
        snap["up"] = is_up(snap)
        snapshots.append(snap)
        if snap["up"] and snap["online"]:
            live[snap["id"]] = snap["online"]

    history.record(snapshots, now)

    state["live"] = live
    state["polledAt"] = now.isoformat(timespec="seconds")
    state["error"] = None


def digest_if_due(now: datetime | None = None) -> bool:
    """Post today's digest when the hour has come and it has not gone yet."""
    now = now or datetime.now(timezone.utc)
    key = due(now, DIGEST_HOUR, send_log.last())

    if key is None:
        return False

    embed = build_embed(window_report(history, now), now)

    if post(WEBHOOK, embed):
        print(f"[digest] posted the digest for {key}", flush=True)

    # Marked either way: a webhook that has been deleted must not make the app
    # retry every minute for the rest of the day.
    send_log.mark(key)
    return True


def worker() -> None:
    last_prune = None

    while True:
        now = datetime.now(timezone.utc)

        poll_once(now)
        digest_if_due(now)

        today = day_key(now)
        if last_prune != today:
            removed = history.prune(now=now)
            if removed:
                print(f"[activity] removed {removed} old day file(s)", flush=True)
            last_prune = today

        time.sleep(POLL_SECONDS)


app = Flask(__name__)


@app.get("/")
def index() -> str:
    now = datetime.now(timezone.utc)
    today = history.read(day_key(now)).get("servers") or {}
    return render(today, now=now, live=state["live"], digest_hour=DIGEST_HOUR)


@app.get("/api/today")
def today_json():
    now = datetime.now(timezone.utc)
    return jsonify(
        {
            "date": day_key(now),
            "polledAt": state["polledAt"],
            "live": state["live"],
            "servers": history.read(day_key(now)).get("servers") or {},
        }
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": state["error"] is None and state["polledAt"] is not None,
            "polledAt": state["polledAt"],
            "error": state["error"],
            "digestHour": DIGEST_HOUR,
            "lastDigest": send_log.last(),
        }
    )


if __name__ == "__main__":
    threading.Thread(target=worker, name="activity-poller", daemon=True).start()

    print(f"[activity] listening on {PORT}", flush=True)
    if os.environ.get("APP_URL"):
        print(f"[activity] public address {os.environ['APP_URL']}", flush=True)

    # 0.0.0.0, because the web address reaches this container from outside it.
    serve(app, host="0.0.0.0", port=PORT, threads=4, _quiet=True)
