"""Ensure release inputs remain reproducible and mutually consistent."""

import re
import tomllib
from pathlib import Path

from proxmox_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_agree():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["version"] == __version__
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(p for p in lock["package"] if p["name"] == "proxmox-ve-mcp")
    assert package["version"] == __version__


def test_docker_stages_use_same_immutable_base():
    dockerfile = (ROOT / "Dockerfile").read_text()
    images = re.findall(r"^FROM (\S+)", dockerfile, flags=re.MULTILINE)
    assert len(images) == 2 and images[0] == images[1]
    assert re.fullmatch(r"python:3\.13-slim@sha256:[0-9a-f]{64}", images[0])
    assert "--require-hashes" in dockerfile
    assert "--no-isolation" in dockerfile


def test_runtime_image_removes_installers():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "/opt/venv/bin/python -m pip uninstall --yes pip" in dockerfile
    assert "RUN python -m pip uninstall --yes pip" in dockerfile
    assert "rm -rf /usr/local/lib/python3.13/ensurepip" in dockerfile
