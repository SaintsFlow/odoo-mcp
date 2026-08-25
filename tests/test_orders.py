"""Reading one sales order with everything a person would ask about it."""

import pytest

from src.client import OdooClient
from src.errors import OdooValidationError
from src.tools.orders import get_sales_order
from tests.helpers import assert_reads_as_a_fact


async def _any_order_id(client: OdooClient) -> int:
    orders = await client.search_read("sale.order", [], ["id"], limit=1)
    assert orders, "the demo data should carry sales orders"
    return int(orders[0]["id"])


async def test_an_order_comes_back_whole(odoo_client: OdooClient) -> None:
    order = await get_sales_order(odoo_client, await _any_order_id(odoo_client))
    assert order.number
    assert order.partner_name
    assert order.partner_id > 0
    assert order.currency
    assert order.state in {"quotation", "quotation_sent", "confirmed", "cancelled"}


async def test_the_lines_of_the_order_are_there(odoo_client: OdooClient) -> None:
    """An order without its lines answers nothing an agent would ask."""
    order = await get_sales_order(odoo_client, await _any_order_id(odoo_client))
    assert order.lines
    first = order.lines[0]
    assert first.product
    assert first.quantity > 0
    assert first.subtotal >= 0


async def test_a_missing_order_says_so(odoo_client: OdooClient) -> None:
    """Odoo answers a missing id with an empty list, so the tool has to speak up."""
    with pytest.raises(OdooValidationError) as caught:
        await get_sales_order(odoo_client, 999999)
    assert "999999" in caught.value.message


async def test_the_answer_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    order = await get_sales_order(odoo_client, await _any_order_id(odoo_client))
    assert_reads_as_a_fact(order.model_dump())
