"""Sales orders: reading one, creating one, confirming one."""

from typing import Any

import structlog
from mcp.server.mcpserver import MCPServer

from src.client import OdooClient
from src.errors import OdooApiError, OdooValidationError
from src.models import OrderLine, OrderLineInput, SalesOrder
from src.tools import CHANGES_DATA, LOOKS_ONLY, readable_errors

# Odoo confirms a quotation whether or not it has been sent to the customer,
# and refuses everything else with "not in a state requiring confirmation",
# never naming the state it found. So the state is checked here and named.
CONFIRMABLE_STATES = ("quotation", "quotation_sent")


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


async def create_sales_order(
    client: OdooClient, partner_id: int, lines: list[OrderLineInput]
) -> SalesOrder:
    """Create a quotation for a partner and hand the whole order back.

    Everything is checked before the call that writes, and not out of caution.
    Odoo takes a line of zero without a word, and answers a bad id with
    "Record does not exist ... (Record: res.partner(999999,), User: 2)", which
    is both a piece of the ERP and no help to whoever asked.
    """
    _lines_have_to_make_sense(lines)
    await _partner_has_to_exist(client, partner_id)
    await _products_have_to_exist(client, lines)

    # A one2many is written with commands, and (0, 0, {...}) means "add a new
    # line built from these values".
    commands: list[tuple[int, int, dict[str, Any]]] = [
        (0, 0, {"product_id": line.product_id, "product_uom_qty": line.quantity}) for line in lines
    ]
    created = await client.execute_kw(
        "sale.order", "create", [{"partner_id": partner_id, "order_line": commands}]
    )
    if isinstance(created, bool) or not isinstance(created, int):
        raise OdooApiError("Odoo did not say which order it created.")

    order = await get_sales_order(client, created)
    # A write into someone's ERP is worth a line of its own in the log. The
    # generic call record underneath says a create happened, not what it was.
    structlog.get_logger().info(
        "sales_order_created",
        order_id=order.id,
        number=order.number,
        partner_id=partner_id,
        lines=len(lines),
        total=order.total,
    )
    return order


async def confirm_sales_order(client: OdooClient, order_id: int) -> SalesOrder:
    """Confirm a quotation and hand the order back as it stands afterwards."""
    order = await get_sales_order(client, order_id)
    if order.state not in CONFIRMABLE_STATES:
        raise OdooValidationError(
            f"Order {order.number} is {order.state}. Only a quotation can be confirmed."
        )

    await client.execute_kw("sale.order", "action_confirm", [[order_id]])

    # Odoo has neighbours of this method that answer with a dialog to open and
    # leave the record untouched, so the new state is read back rather than
    # assumed. A setup that routes orders elsewhere is the caller's business,
    # hence a line in the log and the order as it really is.
    confirmed = await get_sales_order(client, order_id)
    log = structlog.get_logger()
    if confirmed.state == "confirmed":
        log.info(
            "sales_order_confirmed",
            order_id=confirmed.id,
            number=confirmed.number,
            total=confirmed.total,
        )
    else:
        log.warning("order_did_not_confirm", order_id=order_id, state=confirmed.state)
    return confirmed


def _lines_have_to_make_sense(lines: list[OrderLineInput]) -> None:
    """The sense Odoo does not check: an empty order and a line of nothing."""
    if not lines:
        raise OdooValidationError(
            "An order needs at least one line: a product id and how many of it."
        )
    for line in lines:
        if line.quantity <= 0:
            raise OdooValidationError(
                f"Quantity has to be above zero, and product {line.product_id} "
                f"asks for {line.quantity:g}."
            )


async def _partner_has_to_exist(client: OdooClient, partner_id: int) -> None:
    """Refuse an unknown customer in words the agent can act on."""
    records = await client.search_read("res.partner", [("id", "=", partner_id)], ["name"], limit=1)
    if not records:
        raise OdooValidationError(
            f"There is no partner with id {partner_id}. search_partners finds the right one."
        )


async def _products_have_to_exist(client: OdooClient, lines: list[OrderLineInput]) -> None:
    """Same for the goods, and all of them are named at once rather than one per try."""
    wanted = {line.product_id for line in lines}
    records = await client.search_read("product.product", [("id", "in", sorted(wanted))], ["name"])
    missing = sorted(wanted - {int(record["id"]) for record in records})
    if missing:
        listed = ", ".join(str(one) for one in missing)
        subject = "product" if len(missing) == 1 else "products"
        raise OdooValidationError(
            f"There is no {subject} with id {listed}. get_stock reports the id of every "
            f"product it lists."
        )


def register(server: MCPServer, client: OdooClient) -> None:
    """Publish the sales order tools on the server."""

    @server.tool(name="get_sales_order", annotations=LOOKS_ONLY)
    @readable_errors
    async def _get_sales_order(order_id: int) -> SalesOrder:
        """Read one sales order: the customer, the state, the totals and the lines.

        The id is the internal number of the order, the one search results carry.
        Fails with a clear message when no such order exists.
        """
        return await get_sales_order(client, order_id)

    @server.tool(name="create_sales_order", annotations=CHANGES_DATA)
    @readable_errors
    async def _create_sales_order(partner_id: int, lines: list[OrderLineInput]) -> SalesOrder:
        """Create a new quotation for a customer.

        Each line is a product id and how many of it: search_partners gives the
        customer id, get_stock gives the product id. The order is created as a
        quotation and nothing is promised to the customer until
        confirm_sales_order is called on it. Answers with the whole order,
        its number included.
        """
        return await create_sales_order(client, partner_id, lines)

    @server.tool(name="confirm_sales_order", annotations=CHANGES_DATA)
    @readable_errors
    async def _confirm_sales_order(order_id: int) -> SalesOrder:
        """Turn a quotation into a confirmed sales order.

        This is the step that commits the sale: stock gets reserved and the
        order can be invoiced. Only a quotation can be confirmed, and the
        refusal says which state the order is in when it is anything else.
        Answers with the whole order.
        """
        return await confirm_sales_order(client, order_id)
