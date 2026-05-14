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
    mongo_user: str | None = None
    mongo_pass: str | None = None  # noqa: S105
    mongo_db: str = "pad"

    @property
    def mongo_url(self) -> URL:
        if self.mongo_user and self.mongo_pass:
            return URL.build(
                scheme="mongodb",
                host=self.mongo_host,
                port=self.mongo_port,
                user=self.mongo_user,
                password=self.mongo_pass,
                path=f"/{self.mongo_db}",
            )
        return URL.build(
            scheme="mongodb",
            host=self.mongo_host,
            port=self.mongo_port,
            path=f"/{self.mongo_db}",
        )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "pad"
    postgres_pass: str = "pad"  # noqa: S105
    postgres_db: str = "pad"
    postgres_echo: bool = False

    postgres_admin_user: str = "postgres"
    postgres_admin_pass: str = ""  # noqa: S105

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

    @property
    def postgres_admin_url(self) -> URL:
        return URL.build(
            scheme="postgresql+asyncpg",
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_admin_user,
            password=self.postgres_admin_pass,
            path="/postgres",
        )

    minio_host: str = "localhost"
    minio_port: int = 9000
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "pad-bucket"
    minio_use_ssl: bool = False

    @property
    def minio_url(self) -> str:
        scheme = "https" if self.minio_use_ssl else "http"
        return f"{scheme}://{self.minio_host}:{self.minio_port}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PAD_",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
