"""
Application configuration — loads from .env file.
Import `settings` anywhere in the project instead of reading os.environ directly.
"""

from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str

    # App
    app_env:  str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # CORS
    cors_origins: str = "*"

    # OpenAPI
    openapi_server_url: str = ""
    openapi_server_description: str = "Current server"

    # Observability (Azure Application Insights)
    applicationinsights_connection_string: str = ""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def openapi_servers(self) -> List[dict]:
        if self.openapi_server_url.strip():
            return [{
                "url": self.openapi_server_url.strip(),
                "description": self.openapi_server_description,
            }]

        host = "localhost" if self.app_host in {"0.0.0.0", "127.0.0.1"} else self.app_host
        scheme = "https" if self.app_env.lower() == "production" else "http"
        return [{
            "url": f"{scheme}://{host}:{self.app_port}",
            "description": self.openapi_server_description,
        }]


settings = Settings()
