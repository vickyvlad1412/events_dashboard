from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.services import catalog_service, event_service, follow_service
from app.services.connectors import f1_connector, football_connector, tmdb_connector, anilist_connector, dota_connector

scheduler = BackgroundScheduler(timezone="UTC")


F1_SESSION_SETTINGS = {"practice": "f1_practice", "qualifying": "f1_qualifying"}

FOOTBALL_LEAGUE_SETTINGS = {
    "football_champions_league": {football_connector.CHAMPIONS_LEAGUE_ID},
    "football_other_pl": {football_connector.PREMIER_LEAGUE_ID},
    "football_international_tournaments": football_connector.INTERNATIONAL_TOURNAMENT_IDS,
}


def _sync_f1() -> None:
    year = datetime.now(timezone.utc).year
    unwanted_ids = []
    for event in f1_connector.fetch_upcoming_sessions(year):
        setting = F1_SESSION_SETTINGS.get(event["session_kind"])
        if setting and not event_service.is_interest_enabled("f1", setting):
            unwanted_ids.append(event["external_id"])
            continue
        event_service.upsert_external_event(event)
    event_service.remove_upcoming_external_events("openf1", unwanted_ids)


def _followed_football_team_ids() -> set[int]:
    return {
        int(follow["external_id"])
        for follow in event_service.list_follows("team", "football")
        if (follow["external_id"] or "").isdigit()
    }


def _sync_football() -> None:
    fixtures = football_connector.fetch_fixture_window()
    catalog_service.upsert_entities(
        "football", "team", football_connector.teams_from_fixtures(fixtures), mark_active=True
    )
    follow_service.refresh_catalog_follow_details("football", "team")

    team_ids = _followed_football_team_ids()
    extra_league_ids = set()
    for setting, league_ids in FOOTBALL_LEAGUE_SETTINGS.items():
        if event_service.is_interest_enabled("football", setting):
            extra_league_ids |= league_ids

    selected = football_connector.select_fixtures(fixtures, team_ids, extra_league_ids)
    for event in selected:
        event_service.upsert_external_event(event)
    selected_ids = {event["external_id"] for event in selected}
    event_service.remove_upcoming_external_events(
        "api-football", [str(item["fixture"]["id"]) for item in fixtures if str(item["fixture"]["id"]) not in selected_ids]
    )


def _followed_dota_teams() -> list[str]:
    teams = event_service.list_followed("team", "dota")
    players = event_service.list_followed("player", "dota")
    if players:
        try:
            teams += dota_connector.fetch_player_teams(players).values()
        except Exception as exc:
            print(f"[scheduler] couldn't look up teams for followed Dota players: {exc}")
    return teams


def _dota_priority(match: dict, followed_teams: list[str], settings: dict[str, bool]) -> str | None:
    is_followed = settings["dota_followed_players"] and any(
        dota_connector.involves_team(match, team) for team in followed_teams
    )
    if match.get("is_ti") and (is_followed or settings["dota_ti"]):
        return "A"
    if is_followed:
        return "B"
    if match.get("is_tier1") and not match.get("is_ti") and settings["dota_tier1"]:
        return "C"
    return None


def refresh_catalogs() -> None:
    for name, refresh in (("dota", follow_service.refresh_dota_catalog), ("football", follow_service.refresh_football_catalog)):
        try:
            refresh()
        except Exception as exc:
            print(f"[scheduler] {name} catalog refresh failed: {exc}")


def sync_dota() -> None:
    settings = {
        key: event_service.is_interest_enabled("dota", key)
        for key in ("dota_ti", "dota_tier1", "dota_followed_players")
    }
    followed_teams = _followed_dota_teams() if settings["dota_followed_players"] else []
    matches = dota_connector.fetch_upcoming_matches()
    catalog_service.upsert_entities("dota", "team", dota_connector.active_teams(matches), mark_active=True)

    unwanted = {}
    for match in matches:
        priority = _dota_priority(match, followed_teams, settings)
        if priority is None:
            unwanted.setdefault(match["external_source"], []).append(match["external_id"])
            continue
        event_service.upsert_external_event({**match, "priority_tier": priority})
    for source, external_ids in unwanted.items():
        event_service.remove_upcoming_external_events(source, external_ids)


def sync_movie(follow: dict) -> None:
    if follow["external_id"]:
        event = tmdb_connector.fetch_movie_event(follow["external_id"])
    else:
        event = tmdb_connector.fetch_upcoming_movie(follow["name"])
    if event:
        event_service.upsert_external_event(event)
    else:
        print(f"[scheduler] no upcoming release found for {follow['name']!r}")


def _sync_movies() -> None:
    for follow in event_service.list_follows("movie", "movie"):
        try:
            sync_movie(follow)
        except Exception as exc:
            print(f"[scheduler] movie sync failed for {follow['name']!r}: {exc}")


def sync_anime(follow: dict) -> None:
    event = anilist_connector.fetch_anime_event(follow["name"], follow["external_id"])
    if not event:
        print(f"[scheduler] no AniList match for {follow['name']!r}")
        return
    if event.get("status") == "CATCHUP_REQUIRED" and event_service.has_external_events(
        "anilist", f"{event['media_id']}-ep"
    ):
        return
    event_service.upsert_external_event(event)


def _sync_anime() -> None:
    for follow in event_service.list_follows("anime", "anime"):
        try:
            sync_anime(follow)
        except Exception as exc:
            print(f"[scheduler] anime sync failed for {follow['name']!r}: {exc}")


def sync_new_follow(category: str, follow_id: int | None) -> None:
    follow = event_service.get_follow(follow_id) if follow_id else None
    if not follow:
        return
    try:
        if category == "anime":
            sync_anime(follow)
        elif category == "movie":
            sync_movie(follow)
        elif category == "dota":
            sync_dota()
    except Exception as exc:
        print(f"[scheduler] couldn't sync new follow {follow['name']!r}: {exc}")


def sync_all_sources() -> None:
    for name, sync in (
        ("f1", _sync_f1),
        ("football", _sync_football),
        ("dota", sync_dota),
        ("follow backfill", follow_service.backfill_follow_ids),
        ("movies", _sync_movies),
        ("anime", _sync_anime),
    ):
        try:
            sync()
        except Exception as exc:
            print(f"[scheduler] {name} sync failed: {exc}")


def start_scheduler() -> None:
    scheduler.add_job(
        sync_all_sources, "interval", hours=6, id="sync_all_sources", replace_existing=True
    )
    scheduler.add_job(
        refresh_catalogs,
        "interval",
        hours=24,
        id="refresh_catalogs",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
