"""Finding people and companies by what the agent actually knows about them."""

import pytest

from src.client import OdooClient
from src.errors import OdooValidationError
from src.tools.partners import search_partners
from tests.helpers import assert_reads_as_a_fact


async def test_a_partner_is_found_by_name(odoo_client: OdooClient) -> None:
    found = await search_partners(odoo_client, "azure")
    assert any(partner.name == "Azure Interior" for partner in found)


async def test_the_search_is_case_insensitive(odoo_client: OdooClient) -> None:
    """Nobody types the case a database happens to store."""
    assert await search_partners(odoo_client, "AZURE")


async def test_a_partner_is_found_by_email(odoo_client: OdooClient) -> None:
    """The agent often has an address and nothing else."""
    assert await search_partners(odoo_client, "azure.Interior24@example.com")


async def test_a_partner_is_found_by_city(odoo_client: OdooClient) -> None:
    assert await search_partners(odoo_client, "Fremont")


async def test_nothing_found_is_an_empty_list_and_not_an_error(odoo_client: OdooClient) -> None:
    """An empty answer is a fact about the database, not a failure."""
    assert await search_partners(odoo_client, "no such partner anywhere") == []


async def test_the_limit_holds(odoo_client: OdooClient) -> None:
    assert len(await search_partners(odoo_client, "a", limit=3)) <= 3


async def test_a_meaningless_limit_is_refused(odoo_client: OdooClient) -> None:
    """Zero or a negative limit is a mistake worth naming, not a silent empty list."""
    with pytest.raises(OdooValidationError):
        await search_partners(odoo_client, "azure", limit=0)


async def test_the_answer_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    found = await search_partners(odoo_client, "azure")
    assert_reads_as_a_fact([partner.model_dump() for partner in found])
