# Architecture

The MCP host starts the console entry point (stdio) or connects to its loopback
HTTP endpoint. The official MCP Python SDK handles initialization, tool schemas,
JSON-RPC, tool results, protocol negotiation, and transport framing.

`config.py` validates environment configuration once at startup. `server.py`
registers typed tools according to the immutable operator policy. `client.py`
owns an async HTTP connection pool, token authentication, TLS verification,
timeouts, response unwrapping, and an independent read-only write guard.
Each SDK lifespan owns and closes its HTTP client. stdio retains a pool for the
session; stateless HTTP creates a separate client per request so concurrent
requests cannot close one another's connections.

Tools expose a constrained subset of the Proxmox API, not an arbitrary URL or
parameter proxy. Names, guest types, IDs, and task IDs are validated before a
network request. Task path segments are URL encoded. The client sends GET
parameters in the query string and write parameters as form data; Python booleans
become Proxmox's numeric 0/1 values. QEMU/LXC differences are explicit at each call.

The result shape is consistently `{"data": ...}`. This supports both MCP
structured content and the SDK's text representation for older clients. API
errors are sanitized and translated to MCP tool errors. The server returns task
IDs immediately instead of holding connections open while jobs run.

Tests use `httpx.MockTransport` for the upstream Proxmox API and the official SDK
as an MCP client. Protocol tests exercise schema validation, tool policy, and
request mapping. A subprocess test covers stdio framing and initialization;
HTTP tests exercise the ASGI application and SDK Streamable HTTP client. No live
Proxmox credentials are required. See the manual validation checklist before
declaring support for a particular PVE release.

The first release uses the maintained MCP SDK 1.x API, bounded below at the tested
1.30 version and below 2.0 to avoid silent API migration. Dependency ranges allow
compatible security updates. CI checks current resolution; users who need exact
deployment reproducibility should capture their resolved dependencies in their
own deployment lockfile or pin the built container digest.
