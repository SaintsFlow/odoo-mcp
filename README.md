# odoo-mcp

An MCP server for Odoo. It gives an LLM agent read and write access to partners, sales
orders, stock levels and invoices in an Odoo instance.

**Status:** early. The tool list below is the plan. Not all of it works yet.

## Why

Odoo is a full ERP with a wide API, which makes it hard for an agent to use. Its
external API is XML-RPC with generic `search_read` and `execute_kw` calls, so the agent
would need to know model names, field names and domain syntax. This server exposes a
small number of named tools instead, each one covering a task a person would actually
ask for.

Odoo Community runs in Docker with demo data, so the whole thing can be tried without
any real system.

## Tools

| Tool | What it does |
| --- | --- |
| `search_partners` | find customers and suppliers |
| `get_sales_order` | read an order with its lines and status |
| `create_sales_order` | create a draft order for a partner |
| `confirm_sales_order` | confirm a draft order |
| `get_stock` | current quantity on hand for a product |
| `list_invoices` | invoices for a partner, filtered by state |

## Quick start

```bash
docker compose up -d odoo db    # Odoo Community with demo data
cp .env.example .env
docker compose up mcp
```

Odoo takes about a minute to initialise its database on first start.

## How it works

The server connects to Odoo over XML-RPC. Each tool builds the domain and the field
list itself, so the agent never sees Odoo internals. Results are trimmed to the fields
that matter and returned as flat records.

## Design decisions

**Named tools, not a generic query tool.** A single `run_query` tool would be easier to
write and much worse to use. Named tools carry their own validation and make it obvious
what the agent is allowed to do.

**Read and write are separated.** Write tools are marked in the schema so the client can
require confirmation.

**Errors are translated.** Odoo raises faults with long tracebacks. The server extracts
the message and returns it in a form the agent can act on.

## What is not here yet

- pagination and result limits
- multi-company support
- tests against a seeded Odoo instance

## License

MIT
