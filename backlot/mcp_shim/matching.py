"""Small fuzzy-matching helpers used by the shim's tool implementations.

An LLM asking for e.g. "rain effects" won't always spell a catalog key
exactly as it's stored ("rain_effects_unit"), and a real ClickHouse
deployment resolves this kind of near-miss with a `column ILIKE '%token%'`
SQL query instead (see budget.py/resource.py's clickhouse-mode
instructions). Token-overlap scoring is the deterministic, dependency-free
stand-in for that here — good enough to make grounding actually succeed in
typical cases without ever inventing a match that isn't there.
"""

from __future__ import annotations

import re
from datetime import date

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def token_overlap_score(query: str, candidate: str) -> float:
    """Jaccard similarity between the token sets of two strings, in [0, 1]."""
    query_tokens = tokenize(query)
    candidate_tokens = tokenize(candidate)
    if not query_tokens or not candidate_tokens:
        return 0.0
    intersection = query_tokens & candidate_tokens
    union = query_tokens | candidate_tokens
    return len(intersection) / len(union)


def best_matches(
    query: str, candidates: list[dict], key: str, min_score: float = 0.15, top_n: int = 3
) -> list[tuple[dict, float]]:
    """Ranks candidates by token overlap between `query` and candidate[key]."""
    scored = [(c, token_overlap_score(query, c[key])) for c in candidates]
    scored = [(c, s) for c, s in scored if s >= min_score]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_n]


def date_ranges_overlap(
    window_start: str | None,
    window_end: str | None,
    available_from: str,
    available_to: str,
) -> bool:
    """True if [window_start, window_end] overlaps [available_from, available_to].

    A missing window (either side None) means "no date constraint requested"
    and always overlaps.
    """
    if window_start is None or window_end is None:
        return True
    ws, we = date.fromisoformat(window_start), date.fromisoformat(window_end)
    af, at = date.fromisoformat(available_from), date.fromisoformat(available_to)
    return ws <= at and we >= af
