"""Checks shared by the tool tests."""

from typing import Any

# Field names that only make sense inside Odoo. If one of them reaches an
# answer, the tool handed the agent a piece of the ERP instead of a fact.
ODOO_ONLY_KEYS = frozenset(
    {
        "country_id",
        "currency_id",
        "company_id",
        "product_uom",
        "product_uom_qty",
        "amount_untaxed",
        "amount_residual",
        "move_type",
        "customer_rank",
        "supplier_rank",
        "order_line",
        "location_id",
        "warehouse_id",
        "invoice_date_due",
        "payment_state",
    }
)


def walk(value: Any, path: str = "") -> list[tuple[str, Any]]:
    """Every node of a dumped answer, with the path that leads to it."""
    found = [(path, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(walk(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(walk(item, f"{path}[{index}]"))
    return found


def assert_reads_as_a_fact(answer: Any) -> None:
    """No Odoo internals anywhere in what the agent gets.

    Two things are looked for: a link left as the [id, "name"] pair Odoo sends,
    and a key that is an Odoo field name rather than a word a person would use.
    """
    for path, node in walk(answer):
        if isinstance(node, list) and len(node) == 2:
            first, second = node
            assert not (isinstance(first, int) and isinstance(second, str)), (
                f"{path} is still an Odoo link: {node!r}"
            )
        if isinstance(node, dict):
            leaked = ODOO_ONLY_KEYS & set(node)
            assert not leaked, f"{path} carries Odoo field names: {sorted(leaked)}"
