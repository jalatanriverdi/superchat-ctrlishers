"""Deterministic message routing using domain cues and conversation context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .parsing import mentioned_date, price_bounds
from .repositories import Repositories


@dataclass(frozen=True)
class Route:
    category: str
    domains: tuple[str, ...] = ()


_FLIGHT = re.compile(
    r"\b(flights?|fly|flying|airfare|airline|airport|departure|arrival|"
    r"baggage|nonstop|non-stop|direct flight|stops?|uçuş|uçak|рейс|авиабилет)\b",
    re.IGNORECASE,
)
_SHOPPING = re.compile(
    r"\b(shopping|products?|cart|stock|headphones?|earbuds?|laptops?|"
    r"computers?|backpacks?|smartphones?|phones?|smartwatches?|speakers?|"
    r"shoes?|coffee machines?|board games?|qulaqlıq|noutbuk|çanta|məhsul|"
    r"наушники|ноутбук|рюкзак|товар|корзин)\w*\b",
    re.IGNORECASE,
)
_CINEMA = re.compile(
    r"\b(movies?|films?|cinemas?|showtimes?|screenings?|showing|playing tonight|"
    r"what is playing|what's playing|sci-fi|comedy|horror|animation|"
    r"thriller|drama|ticket|film|kino|bilet|фильм|кино|сеанс|билет)\w*\b",
    re.IGNORECASE,
)
_SMALL_TALK = re.compile(
    r"^(?:hi|hello|hey|thanks|thank you|okay|ok|what can you do)\s*[.!?]*$",
    re.IGNORECASE,
)
_OUT_OF_SCOPE = re.compile(
    r"^\s*(?:who|whom|whose)\b|"
    r"^\s*(?:write|compose|translate|translate this|summarize|define)\b|"
    r"\b(?:poems?|jokes?|weather|forecast|temperature|recipes?|homework|"
    r"news|sports? scores?|translation|hava proqnozu|погода)\b",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"\b(it|that|this|one|ones|first|second|third|fourth|fifth|"
    r"cheaper|cheapest|same|again|back|compare|book|reserve|add|remove)\b",
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r"\b(?:the\s+(?:first|second|third|fourth|fifth|cheaper|cheapest|sci-fi)\s+one|"
    r"it|that one|this one|back to|sort by|book\s+(?:\d+|one|two|three|four|five)\s+tickets?)\b",
    re.IGNORECASE,
)


class Router:
    def __init__(self, repositories: Repositories,
                 reference_date: date = date(2026, 11, 2)):
        self._reference_date = reference_date
        # Titles and brands are drawn from the official data rather than a
        # separately maintained list of invented catalogue entries.
        self._movie_titles = tuple(
            movie["title"].casefold() for movie in repositories.movies.list_all()
        )
        self._product_brands = tuple(
            {product["brand"].casefold() for product in repositories.products.list_all()}
        )
        self._airlines = tuple(
            {flight["airline"].casefold() for flight in repositories.flights.list_all()}
        )
        self._flight_places = {
            value.casefold()
            for flight in repositories.flights.list_all()
            for place in (flight["origin"], flight["destination"])
            for value in (place["city"], place["code"])
        }
        self._product_colors = {
            product["color"].casefold() for product in repositories.products.list_all()
        }

    def _pending_answer(self, text: str, domain: str, field: str | None) -> bool:
        if domain != "flights":
            return False
        value = text.strip(" .?!").casefold()
        if field in {"origin", "destination"}:
            marker = "from" if field == "origin" else "to"
            return (value in self._flight_places or
                    any(value == f"{marker} {place}" for place in self._flight_places))
        return field == "travel_date" and mentioned_date(text, self._reference_date) is not None

    def _contextual_followup(self, text: str, domain: str) -> bool:
        if _FOLLOW_UP.search(text):
            return True
        lowered = text.casefold()
        if domain == "flights":
            return bool(
                re.search(r"\b(direct|nonstop|non-stop|earliest|stops?|baggage|"
                          r"sort by|after\s+\d{1,2}:\d{2}|before\s+\d{1,2}:\d{2})\b", text, re.IGNORECASE)
                or mentioned_date(text, self._reference_date)
                or any(name in lowered for name in self._airlines)
                or re.search(r"\b(?:from|to)\s+\w+\b", text, re.IGNORECASE)
                or any(value is not None for value in price_bounds(text))
            )
        if domain == "shopping":
            return bool(
                re.search(r"\b(stock|available|cart|total|details)\b", text, re.IGNORECASE)
                or any(name in lowered for name in self._product_brands)
                or any(re.search(rf"\b{re.escape(color)}\b", text, re.IGNORECASE)
                       for color in self._product_colors)
                or any(value is not None for value in price_bounds(text))
            )
        if domain == "cinema":
            return bool(
                re.search(r"\b(seats?|tickets?|showtimes?|cinemas?|available)\b", text, re.IGNORECASE)
                or mentioned_date(text, self._reference_date)
            )
        return False

    def classify(self, message: str, active_domain: str | None = None,
                 pending_domain: str | None = None,
                 known_domains: set[str] | None = None,
                 pending_field: str | None = None) -> Route:
        text = message.strip()
        lowered = text.casefold()
        if not text:
            return Route("ambiguous")
        if _SMALL_TALK.fullmatch(text):
            return Route("small_talk")
        # An unrelated task remains unrelated even if it mentions a catalogue
        # domain (for example, a poem about flights).
        if _OUT_OF_SCOPE.search(text):
            return Route("out_of_scope")

        domains = set()
        if (_FLIGHT.search(text) or re.search(r"\bF\d{3}\b", text, re.IGNORECASE)
                or any(name in lowered for name in self._airlines)):
            domains.add("flights")
        if (_SHOPPING.search(text) or re.search(r"\bP\d{3}\b", text, re.IGNORECASE)
                or any(name in lowered for name in self._product_brands)):
            domains.add("shopping")
        if (_CINEMA.search(text) or re.search(r"\b[MS]\d{3}\b", text, re.IGNORECASE)
                or any(title in lowered for title in self._movie_titles)):
            domains.add("cinema")

        if len(domains) > 1:
            # The order is stable so a mixed reply reads in the order of the
            # three services, independently of set iteration order.
            return Route("mixed", tuple(name for name in ("flights", "shopping", "cinema") if name in domains))
        if domains:
            domain = next(iter(domains))
            if _REFERENCE.search(text) and domain in (known_domains or set()):
                return Route("followup", (domain,))
            return Route(domain, (domain,))
        if pending_domain and self._pending_answer(text, pending_domain, pending_field):
            return Route("followup", (pending_domain,))
        if active_domain and self._contextual_followup(text, active_domain):
            return Route("followup", (active_domain,))
        if re.search(r"\b(book|reserve|show me|find me|something good|help|suggest|recommend)\b", text, re.IGNORECASE):
            return Route("ambiguous")
        return Route("out_of_scope")
