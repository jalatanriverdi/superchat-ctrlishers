"""Conversation orchestration driven by validated structured plans."""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import date

from .conversation import ConversationEngine, DomainContext, Session, _amount, _say
from .canonical import canonicalize_plan
from .data_validation import DataSourceError
from .domains.common import DomainError
from .parsing import language_of
from .presentation import result_cards
from .query import filter_records
from .repositories import Repositories
from .semantic import InterpretationError, OpenAIPlanner, Planner, validate_plan
from .visual import VisualSearchService


class SemanticConversationEngine(ConversationEngine):
    def __init__(self, repositories: Repositories, planner: Planner | None = None,
                 reference_date: date = date(2026, 11, 2)):
        super().__init__(repositories, reference_date)
        self.planner = planner or OpenAIPlanner()
        self.visual = VisualSearchService(repositories.products)
        self.catalogue = {
            "cities": sorted({place["city"] for flight in repositories.flights.list_all()
                              for place in (flight["origin"], flight["destination"])}),
            "airlines": sorted({row["airline"] for row in repositories.flights.list_all()}),
            "colors": sorted({row["color"] for row in repositories.products.list_all()}),
            "categories": sorted({row["category"] for row in repositories.products.list_all()}),
            "genres": sorted({genre for row in repositories.movies.list_all()
                              for genre in row["genre"]}),
            "movie_languages": sorted({row["language"] for row in repositories.movies.list_all()}),
            "products": [{"id": row["id"], "names": row["name"],
                          "brand": row["brand"], "category": row["category"]}
                         for row in repositories.products.list_all()],
            "films": [{"id": row["id"], "title": row["title"], "genre": row["genre"]}
                      for row in repositories.movies.list_all()],
            "cinemas": [{"id": row["id"], "name": row["name"]}
                        for row in repositories.cinemas.list_all()],
            "supported_fields": {
                "flights": "origin, destination, travel_date, price_azn, stops, departure_time, airline, seats_available, baggage_kg",
                "shopping": "text, category, brand, price_azn, color, rating, stock, name, description",
                "cinema": "title, genre, rating, language, age_rating, showing_on, cinema, showtime, ticket_price_azn, seats_available",
            },
        }

    def _context(self, session: Session) -> dict:
        domains = {}
        for name in ("flights", "shopping", "cinema"):
            state = getattr(session, name)
            rows = []
            for item_id in state.result_ids[:20]:
                row = getattr(self.repositories, {"flights": "flights", "shopping": "products",
                                                   "cinema": "movies"}[name]).get(item_id)
                if row:
                    rows.append({"id": item_id, "name": row.get("title") or row.get("name", {}).get("en")
                                 or row.get("flight_number"), "names": row.get("name"),
                                 "price": row.get("price_azn"),
                                 "rating": row.get("rating"), "genre": row.get("genre")})
            domains[name] = {"criteria": state.criteria, "results": rows,
                             "selected_id": state.selected_id}
        return {"active_domain": session.active_domain,
                "language": session.language,
                "preferences": session.preferences,
                "pending_domain": session.pending_domain,
                "pending_field": session.pending_field,
                "domains": domains, "recent_messages": session.history[-6:]}

    @staticmethod
    def _drop_copied_context_filters(plan: dict, session: Session, message: str) -> dict:
        """Do not re-validate old criteria when the user revisits saved results.

        The saved shortlist already embodies those filters. Only a condition
        matching a saved field/operator/value may be removed; a novel condition
        with invalid evidence must still fail validation.
        """
        for action in plan.get("actions") or []:
            if action.get("mode") != "previous" or action.get("domain") not in {
                    "flights", "shopping", "cinema"}:
                continue
            state = getattr(session, action["domain"])
            if not state.result_ids:
                continue
            saved = state.criteria.get("filter_groups", [])
            signatures = {(condition["field"], condition["op"],
                           str(condition["value"]).casefold(),
                           str(condition.get("other", "")).casefold())
                          for group in saved for condition in group}
            groups = []
            for group in action.get("filter_groups", []):
                retained = []
                for condition in group:
                    evidence = str(condition.get("evidence", "")).strip()
                    signature = (condition.get("field"), condition.get("op"),
                                 str(condition.get("value", "")).casefold(),
                                 str(condition.get("other", "")).casefold())
                    if evidence and evidence.casefold() not in message.casefold() and signature in signatures:
                        continue
                    retained.append(condition)
                if retained:
                    groups.append(retained)
            action["filter_groups"] = groups
        return plan

    def respond(self, session: Session, message: str) -> dict:
        with session.lock:
            text = message.strip()
            detected_language = language_of(text, session.language)
            trace = {"intent": None, "actions": [], "returned_ids": [],
                     "repair_attempted": False}
            card_sections: list[dict] = []
            try:
                context = self._context(session)
                raw = self.planner.interpret(
                    text, context, self.catalogue, self.reference_date.isoformat())
                trace["model_plan"] = deepcopy(raw)
                try:
                    plan = validate_plan(self._drop_copied_context_filters(
                        canonicalize_plan(deepcopy(raw)), session, text), text)
                except InterpretationError as first_error:
                    if not hasattr(self.planner, "repair"):
                        raise
                    trace["repair_attempted"] = True
                    corrected = self.planner.repair(
                        text, context, self.catalogue, self.reference_date.isoformat(),
                        raw, str(first_error))
                    trace["repaired_plan"] = deepcopy(corrected)
                    plan = validate_plan(self._drop_copied_context_filters(
                        canonicalize_plan(deepcopy(corrected)), session, text), text)
                session.language = plan.get("language") or detected_language
                trace["intent"] = plan["status"]
                trace["actions"] = deepcopy(plan["actions"])
                status = plan["status"]
                if status == "execute":
                    parts, domains = [], []
                    for action in plan["actions"]:
                        # Each action is validated before it is run; mixed intents
                        # get independent domain state and independent results.
                        part, ids = self._execute(session, action)
                        parts.append(part)
                        domains.append(action["domain"])
                        trace["returned_ids"].append({"domain": action["domain"], "ids": ids})
                        if ids and action["operation"] in {"search", "showtimes", "return", "compare"}:
                            card_sections.append({"domain": action["domain"],
                                                  "heading": {"flights": _say(session.language, "Flights", "Uçuşlar", "Рейсы"),
                                                              "shopping": _say(session.language, "Shopping", "Alış-veriş", "Покупки"),
                                                              "cinema": _say(session.language, "Cinema", "Kino", "Кино")}[action["domain"]],
                                                  "items": result_cards(
                                                      action["domain"], ids, session.language,
                                                      self.flights, self.shopping, self.cinema)})
                        session.active_domain = action["domain"]
                    reply = "\n\n".join(parts)
                    route = "mixed" if len(domains) > 1 else domains[0]
                    for preference in plan.get("preferences", []):
                        session.preferences[preference["name"]] = preference["value"]
                else:
                    domains = []
                    route = status
                    reply = plan.get("message", "").strip() or {
                        "small_talk": _say(session.language,
                                           "Hi! I can help with flights, shopping and cinema.",
                                           "Salam! Uçuşlar, alış-veriş və kino ilə kömək edə bilərəm.",
                                           "Привет! Я могу помочь с авиарейсами, покупками и кино."),
                        "out_of_scope": _say(session.language,
                                             "That's outside my scope. I can help with flights, shopping and cinema.",
                                             "Bu mövzuda kömək edə bilmirəm. Uçuş, alış-veriş və kino ilə kömək edə bilərəm.",
                                             "Это вне моей области. Я могу помочь с рейсами, покупками и кино."),
                        "clarify": _say(session.language,
                                        "Could you clarify what you mean?",
                                        "Nə nəzərdə tutduğunuzu dəqiqləşdirə bilərsiniz?",
                                        "Уточните, пожалуйста, что вы имеете в виду?"),
                    }[status]
            except InterpretationError as exc:
                domains, route = [], "clarify"
                card_sections = []
                detail = str(exc)
                reply = (detail if detail.startswith(("Set OPENROUTER_API_KEY",
                                                      "Interpretation service returned HTTP")) else
                         _say(session.language,
                              "I couldn't reliably apply every part of that request. Could you clarify it?",
                              "Sorğunun bütün şərtlərini dəqiq tətbiq edə bilmədim. Zəhmət olmasa dəqiqləşdirin.",
                              "Не удалось надёжно учесть все условия запроса. Уточните его, пожалуйста."))
                trace["error"] = str(exc)
            except (DomainError, DataSourceError, ValueError, KeyError, TypeError) as exc:
                domains, route = [], "clarify"
                card_sections = []
                reply = _say(session.language,
                             f"I couldn't complete that request: {exc}",
                             "Sorğunu tamamlaya bilmədim. Zəhmət olmasa yenidən cəhd edin.",
                             "Не удалось выполнить запрос. Попробуйте ещё раз.")
                trace["error"] = str(exc)
            session.history.append({"role": "user", "content": text})
            assistant_entry = {"role": "assistant", "content": reply,
                               "route": route, "language": session.language}
            if card_sections:
                assistant_entry["card_sections"] = card_sections
            session.history.append(assistant_entry)
            result = {"reply": reply, "route": route, "domains": domains,
                      "history": list(session.history)}
            if os.environ.get("SUPERCHAT_DEBUG") == "1":
                result["diagnostics"] = trace
                logging.info("SuperChat plan: %s", json.dumps(trace, ensure_ascii=False, default=str))
            return result

    def respond_to_image(self, session: Session, data_url: str) -> dict:
        """Route a photo through catalogue-backed shopping without storing image bytes."""
        with session.lock:
            ids: list[str] = []
            confidence: float | None = None
            try:
                confidence, products = self.visual.search(data_url)
                if products:
                    ids = [row["id"] for row in products]
                    session.shopping.result_ids = ids
                    session.shopping.selected_id = None
                    session.shopping.criteria = {"visual_search": True}
                    session.active_domain = "shopping"
                    route = "shopping"
                    reply = _say(session.language,
                                 f"Possible catalogue matches (estimated confidence {confidence:.0%}):",
                                 f"Kataloqda mümkün uyğunluqlar (təxmini əminlik {confidence:.0%}):",
                                 f"Возможные товары из каталога (оценка уверенности {confidence:.0%}):")
                    reply += "\n" + self._format_rows("shopping", products, session.language)
                else:
                    route = "clarify"
                    reply = _say(session.language,
                                 f"I cannot match this photo confidently ({confidence:.0%}). What product is it?",
                                 f"Bu şəkli əminliklə tanıya bilmirəm ({confidence:.0%}). Bu hansı məhsuldur?",
                                 f"Не могу уверенно определить товар по фото ({confidence:.0%}). Что это за товар?")
            except (InterpretationError, DataSourceError, ValueError, KeyError, TypeError) as exc:
                route = "clarify"
                reply = _say(session.language, str(exc),
                             "Şəkli təhlil edə bilmədim. Başqa şəkil seçin və ya məhsulu təsvir edin.",
                             "Не удалось распознать фото. Выберите другое или опишите товар.")
            session.history.append({"role": "user", "content": _say(
                session.language, "[Photo uploaded]", "[Şəkil yükləndi]", "[Фото загружено]")})
            assistant_entry = {"role": "assistant", "content": reply,
                               "route": route, "language": session.language}
            if ids:
                assistant_entry["card_sections"] = [{"domain": "shopping",
                                                     "heading": _say(session.language, "Shopping", "Alış-veriş", "Покупки"),
                                                     "items": result_cards(
                    "shopping", ids, session.language, self.flights,
                    self.shopping, self.cinema)}]
            session.history.append(assistant_entry)
            result = {"reply": reply, "route": route,
                      "domains": ["shopping"] if route == "shopping" else [],
                      "history": list(session.history)}
            if os.environ.get("SUPERCHAT_DEBUG") == "1":
                result["diagnostics"] = {"intent": "visual_search", "confidence": confidence,
                                         "returned_ids": [{"domain": "shopping", "ids": ids}]}
            return result

    def respond_to_card_action(self, session: Session, domain: str,
                               item_id: str, intent: str) -> dict:
        """Execute a structured card action against a verified record."""
        allowed = {
            ("flights", "details", "F"): self.repositories.flights,
            ("shopping", "cart_add", "P"): self.repositories.products,
            ("cinema", "showtimes", "M"): self.repositories.movies,
            ("cinema", "details", "S"): self.repositories.showtimes,
        }
        repo = allowed.get((domain, intent, item_id[:1]))
        if repo is None or repo.get(item_id) is None:
            raise ValueError("That card action is unavailable.")
        with session.lock:
            user_text = {
                "details": _say(session.language, f"View {item_id}",
                                f"{item_id} barədə məlumat", f"Сведения о {item_id}"),
                "cart_add": _say(session.language, f"Add {item_id} to cart",
                                 f"{item_id} səbətə əlavə et", f"Добавь {item_id} в корзину"),
                "showtimes": _say(session.language, f"Showtimes for {item_id}",
                                  f"{item_id} seansları", f"Сеансы {item_id}"),
            }[intent]
            action = {"domain": domain, "operation": intent, "mode": "new",
                      "filter_groups": [[]] if intent == "showtimes" else [],
                      "sort_field": "", "sort_desc": False,
                      "references": [item_id], "quantity": 1 if intent == "cart_add" else 0}
            cards = []
            try:
                reply, ids = self._execute(session, action)
                session.active_domain = domain
                route = domain
                if intent == "showtimes" and ids:
                    cards = [{"domain": "cinema",
                              "heading": _say(session.language, "Cinema", "Kino", "Кино"),
                              "items": result_cards("cinema", ids, session.language,
                                                    self.flights, self.shopping, self.cinema)}]
            except (InterpretationError, DomainError, DataSourceError) as exc:
                route, ids = "clarify", []
                reply = _say(session.language, f"I couldn't complete that action: {exc}",
                             "Bu əməliyyatı yerinə yetirə bilmədim.",
                             "Не удалось выполнить это действие.")
            session.history.append({"role": "user", "content": user_text})
            answer = {"role": "assistant", "content": reply, "route": route,
                      "language": session.language}
            if cards:
                answer["card_sections"] = cards
            session.history.append(answer)
            result = {"reply": reply, "route": route,
                      "domains": [domain] if route == domain else [],
                      "history": list(session.history)}
            if os.environ.get("SUPERCHAT_DEBUG") == "1":
                result["diagnostics"] = {"intent": "card_action", "actions": [action],
                                         "returned_ids": [{"domain": domain, "ids": ids}]}
            return result

    def _rows(self, domain: str) -> list[dict]:
        if domain == "flights":
            return [self.flights.get(row["id"]) for row in self.repositories.flights.list_all()]
        if domain == "shopping":
            return self.repositories.products.list_all()
        rows = []
        for show in self.repositories.showtimes.list_all():
            rows.append(self.cinema.get_showtime(show["id"]))
        for movie in self.repositories.movies.list_all():
            if not any(row["movie_id"] == movie["id"] for row in rows):
                rows.append({"id": movie["id"], "movie": movie})
        return rows

    @staticmethod
    def _merge(previous: list[list[dict]], incoming: list[list[dict]]) -> list[list[dict]]:
        if not previous:
            return incoming
        if not incoming:
            return previous
        fields = {condition["field"] for group in incoming for condition in group}
        return [[condition for condition in old if condition["field"] not in fields] + new
                for old in previous for new in incoming]

    def _resolve(self, domain: str, refs: list[str], state: DomainContext) -> list[str]:
        ids = (state.criteria.get("showtime_ids") or state.result_ids) if domain == "cinema" else state.result_ids
        candidates = []
        for ref in refs:
            value = ref.casefold().strip()
            if value in {"it", "that", "that one", "this one"}:
                chosen = state.selected_id or (ids[0] if len(ids) == 1 else None)
            elif value in {"first", "1st", "second", "2nd", "third", "3rd", "fourth", "4th"}:
                index = {"first": 0, "1st": 0, "second": 1, "2nd": 1,
                         "third": 2, "3rd": 2, "fourth": 3, "4th": 3}[value]
                chosen = ids[index] if len(ids) > index else None
            elif value in {"cheapest", "cheaper", "lowest price"}:
                repo = (self.repositories.showtimes if domain == "cinema" and
                        state.criteria.get("showtime_ids") else {
                            "flights": self.repositories.flights,
                            "shopping": self.repositories.products,
                            "cinema": self.repositories.movies}[domain])
                priced = [(repo.get(item_id), item_id) for item_id in ids]
                priced = [(row["price_azn"], item_id) for row, item_id in priced
                          if row and "price_azn" in row]
                chosen = min(priced)[1] if priced else None
            else:
                repo = {"flights": self.repositories.flights,
                        "shopping": self.repositories.products,
                        "cinema": self.repositories.movies}[domain]
                chosen = ref.upper() if repo.get(ref.upper()) else None
                if not chosen and domain == "cinema" and self.repositories.showtimes.get(ref.upper()):
                    chosen = ref.upper()
                if not chosen:
                    named = [row["id"] for row in repo.list_all()
                             if value in [name.casefold() for name in (
                                 [row["title"]] if "title" in row else
                                 list(row["name"].values()) if "name" in row else
                                 [row.get("flight_number", "")])]]
                    chosen = named[0] if len(named) == 1 else None
                if not chosen and domain == "cinema":
                    genre_matches = [item_id for item_id in state.result_ids
                                     if value in {genre.casefold() for genre in
                                                  self.cinema.get_movie(item_id)["genre"]}]
                    chosen = genre_matches[0] if len(genre_matches) == 1 else None
            if not chosen:
                raise InterpretationError("Which item do you mean?")
            candidates.append(chosen)
        return candidates

    def _format_rows(self, domain: str, rows: list[dict], language: str) -> str:
        if not rows:
            return _say(language, "No matching records in the mock data.",
                        "Məlumatlarda uyğun nəticə yoxdur.", "В данных нет подходящих результатов.")
        if domain == "flights":
            return _say(language, "Matching flights:", "Uyğun uçuşlar:", "Подходящие рейсы:") + "\n" + "\n".join(
                self._format_flight(row, i, language) for i, row in enumerate(rows, 1))
        if domain == "shopping":
            return _say(language, "Matching products:", "Uyğun məhsullar:", "Подходящие товары:") + "\n" + "\n".join(
                self._format_product(row, language, i) for i, row in enumerate(rows, 1))
        return _say(language, "Films:", "Filmlər:", "Фильмы:") + "\n" + "\n".join(
            self._format_movie(row, language, i) for i, row in enumerate(rows, 1))

    def _execute(self, session: Session, action: dict) -> tuple[str, list[str]]:
        domain, operation = action["domain"], action["operation"]
        state = getattr(session, domain)
        language = session.language
        if operation == "cart_show":
            return self._cart_summary(session), []
        if operation in {"search", "showtimes", "return"}:
            if operation == "return" or action["mode"] == "previous":
                if not state.result_ids:
                    return _say(language, "There are no earlier results for that topic.",
                                "Bu mövzu üzrə əvvəlki nəticə yoxdur.",
                                "По этой теме пока нет предыдущих результатов."), []
                repo = {"flights": self.repositories.flights,
                        "shopping": self.repositories.products,
                        "cinema": self.repositories.movies}[domain]
                rows = [repo.get(item_id) for item_id in state.result_ids]
                rows = [row for row in rows if row]
                if action["filter_groups"]:
                    rows = filter_records(domain, rows, action["filter_groups"])
                    if rows:
                        state.result_ids = [row["id"] for row in rows]
                        state.selected_id = None
                return self._format_rows(domain, rows, language), [row["id"] for row in rows]
            mode = action["mode"]
            if (mode == "new" and session.pending_domain == domain and
                    any(condition["field"] == session.pending_field
                        for group in action["filter_groups"] for condition in group)):
                # A single slot answer must keep the search that prompted it.
                mode = "refine"
            previous = state.criteria.get("filter_groups", []) if mode == "refine" else []
            groups = self._merge(previous, action["filter_groups"])
            if domain == "flights":
                present = {condition["field"] for group in groups for condition in group
                           if condition["op"] == "eq"}
                missing = next((field for field in ("origin", "destination", "travel_date")
                                if field not in present), None)
                if missing:
                    state.criteria["filter_groups"] = groups
                    session.pending_domain, session.pending_field = domain, missing
                    questions = {
                        "origin": _say(language, "What city are you flying from?",
                                       "Hansı şəhərdən uçursunuz?", "Из какого города вы летите?"),
                        "destination": _say(language, "Where are you flying to?",
                                            "Hara uçmaq istəyirsiniz?", "Куда вы летите?"),
                        "travel_date": _say(language, "What date would you like to fly?",
                                            "Hansı tarixdə uçmaq istəyirsiniz?",
                                            "На какую дату нужен рейс?"),
                    }
                    return questions[missing], []
            source = self._rows(domain)
            if operation == "showtimes" and action["references"]:
                referenced = set(self._resolve(domain, action["references"], state))
                source = [row for row in source if row.get("movie_id") in referenced
                          or row["id"] in referenced]
            rows = filter_records(domain, source, groups,
                                  action["sort_field"], action["sort_desc"])
            state.criteria["filter_groups"] = deepcopy(groups)
            if session.pending_domain == domain:
                session.pending_domain = session.pending_field = None
            if domain == "cinema":
                if operation == "showtimes":
                    shows = [row for row in rows if "movie_id" in row]
                    state.criteria["showtime_ids"] = [row["id"] for row in shows]
                    state.result_ids = list(dict.fromkeys(row["movie_id"] for row in shows))
                    return (_say(language, "Showtimes:", "Seanslar:", "Сеансы:") + "\n" + "\n".join(
                        self._format_showtime(row, language, i) for i, row in enumerate(shows, 1))
                            if shows else _say(language,
                                               "No showtimes match those details in the dataset.",
                                               "Məlumatlarda bu şərtlərə uyğun seans yoxdur.",
                                               "В данных нет сеансов по этим условиям.")), [row["id"] for row in shows]
                movies = list({row["movie"]["id"]: row["movie"] for row in rows}.values())
                if not action["sort_field"]:
                    positions = {movie["id"]: index for index, movie in enumerate(
                        self.repositories.movies.list_all())}
                    movies.sort(key=lambda movie: positions[movie["id"]])
                state.result_ids = [row["id"] for row in movies]
                state.criteria.pop("showtime_ids", None)
                state.selected_id = None
                return self._format_rows(domain, movies, language), state.result_ids
            state.result_ids = [row["id"] for row in rows]
            state.selected_id = None
            return self._format_rows(domain, rows, language), state.result_ids
        refs = self._resolve(domain, action["references"], state)
        if operation in {"details", "availability", "reserve", "cart_add", "cart_remove"} and len(refs) != 1:
            raise InterpretationError("Which item do you mean?")
        if operation == "compare" and len(set(refs)) < 2:
            raise InterpretationError("Which two items should I compare?")
        if action["filter_groups"] and operation != "details":
            selected = (self.flights.get(refs[0]) if domain == "flights" else
                        self.shopping.get(refs[0]) if domain == "shopping" else
                        self.cinema.get_showtime(refs[0]) if refs[0].startswith("S") else
                        self.cinema.get_movie(refs[0]))
            condition_holds = bool(filter_records(domain, [selected], action["filter_groups"]))
            if not condition_holds and operation in {"reserve", "cart_add", "cart_remove"}:
                raise InterpretationError("The selected item does not meet the requested condition.")
        else:
            condition_holds = None
        if operation in {"cart_add", "cart_remove"}:
            if operation == "cart_add":
                session.cart.add(refs[0], action["quantity"])
            else:
                session.cart.remove(refs[0], action["quantity"] or None)
            state.selected_id = refs[0]
            return self._cart_summary(session), [refs[0]]
        if operation == "reserve":
            if domain == "flights":
                reservation = self.flights.reserve(refs[0], action["quantity"])
                detail = refs[0]
            else:
                reservation = self.cinema.reserve_tickets(refs[0], action["quantity"])
                show = self.cinema.get_showtime(refs[0])
                detail = f"{show['movie']['title']} at {show['cinema']['name']} on {show['date']} {show['time']}"
            state.selected_id = refs[0]
            return _say(language,
                        f"Mock reservation {reservation.id}: {reservation.quantity} seat(s) for {detail}; total {_amount(reservation.total_azn)}. No payment taken.",
                        f"Sınaq bronu {reservation.id}: {detail} üçün {reservation.quantity} yer; cəmi {_amount(reservation.total_azn)}. Ödəniş alınmadı.",
                        f"Пробная бронь {reservation.id}: {reservation.quantity} мест(а) на {detail}; всего {_amount(reservation.total_azn)}. Оплата не взималась."), refs
        if domain == "flights":
            rows = self.flights.compare(refs) if operation == "compare" else [self.flights.get(refs[0])]
            state.selected_id = refs[0] if len(refs) == 1 else None
            if operation == "availability":
                prefix = self._yes_no(language, condition_holds)
                return prefix + _say(language,
                                     f"{rows[0]['flight_number']}: {rows[0]['seats_available']} seats available.",
                                     f"{rows[0]['flight_number']}: {rows[0]['seats_available']} boş yer var.",
                                     f"{rows[0]['flight_number']}: доступно {rows[0]['seats_available']} мест."), refs
        elif domain == "shopping":
            rows = self.shopping.compare(refs) if operation == "compare" else [self.shopping.get(refs[0])]
            state.selected_id = refs[0] if len(refs) == 1 else None
            if operation == "availability":
                prefix = self._yes_no(language, condition_holds)
                name = rows[0]["name"].get(language, rows[0]["name"]["en"])
                return prefix + _say(language,
                                     f"{name}: {rows[0]['stock']} in stock.",
                                     f"{name}: stokda {rows[0]['stock']} ədəd var.",
                                     f"{name}: в наличии {rows[0]['stock']} шт."), refs
        else:
            rows = [self.cinema.get_showtime(ref) if ref.startswith("S") else self.cinema.get_movie(ref)
                    for ref in refs]
            state.selected_id = refs[0] if len(refs) == 1 else None
            if operation == "availability":
                if "movie_id" not in rows[0]:
                    raise InterpretationError("Which showtime should I check?")
                prefix = self._yes_no(language, condition_holds)
                return prefix + self._format_showtime(rows[0], language), refs
            if "movie_id" in rows[0]:
                return self._format_showtime(rows[0], language), refs
        answer = self._format_rows(domain, rows, language)
        if operation == "details" and action["filter_groups"] and len(rows) == 1:
            matched = bool(filter_records(domain, rows, action["filter_groups"]))
            answer = self._yes_no(language, matched) + answer
        return answer, refs

    @staticmethod
    def _yes_no(language: str, condition_holds: bool | None) -> str:
        if condition_holds is None:
            return ""
        return (_say(language, "Yes. ", "Bəli. ", "Да. ") if condition_holds else
                _say(language, "No. ", "Xeyr. ", "Нет. "))
