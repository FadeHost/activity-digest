"""Who was online when, kept as one small JSON file per day.

A day file is written after every poll, so nothing is lost when the app
restarts. Files are plain JSON: open one and you can read it.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# How many minutes one sample is worth when adding up somebody's playtime.
DEFAULT_SAMPLE_MINUTES = 1.0

# Day files older than this are deleted. Two months of history is plenty for a
# daily digest, and it keeps the volume small.
KEEP_DAYS = 60


def resolve_data_dir(preferred: str | None = None) -> Path:
    """A directory that survives a redeploy.

    On FadeHost that is ``/data``. Anywhere else, ``./data`` next to the app.
    """
    candidates = [preferred, os.environ.get("DATA_DIR"), "/data", "data"]

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".writable"
            probe.touch()
            probe.unlink()
            return path
        except OSError:
            continue

    raise RuntimeError("No writable data directory.")


def day_key(moment: datetime) -> str:
    """The UTC date a moment belongs to, as ``YYYY-MM-DD``."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


class History:
    """The day files on disk."""

    def __init__(self, data_dir: Path | str, sample_minutes: float = DEFAULT_SAMPLE_MINUTES) -> None:
        self.dir = Path(data_dir) / "history"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sample_minutes = sample_minutes

    def path_for(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def read(self, key: str) -> dict[str, Any]:
        """One day, or an empty day when there is no file."""
        try:
            with self.path_for(key).open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {"date": key, "servers": {}}

        if not isinstance(data, dict) or "servers" not in data:
            return {"date": key, "servers": {}}

        return data

    def write(self, key: str, day: dict[str, Any]) -> None:
        """Write a day out whole, so a crash cannot leave half a file."""
        target = self.path_for(key)
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.dir, delete=False, encoding="utf-8", suffix=".tmp"
        )
        try:
            json.dump(day, handle, indent=1)
            handle.close()
            os.replace(handle.name, target)
        except BaseException:
            handle.close()
            Path(handle.name).unlink(missing_ok=True)
            raise

    def record(self, snapshots: Iterable[dict[str, Any]], moment: datetime | None = None) -> dict[str, Any]:
        """Fold one poll into today's file and return the updated day."""
        moment = moment or datetime.now(timezone.utc)
        key = day_key(moment)
        stamp = moment.astimezone(timezone.utc).isoformat(timespec="seconds")

        day = self.read(key)
        servers = day.setdefault("servers", {})

        for snap in snapshots:
            server_id = snap.get("id")
            if not server_id:
                continue

            entry = servers.setdefault(
                server_id,
                {"name": snap["name"], "peak": 0, "peakAt": None, "upMinutes": 0.0, "players": {}},
            )
            entry["name"] = snap["name"]

            if snap.get("up"):
                entry["upMinutes"] = round(entry.get("upMinutes", 0.0) + self.sample_minutes, 2)

            if snap["online"] > entry.get("peak", 0):
                entry["peak"] = snap["online"]
                entry["peakAt"] = stamp

            for name in snap.get("players", []):
                player = entry["players"].setdefault(name, {"first": stamp, "last": stamp, "minutes": 0.0})
                player["last"] = stamp
                player["minutes"] = round(player.get("minutes", 0.0) + self.sample_minutes, 2)

        day["date"] = key
        day["updatedAt"] = stamp
        self.write(key, day)
        return day

    def days_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Every day file that overlaps a window."""
        days = []
        cursor = start.astimezone(timezone.utc).date()
        last = end.astimezone(timezone.utc).date()

        while cursor <= last:
            days.append(self.read(cursor.strftime("%Y-%m-%d")))
            cursor += timedelta(days=1)

        return days

    def prune(self, keep_days: int = KEEP_DAYS, now: datetime | None = None) -> int:
        """Delete day files older than ``keep_days``. Returns how many went."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=keep_days)).date()
        removed = 0

        for path in self.dir.glob("*.json"):
            try:
                stamp = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if stamp < cutoff:
                path.unlink(missing_ok=True)
                removed += 1

        return removed


def merge_days(days: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Add several day files together into one report.

    Playtime and uptime add up, the peak is the highest of the peaks, and a
    player's first and last sighting span the whole window.
    """
    merged: dict[str, Any] = {}

    for day in days:
        for server_id, entry in (day.get("servers") or {}).items():
            into = merged.setdefault(
                server_id,
                {"name": entry.get("name", server_id), "peak": 0, "peakAt": None, "upMinutes": 0.0, "players": {}},
            )
            into["name"] = entry.get("name", into["name"])
            into["upMinutes"] = round(into["upMinutes"] + float(entry.get("upMinutes") or 0), 2)

            if int(entry.get("peak") or 0) > into["peak"]:
                into["peak"] = int(entry.get("peak") or 0)
                into["peakAt"] = entry.get("peakAt")

            for name, player in (entry.get("players") or {}).items():
                target = into["players"].setdefault(
                    name, {"first": player.get("first"), "last": player.get("last"), "minutes": 0.0}
                )
                target["minutes"] = round(target["minutes"] + float(player.get("minutes") or 0), 2)

                if player.get("first") and (not target["first"] or player["first"] < target["first"]):
                    target["first"] = player["first"]
                if player.get("last") and (not target["last"] or player["last"] > target["last"]):
                    target["last"] = player["last"]

    return merged


def top_players(entry: dict[str, Any], limit: int = 10) -> list[tuple[str, float]]:
    """The busiest players on one server, longest first."""
    players = (entry.get("players") or {}).items()
    ranked = sorted(players, key=lambda item: (-float(item[1].get("minutes") or 0), item[0].lower()))
    return [(name, float(data.get("minutes") or 0)) for name, data in ranked[:limit]]


def format_minutes(minutes: float) -> str:
    """``95`` becomes ``1h 35m``."""
    total = int(round(minutes))
    if total < 60:
        return f"{total}m"

    hours, rest = divmod(total, 60)
    return f"{hours}h" if rest == 0 else f"{hours}h {rest}m"
