# Proxmox VE MCP

[![CI](https://github.com/nite-crawler/proxmox-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/nite-crawler/proxmox-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Manage Proxmox VE through any client that speaks the Model Context Protocol:
Claude Desktop, Claude Code, Codex, or an MCP-capable application using a local model.
No model API key or model-specific SDK is required by this server.

Inspect clusters, nodes, QEMU virtual machines, LXC containers, storage, snapshots,
and tasks. Opt in to starting, shutting down, rebooting, cloning, backing up, and
migrating guests. Track operations through Proxmox task IDs.

**Read-only by default.** Write tools are absent from discovery until enabled.
HTTPS certificate verification is enabled; API token secrets are kept out of
startup diagnostics and upstream error messages. Both stdio and local Streamable
HTTP are supported through the official MCP Python SDK.

## Project status

SDK 2 migration candidate, version 0.3.0 (on this branch; not yet released).
Automated tests exercise the API adapter,
MCP discovery and tool calls, a real stdio subprocess, and Streamable HTTP. Proxmox
API responses are mocked: **a live Proxmox cluster has not yet been validated**.
Client examples use standard MCP configuration; individual desktop apps have not
been manually certified. Please report compatibility results with your PVE/client
version. This project is independent of Proxmox Server Solutions GmbH.

Requires Python 3.11+ and network access from the server process to Proxmox VE.
Proxmox Backup Server and Datacenter Manager are different APIs and are not supported.

## Quick start

Install from source (no PyPI publication is assumed):

```sh
git clone https://github.com/nite-crawler/proxmox-mcp.git
cd proxmox-mcp
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock -r requirements-build.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
cp .env.example .env
chmod 600 .env
```

On Windows, use `py -m venv .venv` and `.venv\Scripts\python.exe` in the pip commands.
Set restrictive file permissions appropriate to your OS. Edit `.env` locally:

```dotenv
PROXMOX_URL=https://pve.example.com:8006
PROXMOX_TOKEN_ID=mcp@pve!assistant
PROXMOX_TOKEN_SECRET=replace-with-your-token-secret
PROXMOX_READ_ONLY=true
PROXMOX_VERIFY_SSL=true
# PROXMOX_CA_BUNDLE=/absolute/path/to/proxmox-ca.pem
```

Create a dedicated Proxmox user and a privilege-separated API token under
**Datacenter → Permissions → API Tokens**. Give the user and token the appropriate
ACLs; `PVEAuditor` on `/` with propagation is a convenient starting point for
cluster-wide monitoring, but exposes cluster-wide inventory. Narrow ACL paths if
needed. The token's permissions intersect with the user's permissions. See
[permissions and deployment](docs/security.md) before enabling writes.

Use your Proxmox CA certificate or a publicly trusted certificate. The CA bundle
must be obtained through a trusted channel; do not work around trust errors by
disabling verification on production infrastructure.

Check installation without contacting Proxmox:

```sh
.venv/bin/proxmox-mcp --version
```

### Claude Desktop

Merge this entry into your Claude Desktop MCP configuration, replacing both
absolute paths. Keep credentials in the env file, not in a shared JSON file.

```json
{
  "mcpServers": {
    "proxmox": {
      "command": "/absolute/path/proxmox-mcp/.venv/bin/proxmox-mcp",
      "args": ["--env-file", "/absolute/path/proxmox-mcp/.env"]
    }
  }
}
```

On Windows, `command` is the absolute path to `.venv\\Scripts\\proxmox-mcp.exe`.
Restart the client after changing configuration. See the
[official local MCP connection guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

### Claude Code

```sh
claude mcp add --transport stdio proxmox -- /absolute/path/proxmox-mcp/.venv/bin/proxmox-mcp --env-file /absolute/path/proxmox-mcp/.env
```

See [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

### Codex

Add to `~/.codex/config.toml`, or a trusted project's `.codex/config.toml`:

```toml
[mcp_servers.proxmox]
command = "/absolute/path/proxmox-mcp/.venv/bin/proxmox-mcp"
args = ["--env-file", "/absolute/path/proxmox-mcp/.env"]
```

Or register with the CLI:

```sh
codex mcp add proxmox -- /absolute/path/proxmox-mcp/.venv/bin/proxmox-mcp --env-file /absolute/path/proxmox-mcp/.env
```

See [official Codex MCP documentation](https://developers.openai.com/codex/mcp).

### Local models and other clients

Configure the same command and arguments in an MCP-capable host, or connect to
the local HTTP endpoint below. A bare model inference endpoint (including an
Ollama API by itself) is not an MCP client: its host application must discover
tools, dispatch tool calls, and return the results to the model.

[examples/list_nodes.py](examples/list_nodes.py) is a minimal model-independent
Python client that launches this server, performs the MCP handshake, discovers
tools, and calls `list_nodes`:

```sh
.venv/bin/python examples/list_nodes.py --env-file /absolute/path/proxmox-mcp/.env
```

### Streamable HTTP

Generate a separate bearer token locally, store it as `PROXMOX_HTTP_TOKEN` in your
protected env file, and configure your MCP client to send
`Authorization: Bearer <that-token>`. Never reuse the Proxmox API token secret.
Generate a token with:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

```sh
.venv/bin/proxmox-mcp --env-file .env --transport streamable-http --port 8000
```

Connect your MCP client to `http://127.0.0.1:8000/mcp`. HTTP is deliberately bound
to IPv4 loopback and uses SDK Host/Origin validation. Every HTTP method requires
one valid bearer header; missing/invalid credentials return 401 before MCP processing.
HTTP startup fails without a token. The token is a shared credential, not OAuth
or per-user authorization: all authenticated clients share the configured Proxmox
identity. Rotate it by replacing the env value, restarting, and updating clients.
Do not expose the plain HTTP endpoint remotely. A remote deployment needs TLS,
appropriate client identity/authorization, and a separate gateway threat model.
Legacy HTTP+SSE transport is not provided. stdio does not require an HTTP token.

## Available tools

Every successful result has a `data` field. Read results are filtered through
operator-configurable field allowlists; omitted fields must not be treated as unset.
Failures become MCP tool errors (`isError: true`), without raw upstream bodies.

| Mode | Tools |
| --- | --- |
| Read-only (default, 14 tools) | `get_version`, `get_cluster_status`, `list_resources`, `list_nodes`, `get_node_status`, `list_storage`, `list_storage_content`, `list_guests`, `get_guest_status`, `get_guest_config`, `list_snapshots`, `list_tasks`, `get_task_status`, `get_next_vmid` |
| Sensitive-output opt-ins (independent) | `get_guest_config_raw` with `PROXMOX_ALLOW_RAW_CONFIG=true`; `get_task_log` with `PROXMOX_ALLOW_TASK_LOGS=true` |
| Write-enabled (7 additional tools) | `start_guest`, `shutdown_guest`, `reboot_guest`, `clone_guest`, `create_snapshot`, `backup_guest`, `migrate_guest` |
| Destructive opt-in (3 additional tools) | `stop_guest`, `delete_snapshot`, `rollback_snapshot` |

To expose normal write tools, set `PROXMOX_READ_ONLY=false` and restart the server.
To additionally expose forced stop and snapshot removal/rollback, also set
`PROXMOX_ALLOW_DESTRUCTIVE=true`. These switches are operator configuration, never
tool arguments. They do not grant Proxmox permissions. Graceful shutdown, reboot,
migration, and some backup modes can still cause downtime in ordinary write mode.
MCP annotations describe impact; client-side approval behavior varies by host.

Use `guest_type="qemu"` for VMs and `guest_type="lxc"` for containers. Provisioning
is supported through `clone_guest` from an existing guest or template. This release
does not expose arbitrary API requests, shell execution, guest deletion, guest
configuration updates, or VM creation from scratch.

Writes returning a `UPID:...` string are asynchronous submissions, **not successful
completion**. Call `get_task_status` with the source node and that UPID until
`status` is `stopped`, then check `exitstatus == "OK"`. Use `get_task_log` for
diagnostics when task-log access is enabled. A timeout does not prove a write failed; check `list_tasks` before
retrying. The server intentionally never retries writes automatically.

Example requests to your assistant:

- “List my VMs and containers and summarize their current state.”
- “Show storage capacity on pve1 and recent failed tasks.”
- “Clone template 9000 to VM 101, then monitor the clone task.”
- “Create a before-upgrade snapshot of VM 101 and confirm the task completed.”

## Configuration

Environment variables override values in an explicitly supplied `--env-file`.
The server never implicitly loads a `.env` from the working directory.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PROXMOX_URL` | Required | HTTPS origin, e.g. `https://pve.example.com:8006`; `/api2/json` suffix accepted |
| `PROXMOX_TOKEN_ID` | Required | Full ID, e.g. `mcp@pve!assistant` |
| `PROXMOX_TOKEN_SECRET` | Required | API token secret; at least 16 printable ASCII characters, no whitespace |
| `PROXMOX_VERIFY_SSL` | `true` | Certificate and hostname verification |
| `PROXMOX_CA_BUNDLE` | System trust | PEM CA bundle path |
| `PROXMOX_TIMEOUT` | `30` | HTTP timeout in seconds, greater than 0 and at most 300 |
| `PROXMOX_OPERATION_TIMEOUT` | `30` | Total operation/HTTP-request deadline in seconds, including slow response streams (0–300, exclusive of 0) |
| `PROXMOX_MAX_RESPONSE_BYTES` | `4194304` | Maximum upstream response size; enforced while streaming (1 KiB–128 MiB) |
| `PROXMOX_MAX_REQUEST_BYTES` | `1048576` | Maximum MCP HTTP request body (1 KiB–4 MiB) |
| `PROXMOX_MAX_CONCURRENT_REQUESTS` | `8` | Concurrent HTTP requests and concurrent tool API calls per server instance (1–64); excess work is rejected |
| `PROXMOX_HTTP_TOKEN` | Unset | Required for HTTP; separate random bearer token, 32–256 URL-safe characters |
| `PROXMOX_ALLOW_RAW_CONFIG` | `false` | Expose full guest configuration tool, with known secret fields redacted |
| `PROXMOX_ALLOW_TASK_LOGS` | `false` | Expose task-log tool; logs may contain arbitrary sensitive text |
| `PROXMOX_OUTPUT_FIELDS` | Built-in allowlists | JSON object replacing selected output views' field lists; see [output policy](docs/security.md#output-policy) |
| `PROXMOX_READ_ONLY` | `true` | Omit write tools and block writes in the API client |
| `PROXMOX_ALLOW_DESTRUCTIVE` | `false` | Enable force-stop, snapshot delete and rollback; requires writes enabled |

Ambient HTTP proxy variables are ignored to keep API tokens on the configured
direct connection. Redirects are not followed. Logs go to stderr so stdout remains
valid MCP traffic. Freeform descriptions/notes and unlisted fields are omitted by
default. Known secret keys and configured credential values are redacted recursively.
Allowlisted names, statuses, and opted-in raw data can still contain arbitrary
sensitive text; only connect clients you trust with your inventory.

Write audit events are emitted at WARNING level even with default settings.
Capture stderr and configure retention in your MCP host or service manager.
Use `--log-level INFO` for additional diagnostics; see
[audit semantics and limitations](docs/security.md#audit-records-and-error-handling).

Responses exceeding the byte limit fail without returning partial data. Compressed
upstream responses are rejected (the client requests `Accept-Encoding: identity`)
to avoid decompression-based memory exhaustion. Busy HTTP requests return 429;
busy stdio tool calls return a tool error. Limits are shared across sessions of
one server instance; separately launched processes have separate budgets.

## Docker (stdio)

```sh
docker build -t proxmox-mcp .
docker run --rm -i --env-file .env proxmox-mcp
```

Use `-i`, not `-t`, to preserve stdio framing. The image runs as a non-root user.
The final image excludes pip and its bootstrap files; update dependencies by
rebuilding the image, not by installing packages inside a running container.
If using a CA bundle, mount it read-only and point `PROXMOX_CA_BUNDLE` at its
container path. Host loopback addresses and paths are not automatically available
inside containers. HTTP inside Docker is not exposed by this image.

## Development

```sh
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
.venv/bin/python -m build --no-isolation
.venv/bin/pip-audit --require-hashes -r requirements.lock
```

Tests use synthetic credentials and mocked Proxmox transport; they never require
or target a live cluster. Coverage includes branches and enforces a 90% minimum.
CI runs the test suite on Python 3.11–3.14 and checks packaging, lint, types, and
dependency vulnerabilities. Container CI reports all OS/Python vulnerabilities and
blocks HIGH/CRITICAL findings with available fixes; unfixed findings remain in the
downloadable report for review. Scheduled weekly CI refreshes the scans.
`uv.lock` and hashed exports pin runtime, development, and build dependencies;
the Docker base is digest-pinned and Dependabot proposes weekly updates.
See [lockfile maintenance](CONTRIBUTING.md#dependency-updates). This branch uses
the official SDK 2.x API (`mcp>=2.2,<3`). CLI options, tool names, environment
variables, and JSON result shapes are unchanged. Embedded Python callers must
use the SDK 2 context and client APIs; see [migration notes](docs/sdk2-migration.md).

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md),
[architecture](docs/architecture.md), and the [live validation checklist](docs/live-validation.md).
The project is distributed under the [MIT license](LICENSE).
