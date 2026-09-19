"""Operator-controlled output minimization, independent of model arguments."""

from typing import Any

DEFAULT_FIELDS: dict[str, tuple[str, ...]] = {
    "version": ("version", "release", "repoid"),
    "cluster": ("id", "name", "type", "nodeid", "nodes", "online", "quorate", "local", "version"),
    "resources": (
        "id",
        "type",
        "node",
        "vmid",
        "name",
        "status",
        "cpu",
        "maxcpu",
        "mem",
        "maxmem",
        "disk",
        "maxdisk",
        "uptime",
        "storage",
        "pool",
        "content",
        "shared",
        "template",
    ),
    "nodes": ("node", "status", "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk", "uptime"),
    "node_status": (
        "cpu",
        "cpuinfo",
        "memory",
        "swap",
        "loadavg",
        "uptime",
        "rootfs",
        "pveversion",
    ),
    "storage": (
        "storage",
        "type",
        "active",
        "enabled",
        "shared",
        "content",
        "total",
        "used",
        "avail",
    ),
    "storage_content": ("volid", "content", "format", "size", "used", "vmid", "ctime", "protected"),
    "guests": (
        "vmid",
        "name",
        "status",
        "cpu",
        "cpus",
        "mem",
        "maxmem",
        "disk",
        "maxdisk",
        "uptime",
        "template",
        "netin",
        "netout",
        "diskread",
        "diskwrite",
    ),
    "guest_status": (
        "vmid",
        "name",
        "status",
        "qmpstatus",
        "cpu",
        "cpus",
        "mem",
        "maxmem",
        "disk",
        "maxdisk",
        "uptime",
        "netin",
        "netout",
        "diskread",
        "diskwrite",
        "ha",
    ),
    "guest_config": ("name", "hostname", "cores", "sockets", "memory", "swap", "onboot", "ostype"),
    "snapshots": ("name", "parent", "snaptime", "vmstate"),
    "tasks": ("upid", "node", "id", "type", "status", "starttime", "endtime", "pid", "pstart"),
    "task_status": (
        "upid",
        "node",
        "id",
        "type",
        "status",
        "exitstatus",
        "starttime",
        "pid",
        "pstart",
    ),
}


def redact(value: Any, secrets: tuple[str, ...], depth: int = 0) -> Any:
    """Redact known secret keys and configured credentials, including nested values."""
    if depth > 32:
        return "[OMITTED: nesting limit]"
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                part in key.lower()
                for part in (
                    "password",
                    "passwd",
                    "secret",
                    "token",
                    "credential",
                    "authorization",
                    "private_key",
                )
            )
            else redact(item, secrets, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets, depth + 1) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
    return value


def filter_output(value: Any, fields: tuple[str, ...], secrets: tuple[str, ...]) -> Any:
    """Select fields on each record; unexpected record shapes fail closed."""
    if isinstance(value, list):
        return [
            filter_output(item, fields, secrets) if isinstance(item, dict) else None
            for item in value
        ]
    if isinstance(value, dict):
        return redact({key: item for key, item in value.items() if key in fields}, secrets)
    return None
