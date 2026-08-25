"""What is on the shelf for a product, and how much of it is still free."""

from mcp.server.mcpserver import MCPServer

from src.client import OdooClient
from src.errors import OdooValidationError
from src.models import Listing, StockLevel
from src.tools import LOOKS_ONLY, listing, readable_errors

MAX_LEVELS = 100


async def get_stock(client: OdooClient, product_query: str) -> Listing[StockLevel]:
    """Stock levels of the products matching a piece of text.

    Only real storage locations count. Odoo also keeps quantities in virtual
    places such as the supplier or the inventory loss account, and those are not
    goods anyone can sell.
    """
    wanted = product_query.strip()
    if not wanted:
        raise OdooValidationError("Say which product to look up, by name or by its code.")

    domain = [
        "&",
        ("location_id.usage", "=", "internal"),
        "|",
        ("product_id.name", "ilike", wanted),
        ("product_id.default_code", "ilike", wanted),
    ]
    found = await client.search_read(
        "stock.quant", domain, StockLevel.ODOO_FIELDS, limit=MAX_LEVELS
    )
    return listing(
        [StockLevel.from_odoo(record) for record in found.rows],
        found.truncated,
        "Name the product more exactly, or use its internal code.",
    )


def register(server: MCPServer, client: OdooClient) -> None:
    """Publish the stock tool on the server."""

    @server.tool(name="get_stock", annotations=LOOKS_ONLY)
    @readable_errors
    async def _get_stock(product_query: str) -> Listing[StockLevel]:
        """Look up how much of a product is in stock, per warehouse.

        The text is matched against the product name and its internal code. Each
        answer separates what is physically on hand from what is already
        reserved for other orders and from what can still be sold.
        """
        return await get_stock(client, product_query)
