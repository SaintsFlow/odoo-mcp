"""What a client sees the moment it connects: the name, the version, the tools."""

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr

from src.client import OdooClient, OdooConfig
from src.server import SERVER_NAME, build_server, configure_logging

READ_TOOLS = {"search_partners", "get_sales_order", "get_stock", "list_invoices"}


def _offline_server() -> MCPServer:
    """A server built against a client that is never called.

    Listing tools touches no network, so these tests need no Odoo.
    """
    config = OdooConfig(
        url="http://odoo.invalid", db="odoo", user="admin", password=SecretStr("unused")
    )
    return build_server(OdooClient(config))


async def test_the_four_read_tools_are_published() -> None:
    """Wave 2 registers the read tools. The write ones arrive in wave 3."""
    tools = await _offline_server().list_tools()
    assert {tool.name for tool in tools} == READ_TOOLS


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
