"""Errors the server raises, and the translation of what Odoo sends back.

Odoo reports a failure as an XML-RPC Fault. The fault code says what kind of
failure it was, and the fault string holds either a full server side traceback
or a message already written for a human. Both shapes were captured from a
running Odoo 17, and the rules below follow what it actually sends.
"""

import re
import xmlrpc.client

# Odoo's own fault codes. They are the only reliable signal: the text of a
# message is translated and changes between versions, the code does not.
FAULT_CLIENT_ERROR = 1  # a traceback, our call was wrong or the server broke
FAULT_APPLICATION_ERROR = 2  # UserError and friends, a message for a human
FAULT_ACCESS_DENIED = 3  # bad credentials on the call itself
FAULT_ACCESS_ERROR = 4  # logged in, but not allowed to touch this

# Long enough for any message Odoo writes on purpose, short enough that a
# runaway string never reaches the agent.
MAX_MESSAGE_CHARS = 500

# The last line of a Python traceback is "SomeError: what happened", sometimes
# with a module in front. The class name means nothing to the agent.
_EXCEPTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*: ")

# Odoo reports an unknown model as an application error, the same code it uses
# for a validation problem. Only the wording tells them apart.
_UNKNOWN_MODEL = re.compile(r"^Object \S+ doesn't exist")


class OdooError(Exception):
    """Base for every error this project raises.

    The message is written for the agent, not for a log reader: one sentence
    about what went wrong and, where it helps, what to try next.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OdooAuthError(OdooError):
    """The credentials did not work. Nobody but the operator can fix this."""


class OdooAccessError(OdooError):
    """The login worked, the user is not allowed to do this."""


class OdooValidationError(OdooError):
    """Odoo refused the data. The agent can act on it by changing arguments."""


class OdooApiError(OdooError):
    """The call itself was wrong, or Odoo failed on its own side."""


def fault_message(fault: xmlrpc.client.Fault) -> str:
    """Pull the one sentence worth showing out of a fault.

    A traceback shrinks to its last line. A message Odoo wrote for a human is
    kept whole and joined into a single line: its useful sentence is sometimes
    the first one and sometimes the last, so cutting either end loses it.
    """
    lines = [line.strip() for line in str(fault.faultString or "").splitlines() if line.strip()]
    if not lines:
        return "Odoo refused the call and said nothing about why."

    if fault.faultCode == FAULT_CLIENT_ERROR:
        message = _EXCEPTION_NAME.sub("", lines[-1], count=1)
    else:
        message = " ".join(lines)

    if len(message) > MAX_MESSAGE_CHARS:
        return message[: MAX_MESSAGE_CHARS - 3].rstrip() + "..."
    return message


def translate_fault(fault: xmlrpc.client.Fault) -> OdooError:
    """Turn a fault into the error that says what the caller should do."""
    message = fault_message(fault)

    if fault.faultCode == FAULT_ACCESS_DENIED:
        return OdooAuthError(message)
    if fault.faultCode == FAULT_ACCESS_ERROR:
        return OdooAccessError(message)
    if fault.faultCode == FAULT_APPLICATION_ERROR and not _UNKNOWN_MODEL.match(message):
        return OdooValidationError(message)
    # Code 1, an unknown model, and anything a future Odoo invents: not the
    # agent's doing, so it must not look like a data problem.
    return OdooApiError(message)
