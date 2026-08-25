"""The tools the agent sees.

Each module here owns one area: it knows which Odoo model to read, which domain
to build and which fields to ask for. None of that appears in the arguments a
tool takes, and none of it appears in what a tool answers.
"""

from collections.abc import Awaitable, Callable
from functools import wraps

from mcp.server.mcpserver.exceptions import ToolError

from src.errors import OdooError


def readable_errors[**Arguments, Answer](
    call: Callable[Arguments, Awaitable[Answer]],
) -> Callable[Arguments, Awaitable[Answer]]:
    """Let the reason for a refusal reach the agent.

    Anything the SDK does not recognise comes out of a tool as "Error executing
    tool" with the cause dropped, which is the right default for a stray
    exception and useless for a message written on purpose. Our own errors are
    exactly those messages, so they are handed over as ToolError.
    """

    @wraps(call)
    async def with_the_reason(*args: Arguments.args, **kwargs: Arguments.kwargs) -> Answer:
        try:
            return await call(*args, **kwargs)
        except OdooError as error:
            raise ToolError(error.message) from error

    return with_the_reason
