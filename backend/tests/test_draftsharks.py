from app.draftsharks import _normalize_name, parse_player_blocks, player_key

# Trimmed fixtures of the real block shape confirmed live against
# draftsharks.com/weekly-rankings/1/ppr and its load-rows endpoint --
# enough markup for parse_player_blocks' regexes to match, not the full
# real page. No live network call in this test file (see CLAUDE.md's
# note that update_data_draftsharks.py itself has no pytest coverage
# either, for the same reason -- verified manually against a live pull).
RB_BLOCK = """<tbody
    data-player-row
    data-key="13542"
    data-fantasy-position="RB"
    data-player-name="Jahmyr Gibbs"
    class="">
    <tr class="player-row">
        <td class="player-cell player-name no-center sticky-left">
            <div class="player-details-group__team-position-container d-flex align-items-center">
                <span class="player-details-group__team-name">DET</span>
            </div>
        </td>
        <td class="ds-cell matchup centered" data-value="NO" data-attribute="matchup"></td>
        <td data-value="16.1" data-attribute="weeklyFloorPts"></td>
        <td data-value="22.9" data-attribute="consensus_projection"></td>
        <td data-value="21.4" data-attribute="weeklyPts"></td>
        <td data-value="24.6" data-attribute="weeklyCeilingPts"></td>
        <td data-value="21.0" data-attribute="weekly3dPts"></td>
    </tr>
</tbody>"""

DEF_BLOCK = """<tbody
    data-player-row
    data-key="2739"
    data-fantasy-position="DEF"
    data-player-name="Seattle Seahawks"
    class="">
    <tr class="player-row">
        <td class="player-cell player-name no-center sticky-left">
            <div class="player-details-group__team-position-container d-flex align-items-center">
                <span class="player-details-group__team-name">SEA</span>
            </div>
        </td>
        <td data-value="4.0" data-attribute="weeklyFloorPts"></td>
        <td data-value="9.0" data-attribute="consensus_projection"></td>
        <td data-value="8.0" data-attribute="weeklyPts"></td>
        <td data-value="14.0" data-attribute="weeklyCeilingPts"></td>
        <td data-value="8.5" data-attribute="weekly3dPts"></td>
    </tr>
</tbody>"""

SUFFIX_BLOCK = """<tbody
    data-player-row
    data-key="99999"
    data-fantasy-position="WR"
    data-player-name="Marvin Harrison Jr."
    class="">
    <tr class="player-row">
        <td class="player-cell player-name no-center sticky-left">
            <div class="player-details-group__team-position-container d-flex align-items-center">
                <span class="player-details-group__team-name">ARI</span>
            </div>
        </td>
        <td data-value="8.0" data-attribute="weeklyFloorPts"></td>
        <td data-value="13.0" data-attribute="consensus_projection"></td>
        <td data-value="12.0" data-attribute="weeklyPts"></td>
        <td data-value="19.0" data-attribute="weeklyCeilingPts"></td>
        <td data-value="12.5" data-attribute="weekly3dPts"></td>
    </tr>
</tbody>"""


def test_normalize_name_strips_suffix_and_punctuation():
    assert _normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert _normalize_name("D.J. Moore") == "dj moore"
    assert _normalize_name("Odell Beckham III") == "odell beckham"


def test_normalize_name_is_idempotent_on_plain_names():
    assert _normalize_name("Jahmyr Gibbs") == "jahmyr gibbs"


def test_parse_player_blocks_extracts_skill_player_fields():
    rows = parse_player_blocks(RB_BLOCK)
    assert len(rows) == 1
    row = rows[0]
    assert row["player_name"] == "Jahmyr Gibbs"
    assert row["position"] == "RB"
    assert row["team"] == "DET"
    assert row["projected_points"] == 21.0
    assert row["floor_points"] == 16.1
    assert row["ceiling_points"] == 24.6
    assert row["consensus_projection"] == 22.9


def test_parse_player_blocks_extracts_def_with_team_code():
    rows = parse_player_blocks(DEF_BLOCK)
    assert rows[0]["position"] == "DEF"
    assert rows[0]["team"] == "SEA"


def test_parse_player_blocks_handles_multiple_blocks():
    rows = parse_player_blocks(RB_BLOCK + DEF_BLOCK + SUFFIX_BLOCK)
    assert len(rows) == 3
    assert {r["player_name"] for r in rows} == {"Jahmyr Gibbs", "Seattle Seahawks", "Marvin Harrison Jr."}


def test_player_key_uses_team_code_for_def():
    assert player_key("Seattle Seahawks", "DEF", "SEA") == "SEA"


def test_player_key_uses_normalized_name_and_position_for_skill_players():
    assert player_key("Marvin Harrison Jr.", "WR", "ARI") == ("marvin harrison", "WR")
