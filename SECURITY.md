# Security policy

Security fixes target the latest release on `main`. Version 0.1.x is an initial
release and has not undergone an independent security audit.

Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/nite-crawler/proxmox-mcp/security/advisories/new).
If private reporting is unavailable, open an issue asking for a private contact
without disclosing exploit details, secrets, or affected infrastructure.

Include the server/Python/SDK versions, the impacted trust boundary, a minimal
reproduction using synthetic data, and the expected behavior. Never include
Proxmox API tokens. Community maintenance is best-effort; no response-time SLA is
promised. See [deployment security](docs/security.md) for the threat model.
