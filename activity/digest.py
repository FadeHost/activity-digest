"""Building the daily digest and posting it to Discord."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .history import History, format_minutes, merge_days, top_players


def window_report(history: History, now: datetime, hours: int = 24) -> dict[str, Any]:
    """Everything that happened in the last ``hours`` hours."""
    start = now - timedelta(hours=hours)
    return merge_days(history.days_between(start, now))


def build_embed(report: dict[str, Any], now: datetime, hours: int = 24) -> dict[str, Any]:
    """The Discord embed for one digest."""
    if not report:
        return {
            "title": "Nothing to report",
            "description": "No servers were seen in the last day.",
            "color": 0x71717A,
            "timestamp": now.isoformat(),
        }

    fields = []
    total_players: set[str] = set()

    for entry in sorted(report.values(), key=lambda e: -float(e.get("upMinutes") or 0)):
        players = top_players(entry, limit=5)
        total_players.update(name for name, _ in players)

        if players:
            lines = [f"{name} for {format_minutes(minutes)}" for name, minutes in players]
            body = "\n".join(lines)
        else:
            body = "Nobody played."

        head = f"Up {format_minutes(entry.get('upMinutes') or 0)}, peak {entry.get('peak', 0)}"
        fields.append({"name": entry.get("name", "server"), "value": f"{head}\n{body}"[:1024]})

    count = len(total_players)
    summary = (
        f"{count} {'player' if count == 1 else 'players'} across "
        f"{len(report)} {'server' if len(report) == 1 else 'servers'} in the last {hours} hours."
    )

    return {
        "title": "Daily activity",
        "description": summary,
        "color": 0x38BDF8,
        "fields": fields[:25],
        "timestamp": now.isoformat(),
        "footer": {"text": "Hosted on FadeHost"},
    }


def post(webhook_url: str | None, embed: dict[str, Any]) -> bool:
    """Post an embed. Never raises: a webhook being down is not fatal."""
    if not webhook_url:
        return False

    try:
        response = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        if not response.ok:
            print(f"[digest] webhook answered {response.status_code}", flush=True)
            return False
        return True
    except requests.RequestException as error:
        print(f"[digest] {error}", flush=True)
        return False


class SendLog:
    """Remembers which digests already went out.

    Without this, restarting inside the digest hour would post the same
    digest again, which is exactly the kind of thing that makes people turn a
    bot off.
    """

    def __init__(self, data_dir: Path | str) -> None:
        self.path = Path(data_dir) / "digest-sent.json"

    def last(self) -> str | None:
        try:
            with self.path.open(encoding="utf-8") as handle:
                value = json.load(handle).get("last")
                return str(value) if value else None
        except (OSError, ValueError):
            return None

    def mark(self, key: str) -> None:
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"last": key, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, handle)
        os.replace(temporary, self.path)


def due(now: datetime, digest_hour: int, last_sent: str | None) -> str | None:
    """The key of a digest that should go out now, or ``None``.

    One digest per day: the key is the UTC date. Being late (the app was
    asleep at the hour, or started afterwards) still sends today's digest, as
    long as the hour has passed.
    """
    now = now.astimezone(timezone.utc)
    if now.hour < digest_hour:
        return None

    key = now.strftime("%Y-%m-%d")
    return None if last_sent == key else key


def read_hour(value: str | None, default: int = 9) -> int:
    """Read DIGEST_HOUR, falling back when it is missing or nonsense."""
    try:
        hour = int(str(value).strip())
    except (TypeError, ValueError):
        return default

    return hour if 0 <= hour <= 23 else default
