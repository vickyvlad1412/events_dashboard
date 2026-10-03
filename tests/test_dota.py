import time

import pytest

from app import scheduler
from app.services.connectors import dota_connector

FUTURE = int(time.time()) + 86400
PAST = int(time.time()) - 3600


def _block(timestamp, left, right, tournament, match_id=None, best_of="(Bo3)"):
    def opponent(name):
        if name is None:
            return '<div class="match-info-header-opponent"><div class="block-team"><span class="name">TBD</span></div></div>'
        return (
            '<div class="match-info-header-opponent"><div class="block-team">'
            f'<span class="team-template-image-icon"><a href="/dota2/{name}" title="{name}"></a></span>'
            f'<span class="name"><a title="{name}">{name.split()[-1]}</a></span>'
            "</div></div>"
        )

    match_link = (
        f'<a href="/dota2/index.php?title=Match:ID_{match_id}&amp;action=edit&amp;redlink=1"></a>' if match_id else ""
    )
    return (
        '<div class="match-info">'
        f'<span class="match-info-countdown"><span class="timer-object" data-timestamp="{timestamp}"></span></span>'
        f'<div class="match-info-header">{opponent(left)}'
        f'<div class="match-info-header-scoreholder"><span class="match-info-header-scoreholder-lower">{best_of}</span></div>'
        f"{opponent(right)}</div>"
        f'<div class="match-info-tournament"><span class="match-info-tournament-name">'
        f'<a href="/dota2/{tournament}" title="{tournament}"><span>{tournament} Display</span></a></span></div>'
        f'<div class="match-info-links">{match_link}</div>'
        "</div>"
    )


def test_parse_matches_handles_ids_tbd_duplicates_and_past():
    html = "".join(
        [
            _block(FUTURE, "Team Spirit", "Xtreme Gaming", "BLAST/SLAM/8", "abc_R01-M001"),
            _block(FUTURE, "Team Spirit", "Xtreme Gaming", "BLAST/SLAM/8", "abc_R01-M001"),
            _block(FUTURE, None, None, "The International/2026", "ti_R05-M001", "(Bo5)"),
            _block(PAST, "Team Liquid", "OG", "BLAST/SLAM/8", "old_R01-M001"),
        ]
    )

    matches = dota_connector._parse_matches(html)

    assert [m["external_id"] for m in matches] == ["abc_R01-M001", "ti_R05-M001"]
    assert matches[0]["title"] == "Team Spirit vs Xtreme Gaming"
    assert matches[0]["subtitle"] == "BLAST/SLAM/8 Display · Bo3"
    assert "Spirit" in matches[0]["teams"]
    assert matches[1]["title"] == "TBD vs TBD"
    assert matches[1]["teams"] == ["TBD", "TBD"]


def test_annotate_tournaments_uses_parent_pages_and_types(monkeypatch):
    monkeypatch.setattr(dota_connector, "_tournament_cache", {})
    wikitext = {
        "The International/2026": "{{Infobox league\n|liquipediatier=1\n}}",
        "The International/2026/Qualifiers": "{{Infobox league\n|liquipediatier=1\n|liquipediatiertype=Qualifier\n}}",
        "BLAST/SLAM/8": "{{Infobox league\n|liquipediatier=1\n}}",
        "BetBoom Streamers Battle/15": "{{Infobox league\n|liquipediatier=3\n|liquipediatiertype=showmatch\n}}",
    }
    monkeypatch.setattr(dota_connector, "_fetch_wikitext", lambda titles: {t: wikitext[t] for t in titles if t in wikitext})
    pages = [
        "The International/2026/Group Stage",
        "The International/2026/Qualifiers",
        "BLAST/SLAM/8",
        "BetBoom Streamers Battle/15",
        "",
    ]
    matches = [{"tournament_page": page} for page in pages]

    dota_connector._annotate_tournaments(matches)

    assert [(m["is_ti"], m["is_tier1"]) for m in matches] == [
        (True, True),
        (False, False),
        (False, True),
        (False, False),
        (False, False),
    ]


@pytest.mark.parametrize(
    "followed, expected",
    [("Team Spirit", True), ("spirit", True), ("Spirit ", True), ("Team Liquid", False), ("Spi", False), ("", False)],
)
def test_involves_team(followed, expected):
    match = {"teams": ["Team Spirit", "Spirit", "Xtreme Gaming", "XG"]}
    assert dota_connector.involves_team(match, followed) is expected


ALL_ON = {"dota_ti": True, "dota_tier1": True, "dota_followed_players": True}


@pytest.mark.parametrize(
    "match, settings, expected",
    [
        ({"is_ti": True, "is_tier1": True, "teams": ["OG"]}, ALL_ON, "A"),
        ({"is_ti": False, "is_tier1": True, "teams": ["OG"]}, ALL_ON, "C"),
        ({"is_ti": False, "is_tier1": True, "teams": ["Team Spirit"]}, ALL_ON, "B"),
        ({"is_ti": False, "is_tier1": False, "teams": ["Team Spirit"]}, ALL_ON, "B"),
        ({"is_ti": False, "is_tier1": False, "teams": ["OG"]}, ALL_ON, None),
        ({"is_ti": True, "is_tier1": True, "teams": ["OG"]}, {**ALL_ON, "dota_ti": False}, None),
        ({"is_ti": True, "is_tier1": True, "teams": ["Team Spirit"]}, {**ALL_ON, "dota_ti": False}, "A"),
        ({"is_ti": False, "is_tier1": True, "teams": ["OG"]}, {**ALL_ON, "dota_tier1": False}, None),
        ({"is_ti": False, "is_tier1": False, "teams": ["Team Spirit"]}, {**ALL_ON, "dota_followed_players": False}, None),
        ({"teams": ["Team Spirit"]}, ALL_ON, "B"),
    ],
)
def test_dota_priority(match, settings, expected):
    assert scheduler._dota_priority(match, ["Team Spirit"], settings) == expected
