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
- HTTP binds only to `127.0.0.1`. It has no authentication or per-user isolation;
  anyone with access to that host's loopback interface may call its tools. SDK
  Host/Origin validation mitigates browser DNS rebinding, not local malicious software.
- All clients share the configured Proxmox token identity. This is not a multi-tenant service.
- Tool descriptions, guest names, configuration values, and task logs are external
  data. A model must not treat them as instructions or permission to make changes.
- Known password fields in guest configuration are redacted, but arbitrary secrets
  in descriptions and logs cannot reliably be detected. Inventory leaves your
  infrastructure when sent to a hosted model; decide which clients may receive it.
- Read-only checks, typed endpoint arguments, and omitted write tools reduce risk;
  Proxmox ACLs remain the authoritative access control. Client approval policies
  are separate, and MCP tool annotations are hints rather than enforcement.

`PROXMOX_ALLOW_DESTRUCTIVE` specifically gates force-stop and snapshot
delete/rollback. Ordinary write tools can still interrupt services, consume disk
space, or fail midway. Operators should review proposed actions in their MCP host.
The API client deliberately avoids automatic retries so a timeout cannot silently
submit duplicate clones, backups, or other writes.

No live credentials belong in issue reports, traces, screenshots, or test fixtures.
