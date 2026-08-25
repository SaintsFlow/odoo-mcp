"""How a Fault from Odoo turns into an error the agent can read.

Every fault string below was captured from a running Odoo 17, so these tests
pin the real shapes rather than what the documentation promises. They need no
Odoo of their own, which is what keeps the parsing covered in CI.
"""

import xmlrpc.client

from src.errors import (
    MAX_MESSAGE_CHARS,
    OdooAccessError,
    OdooApiError,
    OdooAuthError,
    OdooValidationError,
    fault_message,
    translate_fault,
)

# Code 1: the whole server side traceback, the message sits in the last line.
UNKNOWN_METHOD = xmlrpc.client.Fault(
    1,
    "Traceback (most recent call last):\n"
    '  File "/usr/lib/python3/dist-packages/odoo/http.py", line 1810, in _serve_nodb\n'
    "    response = self.dispatcher.dispatch(rule.endpoint, args)\n"
    '  File "/usr/lib/python3/dist-packages/odoo/service/model.py", line 34, in execute\n'
    "    res = execute_cr(cr, uid, obj, method, *args, **kw)\n"
    "AttributeError: The method 'res.partner.no_such_method' does not exist\n",
)

# Code 1 again, this time the last line carries a dotted exception name.
UNKNOWN_DATABASE = xmlrpc.client.Fault(
    1,
    "Traceback (most recent call last):\n"
    '  File "/usr/lib/python3/dist-packages/odoo/sql_db.py", line 934, in connect\n'
    "    return Connection(db, pool)\n"
    'psycopg2.OperationalError: connection to server at "db" (172.19.0.2), port 5432 '
    'failed: FATAL:  database "no_such_db" does not exist\n',
)

# Code 2: a message written for a human, no traceback at all.
UNKNOWN_MODEL = xmlrpc.client.Fault(2, "Object no.such.model doesn't exist")

MISSING_REQUIRED_FIELD = xmlrpc.client.Fault(
    2,
    "The operation cannot be completed:\n"
    "- Create/update: a mandatory field is not set.\n"
    "- Delete: another model requires the record being deleted. If possible, "
    "archive it instead.\n\n"
    "Model: Sales Order (sale.order)\n"
    "Field: Customer (partner_id)\n",
)

MISSING_RECORD = xmlrpc.client.Fault(
    2,
    "Record does not exist or has been deleted.\n(Record: sale.order(999999,), User: 2)",
)

ACCESS_DENIED = xmlrpc.client.Fault(3, "Access Denied")

NO_ACCESS_RIGHTS = xmlrpc.client.Fault(
    4,
    "You are not allowed to access 'System Parameter' (ir.config_parameter) records.\n\n"
    "This operation is allowed for the following groups:\n"
    "\t- Settings/Administration\n"
    "Contact your administrator to request access if necessary.",
)


def test_traceback_shrinks_to_its_last_line() -> None:
    """A 40 line traceback is noise to the agent, the last line is the answer."""
    message = fault_message(UNKNOWN_METHOD)
    assert message == "The method 'res.partner.no_such_method' does not exist"
    assert "Traceback" not in message


def test_dotted_exception_name_is_stripped() -> None:
    """The class name of a server side exception tells the agent nothing."""
    message = fault_message(UNKNOWN_DATABASE)
    assert message.startswith("connection to server at")
    assert 'database "no_such_db" does not exist' in message


def test_a_human_message_keeps_all_of_its_lines() -> None:
    """Codes 2, 3 and 4 carry ready text, and its last line is only the tail.

    Taking the last line here would hand the agent "Field: Customer" and drop
    the sentence that explains what went wrong.
    """
    message = fault_message(MISSING_REQUIRED_FIELD)
    assert message.startswith("The operation cannot be completed:")
    assert "mandatory field is not set" in message
    assert "Field: Customer (partner_id)" in message
    assert "\n" not in message


def test_a_missing_record_keeps_its_first_line() -> None:
    """Here the useful sentence is the first one, not the last."""
    assert fault_message(MISSING_RECORD).startswith("Record does not exist")


def test_a_long_message_gets_cut() -> None:
    """Nothing unbounded reaches the agent."""
    message = fault_message(xmlrpc.client.Fault(2, "x" * 5000))
    assert len(message) <= MAX_MESSAGE_CHARS
    assert message.endswith("...")


def test_an_empty_fault_still_says_something() -> None:
    """An error with no text would leave the agent guessing."""
    assert fault_message(xmlrpc.client.Fault(1, "")) != ""


def test_access_denied_is_an_auth_error() -> None:
    """A wrong password inside a call, not a rights problem."""
    assert isinstance(translate_fault(ACCESS_DENIED), OdooAuthError)


def test_missing_rights_is_an_access_error() -> None:
    """The login worked, the user is simply not allowed to look."""
    error = translate_fault(NO_ACCESS_RIGHTS)
    assert isinstance(error, OdooAccessError)
    assert "not allowed to access" in error.message


def test_application_error_is_a_validation_error() -> None:
    """Odoo said no to the data, which the agent can act on."""
    assert isinstance(translate_fault(MISSING_REQUIRED_FIELD), OdooValidationError)
    assert isinstance(translate_fault(MISSING_RECORD), OdooValidationError)


def test_unknown_model_is_an_api_error() -> None:
    """The agent never picks a model, so this can only be our own bug.

    Odoo reports it with the same code as a validation problem, which is why
    the message shape decides here.
    """
    error = translate_fault(UNKNOWN_MODEL)
    assert isinstance(error, OdooApiError)
    assert error.message == "Object no.such.model doesn't exist"


def test_client_error_is_an_api_error() -> None:
    """Code 1 means the call itself was wrong or the server broke."""
    assert isinstance(translate_fault(UNKNOWN_METHOD), OdooApiError)


def test_an_unknown_fault_code_is_an_api_error() -> None:
    """A future Odoo may add codes, and an unknown one must not slip through."""
    assert isinstance(translate_fault(xmlrpc.client.Fault(99, "something new")), OdooApiError)
