# odoo-mcp

An MCP server for Odoo. It gives an LLM agent read and write access to partners, sales
orders, stock levels and invoices in an Odoo instance.

**Status:** early. All six tools below work against the Odoo in `docker compose`, answers
are capped, every call has a deadline, and `ODOO_READONLY=true` leaves the write tools
unpublished. What is missing is listed at the bottom.

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
| `create_sales_order` | create a quotation for a customer |
| `confirm_sales_order` | turn a quotation into a confirmed order |
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

**Read and write are separated.** The two write tools are marked destructive in their
MCP annotations and the four read tools are marked read-only, so a client can ask its
user before an order is created or confirmed.

**Arguments are checked before Odoo is called.** Odoo takes an order line of zero
quantity without a word, and answers an unknown id with its own record ids in the text.
Both are caught here, so a refusal says what to do instead of what broke inside the ERP.

**A cut answer says it was cut.** No call hands back more than 200 records. When more
matched, the answer carries `truncated: true` and a hint on how to narrow the request,
because twenty results out of thirty-eight look exactly like all of them otherwise.

**Read-only mode removes the write tools rather than blocking them.** With
`ODOO_READONLY=true` they are never published, so a client sees four tools and a call by
name comes back as an unknown tool.

**Errors are translated.** Odoo raises faults with long tracebacks. The server extracts
the message and returns it in a form the agent can act on.

## What is not here yet

- paging through a cut answer: a tool says there is more, but there is no way to ask for
  the next page yet, only a narrower question
- multi-company support: a company is pinned with `ODOO_COMPANY_IDS` and every answer
  names its own, which is not the same as running across several of them
- cancelling an order, and editing one that already exists
- a seeded data set, so a demo run shows the same numbers every time
- the streamable http transport, so the server can run somewhere other than beside its
  client

## License

MIT
