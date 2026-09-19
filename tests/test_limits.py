import asyncio

import anyio
import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.responses import JSONResponse

from proxmox_mcp.client import ProxmoxClient, ProxmoxError
from proxmox_mcp.http import HTTPGuard
from proxmox_mcp.server import create_server


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False
        self.reads = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await anyio.sleep(self.delay)
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1"}])
async def test_streamed_response_size_checked_without_trusting_headers(settings, headers):
    stream = Chunks([b" " * 1024] * 1024)
    api = ProxmoxClient(
        settings.model_copy(update={"max_response_bytes": 1024}),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers=headers, stream=stream)
        ),
    )
    try:
        with pytest.raises(ProxmoxError, match="size limit"):
            await api.request("GET", "/nodes")
        assert stream.closed
        assert stream.reads < len(stream.chunks)
    finally:
        await api.close()


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Length": "2048"},
        {"Content-Length": "invalid"},
        {"Content-Length": "-1"},
        {"Content-Encoding": "gzip"},
    ],
)
async def test_reject_bad_length_and_compression_before_reading(settings, headers):
    stream = Chunks([b"private upstream content"])
    api = ProxmoxClient(
        settings.model_copy(update={"max_response_bytes": 1024}),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers=headers, stream=stream)
        ),
    )
    try:
        with pytest.raises(ProxmoxError):
            await api.request("GET", "/nodes")
        assert stream.reads == 0 and stream.closed
    finally:
        await api.close()


async def test_exact_size_limit_accepted(settings):
    body = b'{"data": []}' + b" " * (1024 - len(b'{"data": []}'))
    stream = Chunks([body])
    api = ProxmoxClient(
        settings.model_copy(update={"max_response_bytes": 1024}),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    try:
        assert await api.request("GET", "/nodes") == []
        assert stream.closed
    finally:
        await api.close()


async def test_total_deadline_bounds_slow_stream_and_does_not_retry(settings):
    stream = Chunks([b" "] * 1000, delay=0.01)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=stream)

    api = ProxmoxClient(
        settings.model_copy(update={"read_only": False, "operation_timeout": 0.04}),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProxmoxError, match="check tasks before retrying"):
            await api.request("POST", "/nodes/pve/qemu/100/status/start")
        assert stream.closed and stream.reads < 1000
        assert len(requests) == 1
    finally:
        await api.close()


async def test_http_admission_limit_shared_and_released():
    entered, release = anyio.Event(), anyio.Event()

    async def downstream(scope, receive, send):
        entered.set()
        await release.wait()
        await JSONResponse({"ok": True})(scope, receive, send)

    app = HTTPGuard(downstream, token="a" * 32, capacity=1, deadline=5)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as http:
        first = asyncio.create_task(http.post("/mcp"))
        try:
            with anyio.fail_after(2):
                await entered.wait()
            blocked = await http.post("/mcp")
            assert blocked.status_code == 429
            assert blocked.headers["retry-after"] == "1"
        finally:
            release.set()
            response = await first
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert (await http.post("/mcp")).status_code == 200


@pytest.mark.parametrize("response_started", [False, True])
async def test_http_deadline_releases_slot_and_does_not_double_send(response_started):
    calls = 0

    async def downstream(scope, receive, send):
        nonlocal calls
        calls += 1
        if calls == 1:
            if response_started:
                await send({"type": "http.response.start", "status": 200, "headers": []})
            await anyio.sleep_forever()
        else:
            await JSONResponse({"ok": True})(scope, receive, send)

    app = HTTPGuard(downstream, token="a" * 32, capacity=1, deadline=0.02)
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "headers": [(b"authorization", b"Bearer " + b"a" * 32)]}
    if response_started:
        with pytest.raises(TimeoutError):
            await app(scope, receive, send)
    else:
        await app(scope, receive, send)
    starts = [message for message in messages if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == (200 if response_started else 504)
    messages.clear()
    await app(scope, receive, send)
    assert messages[0]["status"] == 200


async def test_tool_concurrency_limit_shared_across_mcp_sessions(settings):
    entered, release = anyio.Event(), anyio.Event()

    async def handler(_):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"data": [{"node": "pve"}]})

    settings = settings.model_copy(update={"max_concurrent_requests": 1})
    server = create_server(
        settings, lambda: ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    )
    async with (
        create_connected_server_and_client_session(server) as a,
        create_connected_server_and_client_session(server) as b,
    ):
        first = asyncio.create_task(a.call_tool("list_nodes", {}))
        try:
            with anyio.fail_after(2):
                await entered.wait()
            blocked = await b.call_tool("list_nodes", {})
            assert blocked.isError and "Server busy" in blocked.content[0].text
        finally:
            release.set()
            assert not (await first).isError
        assert not (await b.call_tool("list_nodes", {})).isError


async def test_tool_deadline_releases_slot(settings):
    calls = 0

    async def handler(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            await anyio.sleep_forever()
        return httpx.Response(200, json={"data": []})

    settings = settings.model_copy(update={"max_concurrent_requests": 1, "operation_timeout": 0.02})
    server = create_server(
        settings, lambda: ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    )
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("list_nodes", {})
        assert result.isError and "deadline exceeded" in result.content[0].text
        assert not (await client.call_tool("list_nodes", {})).isError


async def test_http_cancelled_request_releases_capacity():
    entered = anyio.Event()
    count = 0

    async def downstream(scope, receive, send):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await anyio.sleep_forever()
        await JSONResponse({"ok": True})(scope, receive, send)

    app = HTTPGuard(downstream, token="a" * 32, capacity=1, deadline=5)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as http:
        task = asyncio.create_task(http.post("/mcp"))
        with anyio.fail_after(2):
            await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await http.post("/mcp")).status_code == 200
