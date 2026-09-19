from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest

from proxmox_mcp.client import ProxmoxClient, ProxmoxError


async def test_auth_and_query_encoding(settings):
    def handler(request):
        assert request.url == "https://pve.example.test:8006/api2/json/cluster/resources?type=vm"
        assert (
            request.headers["Authorization"]
            == "PVEAPIToken=mcp@pve!tests=test-secret-not-a-real-token"
        )
        return httpx.Response(200, json={"data": [{"vmid": 100}]})

    client = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    assert await client.request("GET", "/cluster/resources", {"type": "vm", "omit": None}) == [
        {"vmid": 100}
    ]
    await client.close()


async def test_write_form_and_no_retries(settings):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert parse_qs(request.content.decode()) == {"full": ["1"], "newid": ["101"]}
        return httpx.Response(200, json={"data": "UPID:node:task:"})

    client = ProxmoxClient(
        settings.model_copy(update={"read_only": False}), transport=httpx.MockTransport(handler)
    )
    assert await client.request("POST", "/clone", {"full": True, "newid": 101}) == "UPID:node:task:"
    assert len(calls) == 1
    await client.close()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
async def test_independent_read_only_guard(settings, method):
    def unexpected(_):
        pytest.fail("A blocked write reached the network")

    client = ProxmoxClient(settings, transport=httpx.MockTransport(unexpected))
    with pytest.raises(ProxmoxError, match="Writes are disabled"):
        await client.request(method, "/nodes/pve/qemu/100/status/start")
    await client.close()


@pytest.mark.parametrize(
    "path", ["https://evil.test", "//evil.test", "/../access", "/a?b", "/a#b", "/a\\b"]
)
async def test_reject_unsafe_path(settings, path):
    client = ProxmoxClient(settings)
    with pytest.raises(ProxmoxError, match="Invalid API path"):
        await client.request("GET", path)
    await client.close()


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500, 503])
async def test_http_errors_do_not_leak_or_follow_redirects(settings, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="SENSITIVE", headers={"Location": "https://evil.test"})

    client = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(ProxmoxError, match=f"HTTP {status}") as exc:
        await client.request("GET", "/nodes")
    assert "SENSITIVE" not in str(exc.value)
    assert len(calls) == 1
    await client.close()


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_errors_sanitized(settings, error):
    def handler(_):
        raise error("SENSITIVE internal details")

    client = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(ProxmoxError) as exc:
        await client.request("GET", "/nodes")
    assert "SENSITIVE" not in str(exc.value)
    if error is httpx.ReadTimeout:
        assert "check tasks before retrying" in str(exc.value)
    await client.close()


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"unexpected":true}'])
async def test_invalid_envelope(settings, body):
    client = ProxmoxClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    with pytest.raises(ProxmoxError):
        await client.request("GET", "/nodes")
    await client.close()


async def test_null_data_is_valid(settings):
    client = ProxmoxClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": None}))
    )
    assert await client.request("GET", "/nodes") is None
    await client.close()


async def test_custom_ca(settings):
    import ssl

    context = ssl.create_default_context()
    with patch("proxmox_mcp.client.ssl.create_default_context", return_value=context) as create:
        client = ProxmoxClient(settings.model_copy(update={"ca_bundle": "/tmp/ca.pem"}))
        create.assert_called_once_with(cafile="/tmp/ca.pem")
    await client.close()
