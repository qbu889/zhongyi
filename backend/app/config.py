from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://linziwang@localhost:5432/zhongyi_test"
    )
    repo_dir: Path = Path(__file__).resolve().parents[2]
    embed_model: str = "BAAI/bge-m3"
    refusal_threshold: float = 0.30   # D2：先用占位值，M5 由问答日志回归
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""

    @property
    def distilled_dir(self) -> Path:
        return self.repo_dir / "distilled"


settings = Settings()
