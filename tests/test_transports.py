import os
import sys

import httpx
import httpx2
import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings
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
        PROXMOX_TOKEN_SECRET="test-only-secret",
    )
    params = StdioServerParameters(command=sys.executable, args=["-m", "proxmox_mcp"], env=env)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, read_timeout_seconds=15) as session,
    ):
        init = await session.initialize()
        assert init.server_info.name == "proxmox-ve"
        assert "UPID" in init.instructions
        assert len((await session.list_tools()).tools) == 14
        result = await session.call_tool(
            "get_guest_status", {"node": "../bad", "guest_type": "qemu", "vmid": 100}
        )
        assert result.is_error


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_streamable_http_initialize_discover_and_call(http_settings, mode):
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
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {HTTP_TOKEN}"},
        ) as http,
        Client(
            streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http),
            mode=mode,
        ) as session,
    ):
        assert session.protocol_version == ("2026-07-28" if mode == "auto" else "2025-11-25")
        assert len((await session.list_tools()).tools) == 14
        result = await session.call_tool("list_nodes", {})
        assert not result.is_error
        assert result.structured_content == {"data": [{"node": "pve", "status": "online"}]}
        assert not (await session.call_tool("list_nodes", {})).is_error
        forged = await session.call_tool(
            "list_nodes", {"ctx": {"request_context": {"lifespan_context": "attacker"}}}
        )
        assert not forged.is_error
        assert forged.structured_content == result.structured_content
    assert len(clients) == 1
    assert all(api._http.is_closed for api in clients)


async def test_modern_stdio_discovery_and_tool_schema():
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROXMOX_")}
    env.update(
        PROXMOX_URL="https://pve.example.test:8006",
        PROXMOX_TOKEN_ID="mcp@pve!test",
        PROXMOX_TOKEN_SECRET="test-only-secret",
    )
    params = StdioServerParameters(command=sys.executable, args=["-m", "proxmox_mcp"], env=env)
    async with Client(params, mode="auto", read_timeout_seconds=15) as client:
        assert client.protocol_version == "2026-07-28"
        listing = await client.list_tools()
        assert len(listing.tools) == 14
        assert all("ctx" not in tool.input_schema.get("properties", {}) for tool in listing.tools)
        result = await client.call_tool(
            "get_guest_status", {"node": "../bad", "guest_type": "qemu", "vmid": 100}
        )
        assert result.is_error


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
    def unexpected(_):
        pytest.fail("Unauthenticated request reached Proxmox")

    server = create_server(
        http_settings,
        lambda: ProxmoxClient(http_settings, transport=httpx.MockTransport(unexpected)),
    )
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


async def test_forwarded_sdk_options_cannot_weaken_http_controls(http_settings):
    server = create_server(http_settings.model_copy(update={"max_request_bytes": 1024}))
    app = server.streamable_http_app(
        host="0.0.0.0",
        stateless_http=False,
        json_response=False,
        max_request_body_size=1024 * 1024,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client,
    ):
        url = "http://127.0.0.1:8765/mcp"
        assert (await client.post(url)).status_code == 401
        headers = {
            "Authorization": f"Bearer {HTTP_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        assert (
            await client.post(url, headers={**headers, "Host": "evil.example"})
        ).status_code == 421
        assert (
            await client.post(url, headers={**headers, "Origin": "https://evil.example"})
        ).status_code == 403
        response = await client.post(
            url, headers={**headers, "Content-Type": "application/json"}, content=b" " * 2048
        )
        assert response.status_code == 413
