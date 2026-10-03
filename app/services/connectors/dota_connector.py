import os
import re
import threading
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

LPDB_API_KEY = os.environ.get("LPDB_API_KEY")
LIQUIPEDIA_CONTACT = os.environ.get("LIQUIPEDIA_CONTACT") or "not set"

LIQUIPEDIA_API_URL = "https://liquipedia.net/dota2/api.php"
HEADERS = {
    "User-Agent": f"PersonalEventsDashboard/1.0 (personal project; contact: {LIQUIPEDIA_CONTACT})",
    "Accept-Encoding": "gzip",
}

MATCH_TICKER = "{{#invoke:Lua|invoke|module=MatchTicker/Custom|fn=mainPage|type=upcoming|limit=300}}"
REQUEST_INTERVALS = {"parse": 30, "query": 2}
MATCH_CACHE_SECONDS = 600
PLAYER_CACHE_SECONDS = 6 * 3600
TI_PAGE = re.compile(r"^The International/\d{4}(/|$)")
NON_MAIN_EVENT_TYPES = {"qualifier", "showmatch", "misc", "national"}

_request_lock = threading.Lock()
_last_request = {"parse": 0.0, "query": 0.0}
_match_cache = {"at": 0.0, "matches": []}
_tournament_cache: dict[str, dict] = {}
_player_cache: dict[str, tuple[float, str]] = {}


def fetch_upcoming_matches() -> list[dict]:
    if LPDB_API_KEY:
        try:
            return _fetch_from_lpdb()
        except Exception as exc:
            print(f"[dota_connector] LPDB fetch failed ({exc}); falling back to MediaWiki.")

    return _fetch_from_mediawiki()


def involves_team(match: dict, team_name: str) -> bool:
    wanted = _tokens(team_name)
    return bool(wanted) and any(wanted <= _tokens(name) for name in match.get("teams", []))


CATALOG_CATEGORIES = {"team": "Category:Teams", "player": "Category:Players"}


def fetch_catalog(entity_type: str) -> list[dict]:
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": CATALOG_CATEGORIES[entity_type],
        "cmnamespace": 0,
        "cmtype": "page",
        "cmlimit": 500,
    }
    entities = []
    while True:
        body = _request("query", params)
        entities += [
            {"external_id": member["title"], "name": member["title"]}
            for member in body["query"]["categorymembers"]
        ]
        if "continue" not in body:
            return entities
        params = {**params, **body["continue"]}


def active_teams(matches: list[dict]) -> list[dict]:
    teams = {}
    for match in matches:
        for opponent in match.get("opponents", []):
            if opponent["full_name"]:
                teams[opponent["full_name"]] = {
                    "external_id": opponent["full_name"],
                    "name": opponent["full_name"],
                    "short_name": opponent["short_name"] or None,
                }
    return list(teams.values())


def fetch_player_teams(players: list[str]) -> dict[str, str]:
    teams = {}
    for player in players:
        cached = _player_cache.get(player.lower())
        if cached and time.monotonic() - cached[0] < PLAYER_CACHE_SECONDS:
            team = cached[1]
        else:
            team = _request(
                "query",
                {"action": "expandtemplates", "prop": "wikitext", "title": player, "text": "{{PlayerTeamAuto}}"},
            )["expandtemplates"]["wikitext"].strip()
            _player_cache[player.lower()] = (time.monotonic(), team)
        if team:
            teams[player] = team
        else:
            print(f"[dota_connector] no current team found for player {player!r}; check the Liquipedia page name.")
    return teams


def _fetch_from_lpdb() -> list[dict]:
    import lpdb_python as lpdb

    session = lpdb.LpdbSession(LPDB_API_KEY)
    # Representative shape — confirm the exact method name/signature for
    # querying matches against lpdb_python's current README before relying
    # on this; it's a young wrapper and may not match exactly.
    raw_matches = session.get_match(
        wiki="dota2", conditions="[[date::>now]]", order="date asc", limit=20
    )

    now = datetime.now(timezone.utc)
    events = []
    for raw in raw_matches:
        match = lpdb.Match(raw)
        start = match.date
        if start < now:
            continue
        events.append(
            {
                "category": "dota",
                "title": f"{match.opponent1} vs {match.opponent2}",
                "subtitle": match.tournament,
                "event_datetime_utc": start,
                "venue": None,
                "priority_tier": "C",
                "live_preference": "LIVE",
                "external_source": "lpdb",
                "external_id": str(match.match_id),
            }
        )
    return events


def _request(kind: str, params: dict) -> dict:
    with _request_lock:
        wait = REQUEST_INTERVALS[kind] - (time.monotonic() - _last_request[kind])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(
                LIQUIPEDIA_API_URL, headers=HEADERS, params={"format": "json", **params}, timeout=30
            )
        finally:
            _last_request[kind] = time.monotonic()
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Liquipedia API error: {body['error']}")
    return body


