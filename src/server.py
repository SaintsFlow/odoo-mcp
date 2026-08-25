"""Entry point of the MCP server.

Six tools live on it: four that only read Odoo and two that write to it. The
two are marked destructive in their annotations, which is what lets a client
ask its user before an order is created or confirmed.
"""

import logging
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

import structlog
import uvicorn

# In SDK 2.x the high level server class is MCPServer. The old FastMCP name and
# the mcp.server.fastmcp module are gone, so 1.x snippets do not apply here.
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.client import OdooClient, OdooConfig
from src.errors import OdooError
from src.tools import invoices, orders, partners, stock

SERVER_NAME = "odoo-mcp"
DEFAULT_LOG_LEVEL = "info"
READONLY_ENV = "ODOO_READONLY"

TRANSPORT_ENV = "MCP_TRANSPORT"
HOST_ENV = "MCP_HOST"
PORT_ENV = "MCP_PORT"

# Loopback on purpose: a server that listens on every interface the moment it
# starts is a surprise. The container overrides it, see docker-compose.yml.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
HEALTH_PATH = "/health"

# What counts as "yes" in an environment variable. Anything else, including an
# empty value, leaves writing on.
TURNED_ON = frozenset({"1", "true", "yes", "on"})

# "http" is what a person types; "streamable-http" is what the SDK calls it.
HTTP_NAMES = frozenset({"http", "streamable-http"})

Transport = Literal["stdio", "streamable-http"]


def read_only_from_env() -> bool:
    """Whether this server may change anything in Odoo."""
    return os.getenv(READONLY_ENV, "").strip().lower() in TURNED_ON


def transport_from_env() -> Transport:
    """How the server talks to its client: over the pipe, or over a port."""
    asked = os.getenv(TRANSPORT_ENV, "").strip().lower()
    if not asked or asked == "stdio":
        return "stdio"
    if asked in HTTP_NAMES:
        return "streamable-http"
    raise OdooError(
        f"{TRANSPORT_ENV} is either stdio or http. It is {asked!r}, and guessing which "
        f"one was meant would be worse than stopping."
    )


def _port_from_env() -> int:
    """Which port the http transport listens on."""
    raw = os.getenv(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    if not raw.isdigit():
        raise OdooError(f"{PORT_ENV} has to be a port number. It is {raw!r}.")
    return int(raw)


def build_http_app(server: MCPServer, host: str = DEFAULT_HOST) -> Starlette:
    """The transport application with our own health endpoint beside it.

    The SDK can run this itself, but only over an app it builds and keeps, and
    a route cannot be added to that one from outside. So the app is built here
    and uvicorn is started here too.
    """
    app = server.streamable_http_app(host=host)

    async def health(_: Request) -> JSONResponse:
        # Deliberately says nothing about Odoo. The compose healthcheck watches
        # this, and a database that is briefly away must not get a running
        # server restarted underneath it.
        return JSONResponse(
            {
                "status": "ok",
                "server": server.name,
                "version": server.version,
                "transport": "streamable-http",
            }
        )

    app.router.routes.append(Route(HEALTH_PATH, health, methods=["GET"]))
    return app


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

    # The SDK logs through the standard library and sets its own level, so
    # LOG_LEVEL has to reach it as well. Without this a server told to keep
    # quiet still narrates every refused tool call.
    logging.getLogger("mcp").setLevel(threshold)

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


def build_server(client: OdooClient, read_only: bool = False) -> MCPServer:
    """Create the server and publish the tools on it.

    The client is passed in rather than built here, so a test can hand over one
    that never reaches the network. In read-only mode the write tools are never
    registered: pointed at a real database, the server should not even offer to
    change it.
    """
    server = MCPServer(SERVER_NAME, version=_package_version())
    for area in (partners, orders, stock, invoices):
        area.register(server, client)
    if not read_only:
        orders.register_writes(server, client)
    return server


def main() -> None:
    """Run the server until its client goes away."""
    level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    configure_logging(level)
    log = structlog.get_logger()

    transport = transport_from_env()
    read_only = read_only_from_env()
    server = build_server(OdooClient(OdooConfig.from_env()), read_only=read_only)

    if transport == "stdio":
        log.info("server_started", transport=transport, read_only=read_only)
        server.run()
        return

    host = os.getenv(HOST_ENV, "").strip() or DEFAULT_HOST
    port = _port_from_env()
    log.info("server_started", transport=transport, host=host, port=port, read_only=read_only)
    uvicorn.run(build_http_app(server, host=host), host=host, port=port, log_level=level.lower())


if __name__ == "__main__":
    main()
