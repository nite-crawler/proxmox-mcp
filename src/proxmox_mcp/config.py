"""Explicit configuration; secrets never appear in validation diagnostics."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from proxmox_mcp.output import DEFAULT_FIELDS


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
    http_token: SecretStr | None = None
    allow_raw_config: bool = False
    allow_task_logs: bool = False
    output_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    operation_timeout: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)
    max_response_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=128 * 1024 * 1024)
    max_request_bytes: int = Field(default=1024 * 1024, ge=1024, le=4 * 1024 * 1024)
    max_concurrent_requests: int = Field(default=8, ge=1, le=64)

    @field_validator("http_token")
    @classmethod
    def validate_http_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]{32,256}", value.get_secret_value()
        ):
            raise ValueError(
                "HTTP token must be 32-256 URL-safe characters; generate a random token"
            )
        return value

    @field_validator("output_fields")
    @classmethod
    def validate_output_fields(
        cls, value: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        if set(value) - DEFAULT_FIELDS.keys():
            raise ValueError("unknown output view; see output policy documentation")
        if any(
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", field)
            for fields in value.values()
            for field in fields
        ):
            raise ValueError("output fields must be exact field names, not wildcards or paths")
        return value

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
        if self.http_token and self.http_token == self.token_secret:
            raise ValueError("HTTP token must differ from the Proxmox API token secret")
        if self.read_only and self.allow_destructive:
            raise ValueError("ALLOW_DESTRUCTIVE requires READ_ONLY=false")
        if self.ca_bundle and not self.verify_ssl:
            raise ValueError("CA_BUNDLE requires VERIFY_SSL=true")
        return self
