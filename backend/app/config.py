from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://linziwang@localhost:5432/zhongyi_test"
    )
    repo_dir: Path = Path(__file__).resolve().parents[2]
    embed_model: str = "BAAI/bge-m3"

    @property
    def distilled_dir(self) -> Path:
        return self.repo_dir / "distilled"


settings = Settings()
