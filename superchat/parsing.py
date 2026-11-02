"""Small, explicit parsers for dates and references in chat messages."""

from __future__ import annotations

import re
from datetime import date, timedelta


WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTHS.update({name[:3]: value for name, value in list(MONTHS.items())})
QUANTITIES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}


def mentioned_date(message: str, reference_date: date) -> str | None:
    text = message.casefold()
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if match:
        try:
            return date.fromisoformat(match.group()).isoformat()
        except ValueError:
            return None
    match = re.search(r"\b(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?\b", text)
    if match and match.group(2) in MONTHS:
        try:
            return date(int(match.group(3) or reference_date.year),
                        MONTHS[match.group(2)], int(match.group(1))).isoformat()
        except ValueError:
            return None
    if re.search(r"\b(today|tonight)\b", text):
        return reference_date.isoformat()
    if re.search(r"\btomorrow\b", text):
        return (reference_date + timedelta(days=1)).isoformat()
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            days = (weekday - reference_date.weekday()) % 7
            if "next " + name in text:
                days = days + 7 if days else 7
            return (reference_date + timedelta(days=days)).isoformat()
    return None


def quantity(message: str, default: int = 1) -> int:
    match = re.search(
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(?:seats?|tickets?|passengers?|items?|units?|products?)\b",
        message, re.IGNORECASE,
    )
    if not match:
        return default
    value = match.group(1).casefold()
    return int(value) if value.isdigit() else QUANTITIES[value]


def ordinal_index(message: str) -> int | None:
    text = message.casefold()
    for word, index in ORDINALS.items():
        if re.search(rf"\b{word}\b", text):
            return index
    match = re.search(r"\b([1-9])(?:st|nd|rd|th)\b", text)
    return int(match.group(1)) - 1 if match else None


def mentioned_id(message: str, prefix: str) -> str | None:
    match = re.search(rf"\b{re.escape(prefix)}\d{{3}}\b", message, re.IGNORECASE)
    return match.group().upper() if match else None


def all_ids(message: str, prefix: str) -> list[str]:
    return [match.upper() for match in
            re.findall(rf"\b{re.escape(prefix)}\d{{3}}\b", message, re.IGNORECASE)]


def price_bounds(message: str) -> tuple[str | None, str | None]:
    text = message.casefold()
    between = re.search(r"\bbetween\s+(\d+(?:\.\d+)?)\s+(?:and|to)\s+(\d+(?:\.\d+)?)", text)
    if between:
        return between.group(1), between.group(2)
    lower = re.search(r"\b(?:over|above|at least|from)\s+(\d+(?:\.\d+)?)\s*(?:azn|manat)?\b", text)
    upper = re.search(r"\b(?:under|below|up to|at most)\s+(\d+(?:\.\d+)?)\s*(?:azn|manat)?\b", text)
    return lower.group(1) if lower else None, upper.group(1) if upper else None


def language_of(message: str, previous: str = "en") -> str:
    if re.search(r"[А-Яа-яЁё]", message):
        return "ru"
    if re.search(r"[ƏəĞğİıÖöŞşÜüÇç]", message):
        return "az"
    if re.search(r"[A-Za-z]", message):
        return "en"
    return previous
