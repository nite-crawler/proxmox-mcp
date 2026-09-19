"""Bounded async Proxmox API access with a second, independent write guard."""

import json
import logging
import ssl
from typing import Any, Literal

import anyio
import httpx

from proxmox_mcp.config import Settings

logger = logging.getLogger(__name__)
Parameters = dict[str, str | int | float | bool | None]


class ProxmoxError(Exception):
    """Safe, actionable error that may be shown to an MCP client."""


class ProxmoxClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        verify: bool | ssl.SSLContext = settings.verify_ssl
        if settings.ca_bundle:
            verify = ssl.create_default_context(cafile=str(settings.ca_bundle))
        self._http = httpx.AsyncClient(
            base_url=settings.url + "/",
            headers={
                "Authorization": (
                    f"PVEAPIToken={settings.token_id}={settings.token_secret.get_secret_value()}"
                ),
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            verify=verify,
            timeout=settings.timeout,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        params: Parameters | None = None,
    ) -> Any:
        if method != "GET" and self.settings.read_only:
            raise ProxmoxError("Writes are disabled; set PROXMOX_READ_ONLY=false and restart.")
        # Tool paths are constructed internally; never expose a raw API proxy.
        if not path.startswith("/") or any(x in path for x in ("..", "//", "?", "#", "\\")):
            raise ProxmoxError("Invalid API path.")
        values = {
            k: int(v) if isinstance(v, bool) else v
            for k, v in (params or {}).items()
            if v is not None
        }
        try:
            with anyio.fail_after(self.settings.operation_timeout):
                async with self._http.stream(
                    method,
                    path.lstrip("/"),
                    params=values if method == "GET" else None,
                    data=values if method != "GET" else None,
                ) as response:
                    logger.info("Proxmox %s %s -> %s", method, path, response.status_code)
                    self._check_status(response.status_code)
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ProxmoxError("Proxmox must return an uncompressed response.")
                    size = response.headers.get("content-length")
                    if size is not None:
                        try:
                            declared = int(size)
                        except ValueError:
                            raise ProxmoxError(
                                "Proxmox returned an invalid response length."
                            ) from None
                        if declared < 0 or declared > self.settings.max_response_bytes:
                            raise ProxmoxError(
                                "Proxmox response exceeds the configured size limit."
                            )
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(body) + len(chunk) > self.settings.max_response_bytes:
                            raise ProxmoxError(
                                "Proxmox response exceeds the configured size limit."
                            )
                        body.extend(chunk)
        except (httpx.TimeoutException, TimeoutError):
            raise ProxmoxError(
                "Proxmox request timed out. A submitted operation may still be running; "
                "check tasks before retrying."
            ) from None
        except httpx.RequestError:
            raise ProxmoxError(
                "Cannot reach Proxmox. Check the URL, network, and trusted TLS certificate."
            ) from None
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            raise ProxmoxError("Proxmox returned invalid JSON.") from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise ProxmoxError("Proxmox returned an unexpected response envelope.")
        return payload["data"]

    @staticmethod
    def _check_status(status: int) -> None:
        if status >= 300:
            hints = {
                401: "Authentication failed. Check the API token and expiration.",
                403: "Permission denied. Check both the user's and token's Proxmox ACLs.",
                404: "Resource not found. Refresh inventory and verify the node and ID.",
                429: "Proxmox is rate limiting requests. Retry later.",
            }
            hint = hints.get(status, "Check Proxmox task logs and API parameters.")
            # Never forward an upstream body: it can contain credentials or HTML.
            raise ProxmoxError(f"Proxmox HTTP {status}: {hint}")
