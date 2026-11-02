"""One conversational entry point over the three mock-data domains."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from threading import Lock
from uuid import uuid4

from .data_validation import DataSourceError
from .domains.cinema import CinemaService
from .domains.common import DomainError, InvalidRequest, ReservationLedger, UnknownItem
from .domains.flights import FlightService
from .domains.shopping import Cart, ShoppingService
from .localization import MOVIE_SYNOPSIS, PRODUCT_DESCRIPTIONS, label, translated
from .parsing import all_ids, language_of, mentioned_date, mentioned_id, ordinal_index, price_bounds, quantity
from .repositories import Repositories
from .routing import Router


def _say(language: str, en: str, az: str, ru: str) -> str:
    return {"az": az, "ru": ru}.get(language, en)


def _amount(value: object) -> str:
    return f"{Decimal(str(value)):.2f} AZN"


def _duration(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


@dataclass
class DomainContext:
    criteria: dict = field(default_factory=dict)
    result_ids: list[str] = field(default_factory=list)
    selected_id: str | None = None


@dataclass
class Session:
    id: str
    cart: Cart
    language: str = "en"
    active_domain: str | None = None
    pending_domain: str | None = None
    pending_field: str | None = None
    preferences: dict = field(default_factory=dict)
    flights: DomainContext = field(default_factory=DomainContext)
    shopping: DomainContext = field(default_factory=DomainContext)
    cinema: DomainContext = field(default_factory=DomainContext)
    history: list[dict] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock, repr=False)


class SessionStore:
    def __init__(self, products):
        self._products = products
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None) -> Session:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            session = Session(uuid4().hex, Cart(self._products))
            self._sessions[session.id] = session
            return session

    def reset(self, session_id: str | None) -> Session:
        with self._lock:
            if session_id:
                self._sessions.pop(session_id, None)
            session = Session(uuid4().hex, Cart(self._products))
            self._sessions[session.id] = session
            return session


class ConversationEngine:
    def __init__(self, repositories: Repositories, reference_date: date = date(2026, 11, 2)):
        self.repositories = repositories
        self.reference_date = reference_date
        self.router = Router(repositories, reference_date)
        self.ledger = ReservationLedger()
        self.flights = FlightService(repositories.flights, self.ledger)
        self.shopping = ShoppingService(repositories.products)
        self.cinema = CinemaService(
            repositories.movies, repositories.cinemas,
            repositories.showtimes, self.ledger,
        )
        self.sessions = SessionStore(repositories.products)
        self._cities = sorted({
            place["city"] for flight in repositories.flights.list_all()
            for place in (flight["origin"], flight["destination"])
        }, key=len, reverse=True)
        self._airlines = sorted({flight["airline"] for flight in repositories.flights.list_all()}, key=len, reverse=True)
        self._brands = sorted({product["brand"] for product in repositories.products.list_all()}, key=len, reverse=True)
        self._colors = sorted({product["color"] for product in repositories.products.list_all()}, key=len, reverse=True)
        self._categories = sorted({product["category"] for product in repositories.products.list_all()}, key=len, reverse=True)
        self._titles = sorted({movie["title"] for movie in repositories.movies.list_all()}, key=len, reverse=True)
        self._genres = sorted({genre for movie in repositories.movies.list_all() for genre in movie["genre"]}, key=len, reverse=True)
        self._movie_languages = sorted({movie["language"] for movie in repositories.movies.list_all()}, key=len, reverse=True)

    def respond(self, session: Session, message: str) -> dict:
        with session.lock:
            text = message.strip()
            session.language = language_of(text, session.language)
            known_domains = {name for name in ("flights", "shopping", "cinema")
                             if getattr(session, name).result_ids or getattr(session, name).criteria}
            route = self.router.classify(
                text, session.active_domain, session.pending_domain, known_domains,
                session.pending_field,
            )
            if route.category == "small_talk":
                if re.fullmatch(r"(?:thanks|thank you)\s*[.!?]*", text, re.IGNORECASE):
                    reply = _say(session.language, "You're welcome.", "Buyurun.", "Пожалуйста.")
                elif re.fullmatch(r"(?:hi|hello|hey)\s*[.!?]*", text, re.IGNORECASE):
                    reply = _say(session.language, "Hi! How can I help?", "Salam! Necə kömək edə bilərəm?", "Здравствуйте! Чем могу помочь?")
                else:
                    reply = _say(session.language,
                                 "I can help with flights, shopping, and cinema.",
                                 "Uçuş, alış-veriş və kino ilə kömək edə bilərəm.",
                                 "Я могу помочь с авиабилетами, покупками и кино.")
            elif route.category == "ambiguous":
                if re.search(r"\b(book|reserve)\b", text, re.IGNORECASE):
                    reply = _say(session.language,
                                 "Which flight, or which film and showtime, would you like to reserve?",
                                 "Hansı uçuşu və ya hansı film və seansı bron etmək istəyirsiniz?",
                                 "Какой рейс или фильм и сеанс вы хотите забронировать?")
                else:
                    reply = _say(session.language,
                                 "Do you mean flights, shopping, or cinema?",
                                 "Uçuş, alış-veriş, yoxsa kino nəzərdə tutursunuz?",
                                 "Вы имеете в виду авиабилеты, покупки или кино?")
            elif route.category == "out_of_scope":
                reply = _say(session.language,
                             "That's outside my scope. I can help with flights, shopping, and cinema.",
                             "Bu, kömək edə biləcəyim mövzulara daxil deyil. Uçuş, alış-veriş və kino ilə kömək edə bilərəm.",
                             "Это вне моих возможностей. Я могу помочь с авиабилетами, покупками и кино.")
            else:
                parts = []
                for domain in route.domains:
                    try:
                        parts.append(getattr(self, f"_handle_{domain}")(session, text))
                    except (DomainError, DataSourceError) as exc:
                        parts.append(_say(session.language,
                                          f"I couldn't complete that request: {exc}",
                                          "Sorğunuzu tamamlamaq mümkün olmadı. Zəhmət olmasa yenidən yoxlayın.",
                                          "Не удалось выполнить запрос. Пожалуйста, уточните его."))
                    session.active_domain = domain
                reply = "\n\n".join(parts)
            session.history.append({"role": "user", "content": text})
            session.history.append({"role": "assistant", "content": reply, "route": route.category})
            return {"reply": reply, "route": route.category,
                    "domains": list(route.domains), "history": list(session.history)}

    def _find_named(self, text: str, names: list[str]) -> str | None:
        for name in names:
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
                return name
        return None

    def _flight_places(self, text: str, context: DomainContext,
                       pending_field: str | None = None) -> None:
        for key, marker in (("origin", "from"), ("destination", "to")):
            for city in self._cities:
                if re.search(rf"\b{marker}\s+{re.escape(city)}\b", text, re.IGNORECASE):
                    context.criteria[key] = city
                    break
            else:
                # Unknown destinations are valid search requests: the repository
                # must return an empty result, not a fabricated route.
                match = re.search(rf"\b{marker}\s+([A-Za-z]+)\b", text, re.IGNORECASE)
                if match:
                    context.criteria[key] = match.group(1)
        for city in self._cities:
            if re.search(rf"\bfor\s+(?:the\s+)?{re.escape(city)}\b", text, re.IGNORECASE):
                context.criteria["destination"] = city
                break
        mentioned = [city for city in self._cities if re.search(
            rf"\b{re.escape(city)}\b", text, re.IGNORECASE)]
        mentioned.sort(key=lambda city: text.casefold().find(city.casefold()))
        if (pending_field in {"origin", "destination"} and len(mentioned) == 1
                and not re.search(r"\b(from|to|for)\b", text, re.IGNORECASE)):
            context.criteria[pending_field] = mentioned[0]
        if len(mentioned) == 2 and "origin" not in context.criteria:
            context.criteria["origin"] = mentioned[0]
        if len(mentioned) == 2 and "destination" not in context.criteria:
            context.criteria["destination"] = mentioned[1]
        if len(mentioned) == 1:
            if "origin" not in context.criteria and "destination" in context.criteria:
                if mentioned[0] != context.criteria["destination"]:
                    context.criteria["origin"] = mentioned[0]
            elif "destination" not in context.criteria and "origin" in context.criteria:
                if mentioned[0] != context.criteria["origin"]:
                    context.criteria["destination"] = mentioned[0]

    def _flight_reference(self, context: DomainContext, text: str) -> str | None:
        explicit = mentioned_id(text, "F")
        if explicit:
            return explicit
        index = ordinal_index(text)
        if index is not None:
            return context.result_ids[index] if index < len(context.result_ids) else None
        if re.search(r"\b(cheaper|cheapest|lowest price)\b", text, re.IGNORECASE) and context.result_ids:
            return min(context.result_ids, key=lambda item_id: Decimal(str(self.flights.get(item_id)["price_azn"])))
        if re.search(r"\b(it|that one|this one)\b", text, re.IGNORECASE):
            return context.selected_id or (context.result_ids[0] if len(context.result_ids) == 1 else None)
        return context.selected_id or (context.result_ids[0] if len(context.result_ids) == 1 else None)

    def _format_flight(self, flight: dict, number: int | None = None, language: str = "en") -> str:
        prefix = f"{number}. " if number is not None else ""
        stops = _say(language, "direct", "birbaşa", "прямой") if flight["stops"] == 0 else (
            f"{flight['stops']} " + _say(language, "stop", "dayanacaq", "пересадка") +
            (f" {_say(language, 'via', 'vasitəsilə', 'через')} {flight['via']}" if flight["via"] else ""))
        return (f"{prefix}{flight['airline']} {flight['flight_number']} ({flight['id']}): "
                f"{flight['origin']['city']} → {flight['destination']['city']}, "
                f"{flight['departure_local'].replace('T', ' ')} → {flight['arrival_local'].replace('T', ' ')}, "
                f"{_duration(flight['duration_min'])}, {stops}; "
                f"{_amount(flight['price_azn'])}; "
                f"{_say(language, 'baggage', 'baqaj', 'багаж')} {flight['baggage_kg']} kg; "
                f"{flight['seats_available']} {_say(language, 'seats left', 'boş yer', 'свободных мест')}.")

    def _handle_flights(self, session: Session, text: str) -> str:
        context = session.flights
        lower = text.casefold()
        if re.search(r"\b(book|reserve)\b", lower):
            flight_id = self._flight_reference(context, text)
            if not flight_id:
                return _say(session.language, "Which flight should I reserve?",
                            "Hansı uçuşu bron edim?", "Какой рейс забронировать?")
            reservation = self.flights.reserve(flight_id, quantity(text))
            context.selected_id = flight_id
            return _say(session.language,
                        f"Mock reservation {reservation.id}: {reservation.quantity} seat(s) on {flight_id}, total {_amount(reservation.total_azn)}. No payment taken.",
                        f"Sınaq bronu {reservation.id}: {flight_id} üçün {reservation.quantity} yer, cəmi {_amount(reservation.total_azn)}. Ödəniş alınmadı.",
                        f"Пробная бронь {reservation.id}: {reservation.quantity} мест(а) на {flight_id}, всего {_amount(reservation.total_azn)}. Оплата не требуется.")
        if "compare" in lower:
            ids = all_ids(text, "F")
            if not ids and re.search(r"\b(first two|these two|both)\b", lower) and len(context.result_ids) >= 2:
                ids = context.result_ids[:2]
            if len(ids) < 2:
                return _say(session.language, "Which two flights should I compare?",
                            "Hansı iki uçuşu müqayisə edim?", "Какие два рейса сравнить?")
            return "\n".join(self._format_flight(item, index, session.language)
                             for index, item in enumerate(self.flights.compare(ids), 1))

        # A reference question should use the previous search rather than
        # silently replacing it with a new search.
        reference = self._flight_reference(context, text)
        is_reference = (mentioned_id(text, "F") is not None or ordinal_index(text) is not None or
                        re.search(r"\b(cheaper|cheapest|is it|baggage|how many seats|details)\b", lower))
        if is_reference and context.result_ids or mentioned_id(text, "F"):
            if not reference:
                return _say(session.language, "Which flight do you mean?",
                            "Hansı uçuşu nəzərdə tutursunuz?", "Какой рейс вы имеете в виду?")
            context.selected_id = reference
            flight = self.flights.get(reference)
            if "direct" in lower:
                direct_answer = ("direct" if flight["stops"] == 0 else
                                 f"not direct ({flight['stops']} stop via {flight['via']})")
                return _say(session.language,
                            f"{flight['flight_number']} is {direct_answer}.",
                            f"{flight['flight_number']}: {'birbaşa uçuşdur' if flight['stops'] == 0 else 'birbaşa deyil'}.",
                            f"{flight['flight_number']}: {'прямой рейс' if flight['stops'] == 0 else 'рейс с пересадкой'}.")
            return self._format_flight(flight, language=session.language)

        self._flight_places(
            text, context,
            session.pending_field if session.pending_domain == "flights" else None,
        )
        travel_date = mentioned_date(text, self.reference_date)
        if travel_date:
            context.criteria["travel_date"] = travel_date
        lower_price, upper_price = price_bounds(text)
        if lower_price is not None:
            context.criteria["min_price"] = lower_price
        if upper_price is not None:
            context.criteria["max_price"] = upper_price
        if re.search(r"\b(direct|nonstop|non-stop)\b", lower):
            context.criteria["max_stops"] = 0
            if "prefer" in lower:
                session.preferences["direct_flights"] = True
        stop_match = re.search(r"\b(?:max(?:imum)?|up to)\s+(\d+)\s+stops?\b", lower)
        if stop_match:
            context.criteria["max_stops"] = int(stop_match.group(1))
        after = re.search(r"\bafter\s+(\d{1,2}:\d{2})\b", lower)
        before = re.search(r"\bbefore\s+(\d{1,2}:\d{2})\b", lower)
        if after:
            context.criteria["departure_after"] = after.group(1).zfill(5)
        if before:
            context.criteria["departure_before"] = before.group(1).zfill(5)
        airline = self._find_named(text, self._airlines)
        if airline:
            context.criteria["airline"] = airline
        sort = re.search(r"\bsort(?:ed)?\s+by\s+(price|stops?|departure|airline)\b", lower)
        if sort:
            context.criteria["sort_by"] = {"stops": "stops", "stop": "stops", "departure": "departure_time"}.get(sort.group(1), sort.group(1))
        elif "earliest" in lower:
            context.criteria["sort_by"] = "departure_time"
        elif "cheapest" in lower:
            context.criteria["sort_by"] = "price"
        if "origin" not in context.criteria:
            session.pending_domain = "flights"
            session.pending_field = "origin"
            return _say(session.language, "What city are you flying from?",
                        "Hansı şəhərdən uçursunuz?", "Из какого города вы летите?")
        if "destination" not in context.criteria:
            session.pending_domain = "flights"
            session.pending_field = "destination"
            return _say(session.language, "What is your destination?",
                        "Hara uçmaq istəyirsiniz?", "Куда вы летите?")
        if "travel_date" not in context.criteria:
            session.pending_domain = "flights"
            session.pending_field = "travel_date"
            return _say(session.language, "What date would you like to fly?",
                        "Hansı tarixdə uçmaq istəyirsiniz?", "На какую дату нужен рейс?")
        results = self.flights.search(**context.criteria)
        if session.pending_domain == "flights":
            session.pending_domain = None
            session.pending_field = None
        context.result_ids = [item["id"] for item in results]
        context.selected_id = None
        if not results:
            return _say(session.language, "No flights match those details in the dataset.",
                        "Bu şərtlərə uyğun uçuş tapılmadı.", "В данных нет рейсов по этим условиям.")
        heading = _say(session.language, "Matching flights:", "Uyğun uçuşlar:", "Подходящие рейсы:")
        return heading + "\n" + "\n".join(
            self._format_flight(item, index, session.language) for index, item in enumerate(results, 1))

    def _product_term(self, text: str) -> str | None:
        terms = ("wireless headphones", "wireless earbuds", "coffee machine", "board game",
                 "running shoes", "portable speaker", "smartphone", "smartwatch",
                 "headphones", "earbuds", "laptops", "laptop", "backpacks", "backpack",
                 "speakers", "speaker", "phones", "phone", "shoes", "game")
        known = self._find_named(text, list(terms))
        if known:
            return known
        match = re.search(
            r"\b(?:show me|find|search for|do you have)\s+(.+)", text, re.IGNORECASE
        )
        if not match:
            return None
        candidate = match.group(1)
        candidate = re.split(r"\b(?:under|below|over|above|between|in|by|from)\b", candidate,
                             maxsplit=1, flags=re.IGNORECASE)[0]
        candidate = re.sub(r"\b(?:some|any|a|an|the|products?|items?)\b", "", candidate,
                           flags=re.IGNORECASE).strip(" .,?!")
        return candidate or None

    def _product_reference(self, context: DomainContext, text: str) -> str | None:
        explicit = mentioned_id(text, "P")
        if explicit:
            return explicit
        index = ordinal_index(text)
        if index is not None:
            return context.result_ids[index] if index < len(context.result_ids) else None
        if re.search(r"\b(cheaper|cheapest)\b", text, re.IGNORECASE) and context.result_ids:
            return min(context.result_ids, key=lambda item_id: Decimal(str(self.shopping.get(item_id)["price_azn"])))
        return context.selected_id or (context.result_ids[0] if len(context.result_ids) == 1 else None)

    def _format_product(self, product: dict, language: str, number: int | None = None) -> str:
        prefix = f"{number}. " if number is not None else ""
        name = product["name"].get(language, product["name"]["en"])
        description = translated(PRODUCT_DESCRIPTIONS, product["id"], language,
                                 product["description"])
        return (f"{prefix}{name} ({product['id']}) — {product['brand']}, {label(product['color'], language)}; "
                f"{_amount(product['price_azn'])}; "
                f"{_say(language, 'rating', 'reytinq', 'рейтинг')} {product['rating']}; "
                f"{_say(language, 'stock', 'stok', 'в наличии')} {product['stock']}. "
                f"{description}")

    def _cart_summary(self, session: Session) -> str:
        summary = session.cart.summary()
        if not summary["items"]:
            return _say(session.language, "Your cart is empty.", "Səbətiniz boşdur.", "Ваша корзина пуста.")
        lines = [_say(session.language, "Cart:", "Səbət:", "Корзина:")]
        for item in summary["items"]:
            product = item["product"]
            lines.append(f"- {product['name'].get(session.language, product['name']['en'])} "
                         f"× {item['quantity']} = {_amount(item['subtotal_azn'])}")
        lines.append(_say(session.language, f"Total: {_amount(summary['total_azn'])}",
                          f"Cəmi: {_amount(summary['total_azn'])}",
                          f"Итого: {_amount(summary['total_azn'])}"))
        return "\n".join(lines)

    def _handle_shopping(self, session: Session, text: str) -> str:
        context = session.shopping
        lower = text.casefold()
        if re.search(r"\b(add|put)\b", lower) and "cart" in lower:
            product_id = self._product_reference(context, text)
            if not product_id:
                return _say(session.language, "Which product should I add to the cart?",
                            "Səbətə hansı məhsulu əlavə edim?", "Какой товар добавить в корзину?")
            session.cart.add(product_id, quantity(text))
            context.selected_id = product_id
            return self._cart_summary(session)
        if re.search(r"\b(remove|delete)\b", lower):
            product_id = self._product_reference(context, text)
            if not product_id:
                return _say(session.language, "Which product should I remove from the cart?",
                            "Səbətdən hansı məhsulu silim?", "Какой товар удалить из корзины?")
            session.cart.remove(product_id)
            return self._cart_summary(session)
        if "cart" in lower or "total" in lower:
            return self._cart_summary(session)
        if "compare" in lower:
            ids = all_ids(text, "P")
            if not ids and re.search(r"\b(first two|these two|both)\b", lower) and len(context.result_ids) >= 2:
                ids = context.result_ids[:2]
            if len(ids) < 2:
                return _say(session.language, "Which two products should I compare?",
                            "Hansı iki məhsulu müqayisə edim?", "Какие два товара сравнить?")
            return "\n".join(self._format_product(item, session.language, index)
                             for index, item in enumerate(self.shopping.compare(ids), 1))

        product_id = self._product_reference(context, text)
        if (mentioned_id(text, "P") or ordinal_index(text) is not None or
                re.search(r"\b(in stock|available|details|tell me about|cheaper one)\b", lower)):
            if not product_id:
                return _say(session.language, "Which product do you mean?",
                            "Hansı məhsulu nəzərdə tutursunuz?", "Какой товар вы имеете в виду?")
            context.selected_id = product_id
            product = self.shopping.get(product_id)
            if "stock" in lower or "available" in lower:
                return _say(session.language,
                            f"{product['name']['en']}: {product['stock']} in stock.",
                            f"{product['name']['az']}: stokda {product['stock']} ədəd var.",
                            f"{product['name']['ru']}: в наличии {product['stock']} шт.")
            return self._format_product(product, session.language)

        term = self._product_term(text)
        if term:
            context.criteria["text"] = term
        category = self._find_named(text, self._categories)
        brand = self._find_named(text, self._brands)
        color = self._find_named(text, self._colors)
        if category:
            context.criteria["category"] = category
        if brand:
            context.criteria["brand"] = brand
        if color:
            context.criteria["color"] = color
        lower_price, upper_price = price_bounds(text)
        if lower_price is not None:
            context.criteria["min_price"] = lower_price
        if upper_price is not None:
            context.criteria["max_price"] = upper_price
        results = self.shopping.search(**context.criteria)
        context.result_ids = [item["id"] for item in results]
        context.selected_id = None
        if not results:
            return _say(session.language, "No products match those details in the dataset.",
                        "Bu şərtlərə uyğun məhsul tapılmadı.", "В данных нет товаров по этим условиям.")
        return _say(session.language, "Matching products:", "Uyğun məhsullar:", "Подходящие товары:") + "\n" + "\n".join(
            self._format_product(item, session.language, index) for index, item in enumerate(results, 1))

    def _movie_candidates(self, context: DomainContext, text: str) -> list[dict]:
        explicit_id = mentioned_id(text, "M")
        if explicit_id:
            return [self.cinema.get_movie(explicit_id)]
        title = self._find_named(text, self._titles)
        if title:
            return [movie for movie in self.repositories.movies.list_all() if movie["title"] == title]
        index = ordinal_index(text)
        if index is not None and index < len(context.result_ids):
            return [self.cinema.get_movie(context.result_ids[index])]
        genre = self._find_named(text, self._genres)
        if genre:
            previous = [self.cinema.get_movie(movie_id) for movie_id in context.result_ids]
            matches = [movie for movie in previous if genre.casefold() in
                       {item.casefold() for item in movie["genre"]}]
            return matches or self.cinema.find_movies(genre=genre)
        if context.selected_id:
            return [self.cinema.get_movie(context.selected_id)]
        if len(context.result_ids) == 1:
            return [self.cinema.get_movie(context.result_ids[0])]
        return []

    def _format_showtime(self, show: dict, language: str, number: int | None = None) -> str:
        prefix = f"{number}. " if number is not None else ""
        return (f"{prefix}{show['movie']['title']} — {show['cinema']['name']}, "
                f"{show['date']} {show['time']}, {show['hall']} ({show['id']}); "
                f"{_amount(show['price_azn'])}; {show['seats_available']} "
                f"{_say(language, 'seats left', 'boş yer', 'свободных мест')}.")

    def _format_movie(self, movie: dict, language: str, number: int | None = None) -> str:
        prefix = f"{number}. " if number is not None else ""
        synopsis = translated(MOVIE_SYNOPSIS, movie["id"], language, movie["synopsis"])
        return (f"{prefix}{movie['title']} ({movie['id']}) — "
                f"{', '.join(label(genre, language) for genre in movie['genre'])}; "
                f"{_say(language, 'rating', 'reytinq', 'рейтинг')} {movie['rating']}; "
                f"{label(movie['language'], language)}; {movie['age_rating']}. {synopsis}")

    def _handle_cinema(self, session: Session, text: str) -> str:
        context = session.cinema
        lower = text.casefold()
        showing_on = mentioned_date(text, self.reference_date)
        if re.search(r"\b(book|reserve)\b", lower):
            showtime_id = mentioned_id(text, "S")
            if not showtime_id:
                candidates = self._movie_candidates(context, text)
                if len(candidates) == 1:
                    shows = self.cinema.showtimes_for(candidates[0]["id"], showing_on=showing_on)
                    if len(shows) == 1:
                        showtime_id = shows[0]["id"]
            if not showtime_id:
                showtime_id = context.criteria.get("selected_showtime")
            if not showtime_id:
                return _say(session.language, "Which film and showtime should I reserve?",
                            "Hansı film və seansı bron edim?", "Какой фильм и сеанс забронировать?")
            reservation = self.cinema.reserve_tickets(showtime_id, quantity(text))
            context.criteria["selected_showtime"] = showtime_id
            show = self.cinema.get_showtime(showtime_id)
            return _say(session.language,
                        f"Mock reservation {reservation.id}: {reservation.quantity} ticket(s) for {show['movie']['title']} at {show['cinema']['name']} on {show['date']} {show['time']}, total {_amount(reservation.total_azn)}. No payment taken.",
                        f"Sınaq bronu {reservation.id}: {show['movie']['title']} üçün {reservation.quantity} bilet, {show['date']} {show['time']}, cəmi {_amount(reservation.total_azn)}. Ödəniş alınmadı.",
                        f"Пробная бронь {reservation.id}: {reservation.quantity} билета на {show['movie']['title']}, {show['date']} {show['time']}, всего {_amount(reservation.total_azn)}. Оплата не требуется.")

        showtime_id = mentioned_id(text, "S")
        if showtime_id:
            show = self.cinema.get_showtime(showtime_id)
            context.selected_id = show["movie_id"]
            context.criteria["selected_showtime"] = showtime_id
            return self._format_showtime(show, session.language)

        showtime_request = bool(re.search(r"\b(showtimes?|cinemas?|where|seats?|tickets?|available|playing at)\b", lower))
        title = self._find_named(text, self._titles)
        genre = self._find_named(text, self._genres)
        if showtime_request or title and not re.search(r"\b(show me|list|find)\b", lower):
            candidates = self._movie_candidates(context, text)
            if not candidates:
                return _say(session.language, "Which film would you like showtimes for?",
                            "Hansı filmin seanslarına baxmaq istəyirsiniz?",
                            "Для какого фильма показать сеансы?")
            shows = [show for movie in candidates
                     for show in self.cinema.showtimes_for(movie["id"], showing_on=showing_on)]
            context.result_ids = [movie["id"] for movie in candidates]
            context.selected_id = candidates[0]["id"] if len(candidates) == 1 else None
            if len(shows) == 1:
                context.criteria["selected_showtime"] = shows[0]["id"]
            else:
                context.criteria.pop("selected_showtime", None)
            if not shows:
                return _say(session.language, "No showtimes match those details in the dataset.",
                            "Bu şərtlərə uyğun seans tapılmadı.", "В данных нет подходящих сеансов.")
            return _say(session.language, "Showtimes:", "Seanslar:", "Сеансы:") + "\n" + "\n".join(
                self._format_showtime(show, session.language, index)
                for index, show in enumerate(shows, 1))

        if showing_on:
            context.criteria["showing_on"] = showing_on
        elif re.search(r"\b(show me|list|find)\b", lower):
            context.criteria.pop("showing_on", None)
        if genre:
            context.criteria["genre"] = genre
        elif re.search(r"\b(show me|list|find|playing)\b", lower):
            context.criteria.pop("genre", None)
        movie_language = self._find_named(text, self._movie_languages)
        if movie_language:
            context.criteria["language"] = movie_language
        rating_match = re.search(
            r"\b(?:rating|rated)\s+(?:(?:above|over|at least)\s+)?(\d+(?:\.\d+)?)\b|"
            r"\b(?:above|over|at least)\s+(\d+(?:\.\d+)?)\b", lower
        )
        if rating_match:
            context.criteria["min_rating"] = rating_match.group(1) or rating_match.group(2)
        filters = {key: value for key, value in context.criteria.items()
                   if key in {"genre", "min_rating", "language", "showing_on"}}
        movies = self.cinema.find_movies(**filters)
        context.result_ids = [movie["id"] for movie in movies]
        context.selected_id = None
        context.criteria.pop("selected_showtime", None)
        if not movies:
            return _say(session.language, "No films match those details in the dataset.",
                        "Bu şərtlərə uyğun film tapılmadı.", "В данных нет подходящих фильмов.")
        lines = [_say(session.language, "Films:", "Filmlər:", "Фильмы:")]
        for index, movie in enumerate(movies, 1):
            lines.append(self._format_movie(movie, session.language, index))
            if showing_on:
                for show in self.cinema.showtimes_for(movie["id"], showing_on=showing_on):
                    lines.append("   " + self._format_showtime(show, session.language))
        return "\n".join(lines)
