from pydantic import BaseModel, field_validator


class LeagueCreate(BaseModel):
    sleeper_league_id: str

    @field_validator("sleeper_league_id")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("sleeper_league_id must not be blank")
        return value


class LeagueOut(BaseModel):
    id: str
    sleeper_league_id: str
    league_name: str
    season: str
    created_at: str
    sleeper_roster_id: int | None = None


class RosterOption(BaseModel):
    sleeper_roster_id: int
    owner_display_name: str


class RosterClaim(BaseModel):
    sleeper_roster_id: int


class LineupPlayer(BaseModel):
    player_id: str
    position: str
    projected_points: float
    name: str | None = None
    team: str | None = None
    injury_status: str | None = None
    slot: str | None = None
    same_team_stack_with: str | None = None  # a starter teammate's player_id, informational only


class AlternateLineup(BaseModel):
    starters: list[LineupPlayer]
    bench: list[LineupPlayer]
    total_projected_points: float
    swapped_out: list[str]


class LineupResponse(BaseModel):
    week: int
    starters: list[LineupPlayer]
    bench: list[LineupPlayer]
    total_projected_points: float
    unresolved_player_ids: list[str] = []
    alternate_lineup: AlternateLineup | None = None
