from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    This central settings object is intentionally small for US-01/US-02 and can be
    extended safely as new stories add storage, tracing exporters, and alerting.
    """

    openai_api_key: str = ""
    database_url: str = "postgresql+psycopg://user:password@localhost:5432/llm_observability"
    otel_service_name: str = "llm-observability-backend"
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_insecure: bool = True
    prometheus_port: int = 9000
    log_level: str = "INFO"
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = True
    langchain_project: str = "llm-observability-platform"
    default_llm_model: str = "gpt-4o-mini"
    cost_alert_threshold_usd: float = 0.05
    model_pricing_json: str = ""
    latency_warning_threshold_ms: float = 2000.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance for dependency injection."""
    return Settings()
