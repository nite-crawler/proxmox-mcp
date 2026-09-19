"""A minimal MCP client; no LLM or provider SDK is required."""

import argparse
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(env_file: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "proxmox_mcp", "--env-file", env_file],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print("Available tools:", ", ".join(tool.name for tool in tools.tools))
        result = await session.call_tool("list_nodes", {})
        print(json.dumps(result.model_dump(mode="json", by_alias=True), indent=2))
        if result.is_error:
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    asyncio.run(run(parser.parse_args().env_file))
