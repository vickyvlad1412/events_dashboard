import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.db import get_meta, set_meta
from app.services import catalog_service, event_service, follow_service
from app.services.connectors import f1_connector, football_connector, tmdb_connector, anilist_connector, dota_connector

scheduler = BackgroundScheduler(timezone="UTC")

SYNC_INTERVAL = timedelta(hours=6)
RETRY_DELAY = timedelta(hours=1)
LAST_SYNC_KEY = "last_synced_at"

FOOTBALL_LEAGUE_RULES = {
    "football_champions_league": {football_connector.CHAMPIONS_LEAGUE_ID},
    "football_other_pl": {football_connector.PREMIER_LEAGUE_ID},
    "football_international_tournaments": football_connector.INTERNATIONAL_TOURNAMENT_IDS,
}

_sync_lock = threading.Lock()
_sync_state = {"running": False, "started_at": None, "finished_at": None}


def _sync_f1(rules: dict) -> None:
    year = datetime.now(timezone.utc).year
    unwanted_ids = []
    for event in f1_connector.fetch_upcoming_sessions(year):
        tier = rules.get(event["rule_key"])
        if tier is None:
            unwanted_ids.append(event["external_id"])
            continue
        event_service.upsert_external_event({**event, "priority_tier": tier})
    event_service.remove_upcoming_external_events("openf1", unwanted_ids)


def _followed_football_team_ids() -> set[int]:
    return {
        int(follow["external_id"])
        for follow in event_service.list_follows("team", "football")
        if (follow["external_id"] or "").isdigit()
    }


def _football_rule(event: dict, rules: dict) -> str | None:
    if event["followed"]:
        key = "football_followed_pl" if event["league_id"] == football_connector.PREMIER_LEAGUE_ID else "football_followed_other"
        if rules.get(key):
            return key
    for key, league_ids in FOOTBALL_LEAGUE_RULES.items():
        if event["league_id"] in league_ids and rules.get(key):
            return key
    return None


