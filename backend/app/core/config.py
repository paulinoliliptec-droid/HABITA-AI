from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local development reads the repo-root .env (git-ignored). On Cloud Run the
# same names are injected as environment variables from Secret Manager.
REPO_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT_ENV,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    backend_cors_origins: str = "http://localhost:3000"

    google_maps_api_key: SecretStr | None = None
    geocoding_timeout_seconds: float = 8.0
    geocoding_default_language: str = "en"
    # Provider snapshots (address, coordinates, components) are refreshed from the
    # stored place ID once older than this. Place IDs themselves may be kept.
    provider_snapshot_ttl_days: int = 30
    # How often a running instance purges expired Google-derived fields (also once at startup).
    # Best effort: a scaled-to-zero service runs it on the next start; for a fixed schedule,
    # call POST /internal/maintenance/run (e.g. from Cloud Scheduler) with MAINTENANCE_TOKEN.
    snapshot_purge_interval_hours: float = 6
    # Enables the maintenance endpoint when set. Unset: the endpoint answers 404.
    maintenance_token: SecretStr | None = None

    resolve_rate_per_minute: float = 30
    resolve_burst: int = 10
    resolve_max_concurrency: int = 4

    # Meta Model API (HR-002 Permit Intelligence). Standard-mode models only: the
    # "-contributor" variants let Meta train on content and are refused.
    meta_api_key: SecretStr | None = None
    meta_api_base_url: str = "https://api.meta.ai/v1"
    meta_text_model: str = "muse-spark-1.3"
    meta_timeout_seconds: float = 90.0
    # Optional reasoning effort ("minimal" … "max"); omitted from requests when unset.
    meta_reasoning_effort: str | None = None

    permit_rate_per_minute: float = 6
    permit_burst: int = 3
    permit_max_concurrency: int = 2

    mongodb_uri: SecretStr | None = None
    mongodb_db_name: str = "habita_ai"
    mongodb_timeout_ms: int = 5000
    # Explicit opt-in for a process-local store when MONGODB_URI is unset (local dev, tests).
    # Never inferred from APP_ENV, so a deployment missing its bindings fails instead.
    allow_ephemeral_storage: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
