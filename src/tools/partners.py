"""Finding partners by the little the agent usually knows about them."""

from mcp.server.mcpserver import MCPServer

from src.client import OdooClient
from src.errors import OdooValidationError
from src.models import Partner
from src.tools import LOOKS_ONLY, readable_errors

MAX_LIMIT = 100


async def search_partners(client: OdooClient, query: str, limit: int = 20) -> list[Partner]:
    """Search partners over several fields at once.

    Someone asking for "Azure" does not know whether the word sits in the name,
    the address or the VAT number, so all of them are searched.
    """
    wanted = query.strip()
    if not wanted:
        raise OdooValidationError(
            "Say what to search for: a name, an email, a city or a VAT number."
        )
    if limit < 1:
        raise OdooValidationError(f"The limit has to be between 1 and {MAX_LIMIT}.")

    domain = [
        "|",
        "|",
        "|",
        ("name", "ilike", wanted),
        ("email", "ilike", wanted),
        ("city", "ilike", wanted),
        ("vat", "ilike", wanted),
    ]
    records = await client.search_read(
        "res.partner", domain, Partner.ODOO_FIELDS, limit=min(limit, MAX_LIMIT)
    )
    return [Partner.from_odoo(record) for record in records]


def register(server: MCPServer, client: OdooClient) -> None:
    """Publish the partner tool on the server."""

    @server.tool(name="search_partners", annotations=LOOKS_ONLY)
    @readable_errors
    async def _search_partners(query: str, limit: int = 20) -> list[Partner]:
        """Find customers and suppliers.

        The search text is matched against the name, the email address, the city
        and the VAT number, so a fragment of any one of them is enough. Answers
        with an empty list when nobody matches.
        """
        return await search_partners(client, query, limit)
