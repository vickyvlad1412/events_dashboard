import re
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
    season
    seasonYear
    startDate { year month day }
    endDate { year month day }
    nextAiringEpisode { episode airingAt }
    coverImage { large medium }
  }
}
"""

DETAILS_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english native }
    description(asHtml: false)
    format
    status
    episodes
    duration
    season
    seasonYear
    source
    genres
    averageScore
    popularity
    siteUrl
    bannerImage
    coverImage { extraLarge large }
    startDate { year month day }
    endDate { year month day }
    nextAiringEpisode { episode airingAt }
    studios(isMain: true) { nodes { name } }
    trailer { id site }
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
query ($season: MediaSeason, $year: Int, $perPage: Int, $sort: [MediaSort]) {
  Page(perPage: $perPage) {
    media(season: $season, seasonYear: $year, type: ANIME, isAdult: false, sort: $sort) {
      id
      title { romaji english }
      averageScore
      popularity
      format
      status
      description(asHtml: false)
      siteUrl
      coverImage { large }
    }
  }
}
"""

SEASON_NAMES = {"WINTER": "Winter", "SPRING": "Spring", "SUMMER": "Summer", "FALL": "Fall"}
SOURCE_LABELS = {
    "ORIGINAL": "Original", "MANGA": "Manga", "LIGHT_NOVEL": "Light novel", "WEB_NOVEL": "Web novel",
    "NOVEL": "Novel", "VISUAL_NOVEL": "Visual novel", "VIDEO_GAME": "Video game", "OTHER": "Other",
}
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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


def _expected_note(media: dict) -> str:
    start = media.get("startDate") or {}
    if start.get("year") and start.get("month"):
        return f"Expected {MONTH_NAMES[start['month'] - 1]} {start['year']}"
    if media.get("season") and media.get("seasonYear"):
        return f"Expected {SEASON_NAMES.get(media['season'], media['season'].title())} {media['seasonYear']}"
    if start.get("year") or media.get("seasonYear"):
        return f"Expected {start.get('year') or media['seasonYear']}"
    return "Date TBD"


def fetch_anime(anime_title: str | None = None, media_id: str | None = None) -> dict:
    if media_id:
        media = _post(ANIME_QUERY, {"id": int(media_id)})["Media"]
    else:
        media = _search(anime_title)
    if not media:
        return {"event": None, "note": None, "media_id": None}
    event = _event_for(media)
    note = None
    if event is None:
        if media.get("status") == "NOT_YET_RELEASED":
            note = _expected_note(media)
        elif media.get("status") == "RELEASING":
            note = "Airing · next episode date TBD"
    return {"event": event, "note": note, "media_id": media["id"]}


def fetch_anime_event(anime_title: str | None = None, media_id: str | None = None) -> dict | None:
    return fetch_anime(anime_title, media_id)["event"]


def _event_for(media: dict) -> dict | None:
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

    start = media.get("startDate") or {}
    if media.get("status") == "NOT_YET_RELEASED" and start.get("year") and start.get("month") and start.get("day"):
        return {
            **event,
            "subtitle": "Premiere",
            "event_datetime_utc": datetime(start["year"], start["month"], start["day"], tzinfo=timezone.utc),
            "external_id": f"{media['id']}-premiere",
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


def fetch_top_seasonal_anime(year: int, season: str, limit: int = 10, sort: str = "SCORE_DESC") -> list[dict]:
    media_list = _post(
        SEASONAL_QUERY, {"season": season.upper(), "year": year, "perPage": limit, "sort": [sort]}
    )["Page"]["media"]
    return [
        {
            "anilist_id": m["id"],
            "title": _display_title(m),
            "score": m["averageScore"] / 10 if m.get("averageScore") else None,
            "popularity": m.get("popularity"),
            "format": FORMAT_LABELS.get(m.get("format"), ""),
            "status": STATUS_LABELS.get(m.get("status"), ""),
            "synopsis": m.get("description"),
            "anilist_url": m.get("siteUrl"),
            "image_url": (m.get("coverImage") or {}).get("large"),
        }
        for m in media_list
    ]


def _format_date(date: dict | None) -> str | None:
    date = date or {}
    if not date.get("year"):
        return None
    if date.get("month") and date.get("day"):
        return f"{date['day']} {MONTH_NAMES[date['month'] - 1]} {date['year']}"
    if date.get("month"):
        return f"{MONTH_NAMES[date['month'] - 1]} {date['year']}"
    return str(date["year"])


def get_anime_details(media_id: str) -> dict | None:
    media = _post(DETAILS_QUERY, {"id": int(media_id)})["Media"]
    if not media:
        return None
    titles = media.get("title") or {}
    trailer = media.get("trailer") or {}
    trailer_url = None
    if trailer.get("site") == "youtube" and trailer.get("id"):
        trailer_url = f"https://www.youtube.com/watch?v={trailer['id']}"
    next_ep = media.get("nextAiringEpisode")
    season = SEASON_NAMES.get(media.get("season") or "", "")
    return {
        "id": str(media["id"]),
        "title": _display_title(media),
        "alt_titles": [t for t in (titles.get("romaji"), titles.get("native")) if t and t != _display_title(media)],
        "description": _plain_text(media.get("description")),
        "format": FORMAT_LABELS.get(media.get("format"), media.get("format")),
        "status": STATUS_LABELS.get(media.get("status"), media.get("status")),
        "episodes": media.get("episodes"),
        "duration": media.get("duration"),
        "season": " ".join(p for p in (season, str(media.get("seasonYear") or "")) if p) or None,
        "source": SOURCE_LABELS.get(media.get("source"), None),
        "genres": media.get("genres") or [],
        "score": media["averageScore"] / 10 if media.get("averageScore") else None,
        "popularity": media.get("popularity"),
        "studios": [node["name"] for node in ((media.get("studios") or {}).get("nodes") or [])],
        "start_date": _format_date(media.get("startDate")),
        "end_date": _format_date(media.get("endDate")),
        "next_episode": next_ep["episode"] if next_ep else None,
        "next_airing": datetime.fromtimestamp(next_ep["airingAt"], tz=timezone.utc).isoformat() if next_ep else None,
        "poster_url": (media.get("coverImage") or {}).get("extraLarge") or _image(media),
        "banner_url": media.get("bannerImage"),
        "trailer_url": trailer_url,
        "site_url": media.get("siteUrl"),
        "note": _expected_note(media) if media.get("status") == "NOT_YET_RELEASED" else None,
    }


def _plain_text(text: str | None) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
