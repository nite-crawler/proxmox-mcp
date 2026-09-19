"""Unexpected failures never expose raw exception details to MCP clients."""

import asyncio
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import mcp_session

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.server import create_server


@pytest.mark.parametrize("error", [httpx.InvalidURL, ssl.SSLError, RuntimeError])
async def test_unexpected_tool_errors_are_sanitized_and_release_capacity(settings, caplog, error):
    settings = settings.model_copy(update={"max_concurrent_requests": 1})
    api = ProxmoxClient(settings)
    api.request = AsyncMock(side_effect=[error("PRIVATE_DETAIL"), {"version": "9"}])
    async with mcp_session(create_server(settings, lambda: api)) as session:
        result = await session.call_tool("get_version", {})
        assert result.is_error
        assert "Unexpected server error" in result.content[0].text
        assert "PRIVATE_DETAIL" not in result.content[0].text
        assert not (await session.call_tool("get_version", {})).is_error
    assert "PRIVATE_DETAIL" not in caplog.text
    assert api._http.is_closed


async def test_unexpected_output_processing_error_is_sanitized(settings, caplog):
    api = ProxmoxClient(settings)
    # An invalid injected Python object exercises processing, not just networking.
    api.request = AsyncMock(return_value={"cpuinfo": {None: "PRIVATE_DETAIL"}})
    async with mcp_session(create_server(settings, lambda: api)) as session:
        result = await session.call_tool("get_node_status", {"node": "pve"})
        assert result.is_error
        assert "Unexpected server error" in result.content[0].text
        assert "PRIVATE_DETAIL" not in result.content[0].text
    assert "PRIVATE_DETAIL" not in caplog.text


@pytest.mark.parametrize("error", [ssl.SSLError, httpx.InvalidURL, RuntimeError])
async def test_client_initialization_errors_are_sanitized(settings, caplog, error):
    def factory():
        raise error("PRIVATE_DETAIL")

    server = create_server(settings, factory)
    with pytest.raises(RuntimeError, match="Cannot initialize Proxmox client") as exc:
        async with server.settings.lifespan(server):
            pytest.fail("Failed initialization entered lifespan")
    assert "PRIVATE_DETAIL" not in str(exc.value)
    assert exc.value.__suppress_context__
    assert "PRIVATE_DETAIL" not in caplog.text


async def test_cleanup_errors_are_sanitized(settings, caplog):
    api = ProxmoxClient(settings)
    await api.close()
    api.close = AsyncMock(side_effect=RuntimeError("PRIVATE_DETAIL"))
    server = create_server(settings, lambda: api)
    with pytest.raises(RuntimeError, match="client cleanup failed") as exc:
        async with server.settings.lifespan(server):
            pass
    assert "PRIVATE_DETAIL" not in str(exc.value)
    assert exc.value.__suppress_context__
    assert "PRIVATE_DETAIL" not in caplog.text


async def test_tool_cancellation_propagates_and_releases_capacity(settings):
    settings = settings.model_copy(update={"max_concurrent_requests": 1})
    api = ProxmoxClient(settings)
    api.request = AsyncMock(side_effect=[asyncio.CancelledError(), {"version": "9"}])
    server = create_server(settings, lambda: api)
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=api))
    async with server.settings.lifespan(server):
        with pytest.raises(asyncio.CancelledError):
            await server.call_tool("get_version", {}, context=context)
        assert await server.call_tool("get_version", {}, context=context)


@pytest.mark.parametrize("stage", ["initialize", "cleanup"])
async def test_lifecycle_cancellation_is_not_converted_to_an_error(settings, stage):
    api = ProxmoxClient(settings)
    await api.close()

    def factory():
        if stage == "initialize":
            raise asyncio.CancelledError()
        return api

    api.close = AsyncMock(side_effect=asyncio.CancelledError())
    server = create_server(settings, factory)
    with pytest.raises(asyncio.CancelledError):
        async with server.settings.lifespan(server):
            assert stage == "cleanup"
