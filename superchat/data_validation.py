"""Validation of the organiser's fixed mock-data schema."""

from __future__ import annotations

from datetime import date, datetime, time
from math import isfinite
from numbers import Real


REQUIRED_FIELDS = {
    "flights": {
        "id", "airline", "flight_number", "origin", "destination",
        "departure_local", "arrival_local", "duration_min", "stops", "via",
        "price_azn", "cabin", "baggage_kg", "seats_available",
    },
    "products": {
        "id", "name", "category", "brand", "price_azn", "rating",
        "stock", "color", "description",
    },
    "movies": {
        "id", "title", "genre", "language", "duration_min",
        "age_rating", "rating", "synopsis",
    },
    "cinemas": {"id", "name", "district", "address"},
    "showtimes": {
        "id", "movie_id", "cinema_id", "date", "time", "hall",
        "price_azn", "seats_total", "seats_available",
    },
}


class DataSourceError(Exception):
    """A mock-data file cannot be used safely."""


def _require(condition: bool, location: str, reason: str) -> None:
    if not condition:
        raise DataSourceError(f"{location}: {reason}")


def _string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _number(value: object, minimum: float = 0) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and isfinite(value)
        and value >= minimum
    )


def _iso(value: object, kind: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        if kind == "date":
            return date.fromisoformat(value).isoformat() == value
        if kind == "time":
            return time.fromisoformat(value).isoformat(timespec="minutes") == value
        return datetime.fromisoformat(value).isoformat(timespec="minutes") == value
    except ValueError:
        return False


def validate_record(collection: str, record: object, index: int) -> None:
    location = f"{collection}.json record {index}"
    _require(isinstance(record, dict), location, "expected an object")
    assert isinstance(record, dict)
    missing = REQUIRED_FIELDS[collection] - record.keys()
    _require(not missing, location, f"missing fields: {', '.join(sorted(missing))}")
    _require(_string(record["id"]), location, "id must be a nonempty string")

    strings = {
        "flights": ("airline", "flight_number", "cabin"),
        "products": ("category", "brand", "color", "description"),
        "movies": ("title", "language", "age_rating", "synopsis"),
        "cinemas": ("name", "district", "address"),
        "showtimes": ("movie_id", "cinema_id", "hall"),
    }
    for field in strings[collection]:
        _require(_string(record[field]), location, f"{field} must be a nonempty string")

    for field in ("price_azn", "rating"):
        if field in record:
            _require(_number(record[field]), location, f"{field} must be nonnegative")
    for field in ("duration_min", "stops", "baggage_kg", "seats_available", "seats_total", "stock"):
        if field in record:
            _require(_integer(record[field]), location, f"{field} must be a nonnegative integer")

    if collection == "flights":
        for field in ("origin", "destination"):
            place = record[field]
            _require(
                isinstance(place, dict) and _string(place.get("code")) and _string(place.get("city")),
                location,
                f"{field} needs code and city",
            )
        _require(record["via"] is None or _string(record["via"]), location, "via must be text or null")
        for field in ("departure_local", "arrival_local"):
            _require(_iso(record[field], "datetime"), location, f"{field} must be an ISO local datetime")
    elif collection == "products":
        name = record["name"]
        _require(
            isinstance(name, dict) and all(_string(name.get(lang)) for lang in ("en", "az", "ru")),
            location,
            "name needs en, az and ru text",
        )
    elif collection == "movies":
        genres = record["genre"]
        _require(isinstance(genres, list) and bool(genres) and all(_string(x) for x in genres),
                 location, "genre must be a nonempty list of text")
    elif collection == "showtimes":
        _require(_iso(record["date"], "date"), location, "date must be an ISO date")
        _require(_iso(record["time"], "time"), location, "time must be an HH:MM time")
        _require(record["seats_available"] <= record["seats_total"],
                 location, "available seats exceed total seats")


def validate_references(movies: list[dict], cinemas: list[dict], showtimes: list[dict]) -> None:
    movie_ids = {movie["id"] for movie in movies}
    cinema_ids = {cinema["id"] for cinema in cinemas}
    for showtime in showtimes:
        location = f"showtimes.json {showtime['id']}"
        _require(showtime["movie_id"] in movie_ids, location, "unknown movie_id")
        _require(showtime["cinema_id"] in cinema_ids, location, "unknown cinema_id")
