import os
import sys
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.server import create_server

HTTP_TOKEN = "test-http-token-abcdefghijklmnopqrstuvwxyz123456"


@pytest.fixture
def http_settings(settings):
    return settings.model_copy(update={"http_token": SecretStr(HTTP_TOKEN)})


async def test_real_stdio_subprocess():
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROXMOX_")}
    env.update(
        PROXMOX_URL="https://pve.example.test:8006",
        PROXMOX_TOKEN_ID="mcp@pve!test",
        PROXMOX_TOKEN_SECRET="test-only",
    )
    params = StdioServerParameters(command=sys.executable, args=["-m", "proxmox_mcp"], env=env)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session,
    ):
        init = await session.initialize()
        assert init.serverInfo.name == "proxmox-ve"
        assert "UPID" in init.instructions
        assert len((await session.list_tools()).tools) == 14
        result = await session.call_tool(
            "get_guest_status", {"node": "../bad", "guest_type": "qemu", "vmid": 100}
        )
        assert result.isError


async def test_streamable_http_initialize_discover_and_call(http_settings):
    settings = http_settings
    clients = []

    def api_factory():
        api = ProxmoxClient(
            settings,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"data": [{"node": "pve", "status": "online"}]})
            ),
        )
        clients.append(api)
        return api

    server = create_server(settings, api_factory)
    app = server.streamable_http_app()

    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {HTTP_TOKEN}"},
        ) as http,
        streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=http,
        ) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        assert len((await session.list_tools()).tools) == 14
        result = await session.call_tool("list_nodes", {})
        assert not result.isError
        assert result.structuredContent == {"data": [{"node": "pve", "status": "online"}]}
        assert not (await session.call_tool("list_nodes", {})).isError
    assert len(clients) >= 4
    assert all(api._http.is_closed for api in clients)


async def test_http_dns_rebinding_protection(http_settings):
    server = create_server(http_settings)
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://evil.example",
            headers={"Authorization": f"Bearer {HTTP_TOKEN}"},
        ) as client,
    ):
        response = await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        assert response.status_code == 421


def test_http_fails_closed_without_token(settings):
    with pytest.raises(ValueError, match="PROXMOX_HTTP_TOKEN"):
        create_server(settings).streamable_http_app()


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE", "OPTIONS"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Basic {HTTP_TOKEN}"},
        {"X-API-Key": HTTP_TOKEN},
        [("Authorization", f"Bearer {HTTP_TOKEN}"), ("Authorization", f"Bearer {HTTP_TOKEN}")],
    ],
)
async def test_http_requires_one_valid_bearer_for_every_method(http_settings, method, headers):
    def unexpected():
        pytest.fail("Unauthenticated request entered the MCP lifespan")

    server = create_server(http_settings, unexpected)
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as client,
    ):
        response = await client.request(method, "/mcp?token=" + HTTP_TOKEN, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["cache-control"] == "no-store"
        assert HTTP_TOKEN not in response.text


async def test_http_rejects_untrusted_origin_even_when_authenticated(http_settings):
    server = create_server(http_settings)
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client,
    ):
        response = await client.post(
            "http://127.0.0.1:8000/mcp",
            headers={
                "Authorization": f"Bearer {HTTP_TOKEN}",
                "Origin": "https://evil.example",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 403


async def test_http_request_size_limit(http_settings):
    server = create_server(http_settings.model_copy(update={"max_request_bytes": 1024}))
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers={
                "Authorization": f"Bearer {HTTP_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        ) as client,
    ):
        response = await client.post("http://127.0.0.1:8000/mcp", content=b" " * 2048)
        assert response.status_code == 413
