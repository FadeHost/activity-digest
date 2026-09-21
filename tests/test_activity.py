from datetime import datetime, timedelta, timezone

import pytest

from activity.digest import build_embed, due, read_hour, window_report
from activity.fadehost import is_up, parse_ids, select, snapshot
from activity.history import (
    History,
    day_key,
    format_minutes,
    merge_days,
    resolve_data_dir,
    top_players,
)
from activity.page import render

NOON = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def raw_server(**overrides):
    server = {
        "prefixed_id": "server_one",
        "name": "Emberfell",
        "status": "Online",
        "onlinePlayerCount": 3,
        "players_sample": ["Notch", "jeb_"],
    }
    server.update(overrides)
    return server


def snap(**overrides):
    value = {"id": "server_one", "name": "Emberfell", "status": "Online", "online": 2, "players": ["Notch"], "up": True}
    value.update(overrides)
    return value


# ---- the API shape -------------------------------------------------------


def test_snapshot_keeps_only_what_the_history_needs():
    result = snapshot(raw_server())

    assert result == {
        "id": "server_one",
        "name": "Emberfell",
        "status": "Online",
        "online": 3,
        "players": ["Notch", "jeb_"],
    }


def test_snapshot_survives_a_server_with_no_players_field():
    result = snapshot({"prefixed_id": "x", "name": None, "status": "Stopped"})

    assert result["players"] == []
    assert result["online"] == 0
    assert result["name"] == "unnamed server"


def test_a_server_counts_as_up_while_it_is_starting_but_not_when_stopped():
    assert is_up({"status": "Online"}) is True
    assert is_up({"status": "Starting"}) is True
    assert is_up({"status": "Stopped"}) is False
    assert is_up({"status": "Hibernating"}) is False


def test_select_keeps_only_the_requested_servers():
    servers = [{"prefixed_id": "a"}, {"prefixed_id": "b"}]

    assert [s["prefixed_id"] for s in select(servers, ["b"])] == ["b"]
    assert len(select(servers, [])) == 2


def test_parse_ids_tolerates_spaces_and_trailing_commas():
    assert parse_ids(" server_a , server_b , ") == ["server_a", "server_b"]
    assert parse_ids(None) == []


# ---- the history ---------------------------------------------------------


def test_a_poll_is_written_down_and_read_back(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap()], NOON)

    day = history.read(day_key(NOON))
    entry = day["servers"]["server_one"]

    assert entry["name"] == "Emberfell"
    assert entry["peak"] == 2
    assert entry["upMinutes"] == 1
    assert entry["players"]["Notch"]["minutes"] == 1


def test_playtime_adds_up_over_several_polls(tmp_path):
    history = History(tmp_path, sample_minutes=1)

    for offset in range(30):
        history.record([snap()], NOON + timedelta(minutes=offset))

    entry = history.read(day_key(NOON))["servers"]["server_one"]

    assert entry["players"]["Notch"]["minutes"] == 30
    assert entry["upMinutes"] == 30
    assert entry["players"]["Notch"]["first"] < entry["players"]["Notch"]["last"]


def test_a_stopped_server_earns_no_uptime(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(status="Stopped", online=0, players=[], up=False)], NOON)

    entry = history.read(day_key(NOON))["servers"]["server_one"]

    assert entry["upMinutes"] == 0
    assert entry["players"] == {}


def test_the_peak_is_the_highest_ever_seen_not_the_last_one(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(online=9)], NOON)
    history.record([snap(online=1)], NOON + timedelta(minutes=1))

    assert history.read(day_key(NOON))["servers"]["server_one"]["peak"] == 9


def test_history_survives_a_restart(tmp_path):
    History(tmp_path, sample_minutes=1).record([snap()], NOON)

    entry = History(tmp_path, sample_minutes=1).read(day_key(NOON))["servers"]["server_one"]
    assert entry["players"]["Notch"]["minutes"] == 1


def test_each_day_gets_its_own_file(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap()], NOON)
    history.record([snap()], NOON + timedelta(days=1))

    assert history.path_for("2026-09-21").exists()
    assert history.path_for("2026-09-22").exists()


def test_a_corrupt_day_file_reads_as_an_empty_day(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.path_for("2026-09-21").write_text("{ not json", encoding="utf-8")

    assert history.read("2026-09-21") == {"date": "2026-09-21", "servers": {}}


def test_old_day_files_are_pruned_and_recent_ones_are_not(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap()], NOON - timedelta(days=90))
    history.record([snap()], NOON)

    assert history.prune(keep_days=60, now=NOON) == 1
    assert history.read(day_key(NOON))["servers"]


