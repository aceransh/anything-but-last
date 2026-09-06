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
