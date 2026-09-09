from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    allowed_origins: str = "http://localhost:5173"
    # Shared secret the /internal/waiver-scan endpoint checks against the
    # X-Cron-Secret header -- unset locally is fine (that endpoint just
    # 401s), but must be set in Vercel Production for the GitHub Actions
    # scan workflow to authenticate (see .github/workflows/waiver-scan.yml).
    cron_secret: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
