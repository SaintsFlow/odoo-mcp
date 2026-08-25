"""Turning an Odoo record into something the agent can read.

Every record below is shaped the way a running Odoo 17 sends it, empty links
included: Odoo answers an unset link with False rather than with an empty list.
"""

from src.models import Invoice, OrderLine, Partner, SalesOrder, StockLevel, link_id, link_name

PARTNER_RECORD = {
    "id": 14,
    "name": "Azure Interior",
    "email": "azure.Interior24@example.com",
    "phone": "(870)-931-0505",
    "city": "Fremont",
    "country_id": [233, "United States"],
    "vat": "US12345677",
    "customer_rank": 6,
    "supplier_rank": 8,
}

ORDER_RECORD = {
    "id": 23,
    "name": "S00023",
    "partner_id": [11, "Gemini Furniture"],
    "state": "sale",
    "date_order": "2026-08-25 08:57:17",
    "amount_untaxed": 4350.0,
    "amount_total": 5002.5,
    "currency_id": [1, "USD"],
    "company_id": [1, "My Company (San Francisco)"],
}

LINE_RECORD = {
    "product_id": [16, "[E-COM06] Corner Desk Right Sit"],
    "name": "[E-COM06] Corner Desk Right Sit",
    "product_uom_qty": 10.0,
    "product_uom": [1, "Units"],
    "price_unit": 199.0,
    "price_subtotal": 1990.0,
}

QUANT_RECORD = {
    "product_id": [17, "[E-COM07] Large Cabinet"],
    "location_id": [8, "WH/Stock"],
    "warehouse_id": [1, "YourCompany"],
    "quantity": 500.0,
    "reserved_quantity": 230.0,
    "available_quantity": 270.0,
}

INVOICE_RECORD = {
    "id": 26,
    "name": "INV/2026/00002",
    "partner_id": [10, "Acme Corporation"],
    "invoice_date": "2026-08-23",
    "invoice_date_due": "2026-08-25",
    "state": "posted",
    "payment_state": "not_paid",
    "amount_total": 41750.0,
    "amount_residual": 41750.0,
    "currency_id": [126, "EUR"],
    "company_id": [3, "AT Company"],
}


def test_a_link_splits_into_a_number_and_a_name() -> None:
    """The whole point of the mapper: [id, "name"] is two facts, not a list."""
    assert link_id([11, "Gemini Furniture"]) == 11
    assert link_name([11, "Gemini Furniture"]) == "Gemini Furniture"


def test_an_empty_link_is_not_a_crash() -> None:
    """Odoo sends False for an unset link, and partners really do have it."""
    assert link_id(False) is None
    assert link_name(False) is None
    assert link_id([]) is None
    assert link_name([]) is None


def test_partner_reads_as_a_person_would_say_it() -> None:
    partner = Partner.from_odoo(PARTNER_RECORD)
    assert partner.name == "Azure Interior"
    assert partner.country == "United States"
    assert partner.is_customer is True
    assert partner.is_supplier is True


def test_a_partner_without_contacts_keeps_empty_fields_empty() -> None:
    """Odoo answers a blank text field with False, which is not a phone number."""
    partner = Partner.from_odoo({"id": 1, "name": "Nobody"})
    assert partner.email is None
    assert partner.phone is None
    assert partner.country is None
    assert partner.is_customer is False


def test_order_state_stops_being_odoo_jargon() -> None:
    """ "sale" means a confirmed order, and no agent can guess that."""
    order = SalesOrder.from_odoo(ORDER_RECORD, lines=[])
    assert order.state == "confirmed"
    assert order.number == "S00023"
    assert order.partner_id == 11
    assert order.partner_name == "Gemini Furniture"
    assert order.currency == "USD"


def test_every_order_state_has_a_word() -> None:
    """A state we forgot to translate would reach the agent as noise."""
    said = {
        SalesOrder.from_odoo({**ORDER_RECORD, "state": raw}, lines=[]).state
        for raw in ("draft", "sent", "sale", "cancel")
    }
    assert said == {"quotation", "quotation_sent", "confirmed", "cancelled"}


def test_order_line_carries_quantity_with_its_unit() -> None:
    """A number without a unit is a guess."""
    line = OrderLine.from_odoo(LINE_RECORD)
    assert line.product == "[E-COM06] Corner Desk Right Sit"
    assert line.quantity == 10.0
    assert line.unit == "Units"
    assert line.subtotal == 1990.0


def test_stock_separates_on_hand_from_available() -> None:
    """Reserved goods are on the shelf and still not sellable."""
    level = StockLevel.from_odoo(QUANT_RECORD)
    assert level.on_hand == 500.0
    assert level.reserved == 230.0
    assert level.available == 270.0
    assert level.warehouse == "YourCompany"
    assert level.location == "WH/Stock"


def test_invoice_says_how_much_is_still_owed() -> None:
    invoice = Invoice.from_odoo(INVOICE_RECORD)
    assert invoice.number == "INV/2026/00002"
    assert invoice.partner_name == "Acme Corporation"
    assert invoice.state == "posted"
    assert invoice.payment == "not_paid"
    assert invoice.total == 41750.0
    assert invoice.amount_due == 41750.0
    assert invoice.currency == "EUR"


def test_a_record_says_which_company_it_came_from() -> None:
    """With several companies allowed, the same invoice number appears twice."""
    assert Invoice.from_odoo(INVOICE_RECORD).company == "AT Company"
    assert SalesOrder.from_odoo(ORDER_RECORD, lines=[]).company == "My Company (San Francisco)"


def test_an_unposted_invoice_has_no_dates() -> None:
    """A draft invoice carries False in both date fields."""
    invoice = Invoice.from_odoo(
        {**INVOICE_RECORD, "invoice_date": False, "invoice_date_due": False, "state": "draft"}
    )
    assert invoice.invoice_date is None
    assert invoice.due_date is None
    assert invoice.state == "draft"
