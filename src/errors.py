"""Errors the server raises on its own.

Odoo answers a failed call with a Fault that carries the whole server side
traceback. The agent must never see that, so every layer turns what it catches
into one of the errors here. Wave 1 adds the specific ones.
"""


class OdooError(Exception):
    """Base for every error this project raises.

    The message is written for the agent, not for a log reader: one sentence
    about what went wrong and, where it helps, what to try next.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
