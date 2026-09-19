# Changelog

## 0.2.1 — 2026-09-19

- Record write attempts, HTTP response status, and acceptance/unknown outcomes
  to stderr at the default log level, with correlation IDs and elapsed time.
- Add explicit CLI logging configuration and `--log-level INFO|WARNING`.
- Redact QEMU `args` and guest `sshkeys` even in raw or custom-allowlisted output.
- Sanitize unexpected tool, initialization, and cleanup errors without swallowing
  cancellation; add regression tests for error leakage and default CLI auditing.
- Clarify log retention limits and require destructive-mode ACLs to exclude guests
  whose disruption or loss the operator cannot accept.

## 0.2.0 — 2026-09-19

- Require a separate bearer token for local HTTP, including startup validation,
  constant-time checks, and authentication before MCP processing.
- Filter read outputs with configurable per-view allowlists. Raw configuration
  and task logs are independent opt-ins; recursively redact known secret keys
  and configured credential values.
- Bound streamed response bytes, incoming HTTP body size, total operation time,
  and concurrency across sessions. Reject compression and release slots on failure.
- Add hashed runtime/development/build locks, digest-pinned Docker bases,
  automated dependency updates, and scheduled OS/Python container scanning.
- Remove unused Python package installers and their vendored dependencies from
  the runtime container, with a CI check preventing their reintroduction.
- Breaking defaults: HTTP needs `PROXMOX_HTTP_TOKEN`; task logs are hidden;
  read responses omit fields outside allowlists. See README for migration.

## 0.1.0 — 2026-09-19

- Initial Proxmox VE MCP server with 15 read tools, seven optional write tools,
  and three separately gated destructive tools.
- QEMU/LXC inventory, clone provisioning, lifecycle, snapshots, backups,
  migration, and asynchronous task inspection.
- stdio and local Streamable HTTP through the official MCP Python SDK.
- TLS verification, API token authentication, sanitized errors, and typed inputs.
- Automated API/protocol/transport tests, CI, packaging, Dockerfile, and client examples.
- Live Proxmox and individual desktop-client validation remain community follow-up work.
