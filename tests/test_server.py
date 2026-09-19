from urllib.parse import parse_qs

import httpx
import pytest
from conftest import mcp_session

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.server import create_server

GUEST = {"node": "pve", "guest_type": "qemu", "vmid": 100}
TASK = "UPID:pve:00001234:00005678:12345678:qmstart:100:mcp@pve!tests:"
READ_TOOLS = {
    "get_version",
    "get_cluster_status",
    "list_resources",
    "list_nodes",
    "get_node_status",
    "list_storage",
    "list_storage_content",
    "list_guests",
    "get_guest_status",
    "get_guest_config",
    "list_snapshots",
    "list_tasks",
    "get_task_status",
    "get_next_vmid",
}
WRITE_TOOLS = {
    "start_guest",
    "shutdown_guest",
    "reboot_guest",
    "clone_guest",
    "create_snapshot",
    "backup_guest",
    "migrate_guest",
}
DANGEROUS_TOOLS = {"stop_guest", "delete_snapshot", "rollback_snapshot"}


@pytest.mark.parametrize(
    "read_only,destructive,expected",
    [
        (True, False, READ_TOOLS),
        (False, False, READ_TOOLS | WRITE_TOOLS),
        (False, True, READ_TOOLS | WRITE_TOOLS | DANGEROUS_TOOLS),
    ],
)
async def test_protocol_discovery_and_gates(settings, read_only, destructive, expected):
    settings = settings.model_copy(
        update={"read_only": read_only, "allow_destructive": destructive}
    )
    api = ProxmoxClient(settings)
    async with mcp_session(create_server(settings, lambda: api)) as session:
        tools = (await session.list_tools()).tools
        assert {tool.name for tool in tools} == expected
        for tool in tools:
            assert tool.annotations.read_only_hint == (tool.name in READ_TOOLS)
            assert tool.input_schema["type"] == "object"
            assert "ctx" not in tool.input_schema.get("properties", {})
            assert tool.description
        if read_only:
            result = await session.call_tool("start_guest", GUEST)
            assert result.is_error
    assert api._http.is_closed


@pytest.mark.parametrize(
    "tool,args,path,query",
    [
        ("get_version", {}, "/version", {}),
        ("get_cluster_status", {}, "/cluster/status", {}),
        ("list_resources", {"resource_type": "vm"}, "/cluster/resources", {"type": ["vm"]}),
        ("list_nodes", {}, "/nodes", {}),
        ("get_node_status", {"node": "pve"}, "/nodes/pve/status", {}),
        ("list_storage", {"node": "pve"}, "/nodes/pve/storage", {}),
        (
            "list_storage_content",
            {"node": "pve", "storage": "local", "content": "backup"},
            "/nodes/pve/storage/local/content",
            {"content": ["backup"]},
        ),
        ("list_guests", {"node": "pve", "guest_type": "lxc"}, "/nodes/pve/lxc", {}),
        ("get_guest_status", GUEST, "/nodes/pve/qemu/100/status/current", {}),
        ("get_guest_config", GUEST, "/nodes/pve/qemu/100/config", {}),
        ("list_snapshots", GUEST, "/nodes/pve/qemu/100/snapshot", {}),
        (
            "list_tasks",
            {"node": "pve", "limit": 5, "start": 10},
            "/nodes/pve/tasks",
            {"limit": ["5"], "start": ["10"]},
        ),
        ("get_task_status", {"node": "pve", "upid": TASK}, f"/nodes/pve/tasks/{TASK}/status", {}),
        (
            "get_task_log",
            {"node": "pve", "upid": TASK},
            f"/nodes/pve/tasks/{TASK}/log",
            {"limit": ["100"], "start": ["0"]},
        ),
        ("get_next_vmid", {}, "/cluster/nextid", {}),
    ],
)
async def test_read_tools_over_protocol(settings, tool, args, path, query):
    if tool == "get_task_log":
        settings = settings.model_copy(update={"allow_task_logs": True})

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api2/json" + path
        assert parse_qs(request.url.query.decode()) == query
        return httpx.Response(200, json={"data": {"test": "result"}})

    api = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    async with mcp_session(create_server(settings, lambda: api)) as session:
        result = await session.call_tool(tool, args)
        assert not result.is_error
        expected = {"test": "result"} if tool in {"get_next_vmid", "get_task_log"} else {}
        assert result.structured_content == {"data": expected}


