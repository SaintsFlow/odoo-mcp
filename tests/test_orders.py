"""Reading one sales order, writing a new one, and confirming it."""

import pytest

from src.client import OdooClient
from src.errors import OdooValidationError
from src.models import OrderLineInput
from src.tools.orders import confirm_sales_order, create_sales_order, get_sales_order
from tests.helpers import assert_reads_as_a_fact

MISSING_ID = 999999


async def _a_demo_order_id(client: OdooClient) -> int:
    """The oldest order in the database, which is one that came with the demo.

    Odoo sorts sale.order newest first, so asking for "one order" hands back
    whatever was written last: an order some other test in this file created a
    second ago, quantities and all. The read tests are about the demo data.
    """
    orders = await client.search_read("sale.order", [], ["id"])
    assert orders.rows, "the demo data should carry sales orders"
    return min(int(order["id"]) for order in orders.rows)


async def _a_customer_id(client: OdooClient) -> int:
    partners = await client.search_read("res.partner", [("customer_rank", ">", 0)], ["id"], limit=1)
    assert partners.rows, "the demo data should carry customers"
    return int(partners.rows[0]["id"])


async def _a_product_id(client: OdooClient) -> int:
    products = await client.search_read(
        "product.product", [("sale_ok", "=", True)], ["id"], limit=1
    )
    assert products.rows, "the demo data should carry sellable products"
    return int(products.rows[0]["id"])


async def _how_many_orders(client: OdooClient) -> int:
    """Used to prove a refused call wrote nothing."""
    count = await client.execute_kw("sale.order", "search_count", [[]])
    return int(count)


async def _a_fresh_draft(client: OdooClient, quantity: float = 3) -> tuple[int, int]:
    """A draft order to work on, plus the product it was built from."""
    product_id = await _a_product_id(client)
    order = await create_sales_order(
        client,
        await _a_customer_id(client),
        [OrderLineInput(product_id=product_id, quantity=quantity)],
    )
    return order.id, product_id


async def test_an_order_comes_back_whole(odoo_client: OdooClient) -> None:
    order = await get_sales_order(odoo_client, await _a_demo_order_id(odoo_client))
    assert order.number
    assert order.partner_name
    assert order.partner_id > 0
    assert order.currency
    assert order.state in {"quotation", "quotation_sent", "confirmed", "cancelled"}


async def test_the_lines_of_the_order_are_there(odoo_client: OdooClient) -> None:
    """An order without its lines answers nothing an agent would ask."""
    order = await get_sales_order(odoo_client, await _a_demo_order_id(odoo_client))
    assert order.lines
    first = order.lines[0]
    assert first.product
    assert first.quantity > 0
    assert first.subtotal >= 0


async def test_a_missing_order_says_so(odoo_client: OdooClient) -> None:
    """Odoo answers a missing id with an empty list, so the tool has to speak up."""
    with pytest.raises(OdooValidationError) as caught:
        await get_sales_order(odoo_client, MISSING_ID)
    assert str(MISSING_ID) in caught.value.message


async def test_the_answer_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    order = await get_sales_order(odoo_client, await _a_demo_order_id(odoo_client))
    assert_reads_as_a_fact(order.model_dump())


async def test_a_created_order_comes_back_whole(odoo_client: OdooClient) -> None:
    """Creating and then reading it back in one call is the point of the tool."""
    product_id = await _a_product_id(odoo_client)
    order = await create_sales_order(
        odoo_client,
        await _a_customer_id(odoo_client),
        [OrderLineInput(product_id=product_id, quantity=3)],
    )
    assert order.id > 0
    assert order.number
    assert order.partner_name
    assert order.state == "quotation"
    assert order.currency
    assert len(order.lines) == 1
    assert order.lines[0].quantity == 3
    assert order.lines[0].product


async def test_a_created_order_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    product_id = await _a_product_id(odoo_client)
    order = await create_sales_order(
        odoo_client,
        await _a_customer_id(odoo_client),
        [OrderLineInput(product_id=product_id, quantity=1)],
    )
    assert_reads_as_a_fact(order.model_dump())


async def test_a_missing_partner_is_refused_before_anything_is_written(
    odoo_client: OdooClient,
) -> None:
    """Odoo would take the call and answer with res.partner(999999,) in the text."""
    product_id = await _a_product_id(odoo_client)
    before = await _how_many_orders(odoo_client)

    with pytest.raises(OdooValidationError) as caught:
        await create_sales_order(
            odoo_client, MISSING_ID, [OrderLineInput(product_id=product_id, quantity=1)]
        )

    assert str(MISSING_ID) in caught.value.message
    assert await _how_many_orders(odoo_client) == before


async def test_a_missing_product_is_refused_before_anything_is_written(
    odoo_client: OdooClient,
) -> None:
    partner_id = await _a_customer_id(odoo_client)
    before = await _how_many_orders(odoo_client)

    with pytest.raises(OdooValidationError) as caught:
        await create_sales_order(
            odoo_client, partner_id, [OrderLineInput(product_id=MISSING_ID, quantity=1)]
        )

    assert str(MISSING_ID) in caught.value.message
    assert await _how_many_orders(odoo_client) == before


async def test_a_quantity_of_zero_is_refused(odoo_client: OdooClient) -> None:
    """Odoo creates such an order without a word, measured on the stand."""
    partner_id = await _a_customer_id(odoo_client)
    product_id = await _a_product_id(odoo_client)
    before = await _how_many_orders(odoo_client)

    with pytest.raises(OdooValidationError):
        await create_sales_order(
            odoo_client, partner_id, [OrderLineInput(product_id=product_id, quantity=0)]
        )

    assert await _how_many_orders(odoo_client) == before


async def test_an_order_without_lines_is_refused(odoo_client: OdooClient) -> None:
    partner_id = await _a_customer_id(odoo_client)
    before = await _how_many_orders(odoo_client)

    with pytest.raises(OdooValidationError):
        await create_sales_order(odoo_client, partner_id, [])

    assert await _how_many_orders(odoo_client) == before


async def test_a_refusal_names_no_odoo_models(odoo_client: OdooClient) -> None:
    """Odoo's own wording here is "Record ... (Record: res.partner(999999,), User: 2)"."""
    product_id = await _a_product_id(odoo_client)
    with pytest.raises(OdooValidationError) as caught:
        await create_sales_order(
            odoo_client, MISSING_ID, [OrderLineInput(product_id=product_id, quantity=1)]
        )

    message = caught.value.message
    for leak in ("res.partner", "product.product", "Record"):
        assert leak not in message, f"the refusal leaks Odoo internals: {message}"


async def test_a_draft_order_gets_confirmed(odoo_client: OdooClient) -> None:
    order_id, _ = await _a_fresh_draft(odoo_client)
    confirmed = await confirm_sales_order(odoo_client, order_id)
    assert confirmed.id == order_id
    assert confirmed.state == "confirmed"
    assert confirmed.lines


async def test_confirming_twice_says_the_state_in_plain_words(odoo_client: OdooClient) -> None:
    """Odoo refuses this itself, but never says what state the order is in."""
    order_id, _ = await _a_fresh_draft(odoo_client)
    await confirm_sales_order(odoo_client, order_id)

    with pytest.raises(OdooValidationError) as caught:
        await confirm_sales_order(odoo_client, order_id)

    assert "confirmed" in caught.value.message
    assert "sale" not in caught.value.message


async def test_confirming_a_missing_order_says_so(odoo_client: OdooClient) -> None:
    with pytest.raises(OdooValidationError) as caught:
        await confirm_sales_order(odoo_client, MISSING_ID)
    assert str(MISSING_ID) in caught.value.message
