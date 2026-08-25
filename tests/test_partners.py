"""Finding people and companies by what the agent actually knows about them."""

import pytest

from src.client import OdooClient
from src.errors import OdooValidationError
from src.tools.partners import search_partners
from tests.helpers import assert_reads_as_a_fact


async def test_a_partner_is_found_by_name(odoo_client: OdooClient) -> None:
    found = await search_partners(odoo_client, "azure")
    assert any(partner.name == "Azure Interior" for partner in found.items)


async def test_the_search_is_case_insensitive(odoo_client: OdooClient) -> None:
    """Nobody types the case a database happens to store."""
    assert (await search_partners(odoo_client, "AZURE")).items


async def test_a_partner_is_found_by_email(odoo_client: OdooClient) -> None:
    """The agent often has an address and nothing else."""
    assert (await search_partners(odoo_client, "azure.Interior24@example.com")).items


async def test_a_partner_is_found_by_city(odoo_client: OdooClient) -> None:
    assert (await search_partners(odoo_client, "Fremont")).items


async def test_nothing_found_is_an_empty_answer_and_not_an_error(odoo_client: OdooClient) -> None:
    """An empty answer is a fact about the database, not a failure."""
    found = await search_partners(odoo_client, "no such partner anywhere")
    assert found.items == []
    assert found.truncated is False


async def test_the_limit_holds(odoo_client: OdooClient) -> None:
    assert len((await search_partners(odoo_client, "a", limit=3)).items) <= 3


async def test_a_cut_answer_says_so_and_says_what_to_do(odoo_client: OdooClient) -> None:
    """Three partners out of dozens look like the whole truth unless it is said."""
    found = await search_partners(odoo_client, "a", limit=3)
    assert len(found.items) == 3
    assert found.truncated is True
    assert found.hint
    assert "3" in found.hint


async def test_a_whole_answer_carries_no_hint(odoo_client: OdooClient) -> None:
    found = await search_partners(odoo_client, "azure")
    assert found.truncated is False
    assert found.hint is None


async def test_a_meaningless_limit_is_refused(odoo_client: OdooClient) -> None:
    """Zero or a negative limit is a mistake worth naming, not a silent empty list."""
    with pytest.raises(OdooValidationError):
        await search_partners(odoo_client, "azure", limit=0)


async def test_the_answer_carries_no_odoo_internals(odoo_client: OdooClient) -> None:
    found = await search_partners(odoo_client, "azure")
    assert_reads_as_a_fact(found.model_dump())
