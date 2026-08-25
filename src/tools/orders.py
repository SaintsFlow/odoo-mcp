"""Reading one sales order with everything a person would ask about it."""

from mcp.server.mcpserver import MCPServer

from src.client import OdooClient
from src.errors import OdooValidationError
from src.models import OrderLine, SalesOrder
from src.tools import readable_errors


async def get_sales_order(client: OdooClient, order_id: int) -> SalesOrder:
    """Read an order and its lines.

    Odoo answers a query for a record that is not there with an empty list and
    no error at all, so the missing case is spotted and named here.
    """
    records = await client.search_read(
        "sale.order", [("id", "=", order_id)], SalesOrder.ODOO_FIELDS, limit=1
    )
    if not records:
        raise OdooValidationError(f"There is no sales order with id {order_id}.")

    # An order can also hold section headers and notes. They carry no product
    # and would reach the agent as empty rows.
    lines = await client.search_read(
        "sale.order.line",
        [("order_id", "=", order_id), ("display_type", "=", False)],
        OrderLine.ODOO_FIELDS,
    )
    return SalesOrder.from_odoo(records[0], [OrderLine.from_odoo(line) for line in lines])


def register(server: MCPServer, client: OdooClient) -> None:
    """Publish the sales order tool on the server."""

    @server.tool(name="get_sales_order")
    @readable_errors
    async def _get_sales_order(order_id: int) -> SalesOrder:
        """Read one sales order: the customer, the state, the totals and the lines.

        The id is the internal number of the order, the one search results carry.
        Fails with a clear message when no such order exists.
        """
        return await get_sales_order(client, order_id)
