"""Local HTTP authentication and admission control, before MCP processing."""

import secrets
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from proxmox_mcp.config import Settings


class HTTPGuard:
    def __init__(self, app: ASGIApp, *, token: str, capacity: int, deadline: float) -> None:
        self.app = app
        self._token = token.encode("ascii")
        self._limiter = anyio.CapacityLimiter(capacity)
        self._deadline = deadline

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
        scheme, _, value = headers[0].partition(b" ") if len(headers) == 1 else (b"", b"", b"")
        if scheme.lower() != b"bearer" or not secrets.compare_digest(value, self._token):
            await JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        try:
            self._limiter.acquire_nowait()
        except anyio.WouldBlock:
            await JSONResponse(
                {"error": "Server busy; retry later"},
                status_code=429,
                headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                    ],
                }
            await send(message)

        try:
            with anyio.fail_after(self._deadline):
                await self.app(scope, receive, guarded_send)
        except TimeoutError:
            if started:
                # The status/headers are already on the wire; let the HTTP
                # server terminate the incomplete response instead of faking success.
                raise
            await JSONResponse(
                {"error": "Request deadline exceeded; check tasks before retrying writes"},
                status_code=504,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
        finally:
            self._limiter.release()


class SecureMCP(MCPServer):
    def __init__(self, security: Settings, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._security = security

    def streamable_http_app(self, **kwargs: Any) -> Starlette:
        if self._security.http_token is None:
            raise ValueError("Streamable HTTP requires PROXMOX_HTTP_TOKEN")
        # SDK run() forwards transport defaults here. Operator security settings
        # remain authoritative, for both CLI and embedded ASGI applications.
        kwargs.update(
            host="127.0.0.1",
            stateless_http=True,
            json_response=True,
            max_request_body_size=self._security.max_request_bytes,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*"],
                allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
            ),
        )
        app = super().streamable_http_app(**kwargs)
        app.add_middleware(
            HTTPGuard,
            token=self._security.http_token.get_secret_value(),
            capacity=self._security.max_concurrent_requests,
            deadline=self._security.operation_timeout,
        )
        return app
