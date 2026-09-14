"""Validated configuration loaded from the environment and optional .env file."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )

    name: str = Field(default="Portfolio API", min_length=1)
    environment: Literal["development", "test", "production"] = "development"

    db_host: str = Field(default="127.0.0.1", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr = Field(min_length=1)

    jwt_secret: SecretStr = Field(min_length=64)
    jwt_issuer: str = Field(default="portfolio-api", min_length=1)
    jwt_audience: str = Field(default="portfolio-api", min_length=1)
    access_token_minutes: int = Field(default=15, ge=1, le=60)
