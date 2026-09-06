from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings


@lru_cache
def get_supabase() -> Client:
    """Service-role client -- bypasses RLS, so every query site using this
    must filter by the caller's own user_id explicitly (see deps.py). RLS is
    still enabled on every table as the real boundary against any other
    access path.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
