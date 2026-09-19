# Permissions and deployment

Use a dedicated Proxmox service user with an expiring, privilege-separated API
token. Never give an assistant your root password. Both the user's ACLs and the
token's ACLs must permit an operation. For monitoring, grant `PVEAuditor` only on
the paths the client needs; `/` with propagation grants broad inventory access.
Some tools may return empty lists when the token cannot see the requested objects.

For write access, create a custom role or use appropriate built-in roles scoped
to the relevant guests and storage. Do not solve every 403 by granting Administrator.
Common privileges to evaluate against your installed API viewer include:

| Operation | Relevant privileges (not an exhaustive ACL recipe) |
| --- | --- |
| Guest configuration/status | `VM.Audit` |
| Start, shutdown, reboot, stop | `VM.PowerMgmt` |
| Clone | `VM.Clone` on source, `VM.Allocate` on destination, `Datastore.AllocateSpace` on destination storage |
| Snapshot create/delete | `VM.Snapshot` |
| Snapshot rollback | `VM.Snapshot.Rollback` |
| Migration | `VM.Migrate`, plus storage requirements of the migration |
| Backup | `VM.Backup`, destination storage permissions |

Check [the Proxmox API viewer](https://pve.proxmox.com/pve-docs/api-viewer/),
[API authentication](https://pve.proxmox.com/wiki/Proxmox_VE_API), and
[user management](https://pve.proxmox.com/pve-docs/chapter-pveum.html) for the
permissions of each endpoint in your installed release. ACL requirements and
storage capabilities vary. This server never modifies user/token permissions.

## Trust boundaries

- Proxmox API tokens remain in the server process. Environment files must be
  readable only by the account that runs it and must not be committed.
- HTTPS is mandatory. Certificate verification is the default; use a trusted
  CA bundle for private certificates. Do not disable TLS verification in production.
- The process ignores proxy environment variables and never follows redirects.
- stdio delegates process access control to the MCP host and operating system.
- HTTP binds only to `127.0.0.1` and requires a separate random bearer token in
  exactly one Authorization header on every request. Comparisons use constant-time
  comparison; tokens in query parameters are not accepted. Unauthenticated requests
  are rejected before MCP processing. HTTP refuses to start without a token.
  SDK Host/Origin checks remain enabled. Keep the token out of shell command lines
  and shared client configs; supply it through your client's secret/environment support.
  Any local process able to read the token can impersonate its holder.
- All clients share the configured Proxmox token identity. This is not a multi-tenant service.
- Tool descriptions, guest names, configuration values, and task logs are external
  data. A model must not treat them as instructions or permission to make changes.
- Output allowlists omit freeform fields by default. Raw configuration and task
  logs are separately disabled by default. Arbitrary secrets in permitted text
  cannot reliably be detected. Inventory leaves your
  infrastructure when sent to a hosted model; decide which clients may receive it.
- Read-only checks, typed endpoint arguments, and omitted write tools reduce risk;
  Proxmox ACLs remain the authoritative access control. Client approval policies
  are separate, and MCP tool annotations are hints rather than enforcement.

`PROXMOX_ALLOW_DESTRUCTIVE` specifically gates force-stop and snapshot
delete/rollback. Ordinary write tools can still interrupt services, consume disk
space, or fail midway. Operators should review proposed actions in their MCP host.
Enable destructive mode only with Proxmox ACLs scoped to guests whose disruption
or loss you explicitly accept. Keep critical guests outside that token's scope.
Model instructions and approval prompts do not enforce this boundary; Proxmox
permissions do. The token holder can invoke every exposed tool without an LLM.
The API client deliberately avoids automatic retries so a timeout cannot silently
submit duplicate clones, backups, or other writes.

No live credentials belong in issue reports, traces, screenshots, or test fixtures.

## Output policy

`get_guest_config` returns only `name`, `hostname`, `cores`, `sockets`, `memory`,
`swap`, `onboot`, and `ostype` by default. Inventory, task status, snapshot, and
storage tools also select fields; descriptions, notes, and user identities are
omitted from their default views. Names and task error statuses remain useful but
can contain operator-entered information. Allowlisting is data minimization, not
a guarantee that every retained value is public.

Set `PROXMOX_OUTPUT_FIELDS` to a JSON object to replace particular view lists:

```dotenv
PROXMOX_OUTPUT_FIELDS='{"guest_config":["cores","memory"],"snapshots":["name","snaptime"]}'
```

An empty list suppresses all fields in that view. Unspecified views retain their
defaults. Exact field names only: no wildcard or dotted-path selectors. See
[the complete default lists](../src/proxmox_mcp/output.py). Valid view names are
`version`, `cluster`, `resources`, `nodes`, `node_status`, `storage`,
`storage_content`, `guests`, `guest_status`, `guest_config`, `snapshots`, `tasks`,
and `task_status`. Allowlists select top-level fields on each record. Selected
nested objects are retained with recursive secret-key redaction.

`PROXMOX_ALLOW_RAW_CONFIG=true` registers `get_guest_config_raw`, bypassing the
field allowlist while retaining secret-key redaction. Independently,
`PROXMOX_ALLOW_TASK_LOGS=true` registers `get_task_log`. Neither flag grants write
permission. Both are operator-only configuration; an LLM cannot turn them on
through tool arguments. Restart after configuration changes.

Known secret-key fragments (password, passwd, secret, token, credential,
authorization, private_key) are recursively redacted. Literal configured Proxmox
credentials and HTTP credentials are removed from string values as well.
Exact keys `args` (arbitrary QEMU arguments) and `sshkeys` (guest access information)
are also redacted, case-insensitively, including raw configuration and explicitly
allowlisted fields. SSH public keys are not private keys, but disclose access
relationships. Other secrets placed in descriptions, arbitrary fields, names,
or log lines may remain when those
outputs are permitted. Redaction is not a general-purpose secret detector.

## Audit records and error handling

The CLI emits write audit records to stderr at WARNING level, with timestamps,
JSON-escaped fields, and a per-request correlation ID. `--log-level INFO` adds
routine diagnostics; the default WARNING level still records writes. stdout is
reserved for the MCP protocol. The CLI explicitly configures its logging handlers;
embedded users of `create_server` must configure and retain their own logs.

After local write/path guards permit an API attempt, records include its method
and endpoint, response status if headers arrive, and elapsed time. `api_accepted`
means a successful API response was received and decoded, not that a background
task completed. `outcome_unknown` means no confirmed acceptance: inspect any
recorded HTTP status and Proxmox task history before retrying. Timeouts, network
errors, and cancellation all produce this conservative outcome. A process crash
may leave only an attempt record. Calls blocked before the API client are not
recorded by this write audit.

Parameters, response bodies, raw exception messages, and configured credentials
are excluded from audit records. Endpoints still reveal node/guest/snapshot names;
restrict log access. Capture stderr in your MCP host, service manager, or log
collector and set retention explicitly. These are operational records, not a
durable, tamper-proof audit store, and the shared Proxmox identity does not identify
individual MCP users. Unexpected tool, initialization, and cleanup exceptions are
replaced with generic messages; cancellation is propagated, not swallowed.

## Resource limits

The default upstream byte cap is 4 MiB, checked both against declared length and
actual streamed bytes. Compressed responses are rejected to prevent decompression
bombs; reverse proxies must honor `Accept-Encoding: identity`. HTTP bodies have a
separate 1 MiB cap. The total deadline is 30 seconds, including slow streams, in
addition to HTTPX network-phase timeouts. Deadline cancellation does not cancel an
already submitted Proxmox task.

There are at most eight concurrent tool API calls per server instance, shared
across sessions. HTTP also has a separate eight-request admission limit before
SDK processing; excess requests get 429 immediately rather than accumulating an
unbounded queue. Tool overload errors state that no API request was submitted.
Timeouts, failures, and cancellations release capacity. This bounds concurrency,
not requests per minute, and separate server processes have separate budgets.

## Dependency and container security

Hash-enforced lockfiles cover runtime, development, and build dependencies.
Docker installs only locked wheels and builds this project's wheel without
dependency resolution. Both build/runtime base images reference an immutable
multi-platform digest. Dependabot proposes uv, Docker, and GitHub Actions updates;
maintainers review them and refresh exported locks before merging.

CI audits locked Python dependencies and scans the final image's OS and Python
packages using a commit-pinned Trivy action. The full JSON report includes unfixed
findings at every severity; a separate gate rejects fixable HIGH/CRITICAL findings.
Unfixed findings require maintainer review and are not a clean bill of health.
Weekly scheduled scans detect newly disclosed vulnerabilities. This does not
replace independent source review or live-cluster validation.
