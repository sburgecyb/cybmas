"""Shared helpers for lexical (non-embedding) supplement in ticket/KB search."""
from __future__ import annotations

import re

# Words too generic to require alone; still allowed inside longer queries.
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "the",
        "this",
        "that",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "with",
        "you",
        "please",
        "could",
        "would",
        "any",
        "can",
        "did",
        "does",
        "get",
        "got",
        # Vague complaint / meta wording (common in user questions, rare in titles).
        "issue",
        "issues",
        "problem",
        "problems",
        "error",
        "errors",
        "broken",
        "fix",
        "fixed",
        "working",
        "work",
        "works",
        "worked",
        "expected",
        "unexpected",
        "functionality",
        "behavior",
        "behaviour",
        "correctly",
        "properly",
        "something",
        "someone",
        "regarding",
        "another",
        "unable",
        "cant",
    }
)


def significant_terms(query: str, *, min_len: int = 3, max_terms: int = 12) -> list[str]:
    """Alphanumeric tokens from the query, de-stopped, for AND-style lexical match.

    Reordered paraphrases share the same token bag (e.g. title vs user question).
    """
    words = re.findall(r"[a-z0-9]+", query.lower())
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        if len(w) < min_len or w in _STOP:
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_terms:
            break
    return out
