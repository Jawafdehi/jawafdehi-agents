from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    jawafdehi_api_base_url: str = Field(
        default="https://portal.jawafdehi.org",
        alias="JAWAFDEHI_API_BASE_URL",
    )
    jawafdehi_api_token: str = Field(alias="JAWAFDEHI_API_TOKEN")
    nes_api_base_url: str = Field(
        default="https://nes.jawafdehi.org",
        alias="NES_API_BASE_URL",
    )
    llm_model: str = Field(default="gpt-5.4", alias="LLM_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