def _fetch_from_mediawiki() -> list[dict]:
    if _match_cache["matches"] and time.monotonic() - _match_cache["at"] < MATCH_CACHE_SECONDS:
        return _match_cache["matches"]

    html = _request(
        "parse", {"action": "parse", "prop": "text", "contentmodel": "wikitext", "text": MATCH_TICKER}
    )["parse"]["text"]["*"]
    matches = _parse_matches(html)
    _annotate_tournaments(matches)

    _match_cache.update(at=time.monotonic(), matches=matches)
    return matches


def _parse_matches(html: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    events = []
    for block in soup.select(".match-info"):
        timer = block.select_one(".timer-object[data-timestamp]")
        opponents = [_opponent(o) for o in block.select(".match-info-header-opponent")]
        if not timer or len(opponents) != 2:
            continue

        timestamp = timer["data-timestamp"]
        start = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        if start < now:
            continue

        tournament_link = block.select_one(".match-info-tournament-name a[title]")
        tournament_page = tournament_link["title"].split("#")[0] if tournament_link else ""
        tournament_name = tournament_link.get_text(strip=True) if tournament_link else ""

        external_id = _match_id(block) or "|".join(
            [tournament_page, timestamp, opponents[0]["name"], opponents[1]["name"]]
        )
        if external_id in seen:
            continue
        seen.add(external_id)

        best_of = block.select_one(".match-info-header-scoreholder-lower")
        best_of_text = best_of.get_text(strip=True).strip("()") if best_of else ""

        events.append(
            {
                "category": "dota",
                "title": f"{opponents[0]['name']} vs {opponents[1]['name']}",
                "subtitle": " · ".join(part for part in (tournament_name, best_of_text) if part) or None,
                "event_datetime_utc": start,
                "venue": None,
                "priority_tier": "C",
                "live_preference": "LIVE",
                "external_source": "liquipedia",
                "external_id": external_id,
                "teams": opponents[0]["names"] + opponents[1]["names"],
                "opponents": opponents,
                "tournament_page": tournament_page,
            }
        )
    return events


def _opponent(element) -> dict:
    icon_link = element.select_one(".team-template-image-icon a[title]")
    short = element.select_one(".name")
    full_name = icon_link["title"] if icon_link else ""
    short_name = short.get_text(strip=True) if short else ""
    name = full_name or short_name or "TBD"
    return {
        "name": name,
        "names": [n for n in {full_name, short_name} if n],
        "full_name": full_name,
        "short_name": short_name if short_name != full_name else "",
    }


def _match_id(block) -> str | None:
    link = block.find("a", href=re.compile(r"Match:ID_"))
    found = re.search(r"Match:ID_([\w-]+)", link["href"]) if link else None
    return found.group(1) if found else None


def _annotate_tournaments(matches: list[dict]) -> None:
    pages = {m["tournament_page"] for m in matches if m["tournament_page"]}
    missing = sorted({p for page in pages - _tournament_cache.keys() for p in _with_parents(page)})
    texts = _fetch_wikitext(missing) if missing else {}

    for page in pages - _tournament_cache.keys():
        info = {"tier": "", "type": ""}
        for candidate in _with_parents(page):
            text = texts.get(candidate, "")
            tier = _field(text, "liquipediatier")
            if tier:
                info = {"tier": tier, "type": _field(text, "liquipediatiertype").lower()}
                break
        _tournament_cache[page] = info

    for match in matches:
        info = _tournament_cache.get(match["tournament_page"], {"tier": "", "type": ""})
        main_event = info["tier"] == "1" and info["type"] not in NON_MAIN_EVENT_TYPES
        match["is_ti"] = main_event and bool(TI_PAGE.match(match["tournament_page"]))
        match["is_tier1"] = main_event


def _with_parents(page: str) -> list[str]:
    parts = page.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _fetch_wikitext(titles: list[str]) -> dict[str, str]:
    result = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        query = _request(
            "query",
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "redirects": 1,
                "titles": "|".join(batch),
            },
        )["query"]

        resolved = {title: title for title in batch}
        for step in query.get("normalized", []) + query.get("redirects", []):
            for original, current in resolved.items():
                if current == step["from"]:
                    resolved[original] = step["to"]

        texts = {
            page["title"]: page["revisions"][0]["slots"]["main"]["*"]
            for page in query.get("pages", {}).values()
            if "revisions" in page
        }
        for original, current in resolved.items():
            if current in texts:
                result[original] = texts[current]
    return result


def _field(wikitext: str, name: str) -> str:
    found = re.search(rf"\|\s*{name}\s*=\s*([^\n|}}]*)", wikitext)
    return found.group(1).strip() if found else ""


def _tokens(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))
