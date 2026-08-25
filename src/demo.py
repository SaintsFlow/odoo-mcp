"""A run through the whole server, the way an agent would use it.

Starts the server as its own process, talks to it over stdio as a real MCP
client does, and walks the path a salesperson would walk: find the customer,
check the shelf, put the order in, confirm it. Every line printed here is an
answer that came back over the protocol, not a description of one.

Run it with `make demo`, after `make seed`.
"""

import asyncio
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.seed import DEMO_PARTNER, DEMO_PRODUCT_CODE

DEMO_QUANTITY = 2


def _server() -> StdioServerParameters:
    """The same server anyone else would start, over stdio."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.server"],
        env={
            **os.environ,
            # The demo watches its own output, so the server's logs stay quiet.
            "LOG_LEVEL": "warning",
            "MCP_TRANSPORT": "stdio",
        },
    )


async def _call(session: ClientSession, tool: str, arguments: dict[str, Any]) -> Any:
    """Call a tool and give up loudly if it refused."""
    result = await session.call_tool(tool, arguments)
    if result.is_error:
        said = " ".join(getattr(block, "text", "") for block in result.content)
        raise SystemExit(f"{tool} refused: {said}")
    return result.structured_content


async def run() -> None:
    async with (
        stdio_client(_server(), errlog=sys.stderr) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        tools = sorted(tool.name for tool in (await session.list_tools()).tools)
        print(f"Connected. Tools on offer: {', '.join(tools)}")

        print(f"\n1. Who is {DEMO_PARTNER}?")
        found = await _call(session, "search_partners", {"query": DEMO_PARTNER})
        customer = found["items"][0]
        print(f"   {customer['name']}, {customer['city']}, id {customer['id']}")

        print(f"\n2. What is on the shelf for {DEMO_PRODUCT_CODE}?")
        stock = await _call(session, "get_stock", {"product_query": DEMO_PRODUCT_CODE})
        level = stock["items"][0]
        print(
            f"   {level['product']}: {level['on_hand']:g} on hand, "
            f"{level['available']:g} free, in {level['warehouse'] or level['location']}"
        )

        print(f"\n3. Order {DEMO_QUANTITY} of them.")
        order = await _call(
            session,
            "create_sales_order",
            {
                "partner_id": customer["id"],
                "lines": [{"product_id": level["product_id"], "quantity": DEMO_QUANTITY}],
            },
        )
        print(
            f"   {order['number']} for {order['partner_name']}: {order['state']}, "
            f"{order['total']:g} {order['currency']}"
        )

        print("\n4. Confirm it.")
        confirmed = await _call(session, "confirm_sales_order", {"order_id": order["id"]})
        print(f"   {confirmed['number']} is now {confirmed['state']}")

        print("\n5. Read it back, lines and all.")
        whole = await _call(session, "get_sales_order", {"order_id": order["id"]})
        for line in whole["lines"]:
            print(f"   {line['quantity']:g} x {line['product']} = {line['subtotal']:g}")

        print("\n6. And what a refusal sounds like.")
        broken = await session.call_tool("confirm_sales_order", {"order_id": order["id"]})
        said = " ".join(getattr(block, "text", "") for block in broken.content)
        print(f"   {said}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
