import datetime
from pathlib import Path
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


settings = Settings()
