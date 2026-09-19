# Contributing

Issues, documentation fixes, compatibility reports, and focused pull requests are
welcome. For a substantial feature, open an issue describing the user need first.

Use Python 3.11 or newer, create a virtual environment, and follow the README's
hash-enforced development installation commands.
Before submitting a PR, run the lint, format, type, test, build, and audit commands
in the README. CI tests Python 3.11–3.14. No Proxmox account or LLM API key is needed
for the automated suite.

New tools need precise MCP schemas and descriptions, correct impact annotations,
appropriate policy gates, tests of the actual Proxmox request, and a README tool
entry. Include QEMU and LXC coverage when applicable. Confirm parameters against
the official Proxmox API viewer. Never add a raw arbitrary API or shell proxy as
a shortcut, and never include real credentials or infrastructure fixtures.

Keep stdout reserved for MCP framing. Treat API responses and logs as sensitive,
and preserve the default read-only behavior. Avoid automatic write retries.
Explain the user-facing behavior and validation in your PR. Contributions are
accepted under the repository's MIT license.

## Releases

Update the version in `pyproject.toml` and `src/proxmox_mcp/__init__.py`, add a
CHANGELOG entry, and ensure CI is green. Build and test the source/wheel artifacts
in clean environments before tagging. PyPI and container registry publishing are
not configured in this initial release; do not advertise registry installation
until a maintainer has published and verified an artifact there.

## Dependency updates

`uv.lock` is the resolution source; `requirements.lock`, `requirements-dev.lock`,
and `requirements-build.lock` are its hash-bearing pip exports. Development locks
include the pinned uv tool. To update dependencies intentionally:

```sh
.venv/bin/uv lock --upgrade
.venv/bin/uv export --quiet --frozen --no-dev --no-emit-project -o requirements.lock
.venv/bin/uv export --quiet --frozen --extra dev --no-emit-project -o requirements-dev.lock
.venv/bin/uv export --quiet --frozen --only-group build --no-emit-project -o requirements-build.lock
```

For targeted updates use `uv lock --upgrade-package PACKAGE`. Review all changes,
then install with `--require-hashes` as in the README and run CI. Never hand-edit
hashes. Dependabot uv PRs may require regenerating the exported files; CI checks
that they match the lock. Docker digest updates are proposed weekly. Review Trivy's
full report, including unfixed vulnerabilities, before accepting an image update.
The build lock pins the build backend; use `--no-build-isolation`/`--no-isolation`
so package builds do not silently resolve an unpinned backend.

## Community conduct

Be respectful, constructive, and specific. Critique code and ideas, not people.
Harassment, discrimination, and publishing another person's private information
are not acceptable. Maintainers may moderate discussions and contributions to
keep the project welcoming.
