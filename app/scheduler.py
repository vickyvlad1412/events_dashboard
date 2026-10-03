from datetime import datetime, timezone

import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.services import event_service
from app.services.connectors import f1_connector, football_connector, tmdb_connector, jikan_connector, dota_connector

scheduler = BackgroundScheduler(timezone="UTC")


def sync_all_sources() -> None:
    year = datetime.now(timezone.utc).year

    for event in f1_connector.fetch_upcoming_sessions(year):
        event_service.upsert_external_event(event)

    for env_var in ("LIVERPOOL_TEAM_ID", "BRAZIL_TEAM_ID"):
        team_id = os.environ.get(env_var)
        if team_id:
            for event in football_connector.fetch_team_fixtures(team_id=int(team_id)):
                event_service.upsert_external_event(event)
    
    for event in dota_connector.fetch_upcoming_matches():
        event_service.upsert_external_event(event)
    
    movie_titles = event_service.list_followed("movie")
    for event in tmdb_connector.fetch_upcoming_movies(movie_titles):
        event_service.upsert_external_event(event)

    anime_titles = event_service.list_followed("anime")
    for title in anime_titles:
        event = jikan_connector.fetch_next_episode(title)
        if event:
            event_service.upsert_external_event(event)


def start_scheduler() -> None:
    scheduler.add_job(
        sync_all_sources, "interval", hours=6, id="sync_all_sources", replace_existing=True
    )
    scheduler.start()
