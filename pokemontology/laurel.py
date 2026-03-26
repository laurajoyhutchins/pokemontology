"""Shared Laurel helpers for NL -> SPARQL -> results -> text flows."""

from __future__ import annotations

SUMMARY_PREVIEW_LIMIT = 5


def summarize_results(question: str, payload: dict[str, object]) -> str:
    question = question.strip()
    rows = payload.get("rows")
    if isinstance(payload.get("answer"), str):
        return str(payload["answer"])

    if isinstance(payload.get("boolean"), bool):
        value = bool(payload["boolean"])
        prefix = "Yes." if value else "No."
        if question:
            return f"{prefix} For: {question}"
        return prefix

    if not isinstance(rows, list):
        return "Laurel could not interpret the query output."

    variables = payload.get("variables")
    if not rows:
        return "Laurel found no matching results."

    if isinstance(variables, list) and len(variables) == 1:
        variable = str(variables[0])
        values = [row.get(variable) for row in rows if isinstance(row, dict) and row.get(variable)]
        if not values:
            return f"Laurel found {len(rows)} matching rows."
        preview = ", ".join(str(value) for value in values[:SUMMARY_PREVIEW_LIMIT])
        if len(values) > SUMMARY_PREVIEW_LIMIT:
            preview += ", …"
        if len(values) == 1:
            return f"Laurel found 1 result: {preview}."
        return f"Laurel found {len(values)} results: {preview}."

    if len(rows) == 1 and isinstance(rows[0], dict):
        details = ", ".join(f"{key}={value}" for key, value in rows[0].items())
        return f"Laurel found 1 matching row: {details}."

    return f"Laurel found {len(rows)} matching rows."
