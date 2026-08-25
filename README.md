# odoo-mcp

An MCP server for Odoo. It gives an LLM agent read and write access to partners, sales
orders, stock levels and invoices in an Odoo instance.

All six tools work against the Odoo in `docker compose`: answers are capped, every call
has a deadline, `ODOO_READONLY=true` leaves the write tools unpublished, and the server
talks either over stdio or over http. What is missing is listed at the bottom.

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
make up                         # Odoo Community with demo data, waits until it answers
make seed                       # one customer, one product, a known quantity of it
make demo                       # the whole path, printed as it happens
```

The first `make up` takes a couple of minutes: Odoo builds its database and loads the
demo data. Everything after that is seconds.

To run the server itself rather than the demo:

```bash
make run                        # over stdio, the way a desktop client starts it
docker compose up -d mcp        # over http, then curl localhost:8080/health
```

Port 8080 is a busy one. If something else on the machine already holds it, set
`MCP_HOST_PORT` to anything free and compose will use that on the host side.

## Demo

`make demo` starts the server as its own process, talks to it over stdio exactly as an
MCP client does, and walks the path a salesperson walks. Every line below came back over
the protocol:

```
Connected. Tools on offer: confirm_sales_order, create_sales_order, get_sales_order, get_stock, list_invoices, search_partners

1. Who is MCP Demo Customer?
   MCP Demo Customer, Vienna, id 44

2. What is on the shelf for MCP-DESK?
   [MCP-DESK] MCP Demo Desk: 42 on hand, 42 free, in YourCompany

3. Order 2 of them.
   S00095 for MCP Demo Customer: quotation, 1147.7 USD

4. Confirm it.
   S00095 is now confirmed

5. Read it back, lines and all.
   2 x [MCP-DESK] MCP Demo Desk = 998

6. And what a refusal sounds like.
   Error executing tool confirm_sales_order: Order S00095 is confirmed. Only a quotation can be confirmed.
```

The order number climbs with every run, the rest stays put: that is what `make seed` is
for, and running it twice changes nothing.

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

**Health says nothing about Odoo.** `/health` answers for the process alone. The compose
healthcheck watches it, and an Odoo that is briefly away must not get a working server
restarted underneath it. Whether Odoo answers is visible on the first tool call.

## What is not here yet

- paging through a cut answer: a tool says there is more, but there is no way to ask for
  the next page yet, only a narrower question
- multi-company support: a company is pinned with `ODOO_COMPANY_IDS` and every answer
  names its own, which is not the same as running across several of them
- cancelling an order, and editing one that already exists: `action_cancel` over XML-RPC
  returns a dialog to open and leaves the order as it was
- creating a partner, so an agent can sell to someone who is not in the database yet
- authentication on the http transport: it is meant for a private network, not the open
  one

## License

MIT
