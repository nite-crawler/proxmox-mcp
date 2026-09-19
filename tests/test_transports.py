import os
import sys
from datetime import timedelta

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.server import create_server


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
        assert len((await session.list_tools()).tools) == 15
        result = await session.call_tool(
            "get_guest_status", {"node": "../bad", "guest_type": "qemu", "vmid": 100}
        )
        assert result.isError


async def test_streamable_http_initialize_discover_and_call(settings):
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
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http,
        streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=http,
        ) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        assert len((await session.list_tools()).tools) == 15
        result = await session.call_tool("list_nodes", {})
        assert not result.isError
        assert result.structuredContent == {"data": [{"node": "pve", "status": "online"}]}
        assert not (await session.call_tool("list_nodes", {})).isError
    assert len(clients) >= 4
    assert all(api._http.is_closed for api in clients)


async def test_http_dns_rebinding_protection(settings):
    server = create_server(settings)
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://evil.example",
        ) as client,
    ):
        response = await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        assert response.status_code == 421
