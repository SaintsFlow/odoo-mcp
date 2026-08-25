"""Customer invoices of one partner."""

from mcp.server.mcpserver import MCPServer

from src.client import OdooClient
from src.errors import OdooValidationError
from src.models import INVOICE_STATES_TO_ODOO, Invoice
from src.tools import readable_errors

MAX_INVOICES = 100


async def list_invoices(
    client: OdooClient, partner_id: int, state: str | None = None
) -> list[Invoice]:
    """Invoices we sent to a partner, newest first.

    Vendor bills live in the same Odoo model and are deliberately left out: the
    question "what do they owe us" is not the question "what do we owe them".
    """
    domain: list[object] = [
        ("partner_id", "=", partner_id),
        ("move_type", "=", "out_invoice"),
    ]
    if state is not None:
        allowed = INVOICE_STATES_TO_ODOO.get(state)
        if allowed is None:
            known = ", ".join(sorted(INVOICE_STATES_TO_ODOO))
            raise OdooValidationError(f"Unknown state '{state}'. Use one of: {known}.")
        domain.append(("state", "=", allowed))

    records = await client.search_read(
        "account.move", domain, Invoice.ODOO_FIELDS, limit=MAX_INVOICES
    )
    return [Invoice.from_odoo(record) for record in records]


def register(server: MCPServer, client: OdooClient) -> None:
    """Publish the invoice tool on the server."""

    @server.tool(name="list_invoices")
    @readable_errors
    async def _list_invoices(partner_id: int, state: str | None = None) -> list[Invoice]:
        """List the invoices sent to one customer.

        The partner id is the one search results carry. The state is optional and
        can be draft, posted or cancelled. Every answer shows the total and how
        much of it is still unpaid.
        """
        return await list_invoices(client, partner_id, state)