def _sync_football(rules: dict) -> None:
    fixtures = football_connector.fetch_fixture_window()
    catalog_service.upsert_entities(
        "football", "team", football_connector.teams_from_fixtures(fixtures), mark_active=True
    )
    follow_service.refresh_catalog_follow_details("football", "team")

    team_ids = _followed_football_team_ids()
    extra_league_ids = set().union(*FOOTBALL_LEAGUE_RULES.values())
    kept_ids = set()
    for event in football_connector.select_fixtures(fixtures, team_ids, extra_league_ids):
        rule_key = _football_rule(event, rules)
        if rule_key is None:
            continue
        event_service.upsert_external_event({**event, "rule_key": rule_key, "priority_tier": rules[rule_key]})
        kept_ids.add(event["external_id"])
    event_service.remove_upcoming_external_events(
        "api-football", [str(item["fixture"]["id"]) for item in fixtures if str(item["fixture"]["id"]) not in kept_ids]
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


def _dota_rule(match: dict, followed_teams: list[str], rules: dict) -> str | None:
    is_followed = bool(rules.get("dota_followed_players")) and any(
        dota_connector.involves_team(match, team) for team in followed_teams
    )
    if match.get("is_ti") and rules.get("dota_ti"):
        return "dota_ti"
    if is_followed:
        return "dota_followed_players"
    if match.get("is_tier1") and not match.get("is_ti") and rules.get("dota_tier1"):
        return "dota_tier1"
    return None


def refresh_catalogs() -> None:
    for name, refresh in (("dota", follow_service.refresh_dota_catalog), ("football", follow_service.refresh_football_catalog)):
        try:
            refresh()
        except Exception as exc:
            print(f"[scheduler] {name} catalog refresh failed: {exc}")


def sync_dota(rules: dict | None = None) -> None:
    rules = rules if rules is not None else event_service.rule_tiers()
    followed_teams = _followed_dota_teams() if rules.get("dota_followed_players") else []
    matches = dota_connector.fetch_upcoming_matches()
    catalog_service.upsert_entities("dota", "team", dota_connector.active_teams(matches), mark_active=True)

    unwanted = {}
    for match in matches:
        rule_key = _dota_rule(match, followed_teams, rules)
        if rule_key is None:
            unwanted.setdefault(match["external_source"], []).append(match["external_id"])
            continue
        event_service.upsert_external_event({**match, "rule_key": rule_key, "priority_tier": rules[rule_key]})
    for source, external_ids in unwanted.items():
        event_service.remove_upcoming_external_events(source, external_ids)


def sync_movie(follow: dict, rules: dict | None = None) -> None:
    rules = rules if rules is not None else event_service.rule_tiers()
    tier = rules.get("movie_releases")
    if tier is None:
        return
    if follow["external_id"]:
        result = tmdb_connector.fetch_movie(follow["external_id"])
    else:
        result = {"event": tmdb_connector.fetch_movie_by_title(follow["name"]), "note": None}
    event_service.set_follow_note(follow["id"], result["note"])
    if result["event"]:
        event_service.upsert_external_event({**result["event"], "rule_key": "movie_releases", "priority_tier": tier})
    elif not result["note"]:
        print(f"[scheduler] no recent or upcoming release found for {follow['name']!r}")


def _sync_movies(rules: dict) -> None:
    for follow in event_service.list_follows("movie", "movie"):
        try:
            sync_movie(follow, rules)
        except Exception as exc:
            print(f"[scheduler] movie sync failed for {follow['name']!r}: {exc}")


def sync_anime(follow: dict, rules: dict | None = None) -> None:
    rules = rules if rules is not None else event_service.rule_tiers()
    tier = rules.get("anime_episodes")
    if tier is None:
        return
    result = anilist_connector.fetch_anime(follow["name"], follow["external_id"])
    event_service.set_follow_note(follow["id"], result["note"])
    event = result["event"]
    if not event:
        if not result["note"]:
            print(f"[scheduler] no AniList match for {follow['name']!r}")
        return
    if event.get("status") == "CATCHUP_REQUIRED" and event_service.has_external_events(
        "anilist", f"{event['media_id']}-ep"
    ):
        return
    event_service.upsert_external_event({**event, "rule_key": "anime_episodes", "priority_tier": tier})


def _sync_anime(rules: dict) -> None:
    for follow in event_service.list_follows("anime", "anime"):
        try:
            sync_anime(follow, rules)
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


SOURCES = ("f1", "football", "dota", "follow backfill", "movies", "anime")


def sync_all_sources(only: tuple[str, ...] | None = None) -> list[str]:
    rules = event_service.rule_tiers()
    steps = {
        "f1": lambda: _sync_f1(rules),
        "football": lambda: _sync_football(rules),
        "dota": lambda: sync_dota(rules),
        "follow backfill": follow_service.backfill_follow_ids,
        "movies": lambda: _sync_movies(rules),
        "anime": lambda: _sync_anime(rules),
    }
    failed = []
    for name in only or SOURCES:
        try:
            steps[name]()
        except Exception as exc:
            failed.append(name)
            print(f"[scheduler] {name} sync failed: {exc}")
    if only is None:
        set_meta(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
    return failed


def _schedule_retry(failed: list[str]) -> None:
    if not failed or not scheduler.running:
        return
    scheduler.add_job(
        run_sync,
        DateTrigger(run_date=datetime.now(timezone.utc) + RETRY_DELAY),
        kwargs={"only": tuple(failed)},
        id="retry_failed_sources",
        replace_existing=True,
    )
    print(f"[scheduler] will retry {', '.join(failed)} in {int(RETRY_DELAY.total_seconds() // 60)} minutes")


def run_sync(only: tuple[str, ...] | None = None) -> bool:
    if not _sync_lock.acquire(blocking=False):
        return False
    _sync_state.update(running=True, started_at=datetime.now(timezone.utc).isoformat())
    try:
        failed = sync_all_sources(only)
    finally:
        _sync_state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat())
        _sync_lock.release()
    _schedule_retry(failed)
    return True


def start_background_sync() -> bool:
    if _sync_state["running"]:
        return False
    threading.Thread(target=run_sync, name="sync", daemon=True).start()
    return True


def sync_status() -> dict:
    return {**_sync_state, "last_synced_at": get_meta(LAST_SYNC_KEY)}


def next_sync_time(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    last = get_meta(LAST_SYNC_KEY)
    if not last:
        return now
    due = datetime.fromisoformat(last) + SYNC_INTERVAL
    return max(due, now)


def start_scheduler() -> None:
    now = datetime.now(timezone.utc)
    scheduler.add_job(
        run_sync,
        IntervalTrigger(hours=SYNC_INTERVAL.total_seconds() / 3600),
        id="sync_all_sources",
        replace_existing=True,
        next_run_time=next_sync_time(now),
    )
    scheduler.add_job(
        refresh_catalogs,
        IntervalTrigger(hours=24),
        id="refresh_catalogs",
        replace_existing=True,
        next_run_time=now + timedelta(seconds=30),
    )
    scheduler.start()
