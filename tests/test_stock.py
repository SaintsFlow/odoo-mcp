"""How much of a product is on the shelf, and how much of it is actually free."""

import pytest

from src.client import OdooClient
from src.errors import OdooValidationError
from src.tools.stock import get_stock
from tests.helpers import assert_reads_as_a_fact


async def test_stock_is_found_by_product_name(odoo_client: OdooClient) -> None:
    levels = await get_stock(odoo_client, "desk")
    assert levels
    assert all("desk" in level.product.lower() for level in levels)


async def test_a_level_names_its_warehouse(odoo_client: OdooClient) -> None:
    """A quantity without a place is not an answer in a company with two sites."""
    levels = await get_stock(odoo_client, "desk")
    assert any(level.warehouse for level in levels)


async def test_reserved_goods_are_not_counted_as_available(odoo_client: OdooClient) -> None:
    """On hand minus reserved is the number a salesperson can promise."""
    levels = await get_stock(odoo_client, "cabinet")
    assert levels
    for level in levels:
        assert level.available == pytest.approx(level.on_hand - level.reserved)


async def test_an_unknown_product_gives_an_empty_list(odoo_client: OdooClient) -> None:
    assert await get_stock(odoo_client, "no such product anywhere") == []


async def test_an_empty_query_is_refused(odoo_client: OdooClient) -> None:
    """An empty query would drag back the whole warehouse."""
    with pytest.raises(OdooValidationError):
        await get_stock(odoo_client, "   ")


async def test_the_answer_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    levels = await get_stock(odoo_client, "desk")
    assert_reads_as_a_fact([level.model_dump() for level in levels])
