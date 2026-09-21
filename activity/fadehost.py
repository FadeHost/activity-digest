"""Everything this app asks of the FadeHost API."""

from __future__ import annotations

import os
from typing import Any

import requests

API_BASE = os.environ.get("FADEHOST_API", "https://api.fadehost.com/api")


class ApiError(RuntimeError):
    """FadeHost answered with something we cannot use."""


def fetch_servers(token: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Every server the token can see."""
    response = requests.get(
        f"{API_BASE}/servers",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=timeout,
    )

    if response.status_code in (401, 403):
        raise ApiError(
            "FadeHost rejected the token. Mint a new one under Profile, AI Access "
            "and set it as FADEHOST_TOKEN."
        )

    if not response.ok:
        raise ApiError(f"FadeHost answered {response.status_code}.")

    body = response.json()
    return body if isinstance(body, list) else []


def snapshot(server: dict[str, Any]) -> dict[str, Any]:
    """Boil a raw server entry down to what the history keeps.

    ``players`` is only the sample the API returns, which is the first five
    names. ``online`` is the real count, so a busy server shows the right
    number even when not every name is known.
    """
    sample = server.get("players_sample")
    names = [str(name) for name in sample] if isinstance(sample, list) else []

    return {
        "id": server.get("prefixed_id"),
        "name": server.get("name") or "unnamed server",
        "status": str(server.get("status") or "Unknown"),
        "online": int(server.get("onlinePlayerCount") or 0),
        "players": names,
    }


def is_up(snap: dict[str, Any]) -> bool:
    """Was the server actually running at this sample?"""
    return snap.get("status") in ("Online", "Starting", "Restarting")


def select(servers: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    """Keep only the requested servers. An empty list means all of them."""
    if not ids:
        return servers

    wanted = set(ids)
    return [server for server in servers if server.get("prefixed_id") in wanted]


def parse_ids(value: str | None) -> list[str]:
    """Read a comma separated SERVER_IDS value."""
    return [part.strip() for part in str(value or "").split(",") if part.strip()]
