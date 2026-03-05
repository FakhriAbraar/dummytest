
from __future__ import annotations

import enum
from pathlib import Path
from tempfile import gettempdir

from pydantic_settings import BaseSettings, SettingsConfigDict
from yarl import URL

TEMP_DIR = Path(gettempdir())


class LogLevel(enum.StrEnum):

    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    workers_count: int = 1
    reload: bool = False

    environment: str = "dev"

    log_level: LogLevel = LogLevel.INFO

    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_user: str = "pad"
    mongo_pass: str = "pad"  # noqa: S105
    mongo_db: str = "pad"

    @property
    def mongo_url(self) -> URL:
        return URL.build(
            scheme="mongodb",
            host=self.mongo_host,
            port=self.mongo_port,
            user=self.mongo_user,
            password=self.mongo_pass,
            path=f"/{self.mongo_db}",
        )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "pad"
    postgres_pass: str = "pad"  # noqa: S105
    postgres_db: str = "pad"
    postgres_echo: bool = False

    @property
    def postgres_url(self) -> URL:
        return URL.build(
            scheme="postgresql+asyncpg",
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_pass,
            path=f"/{self.postgres_db}",
        )

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_api_key: str | None = None
    qdrant_https: bool = False

    @property
    def qdrant_url(self) -> str:
        scheme = "https" if self.qdrant_https else "http"
        return f"{scheme}://{self.qdrant_host}:{self.qdrant_port}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PAD_",
        env_file_encoding="utf-8",
    )


settings = Settings()
