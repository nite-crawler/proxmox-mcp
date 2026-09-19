# Architecture

The MCP host starts the console entry point (stdio) or connects to its loopback
HTTP endpoint. The official MCP Python SDK handles initialization, tool schemas,
JSON-RPC, tool results, protocol negotiation, and transport framing.

`config.py` validates environment configuration once at startup. `server.py`
registers typed tools according to the immutable operator policy. `client.py`
owns an async HTTP connection pool, token authentication, TLS verification,
timeouts, response unwrapping, and an independent read-only write guard.
Each SDK lifespan owns and closes its HTTP client. stdio retains a pool for the
connection; SDK 2 HTTP retains one shared pool for the application's lifespan.
Request handlers never close this shared pool. Tools receive their API client
through the SDK's injected, typed `Context`, not ambient context lookup.

Tools expose a constrained subset of the Proxmox API, not an arbitrary URL or
parameter proxy. Names, guest types, IDs, and task IDs are validated before a
network request. Task path segments are URL encoded. The client sends GET
parameters in the query string and write parameters as form data; Python booleans
become Proxmox's numeric 0/1 values. QEMU/LXC differences are explicit at each call.

`SecureMCP` installs a pure ASGI HTTP guard that verifies the shared bearer token
and enforces HTTP admission/deadlines before SDK request handling. stdio remains
OS/process-isolated. A separate tool-call limiter is shared by all SDK lifespans
of one server. API responses are streamed under a byte cap and total deadline.

The result shape is consistently `{"data": ...}`. Read records are selected
through per-view field allowlists and recursively redacted. Raw config and logs
are independently opt-in. This supports both MCP
structured content and the SDK's text representation for older clients. API
errors are sanitized and translated to MCP tool errors. The server returns task
IDs immediately instead of holding connections open while jobs run.

Tests use `httpx.MockTransport` for the upstream Proxmox API and the official SDK
as an MCP client. Protocol tests exercise schema validation, tool policy, and
request mapping. A subprocess test covers stdio framing and initialization;
HTTP tests exercise the ASGI application and SDK Streamable HTTP client. No live
Proxmox credentials are required. See the manual validation checklist before
declaring support for a particular PVE release.

This migration branch uses MCP SDK 2.x, bounded below at the tested 2.2 version
and below 3.0 to avoid silent major API migration. Dependency ranges allow
compatible security updates when maintainers refresh `uv.lock`. CI and Docker
use hashed pip exports for reproducible resolution, including the build backend.
CI verifies exports against the lock, and Docker's base image is digest-pinned.
Vulnerability scans cover both Python packages and the final image's OS packages.

SDK transport tests use `httpx2`; the Proxmox adapter deliberately retains its
explicit `httpx` dependency and previously tested TLS/redirect/proxy behavior.
Legacy SDK 1.30.0 clients are tested in an isolated, hash-locked environment against
the actual SDK 2 CLI over stdio and authenticated loopback HTTP. Modern discovery
and the legacy initialize handshake are covered separately. See
[SDK 2 migration notes](sdk2-migration.md).
