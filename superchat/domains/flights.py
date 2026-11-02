"""One-way flight search, comparison, and mock reservations."""

from __future__ import annotations

from datetime import date, time

from ..repositories import FlightRepository
from .common import InvalidRequest, Reservation, ReservationLedger, UnknownItem, money


def _valid_date(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (TypeError, ValueError):
        pass
    raise InvalidRequest("Date must be YYYY-MM-DD.")


def _valid_time(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        if time.fromisoformat(value).isoformat(timespec="minutes") == value:
            return value
    except (TypeError, ValueError):
        pass
    raise InvalidRequest("Departure time must be HH:MM.")


class FlightService:
    def __init__(self, flights: FlightRepository, reservations: ReservationLedger):
        self._flights = flights
        self._reservations = reservations

    def get(self, flight_id: str) -> dict:
        flight = self._flights.get(flight_id)
        if flight is None:
            raise UnknownItem(f"Unknown flight: {flight_id}")
        flight["seats_available"] = self._reservations.remaining(
            "flight", flight_id, flight["seats_available"]
        )
        return flight

    def search(
        self, origin: str, destination: str, travel_date: str, *,
        min_price: object | None = None, max_price: object | None = None,
        max_stops: int | None = None, departure_after: str | None = None,
        departure_before: str | None = None, airline: str | None = None,
        sort_by: str = "price", descending: bool = False,
    ) -> list[dict]:
        if (not isinstance(origin, str) or not origin.strip() or
                not isinstance(destination, str) or not destination.strip()):
            raise InvalidRequest("Origin and destination are required.")
        travel_date = _valid_date(travel_date)
        if max_stops is not None and (type(max_stops) is not int or max_stops < 0):
            raise InvalidRequest("Maximum stops must be a nonnegative whole number.")
        if sort_by not in {"price", "stops", "departure_time", "airline"}:
            raise InvalidRequest("Unsupported flight sort order.")
        lower = money(min_price) if min_price is not None else None
        upper = money(max_price) if max_price is not None else None
        if lower is not None and upper is not None and lower > upper:
            raise InvalidRequest("Minimum price exceeds maximum price.")
        after = _valid_time(departure_after)
        before = _valid_time(departure_before)
        if after and before and after > before:
            raise InvalidRequest("Departure time range is reversed.")

        def place_matches(place: dict, query: str) -> bool:
            return query.casefold() in {place["code"].casefold(), place["city"].casefold()}

        results = []
        for flight in self._flights.list_all():
            if not place_matches(flight["origin"], origin.strip()):
                continue
            if not place_matches(flight["destination"], destination.strip()):
                continue
            if flight["departure_local"][:10] != travel_date:
                continue
            if lower is not None and money(flight["price_azn"]) < lower:
                continue
            if upper is not None and money(flight["price_azn"]) > upper:
                continue
            if max_stops is not None and flight["stops"] > max_stops:
                continue
            departure_time = flight["departure_local"][11:16]
            if after is not None and departure_time < after:
                continue
            if before is not None and departure_time > before:
                continue
            if airline is not None and flight["airline"].casefold() != airline.strip().casefold():
                continue
            flight["seats_available"] = self._reservations.remaining(
                "flight", flight["id"], flight["seats_available"]
            )
            results.append(flight)

        keys = {
            "price": lambda item: (money(item["price_azn"]), item["id"]),
            "stops": lambda item: (item["stops"], money(item["price_azn"]), item["id"]),
            "departure_time": lambda item: (item["departure_local"], item["id"]),
            "airline": lambda item: (item["airline"].casefold(), item["id"]),
        }
        return sorted(results, key=keys[sort_by], reverse=descending)

    def compare(self, flight_ids: list[str]) -> list[dict]:
        if len(set(flight_ids)) < 2 or len(set(flight_ids)) != len(flight_ids):
            raise InvalidRequest("Choose at least two different flights to compare.")
        return [self.get(flight_id) for flight_id in flight_ids]

    def reserve(self, flight_id: str, quantity: int = 1) -> Reservation:
        flight = self._flights.get(flight_id)
        if flight is None:
            raise UnknownItem(f"Unknown flight: {flight_id}")
        return self._reservations.reserve(
            "flight", flight_id, flight["seats_available"], quantity, flight["price_azn"]
        )
