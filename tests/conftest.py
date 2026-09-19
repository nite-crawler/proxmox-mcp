import os

import pytest

from proxmox_mcp.config import Settings


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
