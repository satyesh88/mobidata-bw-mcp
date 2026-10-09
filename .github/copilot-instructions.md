# MobiData BW MCP development

- Use Python 3.11+ and manage dependencies and commands with `uv`.
- Follow the official MCP Python SDK documentation: https://py.sdk.modelcontextprotocol.io/
- Keep tool descriptions concise and written for an LLM choosing between tools.
- Every data result must include source, licence/attribution, timestamp where available, and freshness warnings.
- Never add customer data to code, fixtures, tests, examples, or documentation.
- Run `uv run ruff check .` and `uv run pytest` before committing.