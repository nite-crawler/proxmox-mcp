import os
from contextlib import asynccontextmanager

import pytest
from mcp import Client

from proxmox_mcp.config import Settings


@asynccontextmanager
async def mcp_session(server):
    # Force the legacy handshake and real in-memory JSON-RPC transport, rather
    # than v2's default direct-dispatch shortcut, to retain protocol coverage.
    async with Client(server, mode="legacy") as client:
        yield client.session


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Never inherit real infrastructure credentials or settings into tests.
    for key in os.environ:
        if key.startswith("PROXMOX_"):
            monkeypatch.delenv(key)


@pytest.fixture
def settings():
    return Settings(
        url="https://pve.example.test:8006",
        token_id="mcp@pve!tests",
        token_secret="test-secret-not-a-real-token",
    )
