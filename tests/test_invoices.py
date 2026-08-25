"""Invoices of one partner, and only from the company the server is pinned to."""

import pytest

from src.client import OdooClient
from src.errors import OdooValidationError
from src.tools.invoices import list_invoices
from tests.helpers import assert_reads_as_a_fact


async def _partner_with_invoices(client: OdooClient) -> int:
    partners = await client.search_read("res.partner", [("name", "=", "Acme Corporation")], ["id"])
    assert partners, "the demo data should carry Acme Corporation"
    return int(partners[0]["id"])


async def test_the_invoices_of_a_partner_come_back(odoo_client: OdooClient) -> None:
    invoices = await list_invoices(odoo_client, await _partner_with_invoices(odoo_client))
    assert invoices
    first = invoices[0]
    assert first.number
    assert first.total > 0
    assert first.currency


async def test_only_one_company_answers(odoo_client: OdooClient) -> None:
    """Three companies share the demo, and two of them invoice the same partner.

    Without a pinned company the agent would get two invoices with the same
    number, different amounts and different currencies.
    """
    invoices = await list_invoices(odoo_client, await _partner_with_invoices(odoo_client))
    assert len({invoice.currency for invoice in invoices}) == 1
    assert len({invoice.number for invoice in invoices}) == len(invoices)


async def test_the_state_filter_works(odoo_client: OdooClient) -> None:
    partner_id = await _partner_with_invoices(odoo_client)
    posted = await list_invoices(odoo_client, partner_id, state="posted")
    assert posted
    assert all(invoice.state == "posted" for invoice in posted)


async def test_an_unknown_state_is_refused_before_odoo_is_called(
    odoo_client: OdooClient,
) -> None:
    """The message has to say what is allowed, otherwise the agent guesses again."""
    with pytest.raises(OdooValidationError) as caught:
        await list_invoices(odoo_client, 1, state="paid-ish")
    assert "posted" in caught.value.message


async def test_a_partner_without_invoices_gives_an_empty_list(odoo_client: OdooClient) -> None:
    assert await list_invoices(odoo_client, 999999) == []


async def test_the_answer_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    invoices = await list_invoices(odoo_client, await _partner_with_invoices(odoo_client))
    assert_reads_as_a_fact([invoice.model_dump() for invoice in invoices])
