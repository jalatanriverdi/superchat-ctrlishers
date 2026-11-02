"""Deterministic filtering over detached official mock records."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal, InvalidOperation
import re

from .semantic import InterpretationError, NUMERIC


def _text_tokens(value: str) -> list[str]:
    """Normalize simple inflections in the three supported catalogue languages."""
    tokens = re.findall(r"\w+", value.casefold())
    normalized = []
    for token in tokens:
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        elif len(token) > 6 and token.endswith(("ları", "ləri")):
            token = token[:-4]
        elif len(token) > 5 and token.endswith(("lar", "lər")):
            token = token[:-3]
        elif len(token) > 5 and re.search(r"[а-яё]", token):
            if token.endswith(("ам", "ям")):
                token = token[:-2]
            elif token.endswith("и"):
                token = token[:-1]
        normalized.append(token)
    return normalized


def _number(value: object) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ".").rstrip("+"))
    except (InvalidOperation, ValueError) as exc:
        raise InterpretationError("A numeric filter is invalid.") from exc


def _value(domain: str, row: dict, field: str):
    if domain == "flights":
        if field in {"origin", "destination"}:
            place = row[field]
            return [place["city"], place["code"]]
        if field == "travel_date":
            return row["departure_local"][:10]
        if field == "departure_time":
            return row["departure_local"][11:16]
        return row[field]
    if domain == "shopping":
        if field == "text":
            return " ".join([*row["name"].values(), row["category"], row["brand"],
                             row["color"], row["description"]])
        if field == "name":
            return list(row["name"].values())
        return row[field]
    if field == "showing_on":
        return row.get("date")
    if field == "cinema":
        return row.get("cinema", {}).get("name")
    if field == "showtime":
        return row.get("time")
    if field == "ticket_price_azn":
        return row.get("price_azn")
    if field == "seats_available":
        return row.get("seats_available")
    movie = row.get("movie", row)
    if field == "age_rating":
        return int(movie["age_rating"].rstrip("+"))
    return movie[field]


def _match_value(actual, field: str, op: str, wanted: str, other: str) -> bool:
    if actual is None:
        return False
    if isinstance(actual, list):
        return any(_match_value(value, field, op, wanted, other) for value in actual)
    if field in NUMERIC:
        actual, wanted = _number(actual), _number(wanted)
        other = _number(other) if op == "between" else other
    elif field in {"travel_date", "showing_on"}:
        try:
            actual, wanted = date.fromisoformat(str(actual)), date.fromisoformat(wanted)
            other = date.fromisoformat(other) if op == "between" else other
        except ValueError as exc:
            raise InterpretationError("A date filter is invalid.") from exc
    elif field in {"departure_time", "showtime"} and op not in {"contains", "ne"}:
        try:
            actual, wanted = time.fromisoformat(str(actual)), time.fromisoformat(wanted)
            other = time.fromisoformat(other) if op == "between" else other
        except ValueError as exc:
            raise InterpretationError("A time filter is invalid.") from exc
    else:
        actual, wanted = str(actual).casefold(), str(wanted).casefold()
        other = str(other).casefold()
    if op == "eq":
        return actual == wanted
    if op == "ne":
        return actual != wanted
    if op == "lt":
        return actual < wanted
    if op == "lte":
        return actual <= wanted
    if op == "gt":
        return actual > wanted
    if op == "gte":
        return actual >= wanted
    if op == "between":
        return wanted <= actual <= other
    if op == "contains":
        if wanted in actual:
            return True
        if field in {"text", "name", "description", "category"}:
            actual_tokens = set(_text_tokens(actual))
            return bool(_text_tokens(wanted)) and all(
                token in actual_tokens for token in _text_tokens(wanted))
        return False
    raise InterpretationError("Unsupported filter operator.")


def matches(domain: str, row: dict, groups: list[list[dict]]) -> bool:
    if not groups:
        return True
    return any(all(_match_value(_value(domain, row, condition["field"]),
                                condition["field"], condition["op"],
                                condition["value"], condition["other"])
                   for condition in group) for group in groups)


def _sort_value(domain: str, row: dict, field: str):
    value = _value(domain, row, field)
    if value is None:
        return (1, "")
    if field in NUMERIC:
        value = _number(value)
    elif isinstance(value, list):
        value = str(value[0]).casefold()
    elif isinstance(value, str):
        value = value.casefold()
    return (0, value)


def filter_records(domain: str, rows: list[dict], groups: list[list[dict]],
                   sort_field: str = "", sort_desc: bool = False) -> list[dict]:
    results = [row for row in rows if matches(domain, row, groups)]
    if sort_field:
        results.sort(key=lambda row: (_sort_value(domain, row, sort_field), row["id"]),
                     reverse=sort_desc)
    return results
