"""Predictable data on top of the demo database.

The Odoo demo data is rich and a little random: two products share a name, the
quantities differ between builds. A demo and a test want something they can name
out loud, so this puts one customer, one product and a known quantity of it in
place. Running it again changes nothing, which is what makes it usable in a
loop.
"""

import asyncio
from typing import Any

import structlog
from pydantic import BaseModel

from src.client import OdooClient, OdooConfig
from src.errors import OdooApiError
from src.server import configure_logging

DEMO_PARTNER = "MCP Demo Customer"
DEMO_PARTNER_CITY = "Vienna"
DEMO_PRODUCT = "MCP Demo Desk"
DEMO_PRODUCT_CODE = "MCP-DESK"
DEMO_PRODUCT_PRICE = 499.0
DEMO_QUANTITY = 42.0


class Seeded(BaseModel):
    """What the seeding left behind, by id."""

    partner_id: int
    product_id: int
    quantity: float


async def seed(client: OdooClient) -> Seeded:
    """Put the demo customer, product and stock in place, once."""
    partner_id = await _partner(client)
    product_id = await _product(client)
    quantity = await _stock(client, product_id)

    structlog.get_logger().info(
        "demo_data_seeded", partner_id=partner_id, product_id=product_id, quantity=quantity
    )
    return Seeded(partner_id=partner_id, product_id=product_id, quantity=quantity)


async def _partner(client: OdooClient) -> int:
    """The customer the demo sells to."""
    found = await client.search_read("res.partner", [("name", "=", DEMO_PARTNER)], ["id"], limit=1)
    if found.rows:
        return int(found.rows[0]["id"])

    return await _created(
        client,
        "res.partner",
        {
            "name": DEMO_PARTNER,
            "city": DEMO_PARTNER_CITY,
            "email": "demo@example.com",
            # Anything above zero marks a partner as someone we sell to.
            "customer_rank": 1,
        },
    )


async def _product(client: OdooClient) -> int:
    """The product the demo orders, found by its code rather than its name.

    A name is not an identity in Odoo: the demo data alone carries two products
    called "Customizable Desk". The internal code is ours and stays unique.
    """
    found = await client.search_read(
        "product.product", [("default_code", "=", DEMO_PRODUCT_CODE)], ["id"], limit=1
    )
    if found.rows:
        return int(found.rows[0]["id"])

    return await _created(
        client,
        "product.product",
        {
            "name": DEMO_PRODUCT,
            "default_code": DEMO_PRODUCT_CODE,
            "list_price": DEMO_PRODUCT_PRICE,
            "sale_ok": True,
            # Only a storable product has stock to speak of. A consumable would
            # answer every stock question with nothing.
            "type": "product",
        },
    )


async def _stock(client: OdooClient, product_id: int) -> float:
    """Put the known quantity in a real warehouse location, not a virtual one."""
    location_id = await _internal_location(client)

    existing = await client.search_read(
        "stock.quant",
        [("product_id", "=", product_id), ("location_id", "=", location_id)],
        ["quantity"],
        limit=1,
    )
    if existing.rows:
        quant_id = int(existing.rows[0]["id"])
        if float(existing.rows[0].get("quantity") or 0) != DEMO_QUANTITY:
            await client.execute_kw(
                "stock.quant", "write", [[quant_id], {"quantity": DEMO_QUANTITY}]
            )
        return DEMO_QUANTITY

    await _created(
        client,
        "stock.quant",
        {"product_id": product_id, "location_id": location_id, "quantity": DEMO_QUANTITY},
    )
    return DEMO_QUANTITY


async def _internal_location(client: OdooClient) -> int:
    """A location goods can actually be sold out of."""
    found = await client.search_read(
        "stock.location", [("usage", "=", "internal")], ["complete_name"], limit=1
    )
    if not found.rows:
        raise OdooApiError("This Odoo has no internal stock location to put the demo goods in.")
    return int(found.rows[0]["id"])


async def _created(client: OdooClient, model: str, values: dict[str, Any]) -> int:
    """Create one record and hand back its id, or say Odoo answered oddly."""
    created = await client.execute_kw(model, "create", [values])
    if isinstance(created, bool) or not isinstance(created, int):
        raise OdooApiError(f"Odoo did not say which {model} record it created.")
    return created


def main() -> None:
    """Run the seeding from the command line: make seed."""
    configure_logging()
    asyncio.run(seed(OdooClient(OdooConfig.from_env())))


if __name__ == "__main__":
    main()
