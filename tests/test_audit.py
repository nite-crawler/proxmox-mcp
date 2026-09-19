"""Write records survive defaults, failures and cancellation without leaking data."""

import asyncio
import json
import logging
import os
import subprocess
import sys

import httpx
import pytest
from pydantic import SecretStr

from proxmox_mcp.client import ProxmoxClient, ProxmoxError


def records(caplog):
    return [
        json.loads(record.getMessage().removeprefix("Proxmox audit "))
        for record in caplog.records
        if record.name == "proxmox_mcp.client" and record.levelno == logging.WARNING
    ]


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
async def test_write_audit_has_attempt_status_and_acceptance(settings, caplog, method):
    api = ProxmoxClient(
        settings.model_copy(update={"read_only": False}),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": "PRIVATE_TASK_BODY"})
        ),
    )
    await api.request(method, "/nodes/pve/qemu/100/status/stop", {"password": "PRIVATE_PARAM"})
    await api.close()
    events = records(caplog)
    assert [e["event"] for e in events] == ["attempt", "response_headers", "api_accepted"]
    assert len({e["request_id"] for e in events}) == 1
    assert events[0]["method"] == method
    assert events[0]["path"] == "/nodes/pve/qemu/100/status/stop"
    assert events[1]["status"] == 200
    assert events[2]["duration_ms"] >= 0
    assert "PRIVATE" not in caplog.text
    assert settings.token_secret.get_secret_value() not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError, httpx.ReadTimeout, httpx.InvalidURL, RuntimeError, asyncio.CancelledError],
)
async def test_failure_and_cancellation_audited_without_details(settings, caplog, failure):
    def handler(_):
        raise failure("PRIVATE_ERROR")

    api = ProxmoxClient(
        settings.model_copy(update={"read_only": False}), transport=httpx.MockTransport(handler)
    )
    expected = ProxmoxError if issubclass(failure, httpx.RequestError) else failure
    with pytest.raises(expected):
        await api.request("POST", "/nodes/pve/qemu/100/status/stop")
    await api.close()
    assert [e["event"] for e in records(caplog)] == ["attempt", "outcome_unknown"]
    assert "PRIVATE_ERROR" not in caplog.text


@pytest.mark.parametrize("status", [403, 500])
async def test_http_failure_status_retained_without_body(settings, caplog, status):
    api = ProxmoxClient(
        settings.model_copy(update={"read_only": False}),
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="PRIVATE_BODY")),
    )
    with pytest.raises(ProxmoxError):
        await api.request("DELETE", "/nodes/pve/qemu/100/snapshot/before")
    await api.close()
    events = records(caplog)
    assert [e["event"] for e in events] == ["attempt", "response_headers", "outcome_unknown"]
    assert events[1]["status"] == status
    assert "PRIVATE_BODY" not in caplog.text


async def test_audit_escapes_path_and_redacts_credentials(settings, caplog):
    api = ProxmoxClient(
        settings.model_copy(
            update={"read_only": False, "http_token": SecretStr("HTTP_SYNTHETIC_SECRET")}
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": None})),
    )
    with pytest.raises(httpx.InvalidURL):
        await api.request(
            "POST", "/" + settings.token_secret.get_secret_value() + "\nHTTP_SYNTHETIC_SECRET"
        )
    await api.close()
    assert records(caplog)[0]["path"] == "/[REDACTED]\n[REDACTED]"
    assert settings.token_secret.get_secret_value() not in caplog.text
    assert "HTTP_SYNTHETIC_SECRET" not in caplog.text
    assert "\\n" in caplog.records[0].getMessage()


@pytest.mark.parametrize("level", [None, "INFO", "WARNING"])
def test_real_cli_audits_destructive_operations_on_stderr(level):
    script = """
import asyncio
import logging
from unittest.mock import patch
import httpx
from proxmox_mcp.cli import main
from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import Settings
from proxmox_mcp.http import SecureMCP

# Simulate an embedding host that already installed a restrictive handler.
logging.basicConfig(level=logging.CRITICAL)
settings = Settings(url="https://pve.example.test", token_id="mcp@pve!test",
                    token_secret="SYNTHETIC_ONLY_SECRET", read_only=False, allow_destructive=True)
async def requests():
    api = ProxmoxClient(settings, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": None})))
    await api.request("POST", "/nodes/pve/qemu/100/status/stop")
    await api.request("DELETE", "/nodes/pve/qemu/100/snapshot/before")
    await api.close()
def run(self, **kwargs):
    asyncio.run(requests())
with patch("proxmox_mcp.cli.Settings", return_value=settings), patch.object(SecureMCP, "run", run):
    main(CLI_ARGS)
""".replace("CLI_ARGS", repr(["--log-level", level] if level else []))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROXMOX_")}
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    events = [
        json.loads(line.split("Proxmox audit ", 1)[1])
        for line in result.stderr.splitlines()
        if "Proxmox audit " in line
    ]
    assert len(events) == 6
    assert len({e["request_id"] for e in events}) == 2
    assert sum(e["event"] == "api_accepted" for e in events) == 2
    assert "SYNTHETIC_ONLY" not in result.stderr


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("read_only", [True, False])
async def test_refused_writes_audited_without_network_or_unvalidated_input(
    settings, caplog, method, read_only
):
    def unexpected(_):
        pytest.fail("Blocked request reached Proxmox")

    api = ProxmoxClient(
        settings.model_copy(update={"read_only": read_only}),
        transport=httpx.MockTransport(unexpected),
    )
    path = "/nodes/pve/qemu/100/status/stop" if read_only else "/../PRIVATE\nINJECTED"
    with pytest.raises(ProxmoxError):
        await api.request(method, path, {"password": "PRIVATE_PARAM"})
    await api.close()
    events = records(caplog)
    assert len(events) == 1
    assert events[0]["event"] == "blocked"
    assert events[0]["method"] == method
    assert events[0]["reason"] == ("read_only" if read_only else "invalid_path")
    assert len(events[0]["request_id"]) == 32
    assert "PRIVATE" not in caplog.text
    assert "INJECTED" not in caplog.text
    assert "path" not in events[0]
