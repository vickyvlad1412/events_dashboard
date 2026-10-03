import time
from datetime import datetime, timezone

import requests

ANILIST_URL = "https://graphql.anilist.co"
RETRY_STATUSES = {429, 500, 502, 503, 504}


ANIME_QUERY = """
query ($id: Int, $search: String, $status: MediaStatus) {
  Media(id: $id, search: $search, type: ANIME, status: $status, sort: POPULARITY_DESC) {
    id
    title { romaji english }
    status
    episodes
    format
    seasonYear
    endDate { year month day }
    nextAiringEpisode { episode airingAt }
    coverImage { large medium }
  }
}
"""

SEARCH_QUERY = """
query ($search: String, $perPage: Int) {
  Page(perPage: $perPage) {
    media(search: $search, type: ANIME, isAdult: false, sort: [SEARCH_MATCH, POPULARITY_DESC]) {
      id
      title { romaji english }
      status
      format
      seasonYear
      coverImage { large medium }
    }
  }
}
"""

FORMAT_LABELS = {
    "TV": "TV", "TV_SHORT": "TV Short", "MOVIE": "Movie", "SPECIAL": "Special",
    "OVA": "OVA", "ONA": "ONA", "MUSIC": "Music",
}

STATUS_LABELS = {
    "RELEASING": "Airing",
    "FINISHED": "Finished",
    "NOT_YET_RELEASED": "Upcoming",
    "CANCELLED": "Cancelled",
    "HIATUS": "On hiatus",
}

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
    variables = {key: value for key, value in variables.items() if value is not None}
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


def _image(media: dict) -> str | None:
    cover = media.get("coverImage") or {}
    return cover.get("large") or cover.get("medium")


def _summary(media: dict) -> dict:
    details = [
        FORMAT_LABELS.get(media.get("format"), ""),
        str(media["seasonYear"]) if media.get("seasonYear") else "",
        STATUS_LABELS.get(media.get("status"), ""),
    ]
    return {
        "external_id": str(media["id"]),
        "name": _display_title(media),
        "detail": " · ".join(part for part in details if part),
        "image_url": _image(media),
    }


def search_anime(query: str, limit: int = 8) -> list[dict]:
    media_list = _post(SEARCH_QUERY, {"search": query, "perPage": limit})["Page"]["media"]
    return [_summary(media) for media in media_list]


def get_anime(media_id: str) -> dict | None:
    media = _post(ANIME_QUERY, {"id": int(media_id)})["Media"]
    return _summary(media) if media else None


def fetch_anime_event(anime_title: str | None = None, media_id: str | None = None) -> dict | None:
    if media_id:
        media = _post(ANIME_QUERY, {"id": int(media_id)})["Media"]
    else:
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
        "image_url": _image(media),
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
