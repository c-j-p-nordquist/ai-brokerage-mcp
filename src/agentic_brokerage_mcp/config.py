from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTIC_BROKERAGE_MCP_",
        env_file=".env",
        extra="ignore",
    )

    broker_mode: Literal["demo", "live"] = "demo"
    db_path: str = "~/.agentic-brokerage-mcp/state.db"
    base_currency: str = "USD"
    ibkr_base_url: str = "https://localhost:5001/v1/api"
    ibkr_account_id: str = ""
    ibkr_verify_ssl: bool = False
    enable_live_trading: bool = False
    log_level: str = "INFO"

    @field_validator("base_currency")
    @classmethod
    def normalize_base_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("base_currency must be a 3-letter ISO currency code")
        return normalized


settings = Settings()
