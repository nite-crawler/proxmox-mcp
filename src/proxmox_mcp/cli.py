"""Console entry point. stdout belongs exclusively to the MCP protocol."""

import argparse
import logging
import ssl
from pathlib import Path

from pydantic import ValidationError

from proxmox_mcp import __version__
from proxmox_mcp.config import Settings
from proxmox_mcp.server import create_server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Proxmox VE MCP server")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--env-file", type=Path, help="Explicit dotenv file (not loaded by default)"
    )
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--port", type=int, default=8000, help="Loopback HTTP port (default: 8000)")
    parser.add_argument(
        "--log-level",
        choices=("INFO", "WARNING"),
        default="WARNING",
        help="stderr verbosity; write audit events are always WARNING",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.env_file and not args.env_file.is_file():
        parser.error("the specified env file does not exist")
    logging.basicConfig(
        level=args.log_level,
        force=True,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = Settings(_env_file=args.env_file)  # type: ignore[call-arg]
        if args.transport == "streamable-http" and settings.http_token is None:
            parser.error(
                "Streamable HTTP requires PROXMOX_HTTP_TOKEN (a separate random bearer token)"
            )
        if settings.ca_bundle:
            ssl.create_default_context(cafile=str(settings.ca_bundle))
        server = create_server(settings)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'settings'}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        parser.error(f"invalid Proxmox configuration: {details}")
    except (OSError, ValueError):
        parser.error("cannot load TLS configuration; check PROXMOX_CA_BUNDLE")
    except Exception:
        parser.error("cannot initialize server; check configuration")
    if not settings.verify_ssl:
        logging.warning("TLS verification is disabled; use only with isolated test infrastructure")
    server.settings.port = args.port
    try:
        server.run(transport=args.transport)
    except Exception:
        parser.error("server failed; check configuration and tasks before retrying writes")
