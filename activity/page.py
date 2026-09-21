"""The page that shows today's activity."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from .history import format_minutes, top_players

STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 20px 64px;
  background: #0b0b0f; color: #e7e7ea;
  font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 720px; margin: 0 auto; }
h1 { font-size: 26px; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: #8b8b95; font-size: 14px; margin: 0 0 28px; }
.card { background: #131318; border: 1px solid #23232c; border-radius: 14px; padding: 20px; }
.card + .card { margin-top: 14px; }
.card-top { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; flex-wrap: wrap; }
h2 { font-size: 18px; font-weight: 600; margin: 0; overflow-wrap: anywhere; }
.stat { color: #8b8b95; font-size: 13px; white-space: nowrap; }
.now { color: #4ade80; }
table { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 14px; }
th { text-align: left; color: #8b8b95; font-weight: 500; font-size: 13px; padding: 0 0 7px; }
td { padding: 7px 0; border-top: 1px solid #1d1d24; overflow-wrap: anywhere; }
td.mins { text-align: right; color: #c9c9d1; white-space: nowrap; }
.empty { color: #8b8b95; text-align: center; padding: 22px 0; }
footer { margin-top: 32px; text-align: center; color: #6b6b75; font-size: 13px; }
footer a { color: #8b8b95; }
@media (max-width: 480px) { body { padding: 28px 14px 48px; } }
"""


def render(report: dict[str, Any], *, now: datetime, live: dict[str, int], digest_hour: int) -> str:
    """The whole page for one day's report.

    ``live`` is the online count per server id from the last poll, so the page
    can say what is happening right now as well as what happened today.
    """
    if report:
        cards = "".join(
            server_card(server_id, entry, live.get(server_id))
            for server_id, entry in sorted(
                report.items(), key=lambda item: -float(item[1].get("upMinutes") or 0)
            )
        )
    else:
        cards = '<div class="card"><div class="empty">Nothing recorded yet today. Check back in a few minutes.</div></div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>Today on the servers</title>
<style>{STYLE}</style>
</head>
<body><div class="wrap">
<h1>Today on the servers</h1>
<p class="sub">{escape(now.strftime('%d %B %Y'))} so far, UTC.
The digest goes out at {digest_hour:02d}:00 UTC.</p>
{cards}
<footer>Hosted on <a href="https://fadehost.com" rel="noreferrer">FadeHost</a></footer>
</div></body>
</html>"""


def server_card(server_id: str, entry: dict[str, Any], online_now: int | None) -> str:
    players = top_players(entry, limit=15)

    if players:
        rows = "".join(
            f'<tr><td>{escape(name)}</td><td class="mins">{escape(format_minutes(minutes))}</td></tr>'
            for name, minutes in players
        )
        table = f'<table><thead><tr><th>Player</th><th style="text-align:right">Time on</th></tr></thead><tbody>{rows}</tbody></table>'
    else:
        table = '<div class="empty">Nobody has played today.</div>'

    now_line = (
        f'<span class="stat now">{online_now} online now</span> · ' if online_now else ""
    )

    return f"""<div class="card">
  <div class="card-top">
    <h2>{escape(str(entry.get('name', server_id)))}</h2>
    <div>{now_line}<span class="stat">up {escape(format_minutes(entry.get('upMinutes') or 0))} · peak {int(entry.get('peak') or 0)}</span></div>
  </div>
  {table}
</div>"""
