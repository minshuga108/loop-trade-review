# Loop MCP server

Loop exposes its review engine to AI agents (Claude, Cursor, any MCP client) at one endpoint: `POST /mcp`.

- **Read-only and paper-only.** No tool places, previews or routes an order. No tool proposes into, arms, retires or reverts a rule: arming stays a human click on the Loop web page. MCP gate checks are not written to the public forward record.
- **Every number is computed** by the same engine the web page uses (`app/service.py`, `engine/*`). Every sentence with a numeral passes `engine.numberlock`; one that cannot be backed is replaced by a number-free line.
- **Strict inputs.** JSON Schemas with enums, bounds, `maxLength` and `additionalProperties: false`. Bodies over 64 KB and batches over 16 messages are refused.
- **Injection-safe.** `order_text` is parsed for side, symbol and size only. It is never echoed back and never read as an instruction. Tool outputs are data.
- **Per-session sandbox.** Each handshake gets a fresh `Mcp-Session-Id`, and the tools use the sandbox `mcp:<session id>` (or `mcp` with no header). An MCP client can never see or change a web visitor's rulebook.

## Wire-up (owner)

```python
# app/main.py
from .mcp_server import router as mcp_router
app.include_router(mcp_router)
```

## Tools

| Tool | Input | Returns |
|---|---|---|
| `list_traders` | none | the demo traders, with role, round trips and provenance label |
| `review_fills` | `trader` (A-F) | habit findings, the priced headline rule (all-history and held-out), required vs actual win rate, fee drag, rule-court summary and verdicts |
| `rule_court` | `trader`, `multiple` (0.5-10) | a walk-forward court verdict for "cap opening size at Nx your usual size after a loss". Runs in a throwaway court: `saved: false`, `armed: false`. Every proposal in the session is counted, so the threshold drops with each try and fishing for a pass gets harder. |
| `rule_gate` | `trader`, `order_text` (1-300 chars), optional `last_trade_was_loss` | gate state, reasons, checklist, broken rules, evidence and the cost check line (from the cached public book) |
| `weekly_report` | `trader`, `lang` (`en`/`zh`) | the fupan weekly review as number-locked markdown, plus its facts |
| `checklist` | `trader` | the pre-trade checklist, with each item's measured effect |

Every tool is listed with `annotations.readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false`, plus an `outputSchema`. Each result has a short text summary, the JSON as a second text block (for older clients), and `structuredContent`.

## Protocol

- Transport: Streamable HTTP, JSON responses only (no SSE). `GET` and `DELETE /mcp` return `405` with `Allow: POST`.
- Methods: `initialize`, `notifications/initialized` (`202`), `ping`, `tools/list`, `tools/call`. Any other method returns `-32601`.
- Revisions served: `2025-11-25`, `2025-06-18` and `2025-03-26`. These are the `initialize`-handshake revisions that shipping clients speak. If a client asks for an unknown revision, the server offers `2025-11-25`. If an `MCP-Protocol-Version` header names an unsupported revision, the server returns `400`.
- **Not implemented:** the `2026-07-28` stateless revision (no `initialize`, `server/discover`, `resultType`). Under its compatibility table, dual-era clients fall back to `initialize` and work. A modern-only client would not.
- JSON-RPC batches (arrays) are accepted. `initialize` inside a batch is refused.
- Errors: `-32700` parse error (HTTP 400), `-32600` invalid request, `-32601` unknown method, `-32602` unknown tool or invalid arguments (with `data.errors`), `-32603` internal error (no traceback).
- `Origin`: requests with no Origin header are allowed. So are localhost, the server's own host, and hosts listed in `LOOP_MCP_ORIGINS` (comma-separated). Any other Origin gets `403`, which guards against DNS rebinding.
- No SDK dependency. The official Python SDK (`mcp`, MIT) is not installed in the venv, so `app/mcp_server.py` implements the protocol directly on FastAPI.

## Client config

Replace `https://loop.example.com` with the deployed host, or use `http://localhost:8000` locally.

**Claude Desktop**: open Settings > Connectors > Add custom connector, and enter URL `https://loop.example.com/mcp`. For older builds that only read `claude_desktop_config.json`, use the `mcp-remote` bridge:

```json
{
  "mcpServers": {
    "loop": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://loop.example.com/mcp"]
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json` or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "loop": { "url": "https://loop.example.com/mcp" }
  }
}
```

**Claude Code**:

```bash
claude mcp add --transport http loop https://loop.example.com/mcp
```

## curl

```bash
URL=http://localhost:8000/mcp
H=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")

# handshake (note the Mcp-Session-Id response header)
curl -si "${H[@]}" $URL -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

# list tools
curl -s "${H[@]}" -H "MCP-Protocol-Version: 2025-06-18" $URL -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# check an order idea (paper only)
curl -s "${H[@]}" -H "MCP-Protocol-Version: 2025-06-18" -H "Mcp-Session-Id: <id from the handshake>" $URL \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"rule_gate","arguments":{"trader":"B","order_text":"buy $20k rNVDA"}}}'
```

## Tests

`tests/test_mcp.py` drives the router with FastAPI `TestClient`. It covers:

- the handshake, `tools/list` and every tool call
- invalid-params codes, unknown tools and methods, parse, size and origin errors
- batches
- an injection string in `order_text`, which must leave the gate result unchanged
- that the court never saves or arms
- that the gate never writes the record
- that no tool name contains place, order, arm or withdraw