def test_merge_days_adds_playtime_and_takes_the_highest_peak(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(online=2)], NOON)
    history.record([snap(online=7)], NOON + timedelta(days=1))

    merged = merge_days(history.days_between(NOON, NOON + timedelta(days=1)))
    entry = merged["server_one"]

    assert entry["peak"] == 7
    assert entry["players"]["Notch"]["minutes"] == 2
    assert entry["upMinutes"] == 2


def test_top_players_is_longest_first():
    entry = {
        "players": {
            "short": {"minutes": 5},
            "long": {"minutes": 200},
            "middle": {"minutes": 50},
        }
    }

    assert [name for name, _ in top_players(entry)] == ["long", "middle", "short"]
    assert len(top_players(entry, limit=2)) == 2


@pytest.mark.parametrize(
    ("minutes", "text"),
    [(0, "0m"), (1, "1m"), (59, "59m"), (60, "1h"), (95, "1h 35m"), (1440, "24h")],
)
def test_minutes_read_the_way_people_say_them(minutes, text):
    assert format_minutes(minutes) == text


def test_resolve_data_dir_uses_the_directory_it_is_given(tmp_path):
    assert resolve_data_dir(str(tmp_path)) == tmp_path


# ---- the digest ----------------------------------------------------------


def test_a_digest_is_due_once_the_hour_has_passed():
    assert due(NOON, 9, None) == "2026-09-21"
    assert due(NOON, 15, None) is None


def test_a_digest_that_already_went_out_does_not_go_again():
    assert due(NOON, 9, "2026-09-21") is None
    assert due(NOON + timedelta(days=1), 9, "2026-09-21") == "2026-09-22"


def test_a_late_start_still_sends_the_day_it_missed_the_hour_for():
    late = datetime(2026, 9, 21, 23, 30, tzinfo=timezone.utc)
    assert due(late, 9, None) == "2026-09-21"


def test_read_hour_falls_back_on_nonsense():
    assert read_hour("0") == 0
    assert read_hour("23") == 23
    assert read_hour("24") == 9
    assert read_hour("nine") == 9
    assert read_hour(None) == 9


def test_the_embed_names_the_servers_and_the_busiest_players(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    for offset in range(45):
        history.record([snap(players=["Notch", "jeb_"], online=2)], NOON + timedelta(minutes=offset))

    embed = build_embed(window_report(history, NOON + timedelta(hours=1)), NOON)

    assert embed["title"] == "Daily activity"
    assert "2 players" in embed["description"]
    assert embed["fields"][0]["name"] == "Emberfell"
    assert "Notch for 45m" in embed["fields"][0]["value"]


def test_the_embed_says_so_when_nothing_happened():
    embed = build_embed({}, NOON)
    assert embed["title"] == "Nothing to report"


def test_a_server_nobody_played_on_is_still_reported(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(players=[], online=0)], NOON)

    embed = build_embed(window_report(history, NOON), NOON)
    assert "Nobody played." in embed["fields"][0]["value"]


# ---- the page ------------------------------------------------------------


def test_the_page_shows_the_players_and_the_live_count(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(players=["Notch"], online=4)], NOON)

    html = render(
        history.read(day_key(NOON))["servers"],
        now=NOON,
        live={"server_one": 4},
        digest_hour=9,
    )

    assert "Emberfell" in html
    assert "Notch" in html
    assert "4 online now" in html
    assert "09:00 UTC" in html


def test_the_page_says_so_when_there_is_nothing_yet():
    assert "Nothing recorded yet today" in render({}, now=NOON, live={}, digest_hour=9)


def test_a_player_name_cannot_inject_markup_into_the_page(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(players=["<script>alert(1)</script>"])], NOON)

    html = render(history.read(day_key(NOON))["servers"], now=NOON, live={}, digest_hour=9)

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html


def test_a_server_name_cannot_inject_markup_into_the_page(tmp_path):
    history = History(tmp_path, sample_minutes=1)
    history.record([snap(name="<img src=x onerror=alert(1)>")], NOON)

    html = render(history.read(day_key(NOON))["servers"], now=NOON, live={}, digest_hour=9)

    assert "<img src=x" not in html
