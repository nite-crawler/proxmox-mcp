# SDK 2 migration candidate

This branch prepares version 0.3.0; the SDK 1-based 0.2.2 release remains on `main`
until this migration is reviewed. Upstream continues to maintain the newest 1.x
release for critical/security fixes, so this is planned compatibility work rather
than an emergency replacement. See the upstream
[migration guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md)
and [support policy](https://github.com/modelcontextprotocol/python-sdk/blob/main/SECURITY.md).

## User-facing compatibility

The executable, environment variables, stdio framing, `/mcp` endpoint, tool names,
tool inputs, policy gates, and `{"data": ...}` result envelopes are unchanged.
The server continues to understand the legacy initialize handshake as well as
modern SDK 2 discovery. A client does not need SDK 2 to use this server.

Embedded Python integrations must update from `FastMCP` to `MCPServer`, use
injected `Context`, and read SDK model attributes in snake_case. When serializing
protocol models manually, use `model_dump(by_alias=True)` to retain the camelCase
wire format. CLI users do not need to change client configuration.

SDK 2 moved HTTP configuration from server construction to `run()` and the app
factory. `SecureMCP.streamable_http_app()` keeps operator configuration authoritative
even when SDK run helpers forward their own defaults: bearer auth is mandatory,
DNS-rebinding protection is explicitly enabled, the configured body cap is applied,
and the app stays stateless with JSON responses. The CLI binds only to `127.0.0.1`.
An embedding ASGI host remains responsible for its own socket binding and must
run the SDK session manager's lifespan.

SDK 2 initializes one Proxmox client pool when the HTTP application starts, shares
it among requests, and closes it at shutdown. This startup is not an API request;
unauthenticated HTTP traffic is still rejected before MCP request processing.
The instance-wide tool limiter continues to bound upstream concurrency.

## Dependencies

Runtime locks now include SDK 2's `mcp-types`, `httpx2`, `httpcore2`, `truststore`,
and `opentelemetry-api` dependencies. The server does not configure a telemetry
exporter; embedding applications that enable tracing must apply their own privacy
and retention policy. Existing credential/error filtering remains in place.

The Proxmox API adapter still uses the explicitly declared `httpx` dependency:
no incidental change to its certificate verification, proxy behavior, redirect
handling, exception classes, or no-retry policy. SDK transport tests explicitly
depend on `httpx2`; its client objects are not interchangeable with `httpx` objects.

## Merge checks

- Run the full suite on Python 3.11–3.14, lint, typing, packaging, and dependency audit.
- Verify HTTP authentication on every method, hostile Host/Origin rejection,
  request-body caps, concurrency limits, deadlines, and cancellation cleanup.
- Verify tool schemas exclude the injected context parameter and keep write gates.
- Exercise legacy handshakes and modern discovery over stdio and HTTP.
- Run the frozen SDK 1 client smoke test against the real SDK 2 CLI, including a
  non-default loopback HTTP port and unauthenticated rejection.
- Build and scan the runtime image without weakening vulnerability gates.
- Follow the [live validation checklist](live-validation.md) before production writes.

Automated checks do not certify individual Claude/Codex/local-model host releases
or a live Proxmox cluster. Those manual checks remain outstanding.
