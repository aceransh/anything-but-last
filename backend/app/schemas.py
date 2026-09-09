from pydantic import BaseModel, field_validator, model_validator


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
    injury_warning: bool = False  # True for starters whose status means "likely/definitely not playing"


class AlternateLineup(BaseModel):
    starters: list[LineupPlayer]
    bench: list[LineupPlayer]
    total_projected_points: float
    swapped_out: list[str]


class UnresolvedPlayer(BaseModel):
    player_id: str
    reason: str  # "bye" (confirmed, DEF only) or "no_projection" (likely bye or unmodeled)


class ContextLineup(BaseModel):
    starters: list[LineupPlayer]
    bench: list[LineupPlayer]
    total_projected_points: float
    w_context: float  # 1.0 = full underdog/ceiling-favoring, 0.0 = full favorite/floor-favoring


class LineupResponse(BaseModel):
    week: int
    starters: list[LineupPlayer]
    bench: list[LineupPlayer]
    total_projected_points: float
    unresolved_players: list[UnresolvedPlayer] = []
    alternate_lineup: AlternateLineup | None = None
    context_lineup: ContextLineup | None = None


class TradeRosterPlayer(BaseModel):
    player_id: str
    position: str
    projected_points: float
    name: str | None = None
    team: str | None = None
    injury_status: str | None = None


class TradeMove(BaseModel):
    player_id: str
    from_roster_id: int
    to_roster_id: int


class TradeEvaluateRequest(BaseModel):
    roster_ids: list[int]
    moves: list[TradeMove]

    @model_validator(mode="after")
    def valid(self) -> "TradeEvaluateRequest":
        if len(self.roster_ids) < 2:
            raise ValueError("A trade needs at least two teams")
        if len(set(self.roster_ids)) != len(self.roster_ids):
            raise ValueError("Duplicate roster in trade")
        if not self.moves:
            raise ValueError("A trade needs at least one player movement")
        for move in self.moves:
            if move.from_roster_id == move.to_roster_id:
                raise ValueError("A player can't move to the same roster")
            if move.from_roster_id not in self.roster_ids or move.to_roster_id not in self.roster_ids:
                raise ValueError("Move references a roster not in this trade")
        return self


class TradePlayer(BaseModel):
    player_id: str
    position: str
    projected_points: float
    name: str | None = None
    team: str | None = None
    injury_status: str | None = None


class LineupImpactSide(BaseModel):
    before_total_projected_points: float
    after_total_projected_points: float
    change: float


class TeamTradeResult(BaseModel):
    roster_id: int
    giving_players: list[TradePlayer]
    receiving_players: list[TradePlayer]
    giving_total: float
    receiving_total: float
    differential: float  # lineup_impact.change -- real optimal-lineup swing, not raw point totals
    verdict: str
    lineup_impact: LineupImpactSide
    # Same shape, scoped to weeks >= TradeEvaluateResponse.playoff_start_week --
    # a second honest number, not folded into the season-total one above.
    # None if the league's playoff_week_start is unknown or already past
    # the evaluated week range.
    playoff_lineup_impact: LineupImpactSide | None = None


class TradeEvaluateResponse(BaseModel):
    start_week: int
    end_week: int
    playoff_start_week: int | None = None
    teams: list[TeamTradeResult]


class TradeCandidate(BaseModel):
    roster_ids: list[int]
    moves: list[TradeMove]
    teams: list[TeamTradeResult]


class TradeFinderResponse(BaseModel):
    start_week: int
    end_week: int
    playoff_start_week: int | None = None
    candidates: list[TradeCandidate]


class MatchupPlayer(BaseModel):
    player_id: str
    position: str
    projected_points: float
    name: str | None = None
    team: str | None = None
    injury_status: str | None = None
    slot: str | None = None


class MatchupScoreStats(BaseModel):
    mean: float
    median: float
    p10: float
    p90: float


class MatchupSimulationResponse(BaseModel):
    week: int
    own_roster_id: int
    opponent_roster_id: int
    win_prob: float
    opponent_win_prob: float
    own_score: MatchupScoreStats
    opponent_score: MatchupScoreStats
    own_starters: list[MatchupPlayer]
    opponent_starters: list[MatchupPlayer]


class PlayoffOddsEntry(BaseModel):
    roster_id: int
    current_wins: int
    current_losses: int
    current_ties: int
    current_fpts: float
    playoff_odds: float


class PlayoffOddsResponse(BaseModel):
    playoff_teams: int
    playoff_week_start: int | None = None
    entries: list[PlayoffOddsEntry]
