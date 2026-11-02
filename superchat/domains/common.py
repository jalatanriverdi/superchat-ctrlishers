"""Small shared types for mock reservations and domain validation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock


class DomainError(Exception):
    """A request cannot be completed as asked."""


class InvalidRequest(DomainError):
    """A requested filter or quantity is invalid."""


class UnknownItem(DomainError):
    """An ID does not exist in the official data."""


class Unavailable(DomainError):
    """There is insufficient stock or seat availability."""


def money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidRequest("Price must be a number.") from exc
    if not amount.is_finite() or amount < 0:
        raise InvalidRequest("Price must be nonnegative.")
    return amount


def positive_quantity(value: object) -> int:
    if type(value) is not int or value < 1:
        raise InvalidRequest("Quantity must be a positive whole number.")
    return value


@dataclass(frozen=True)
class Reservation:
    id: str
    kind: str
    item_id: str
    quantity: int
    total_azn: Decimal


class ReservationLedger:
    """In-memory seat deductions; the official JSON files remain unchanged."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._reserved: dict[tuple[str, str], int] = {}
        self._next_id = 1

    def remaining(self, kind: str, item_id: str, listed_seats: int) -> int:
        with self._lock:
            return listed_seats - self._reserved.get((kind, item_id), 0)

    def reserve(
        self, kind: str, item_id: str, listed_seats: int,
        quantity: int, unit_price: object,
    ) -> Reservation:
        positive_quantity(quantity)
        price = money(unit_price)
        key = (kind, item_id)
        with self._lock:
            remaining = listed_seats - self._reserved.get(key, 0)
            if quantity > remaining:
                raise Unavailable(f"Only {remaining} seat(s) remain.")
            self._reserved[key] = self._reserved.get(key, 0) + quantity
            reservation = Reservation(
                f"R{self._next_id:06d}", kind, item_id, quantity, price * quantity
            )
            self._next_id += 1
            return reservation
