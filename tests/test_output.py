import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import Settings
from proxmox_mcp.output import filter_output, redact
from proxmox_mcp.server import create_server

GUEST = {"node": "pve", "guest_type": "qemu", "vmid": 100}


@pytest.mark.parametrize("raw,logs", [(False, False), (True, False), (False, True), (True, True)])
async def test_sensitive_tools_have_independent_operator_gates(settings, raw, logs):
    settings = settings.model_copy(update={"allow_raw_config": raw, "allow_task_logs": logs})

    def unexpected(_):
        pytest.fail("Disabled tool reached Proxmox")

    api = ProxmoxClient(settings, transport=httpx.MockTransport(unexpected))
    async with create_connected_server_and_client_session(
        create_server(settings, lambda: api)
    ) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert ("get_guest_config_raw" in names) == raw
        assert ("get_task_log" in names) == logs
        if not raw:
            assert (await client.call_tool("get_guest_config_raw", GUEST)).isError
        if not logs:
            assert (
                await client.call_tool("get_task_log", {"node": "pve", "upid": "UPID:pve:task:"})
            ).isError


@pytest.mark.parametrize(
    "tool,options,expected",
    [
        ("get_guest_config", {}, {"name": "guest", "cores": 4}),
        ("get_guest_config", {"output_fields": {"guest_config": ("cores",)}}, {"cores": 4}),
        ("get_guest_config", {"output_fields": {"guest_config": ()}}, {}),
        (
            "get_guest_config",
            {"output_fields": {"guest_config": ("description", "cipassword")}},
            {"description": "operator opted in", "cipassword": "[REDACTED]"},
        ),
        (
            "get_guest_config_raw",
            {"allow_raw_config": True},
            {
                "name": "guest",
                "cores": 4,
                "description": "operator opted in",
                "cipassword": "[REDACTED]",
                "args": "[REDACTED]",
                "sshkeys": "[REDACTED]",
                "extra": {"api_token": "[REDACTED]"},
            },
        ),
    ],
)
async def test_config_minimization_and_raw_redaction(settings, tool, options, expected):
    settings = settings.model_copy(update=options)
    data = {
        "name": "guest",
        "cores": 4,
        "description": "operator opted in",
        "cipassword": "SECRET",
        "args": "private value",
        "sshkeys": "public key access information",
        "extra": {"api_token": "SECRET"},
    }
    api = ProxmoxClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": data}))
    )
    async with create_connected_server_and_client_session(
        create_server(settings, lambda: api)
    ) as client:
        result = await client.call_tool(tool, GUEST)
        assert not result.isError
        assert result.structuredContent == {"data": expected}
        assert "SECRET" not in result.content[0].text


@pytest.mark.parametrize(
    "tool,args,data,expected",
    [
        (
            "list_snapshots",
            GUEST,
            [{"name": "before", "description": "PRIVATE"}],
            [{"name": "before"}],
        ),
        (
            "list_storage_content",
            {"node": "pve", "storage": "local"},
            [{"volid": "local:backup/x", "notes": "PRIVATE"}],
            [{"volid": "local:backup/x"}],
        ),
        (
            "list_resources",
            {},
            [{"vmid": 100, "description": "PRIVATE", "tags": "PRIVATE"}],
            [{"vmid": 100}],
        ),
    ],
)
async def test_freeform_fields_omitted_across_read_tools(settings, tool, args, data, expected):
    api = ProxmoxClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": data}))
    )
    async with create_connected_server_and_client_session(
        create_server(settings, lambda: api)
    ) as client:
        result = await client.call_tool(tool, args)
        assert result.structuredContent == {"data": expected}
        assert "PRIVATE" not in result.content[0].text


def test_nested_secrets_and_literal_credentials_redacted():
    assert redact(
        {"nested": [{"private_key": "hidden", "text": "contains abc-secret"}]}, ("abc-secret",)
    ) == {"nested": [{"private_key": "[REDACTED]", "text": "contains [REDACTED]"}]}
    assert filter_output("unexpected scalar", ("name",), ()) is None
    assert redact({}, (), depth=33) == "[OMITTED: nesting limit]"


@pytest.mark.parametrize("key", ["args", "ARGS", "sshkeys", "SSHKeys"])
def test_known_sensitive_fields_cannot_be_allowlisted_around_redaction(key):
    assert filter_output({key: "PRIVATE"}, (key,), ()) == {key: "[REDACTED]"}
    assert redact({"nested": [{key: "PRIVATE"}]}, ()) == {"nested": [{key: "[REDACTED]"}]}


@pytest.mark.parametrize(
    "data",
    [
        {"status": "stopped", "exitstatus": "ERROR"},
        {"status": "stopped", "exitstatus": "OK"},
        {"status": "running"},
        {"status": "stopped"},
        {"exitstatus": "OK"},
        {},
    ],
)
async def test_required_task_fields_preserved_without_inventing_upstream_values(settings, data):
    settings = Settings.model_validate(
        {**settings.model_dump(), "output_fields": {"task_status": ["status", "exitstatus"]}}
    )
    api = ProxmoxClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": {**data, "user": "PRIVATE"}})
        ),
    )
    async with create_connected_server_and_client_session(
        create_server(settings, lambda: api)
    ) as session:
        init = await session.initialize()
        assert "success is unverified" in init.instructions
        result = await session.call_tool(
            "get_task_status", {"node": "pve", "upid": "UPID:pve:task:"}
        )
        assert not result.isError
        assert result.structuredContent == {"data": data}
        assert "PRIVATE" not in result.content[0].text
