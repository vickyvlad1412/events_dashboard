from datetime import datetime, timezone

import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.services import event_service
from app.services.connectors import f1_connector, football_connector, tmdb_connector, anilist_connector, dota_connector

scheduler = BackgroundScheduler(timezone="UTC")


def _sync_f1() -> None:
    year = datetime.now(timezone.utc).year
    for event in f1_connector.fetch_upcoming_sessions(year):
        event_service.upsert_external_event(event)


def _sync_football() -> None:
    team_ids = set()
    for env_var in ("LIVERPOOL_TEAM_ID", "BRAZIL_TEAM_ID"):
        team_id = os.environ.get(env_var)
        if team_id:
            team_ids.add(int(team_id))
        else:
            print(f"[scheduler] {env_var} not set; skipping.")
    if not team_ids:
        return
    for event in football_connector.fetch_team_fixtures(team_ids):
        event_service.upsert_external_event(event)


def _sync_dota() -> None:
    for event in dota_connector.fetch_upcoming_matches():
        event_service.upsert_external_event(event)


def _sync_movies() -> None:
    movie_titles = event_service.list_followed("movie")
    for event in tmdb_connector.fetch_upcoming_movies(movie_titles):
        event_service.upsert_external_event(event)


def sync_anime_title(title: str) -> None:
    event = anilist_connector.fetch_anime_event(title)
    if not event:
        print(f"[scheduler] no AniList match for {title!r}")
        return
    # A show followed while airing already has its missed episodes in catch-up,
    # so don't add a second "finished" entry once it ends.
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
