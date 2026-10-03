import time
from datetime import datetime, timezone

import requests

ANILIST_URL = "https://graphql.anilist.co"
RETRY_STATUSES = {429, 500, 502, 503, 504}


ANIME_QUERY = """
query ($search: String, $status: MediaStatus) {
  Media(search: $search, type: ANIME, status: $status, sort: POPULARITY_DESC) {
    id
    title { romaji english }
    status
    episodes
    endDate { year month day }
    nextAiringEpisode { episode airingAt }
  }
}
"""

CATCHUP_TAGS = {"FINISHED": "Finished airing", "CANCELLED": "Cancelled", "HIATUS": "On hiatus"}

SEASONAL_QUERY = """
query ($season: MediaSeason, $year: Int, $perPage: Int) {
  Page(perPage: $perPage) {
    media(season: $season, seasonYear: $year, type: ANIME, isAdult: false, sort: SCORE_DESC) {
      id
      title { romaji english }
      averageScore
      description(asHtml: false)
      siteUrl
      coverImage { large }
    }
  }
}
"""


def _display_title(media: dict) -> str:
    return media["title"]["english"] or media["title"]["romaji"]


def _post(query: str, variables: dict, attempts: int = 3) -> dict:
    for attempt in range(attempts):
        resp = requests.post(
            ANILIST_URL, json={"query": query, "variables": variables}, timeout=10
        )
        if resp.status_code not in RETRY_STATUSES or attempt == attempts - 1:
            break
        time.sleep(min(int(resp.headers.get("Retry-After", 2 ** attempt)), 60))
    body = resp.json()
    if resp.status_code == 404 and (body.get("data") or {}).get("Media") is None:
        return {"Media": None}
    resp.raise_for_status()
    return body["data"]


def _search(anime_title: str) -> dict | None:
    return (
        _post(ANIME_QUERY, {"search": anime_title, "status": "RELEASING"})["Media"]
        or _post(ANIME_QUERY, {"search": anime_title})["Media"]
    )


def _end_date(media: dict) -> datetime:
    end = media.get("endDate") or {}
    if not end.get("year"):
        return datetime.now(timezone.utc)
    return datetime(end["year"], end.get("month") or 1, end.get("day") or 1, tzinfo=timezone.utc)


def fetch_anime_event(anime_title: str) -> dict | None:
    media = _search(anime_title)
    if not media:
        return None

    event = {
        "category": "anime",
        "title": _display_title(media),
        "venue": None,
        "priority_tier": "B",
        "live_preference": "ANYTIME",
        "external_source": "anilist",
        "media_id": media["id"],
    }

    next_ep = media.get("nextAiringEpisode")
    if next_ep:
        return {
            **event,
            "subtitle": f"Episode {next_ep['episode']}",
            "event_datetime_utc": datetime.fromtimestamp(next_ep["airingAt"], tz=timezone.utc),
            "external_id": f"{media['id']}-ep{next_ep['episode']}",
        }

    tag = CATCHUP_TAGS.get(media.get("status"))
    if not tag:
        return None
    if media.get("episodes"):
        tag += f" · {media['episodes']} episodes"
    return {
        **event,
        "subtitle": tag,
        "event_datetime_utc": _end_date(media),
        "status": "CATCHUP_REQUIRED",
        "external_id": f"{media['id']}-catchup",
    }


def fetch_top_seasonal_anime(year: int, season: str, limit: int = 10) -> list[dict]:
    media_list = _post(
        SEASONAL_QUERY, {"season": season.upper(), "year": year, "perPage": limit}
    )["Page"]["media"]
    return [
        {
            "anilist_id": m["id"],
            "title": _display_title(m),
            "score": m["averageScore"] / 10 if m.get("averageScore") else None,
            "synopsis": m.get("description"),
            "anilist_url": m.get("siteUrl"),
            "image_url": (m.get("coverImage") or {}).get("large"),
        }
        for m in media_list
    ]
