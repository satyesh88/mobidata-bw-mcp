# Contributor guidelines

- Use Python 3.11+ and manage dependencies and commands with `uv`.
- Follow the official MCP Python SDK documentation: https://py.sdk.modelcontextprotocol.io/
- Keep tool descriptions concise and written for an LLM choosing between tools.
- Every data result must include source, licence/attribution, timestamp where available, and freshness warnings.
- Never add customer data to code, fixtures, tests, examples, or documentation.
- Run `uv run ruff check .` and `uv run pytest` before committing.

## Contribution licensing

The current project uses PolyForm Noncommercial 1.0.0, with separate commercial licences
available from the maintainer. Contributors must own or have permission to submit their
work. Before accepting third-party code, the maintainer obtains a separate written grant
covering both noncommercial distribution and commercial relicensing. Third-party notices
and dataset licences remain intact. Earlier Apache-2.0 releases retain their original rights.
