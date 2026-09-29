# Activity digest

[![Deploy to FadeHost](https://fadehost.com/deploy-button.svg)](https://laplace.fadehost.com/register?intent=bot&repo=https://github.com/FadeHost/activity-digest)

[![Deploy on FadeHost](https://img.shields.io/badge/deploy%20on-FadeHost-0ea5e9?style=flat-square)](https://laplace.fadehost.com/bots?new=1)

Watches your FadeHost servers, remembers who played and for how long, and
posts a summary to Discord once a day. There is also a page showing today so
far, which is handy to pin in your community.

- Asks the FadeHost API who is online every minute
- Keeps a small file per day, so you build up a record of your server's life
- Posts a digest at an hour you choose: uptime, peak players and the busiest
  people on each server
- Serves a page with today's numbers and who is on right now
- Old day files are cleaned up after two months

## Deploy on FadeHost

1. Open [Apps](https://laplace.fadehost.com/bots) in the panel and choose
   **Host an app**, then the **Activity digest** template.
2. Paste a Discord webhook for the channel the digest should land in, and pick
   the hour. A read-only access token is created for the app.
3. Turn on the web address to get the page as well. The digest works without
   one.

Make the webhook in Discord under **Edit Channel, Integrations, Webhooks, New
Webhook, Copy Webhook URL**.

## Environment variables

| Variable | Required | What it is |
|---|---|---|
| `FADEHOST_TOKEN` | yes | An access token with the **read** scope, from [Profile, AI Access](https://laplace.fadehost.com/profile/ai-access). |
| `DISCORD_WEBHOOK_URL` | no | Where the digest goes. Without it the app still records and still serves the page, it just posts nothing. |
| `DIGEST_HOUR` | no | The hour in UTC, 0 to 23, that the digest goes out. Defaults to 9. |
| `SERVER_IDS` | no | Which servers to watch, comma separated. Empty means all of them. |
| `PORT` | no | The port to listen on. FadeHost sets this for you. |

## Run it somewhere else

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
FADEHOST_TOKEN=... DISCORD_WEBHOOK_URL=... .venv/bin/python main.py
```

Then open `http://localhost:8080`. Python 3.11 or newer. The history goes in
`./data` when `/data` is not there.

## Routes

| Route | What it is |
|---|---|
| `/` | today's activity, refreshing itself every two minutes |
| `/api/today` | the same numbers as JSON |
| `/health` | `{ ok, polledAt, digestHour, lastDigest }` for uptime checks |

## What it can and cannot see

The FadeHost API reports the exact number of players online, and names for up
to five of them. On a server with more than five people at once, the count on
the page is right and the list of names is the five the API named. For most
community servers that is the whole picture; on a busy one, read the peak and
the uptime rather than the name list.

Names come from the join tracking, which today covers Minecraft Java servers.
Other games still get uptime and peak player counts.

## The digest

It covers the 24 hours before it is sent, so nothing falls between two days.
One digest goes out per day: if the app was asleep or was redeployed at the
digest hour, it sends when it comes back rather than skipping the day, and it
will not send the same day twice.

## Where the data lives

```
/data/history/2026-09-21.json   one file per day
/data/digest-sent.json          which digest went out last
```

Both are on the volume that survives a redeploy. The files are small: a busy
server is a few kilobytes a day.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Built and maintained by [FadeHost](https://fadehost.com). MIT licensed.
