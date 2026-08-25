"""The predictable data a demo and a test can count on."""

from src.client import OdooClient
from src.seed import DEMO_PARTNER, DEMO_PRODUCT, DEMO_PRODUCT_CODE, DEMO_QUANTITY, seed
from src.tools.partners import search_partners
from src.tools.stock import get_stock


async def _how_many(client: OdooClient, model: str, domain: list[object]) -> int:
    count = await client.execute_kw(model, "search_count", [domain])
    return int(count)


async def test_seeding_puts_the_demo_data_in_place(odoo_client: OdooClient) -> None:
    planted = await seed(odoo_client)
    assert planted.partner_id > 0
    assert planted.product_id > 0

    found = await search_partners(odoo_client, DEMO_PARTNER)
    assert any(partner.name == DEMO_PARTNER for partner in found.items)

    levels = await get_stock(odoo_client, DEMO_PRODUCT_CODE)
    assert levels.items
    assert sum(level.on_hand for level in levels.items) >= DEMO_QUANTITY


async def test_seeding_twice_changes_nothing(odoo_client: OdooClient) -> None:
    """A demo that doubles its own data every run is worse than no demo."""
    first = await seed(odoo_client)
    partners_after_first = await _how_many(
        odoo_client, "res.partner", [("name", "=", DEMO_PARTNER)]
    )
    products_after_first = await _how_many(
        odoo_client, "product.product", [("default_code", "=", DEMO_PRODUCT_CODE)]
    )

    second = await seed(odoo_client)

    assert second.partner_id == first.partner_id
    assert second.product_id == first.product_id
    assert (
        await _how_many(odoo_client, "res.partner", [("name", "=", DEMO_PARTNER)])
        == partners_after_first
    )
    assert (
        await _how_many(odoo_client, "product.product", [("default_code", "=", DEMO_PRODUCT_CODE)])
        == products_after_first
    )


async def test_the_seeded_product_is_sellable(odoo_client: OdooClient) -> None:
    """An order line needs a product that may be sold, or Odoo refuses the order."""
    planted = await seed(odoo_client)
    rows = await odoo_client.search_read(
        "product.product", [("id", "=", planted.product_id)], ["name", "sale_ok"]
    )
    assert rows.rows
    assert rows.rows[0]["sale_ok"] is True
    assert rows.rows[0]["name"] == DEMO_PRODUCT


async def test_the_seeded_stock_is_available_to_sell(odoo_client: OdooClient) -> None:
    """Stock in a virtual location is not stock anyone can promise to a customer."""
    await seed(odoo_client)
    levels = await get_stock(odoo_client, DEMO_PRODUCT_CODE)
    assert levels.items
    assert any(level.available > 0 for level in levels.items)
