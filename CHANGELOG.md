# Changelog

## 0.3.0 — Unreleased (SDK 2 migration)

- Migrate to MCP SDK 2.2+ with explicit typed context injection and snake-case
  SDK model attributes, preserving camelCase JSON wire fields and tool schemas.
- Move HTTP settings to the SDK 2 app factory, explicitly enforcing bearer auth,
  DNS-rebinding checks, body caps, stateless mode, and JSON responses.
- Adapt HTTP pool lifetime to the SDK 2 application lifespan and keep upstream
  Proxmox networking on the existing HTTPX adapter.
- Add legacy SDK 1.30.0 CLI compatibility checks for stdio/authenticated HTTP,
  plus modern discovery tests and forwarded-option security regression tests.
- Update hashed dependency locks, Python-client example, and migration docs.
  This branch does not replace the SDK 1-based release on main until reviewed.

## 0.2.2 — 2026-09-19

- Reject Proxmox token secrets shorter than 16 characters to avoid silent output
  and audit-record corruption from substring redaction of misconfigured secrets.
- Audit write refusals from the independent read-only and path guards without
  logging unvalidated paths or parameters and without submitting network requests.
- Reject `task_status` output overrides that omit `status` or `exitstatus`;
  explicitly treat missing upstream completion fields as unverified success.
- Configuration compatibility: short secrets and incomplete task-status overrides
  now fail validation. SDK 2.x remains a separately tested migration.

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
