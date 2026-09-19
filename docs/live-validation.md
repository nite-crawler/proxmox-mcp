# Live validation checklist

Automated tests mock the Proxmox API. They establish request mapping and protocol
behavior, not hardware, guest OS, storage, or cluster compatibility. Before using
writes on important workloads, validate an isolated lab and record PVE, Python,
MCP host, and server versions.

1. Create a dedicated audit-only user/token and trusted TLS configuration.
2. Connect the MCP host. Verify initialization and exactly 15 read-only tools.
3. Compare nodes, guests, storage, status, and snapshots with the PVE web UI.
4. Check a task's status and paginated log against the UI.
5. Confirm a token without permission receives a sanitized error or restricted inventory.
6. In a disposable lab, grant narrowly scoped write ACLs, enable writes, and restart.
7. Clone a disposable QEMU template and an LXC template. Poll each returned UPID
   until stopped and verify `exitstatus=OK` before using the new guest.
8. Start and gracefully shut down each guest. Verify behavior in the web UI.
9. On snapshot-capable storage, create a snapshot; back up to a test backup store.
10. If testing migration, use a compatible second node and verify target/storage
    requirements. LXC restart migration interrupts the guest.
11. Only on disposable guests, test force-stop, snapshot rollback, and snapshot
    deletion with the destructive flag enabled. Verify the effects in the UI.
12. Remove disposable lab resources through the PVE UI and revoke the test token.

Do not run these steps against production guests as an unattended test suite.
Report findings without credentials or sensitive logs. This checklist has not
been executed by the initial release's automated test run.
