"""Settings, read once from the environment.

Every secret enters the app here. Nothing else calls os.environ, so there is one
place to look when a key is missing and one place to add a new one.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Gemini. Model names live in config so they can be swapped without a code
    # change — the available names differ per key and change between releases.
    gemini_api_key: str = ""
    gemini_model: str = ""
    gemini_embed_model: str = ""

    # Hard stop for a day's AI spend. The wrapper refuses to call Gemini once
    # the day's logged cost crosses this, so a runaway loop in a factory script
    # costs one afternoon's budget and not the month's.
    daily_ai_budget_usd: float = 2.0

    # Local dev defaults; the deployed frontend origin is added on Render.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def missing(self) -> list[str]:
        """Required settings that are still empty.

        Returned rather than raised: the API has to start without a Gemini key
        so that /health can report what is wrong.
        """
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "SUPABASE_JWT_SECRET": self.supabase_jwt_secret,
            "GEMINI_API_KEY": self.gemini_api_key,
            "GEMINI_MODEL": self.gemini_model,
            "GEMINI_EMBED_MODEL": self.gemini_embed_model,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
