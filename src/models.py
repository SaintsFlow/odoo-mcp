"""The shapes the agent reads.

Odoo sends a link to another record as `[id, "name"]`, and `False` when the link
is empty. Neither reaches the agent: a link becomes a number and a name, an
empty one becomes nothing at all. The same goes for the short codes Odoo uses
for states, which mean nothing to anyone who has not read the source.

Each model also owns the list of Odoo fields it is built from. Keeping the two
together is what stops a field from being read and then quietly dropped.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, Field

# "sale" is Odoo's word for an order that has been confirmed. No agent will
# guess that, so every state gets a word that says what it means.
ORDER_STATES = {
    "draft": "quotation",
    "sent": "quotation_sent",
    "sale": "confirmed",
    "cancel": "cancelled",
}

INVOICE_STATES = {"draft": "draft", "posted": "posted", "cancel": "cancelled"}

# The reverse direction, used when a tool takes a state as an argument. Built
# from the table above so the two can never drift apart.
INVOICE_STATES_TO_ODOO = {ours: theirs for theirs, ours in INVOICE_STATES.items()}

PAYMENT_STATES = {
    "not_paid": "not_paid",
    "in_payment": "in_payment",
    "paid": "paid",
    "partial": "partially_paid",
    "reversed": "reversed",
    "invoicing_legacy": "unknown",
}


def link_id(value: Any) -> int | None:
    """The number out of an Odoo link, or nothing if the link is empty."""
    if isinstance(value, list) and value:
        return int(value[0])
    return None


def link_name(value: Any) -> str | None:
    """The name out of an Odoo link, or nothing if the link is empty."""
    if isinstance(value, list) and len(value) > 1:
        return str(value[1])
    return None


def text(value: Any) -> str | None:
    """An empty text field comes back as False, which is not a value."""
    return str(value) if value else None


def number(value: Any) -> float:
    """Odoo answers an empty numeric field with False as well."""
    return float(value) if value else 0.0


class Partner(BaseModel):
    """A customer or a supplier."""

    id: int
    name: str
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    vat: str | None = Field(default=None, description="VAT identification number")
    is_customer: bool = Field(default=False, description="This partner buys from us")
    is_supplier: bool = Field(default=False, description="This partner sells to us")

    ODOO_FIELDS: ClassVar[list[str]] = [
        "name",
        "email",
        "phone",
        "city",
        "country_id",
        "vat",
        "customer_rank",
        "supplier_rank",
    ]

    @classmethod
    def from_odoo(cls, record: dict[str, Any]) -> "Partner":
        return cls(
            id=int(record["id"]),
            name=str(record.get("name") or ""),
            email=text(record.get("email")),
            phone=text(record.get("phone")),
            city=text(record.get("city")),
            country=link_name(record.get("country_id")),
            vat=text(record.get("vat")),
            # Odoo counts how often a partner played each role. Anything above
            # zero is a yes, and the count itself is of no use to the agent.
            is_customer=bool(record.get("customer_rank") or 0),
            is_supplier=bool(record.get("supplier_rank") or 0),
        )


class OrderLine(BaseModel):
    """One product on a sales order."""

    product: str
    quantity: float
    unit: str | None = Field(default=None, description="Unit the quantity is counted in")
    unit_price: float
    subtotal: float = Field(description="Line total before tax")

    ODOO_FIELDS: ClassVar[list[str]] = [
        "product_id",
        "name",
        "product_uom_qty",
        "product_uom",
        "price_unit",
        "price_subtotal",
    ]

    @classmethod
    def from_odoo(cls, record: dict[str, Any]) -> "OrderLine":
        return cls(
            product=link_name(record.get("product_id")) or str(record.get("name") or ""),
            quantity=number(record.get("product_uom_qty")),
            unit=link_name(record.get("product_uom")),
            unit_price=number(record.get("price_unit")),
            subtotal=number(record.get("price_subtotal")),
        )


class SalesOrder(BaseModel):
    """A sales order with its lines."""

    id: int
    number: str
    partner_id: int
    partner_name: str
    state: str = Field(description="quotation, quotation_sent, confirmed or cancelled")
    ordered_on: str | None = None
    untaxed_total: float
    total: float = Field(description="Total including tax")
    currency: str
    lines: list[OrderLine]

    ODOO_FIELDS: ClassVar[list[str]] = [
        "name",
        "partner_id",
        "state",
        "date_order",
        "amount_untaxed",
        "amount_total",
        "currency_id",
    ]

    @classmethod
    def from_odoo(cls, record: dict[str, Any], lines: list[OrderLine]) -> "SalesOrder":
        raw_state = str(record.get("state") or "")
        return cls(
            id=int(record["id"]),
            number=str(record.get("name") or ""),
            partner_id=link_id(record.get("partner_id")) or 0,
            partner_name=link_name(record.get("partner_id")) or "",
            state=ORDER_STATES.get(raw_state, raw_state),
            ordered_on=text(record.get("date_order")),
            untaxed_total=number(record.get("amount_untaxed")),
            total=number(record.get("amount_total")),
            currency=link_name(record.get("currency_id")) or "",
            lines=lines,
        )


class StockLevel(BaseModel):
    """How much of a product sits in one place."""

    product: str
    warehouse: str | None = None
    location: str | None = None
    on_hand: float = Field(description="Physically in stock, reserved goods included")
    reserved: float = Field(description="Already promised to other orders")
    available: float = Field(description="On hand minus reserved, what can still be sold")

    ODOO_FIELDS: ClassVar[list[str]] = [
        "product_id",
        "location_id",
        "warehouse_id",
        "quantity",
        "reserved_quantity",
        "available_quantity",
    ]

    @classmethod
    def from_odoo(cls, record: dict[str, Any]) -> "StockLevel":
        return cls(
            product=link_name(record.get("product_id")) or "",
            warehouse=link_name(record.get("warehouse_id")),
            location=link_name(record.get("location_id")),
            on_hand=number(record.get("quantity")),
            reserved=number(record.get("reserved_quantity")),
            available=number(record.get("available_quantity")),
        )


class Invoice(BaseModel):
    """A customer invoice."""

    id: int
    number: str
    partner_id: int
    partner_name: str
    invoice_date: str | None = None
    due_date: str | None = None
    state: str = Field(description="draft, posted or cancelled")
    payment: str = Field(description="not_paid, partially_paid, in_payment, paid or reversed")
    total: float
    amount_due: float = Field(description="Still unpaid out of the total")
    currency: str

    ODOO_FIELDS: ClassVar[list[str]] = [
        "name",
        "partner_id",
        "invoice_date",
        "invoice_date_due",
        "state",
        "payment_state",
        "amount_total",
        "amount_residual",
        "currency_id",
    ]

    @classmethod
    def from_odoo(cls, record: dict[str, Any]) -> "Invoice":
        raw_state = str(record.get("state") or "")
        raw_payment = str(record.get("payment_state") or "")
        return cls(
            id=int(record["id"]),
            number=str(record.get("name") or ""),
            partner_id=link_id(record.get("partner_id")) or 0,
            partner_name=link_name(record.get("partner_id")) or "",
            invoice_date=text(record.get("invoice_date")),
            due_date=text(record.get("invoice_date_due")),
            state=INVOICE_STATES.get(raw_state, raw_state),
            payment=PAYMENT_STATES.get(raw_payment, raw_payment),
            total=number(record.get("amount_total")),
            amount_due=number(record.get("amount_residual")),
            currency=link_name(record.get("currency_id")) or "",
        )
