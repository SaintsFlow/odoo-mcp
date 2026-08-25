"""Entry point of the MCP server.

Six tools live on it: four that only read Odoo and two that write to it. The
two are marked destructive in their annotations, which is what lets a client
ask its user before an order is created or confirmed.
"""

import logging
import os
import sys
from importlib.metadata import PackageNotFoundError, version

import structlog

# In SDK 2.x the high level server class is MCPServer. The old FastMCP name and
# the mcp.server.fastmcp module are gone, so 1.x snippets do not apply here.
from mcp.server.mcpserver import MCPServer

from src.client import OdooClient, OdooConfig
from src.tools import invoices, orders, partners, stock

SERVER_NAME = "odoo-mcp"
DEFAULT_LOG_LEVEL = "info"


def _package_version() -> str:
    """Version the client sees in the handshake.

    It comes from the installed package, so pyproject.toml stays the only place
    where the number is written. A plain checkout has no metadata, hence the
    fallback.
    """
    try:
        return version("odoo-mcp")
    except PackageNotFoundError:
        return "0.0.0"


def configure_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    """Send JSON logs to stderr.

    On the stdio transport stdout carries the protocol itself, so a log line
    printed there breaks the client. Everything goes to stderr instead.
    """
    threshold = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(threshold),
        logger_factory=structlog.WriteLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def build_server(client: OdooClient) -> MCPServer:
    """Create the server and publish the tools on it.

    The client is passed in rather than built here, so a test can hand over one
    that never reaches the network.
    """
    server = MCPServer(SERVER_NAME, version=_package_version())
    for area in (partners, orders, stock, invoices):
        area.register(server, client)
    return server


def main() -> None:
    """Run the server over stdio until the client closes the connection."""
    configure_logging(os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL))
    log = structlog.get_logger()
    server = build_server(OdooClient(OdooConfig.from_env()))
    log.info("server_started", transport="stdio")
    server.run()


if __name__ == "__main__":
    main()