@pytest.mark.parametrize("guest_type", ["qemu", "lxc"])
@pytest.mark.parametrize(
    "tool,extra,suffix,method,form",
    [
        ("start_guest", {}, "/status/start", "POST", {}),
        ("shutdown_guest", {"timeout": 120}, "/status/shutdown", "POST", {"timeout": ["120"]}),
        ("reboot_guest", {}, "/status/reboot", "POST", {}),
        ("stop_guest", {}, "/status/stop", "POST", {}),
        (
            "create_snapshot",
            {"snapshot": "before-upgrade"},
            "/snapshot",
            "POST",
            {"snapname": ["before-upgrade"], "description": [""]},
        ),
        ("delete_snapshot", {"snapshot": "old"}, "/snapshot/old", "DELETE", {}),
        ("rollback_snapshot", {"snapshot": "old"}, "/snapshot/old/rollback", "POST", {}),
    ],
)
async def test_guest_write_tools(settings, guest_type, tool, extra, suffix, method, form):
    settings = settings.model_copy(update={"read_only": False, "allow_destructive": True})

    def handler(request):
        assert request.method == method
        assert request.url.path == f"/api2/json/nodes/pve/{guest_type}/100{suffix}"
        assert parse_qs(request.content.decode(), keep_blank_values=True) == form
        return httpx.Response(200, json={"data": TASK})

    api = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    async with mcp_session(create_server(settings, lambda: api)) as session:
        result = await session.call_tool(tool, {**GUEST, "guest_type": guest_type, **extra})
        assert not result.is_error
        assert result.structured_content == {"data": TASK}


@pytest.mark.parametrize("guest_type", ["qemu", "lxc"])
@pytest.mark.parametrize("tool", ["clone_guest", "migrate_guest"])
async def test_guest_specific_parameters(settings, guest_type, tool):
    settings = settings.model_copy(update={"read_only": False})
    args = {**GUEST, "guest_type": guest_type, "target": "pve2"}
    expected = {"target": ["pve2"]}
    if tool == "clone_guest":
        args.update(new_vmid=101, name="new-guest", storage="local-lvm")
        expected.update(newid=["101"], full=["1"], storage=["local-lvm"])
        expected["name" if guest_type == "qemu" else "hostname"] = ["new-guest"]
    else:
        args["online"] = True
        expected["online" if guest_type == "qemu" else "restart"] = ["1"]

    def handler(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/clone" if tool == "clone_guest" else "/migrate")
        assert parse_qs(request.content.decode()) == expected
        return httpx.Response(200, json={"data": TASK})

    api = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    async with mcp_session(create_server(settings, lambda: api)) as session:
        assert not (await session.call_tool(tool, args)).is_error


async def test_backup_endpoint(settings):
    settings = settings.model_copy(update={"read_only": False})

    def handler(request):
        assert request.url.path == "/api2/json/nodes/pve/vzdump"
        assert parse_qs(request.content.decode()) == {
            "vmid": ["100"],
            "storage": ["backups"],
            "mode": ["snapshot"],
            "compress": ["zstd"],
        }
        return httpx.Response(200, json={"data": TASK})

    api = ProxmoxClient(settings, transport=httpx.MockTransport(handler))
    async with mcp_session(create_server(settings, lambda: api)) as session:
        assert not (
            await session.call_tool(
                "backup_guest", {"node": "pve", "vmid": 100, "storage": "backups"}
            )
        ).is_error


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_guest_status", {**GUEST, "node": "../access"}),
        ("get_guest_status", {**GUEST, "node": "pve%2fstatus"}),
        ("get_guest_status", {**GUEST, "vmid": 99}),
        ("get_guest_status", {**GUEST, "guest_type": "shell"}),
        ("list_tasks", {"node": "pve", "limit": 0}),
        ("get_task_log", {"node": "pve", "upid": "../../access"}),
        ("clone_guest", {**GUEST, "new_vmid": 100, "name": "copy"}),
        (
            "clone_guest",
            {**GUEST, "new_vmid": 101, "name": "copy", "full": False, "storage": "local"},
        ),
        ("migrate_guest", {**GUEST, "target": "pve"}),
        ("create_snapshot", {**GUEST, "snapshot": "current"}),
        ("delete_snapshot", {**GUEST, "snapshot": "current"}),
        ("rollback_snapshot", {**GUEST, "snapshot": "current"}),
    ],
)
async def test_invalid_input_never_reaches_api(settings, tool, args):
    settings = settings.model_copy(update={"read_only": False, "allow_destructive": True})

    def unexpected(_):
        pytest.fail("Invalid tool arguments reached the network")

    api = ProxmoxClient(settings, transport=httpx.MockTransport(unexpected))
    async with mcp_session(create_server(settings, lambda: api)) as session:
        assert (await session.call_tool(tool, args)).is_error


async def test_api_failure_becomes_mcp_tool_error(settings):
    api = ProxmoxClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(403, text="SECRET"))
    )
    async with mcp_session(create_server(settings, lambda: api)) as session:
        result = await session.call_tool("list_nodes", {})
        assert result.is_error
        assert "Permission denied" in result.content[0].text
        assert "SECRET" not in result.content[0].text


async def test_configuration_redaction(settings):
    api = ProxmoxClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"data": {"name": "guest", "cipassword": "SECRET", "password": "SECRET"}}
            )
        ),
    )
    async with mcp_session(create_server(settings, lambda: api)) as session:
        result = await session.call_tool("get_guest_config", GUEST)
        assert result.structured_content["data"] == {
            "name": "guest",
        }
