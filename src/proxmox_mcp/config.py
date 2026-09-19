"""Explicit configuration; secrets never appear in validation diagnostics."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROXMOX_", extra="ignore", hide_input_in_errors=True, frozen=True
    )

    url: str
    token_id: str
    token_secret: SecretStr
    verify_ssl: bool = True
    ca_bundle: Path | None = None
    timeout: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)
    read_only: bool = True
    allow_destructive: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/", "/api2/json", "/api2/json/")
        ):
            raise ValueError("use an HTTPS origin, optionally ending in /api2/json")
        # Accessing port also rejects malformed and out-of-range ports.
        _ = url.port
        return f"https://{url.netloc}/api2/json"

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+", value):
            raise ValueError("expected USER@REALM!TOKENID")
        return value

    @field_validator("token_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or not raw.isascii() or not raw.isprintable() or any(c.isspace() for c in raw):
            raise ValueError("token secret must be nonempty printable ASCII without whitespace")
        return value

    @model_validator(mode="after")
    def validate_options(self) -> "Settings":
        if self.read_only and self.allow_destructive:
            raise ValueError("ALLOW_DESTRUCTIVE requires READ_ONLY=false")
        if self.ca_bundle and not self.verify_ssl:
            raise ValueError("CA_BUNDLE requires VERIFY_SSL=true")
        return self
