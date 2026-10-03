from datetime import datetime, timezone

import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.services import event_service
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


def _sync_football() -> None:
    team_ids = set()
    for env_var in ("LIVERPOOL_TEAM_ID", "BRAZIL_TEAM_ID"):
        team_id = os.environ.get(env_var)
        if team_id:
            team_ids.add(int(team_id))
        else:
            print(f"[scheduler] {env_var} not set; skipping.")
    extra_league_ids = set()
    for setting, league_ids in FOOTBALL_LEAGUE_SETTINGS.items():
        if event_service.is_interest_enabled("football", setting):
            extra_league_ids |= league_ids
    if not team_ids and not extra_league_ids:
        return
    for event in football_connector.fetch_team_fixtures(team_ids, extra_league_ids):
        event_service.upsert_external_event(event)


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
    if match.get("is_tier1") and not match.get("is_ti") and settings["dota_majors"]:
        return "C"
    return None


def _sync_dota() -> None:
    settings = {
        key: event_service.is_interest_enabled("dota", key)
        for key in ("dota_ti", "dota_majors", "dota_followed_players")
    }
    followed_teams = _followed_dota_teams() if settings["dota_followed_players"] else []
    unwanted = {}
    for match in dota_connector.fetch_upcoming_matches():
        priority = _dota_priority(match, followed_teams, settings)
        if priority is None:
            unwanted.setdefault(match["external_source"], []).append(match["external_id"])
            continue
        event_service.upsert_external_event({**match, "priority_tier": priority})
    for source, external_ids in unwanted.items():
        event_service.remove_upcoming_external_events(source, external_ids)


def _sync_movies() -> None:
    for title in event_service.list_followed("movie"):
        try:
            event = tmdb_connector.fetch_upcoming_movie(title)
        except Exception as exc:
            print(f"[scheduler] movie sync failed for {title!r}: {exc}")
            continue
        if event:
            event_service.upsert_external_event(event)
        else:
            print(f"[scheduler] no upcoming release found for {title!r}")


def sync_anime_title(title: str) -> None:
    event = anilist_connector.fetch_anime_event(title)
    if not event:
        print(f"[scheduler] no AniList match for {title!r}")
        return
    if event.get("status") == "CATCHUP_REQUIRED" and event_service.has_external_events(
        "anilist", f"{event['media_id']}-ep"
    ):
        return
    event_service.upsert_external_event(event)


def _sync_anime() -> None:
    for title in event_service.list_followed("anime"):
        try:
            sync_anime_title(title)
        except Exception as exc:
            print(f"[scheduler] anime sync failed for {title!r}: {exc}")


def sync_all_sources() -> None:
    for name, sync in (
        ("f1", _sync_f1),
        ("football", _sync_football),
        ("dota", _sync_dota),
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
    scheduler.start()
