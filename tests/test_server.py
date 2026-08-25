"""What a client sees the moment it connects: the name, the version, the tools."""

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import SecretStr
from starlette.testclient import TestClient

from src.client import OdooClient, OdooConfig
from src.errors import OdooError
from src.server import (
    SERVER_NAME,
    build_http_app,
    build_server,
    configure_logging,
    read_only_from_env,
    transport_from_env,
)

READ_TOOLS = {"search_partners", "get_sales_order", "get_stock", "list_invoices"}
WRITE_TOOLS = {"create_sales_order", "confirm_sales_order"}


def _offline_server(read_only: bool = False) -> MCPServer:
    """A server built against a client that is never called.

    Listing tools touches no network, so these tests need no Odoo.
    """
    config = OdooConfig(
        url="http://odoo.invalid", db="odoo", user="admin", password=SecretStr("unused")
    )
    return build_server(OdooClient(config), read_only=read_only)


async def test_read_only_leaves_the_write_tools_unpublished() -> None:
    """Pointed at a real database, the server should not even offer to write."""
    tools = await _offline_server(read_only=True).list_tools()
    assert {tool.name for tool in tools} == READ_TOOLS


async def test_a_write_tool_is_not_callable_in_read_only_mode() -> None:
    """Unpublished means gone, not "refuses politely when called"."""
    with pytest.raises(ToolError) as caught:
        await _offline_server(read_only=True).call_tool(
            "create_sales_order",
            {"partner_id": 1, "lines": [{"product_id": 1, "quantity": 1}]},
        )
    assert "create_sales_order" in str(caught.value)


def test_the_transport_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """stdio unless asked otherwise, and a typo is not silently one of them."""
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    assert transport_from_env() == "stdio"

    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    assert transport_from_env() == "stdio"

    for asked in ("http", "HTTP", "streamable-http"):
        monkeypatch.setenv("MCP_TRANSPORT", asked)
        assert transport_from_env() == "streamable-http", f"{asked!r} should mean http"

    monkeypatch.setenv("MCP_TRANSPORT", "carrier pigeon")
    with pytest.raises(OdooError) as caught:
        transport_from_env()
    assert "carrier pigeon" in caught.value.message
    assert "stdio" in caught.value.message


def test_health_answers_without_touching_odoo() -> None:
    """The compose healthcheck lives on this, so it must not depend on Odoo.

    The client here points at a host that does not exist. A health check that
    talked to Odoo would hang or fail; this one answers.
    """
    app = build_http_app(_offline_server())
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["server"] == SERVER_NAME
    assert body["transport"] == "streamable-http"
    assert body["version"]


def test_the_mcp_endpoint_is_still_there_next_to_health() -> None:
    """Adding our own route must not push the transport off its path."""
    paths = {getattr(route, "path", None) for route in build_http_app(_offline_server()).routes}
    assert "/health" in paths
    assert "/mcp" in paths


def test_read_only_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whoever runs this against production sets one variable and is done."""
    monkeypatch.delenv("ODOO_READONLY", raising=False)
    assert read_only_from_env() is False

    for yes in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("ODOO_READONLY", yes)
        assert read_only_from_env() is True, f"{yes!r} should turn read-only on"

    for no in ("false", "0", "no", "", "off"):
        monkeypatch.setenv("ODOO_READONLY", no)
        assert read_only_from_env() is False, f"{no!r} should leave writing on"


async def test_the_read_and_write_tools_are_published() -> None:
    """Four tools that only look, two that change something."""
    tools = await _offline_server().list_tools()
    assert {tool.name for tool in tools} == READ_TOOLS | WRITE_TOOLS


async def _annotations_by_tool() -> dict[str, ToolAnnotations]:
    """Annotations of every published tool, keyed by name.

    A tool that is not published is missing from here, and the test that asks
    for it fails on the lookup instead of quietly checking nothing.
    """
    published = {}
    for tool in await _offline_server().list_tools():
        assert tool.annotations is not None, f"{tool.name} carries no annotations"
        published[tool.name] = tool.annotations
    return published


async def test_the_write_tools_are_marked_destructive() -> None:
    """A client that asks before changing anything has to know which tools change it."""
    published = await _annotations_by_tool()
    for name in WRITE_TOOLS:
        assert published[name].destructive_hint is True
        assert published[name].read_only_hint is False


async def test_the_read_tools_are_marked_read_only() -> None:
    """Without this the destructive mark on the other two says nothing.

    MCP treats a tool with no annotations as destructive by default, so leaving
    the read tools bare would put all six in the same bucket.
    """
    published = await _annotations_by_tool()
    for name in READ_TOOLS:
        assert published[name].read_only_hint is True


async def test_every_tool_explains_itself() -> None:
    """A tool with no description makes the agent guess what it does."""
    for tool in await _offline_server().list_tools():
        assert tool.description
        assert tool.input_schema["type"] == "object"


async def test_the_tools_ask_for_meaningful_arguments() -> None:
    """No domains, no model names, no Odoo field names in the arguments."""
    arguments = {
        tool.name: set(tool.input_schema.get("properties", {}))
        for tool in await _offline_server().list_tools()
    }
    assert arguments["search_partners"] == {"query", "limit"}
    assert arguments["get_sales_order"] == {"order_id"}
    assert arguments["get_stock"] == {"product_query"}
    assert arguments["list_invoices"] == {"partner_id", "state"}
    assert arguments["create_sales_order"] == {"partner_id", "lines"}
    assert arguments["confirm_sales_order"] == {"order_id"}


async def test_a_refusal_reaches_the_agent_with_its_reason() -> None:
    """An error the SDK does not recognise arrives as "Error executing tool".

    That is the right default for a stray exception and useless for a message
    written on purpose. This state is rejected before Odoo is called, so the
    check needs no stand.
    """
    with pytest.raises(ToolError) as caught:
        await _offline_server().call_tool("list_invoices", {"partner_id": 1, "state": "paid-ish"})
    assert "paid-ish" in str(caught.value)
    assert "posted" in str(caught.value)


def test_server_name_is_stable() -> None:
    """Clients pick the server by this name, so it should not drift."""
    assert _offline_server().name == SERVER_NAME


def test_server_reports_a_version() -> None:
    """An empty version in the handshake tells the client nothing."""
    assert _offline_server().version not in (None, "", "0.0.0")


def test_logging_accepts_an_unknown_level() -> None:
    """A typo in LOG_LEVEL must not take the server down on start."""
    configure_logging("not-a-level")
