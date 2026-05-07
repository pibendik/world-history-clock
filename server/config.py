import datetime
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YEARCLOCK_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    port: int = 8421
    db_path: Path = Path.home() / ".clockapp" / "yearclock.db"
    sparql_endpoint: str = "https://query.wikidata.org/sparql"
    cache_ttl_days: int = 7
    cors_origins: list[str] = ["*"]
    current_year: int = datetime.date.today().year
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    llm_scoring_enabled: bool = Field(default=False, validation_alias="YEARCLOCK_LLM_SCORING")


settings = Settings()
