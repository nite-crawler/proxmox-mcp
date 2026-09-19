"""Run with the frozen SDK 1 client environment against the SDK 2 server CLI.

Only protocol discovery and locally rejected arguments are exercised: no live
Proxmox credentials or upstream network requests are needed.
"""

import argparse
import asyncio
import os
import socket
import subprocess
from datetime import timedelta
from importlib.metadata import version

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

TOKEN = "sdk1-compat-http-token-synthetic-only-123456789"


async def check(session):
    initialized = await session.initialize()
    assert initialized.serverInfo.name == "proxmox-ve"
    listing = await session.list_tools()
    assert len(listing.tools) == 14
    for tool in listing.tools:
        wire = tool.model_dump(by_alias=True)
        assert "inputSchema" in wire and "input_schema" not in wire
        assert "ctx" not in wire["inputSchema"].get("properties", {})
        assert wire["annotations"]["readOnlyHint"] is True
    result = await session.call_tool(
        "get_guest_status", {"node": "../bad", "guest_type": "qemu", "vmid": 100}
    )
    assert result.isError
    assert result.model_dump(by_alias=True)["isError"] is True


async def run(server_python):
    assert version("mcp") == "1.30.0", "Run in the frozen SDK 1 client environment"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROXMOX_")}
    env.update(
        PROXMOX_URL="https://pve.example.test:8006",
        PROXMOX_TOKEN_ID="mcp@pve!compat",
        PROXMOX_TOKEN_SECRET="synthetic-compat-secret-only",
        PROXMOX_HTTP_TOKEN=TOKEN,
    )
    params = StdioServerParameters(command=server_python, args=["-m", "proxmox_mcp"], env=env)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session,
    ):
        await check(session)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [server_python, "-m", "proxmox_mcp", "--transport", "streamable-http", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        async with httpx.AsyncClient(trust_env=False, timeout=1) as probe:
            async with asyncio.timeout(15):
                while True:
                    if process.poll() is not None:
                        raise AssertionError("HTTP server exited before readiness")
                    try:
                        response = await probe.post(url)
                        assert response.status_code == 401
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.05)
        async with (
            httpx.AsyncClient(
                headers={"Authorization": f"Bearer {TOKEN}"}, trust_env=False
            ) as http,
            streamable_http_client(url, http_client=http) as (read, write, _),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session,
        ):
            await check(session)
    finally:
        process.terminate()
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate(timeout=5)
        assert TOKEN.encode() not in stderr
    print("SDK 1.30.0 client: stdio and authenticated HTTP compatibility passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-python", required=True)
    asyncio.run(run(parser.parse_args().server_python))
