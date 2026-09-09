"""Builds InstructionProvider callables that inject compact JSON state."""

from __future__ import annotations

import json
from typing import Callable

from google.adk.agents.readonly_context import ReadonlyContext

from ..config import Settings


CLICKHOUSE_TOOL_FILTER = ["run_query", "list_tables"]


def clickhouse_sql_rule(settings: Settings, tables: str) -> str:
    """Shared instruction block for any agent querying the real ClickHouse MCP
    server directly with SQL, instead of mcp_shim's fuzzy-matched tool calls."""
    database = settings.clickhouse_database or "<CLICKHOUSE_DATABASE not set>"
    return f"""\
You are connected to a real ClickHouse cluster via MCP — tool names and \
signatures verified against github.com/ClickHouse/mcp-clickhouse's own \
README: run_query(query), list_tables(database, like=None, not_like=None, \
page_token=None, page_size=None, include_detailed_columns=True).

Database: {database}
Tables available to you: {tables}

Rules for querying:
1. Qualify table names as {database}.<table> in every query. If you're \
   unsure of a column name, call list_tables(database="{database}") once — \
   it returns column details by default — rather than guessing.
2. This is a real SQL engine, not a fuzzy matcher: match free-text columns \
   with `column ILIKE '%token%'` (ClickHouse's case-insensitive LIKE; \
   combine multiple tokens with OR/AND as the search calls for) rather \
   than expecting an exact string match. `lower(column) LIKE lower('%tok%')` \
   works too if you prefer it.
3. A query that returns zero rows means nothing matched in ClickHouse — do \
   not invent a number or loosen the query until something returns; record \
   that line item/pick as ungrounded instead, per the grounding rules below.
4. In every returned row's source_records, record_id is that row's natural \
   key (e.g. a scene_profile, crew_id, or location_id value already in the \
   row) and source is "clickhouse:{database}.<table>".
"""


TOOL_ECONOMY_RULE = """\
Be economical with tool calls — each one costs real, scarce quota:
- Batch everything you can into as FEW separate tool-calling turns as \
  possible. If you need to look up several distinct items (costs, rates, \
  crew, locations), issue all of those tool calls together in the same \
  turn rather than one at a time, waiting for each result before deciding \
  the next call.
- Deduplicate before calling: if two needs share the same underlying \
  profile (the same location + int/ext + time of day, or the same \
  vendor/crew category), look it up once and reuse that result for both — \
  never call the same tool with an equivalent query twice.
- Do not call a tool "to double check" or to explore alternatives once you \
  already have a usable result.
"""


def with_state_json(base_instruction: str, *state_keys: str) -> Callable[[ReadonlyContext], str]:
    def _build(ctx: ReadonlyContext) -> str:
        sections = [base_instruction]
        for key in state_keys:
            value = ctx.state.get(key)
            if value is not None:
                sections.append(f"\n## {key} (JSON)\n{json.dumps(value, indent=2)}")
        return "\n".join(sections)

    return _build
