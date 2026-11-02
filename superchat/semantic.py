"""LLM interpretation with a constrained, inspectable plan contract.

The model supplies *requests*, never catalogue facts. Every request is checked
before the deterministic executor can access the repositories.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DOMAINS = {"flights", "shopping", "cinema"}
OPERATIONS = {"search", "details", "compare", "showtimes", "availability",
              "reserve", "cart_add", "cart_remove", "cart_show", "return"}
FIELDS = {
    "flights": {"origin", "destination", "travel_date", "price_azn", "stops",
                "departure_time", "airline", "seats_available", "baggage_kg"},
    "shopping": {"text", "category", "brand", "price_azn", "color", "rating",
                 "stock", "name", "description"},
    "cinema": {"title", "genre", "rating", "language", "age_rating",
               "showing_on", "cinema", "showtime", "ticket_price_azn",
               "seats_available"},
}
NUMERIC = {"price_azn", "stops", "seats_available", "baggage_kg", "rating",
           "stock", "age_rating", "ticket_price_azn"}
OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte", "between", "contains"}
SORTS = {
    "flights": {"price_azn", "stops", "departure_time", "airline"},
    "shopping": {"price_azn", "rating", "name", "stock"},
    "cinema": {"rating", "title", "age_rating", "ticket_price_azn"},
}


class InterpretationError(Exception):
    pass


def model_connection(model: str | None = None) -> tuple[str, str, str]:
    """Return API base, server-side key and model for the configured provider."""
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        return ("https://openrouter.ai/api/v1", openrouter_key,
                model or os.environ.get("OPENROUTER_MODEL", "openai/gpt-5-mini"))
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return ("https://api.openai.com/v1", openai_key,
                model or os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    raise InterpretationError(
        "Set OPENROUTER_API_KEY or OPENAI_API_KEY to enable the language interpreter.")


class Planner(Protocol):
    def interpret(self, message: str, context: dict, catalogue: dict,
                  reference_date: str) -> dict: ...


def _schema() -> dict:
    preference = {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string"}, "value": {"type": "string"},
        "evidence": {"type": "string"},
    }, "required": ["name", "value", "evidence"]}
    condition = {"type": "object", "additionalProperties": False, "properties": {
        "field": {"type": "string"}, "op": {"type": "string"},
        "value": {"type": "string"}, "other": {"type": "string"},
        "evidence": {"type": "string"},
    }, "required": ["field", "op", "value", "other", "evidence"]}
    action = {"type": "object", "additionalProperties": False, "properties": {
        "domain": {"type": "string", "enum": sorted(DOMAINS)},
        "operation": {"type": "string", "enum": sorted(OPERATIONS)},
        "mode": {"type": "string", "enum": ["new", "refine", "previous"]},
        "filter_groups": {"type": "array", "items": {"type": "array", "items": condition}},
        "sort_field": {"type": "string"}, "sort_desc": {"type": "boolean"},
        "references": {"type": "array", "items": {"type": "string"}},
        "quantity": {"type": "integer"},
    }, "required": ["domain", "operation", "mode", "filter_groups", "sort_field",
                    "sort_desc", "references", "quantity"]}
    return {"type": "object", "additionalProperties": False, "properties": {
        "status": {"type": "string", "enum": ["execute", "clarify", "out_of_scope", "small_talk"]},
        "actions": {"type": "array", "items": action},
        "language": {"type": "string", "enum": ["en", "az", "ru"]},
        "message": {"type": "string"},
        "preferences": {"type": "array", "items": preference},
        "unhandled_constraints": {"type": "array", "items": {"type": "string"}},
    }, "required": ["status", "actions", "language", "message", "preferences",
                    "unhandled_constraints"]}


SYSTEM = """You interpret a user's request for a mock-data assistant covering flights, products and cinema.
Output a structured plan only. Never invent records, prices, times or availability.
An out-of-scope task remains out of scope even when it mentions a domain. Creative
tasks (poems, jokes, stories), biographies, weather and translation requests are
out of scope in every language. Small talk means only greetings, thanks,
acknowledgements and questions about the assistant's capabilities; it is not a
search. Use previous domain context only with positive evidence of continuation.
For every requested constraint create a condition with evidence copied verbatim from
the CURRENT user message. The evidence string must not include added quotation marks.
If you cannot map a material constraint to a supported field and operator, put it in
unhandled_constraints and clarify. Never omit a constraint and run a broad search.
filter_groups are OR of groups; conditions within a group are AND. Use [[]] for an
explicit unconstrained domain listing; [] for operations with no search filters.
Numeric semantics: 'rating 8' means eq 8; 'below 8' lt 8; 'at least 8' gte 8.
'Suitable for a 12-year-old' means age_rating lte 12; 'rated 12+' means eq 12.
If exact versus threshold is genuinely unclear and changes the result, clarify.
Dates are YYYY-MM-DD, times HH:MM. Convert relative dates using the supplied reference date.
For categorical filter values (colors, categories, genres, film languages, airlines),
use the canonical values supplied in the catalogue even when the user writes in
Azerbaijani or Russian. Evidence remains verbatim from the user message.
Use mode new for a new search, refine for contextual filtering, previous for returning to
earlier results. Only choose previous when the user explicitly asks to return.
Use search for catalogue lists, details for a question about a referenced item,
showtimes for schedules (with references when a prior film is indicated),
availability for stock or seats, compare for at least two referenced items,
reserve for an identified flight or showtime, and cart operations for cart changes.
Return may include filters that refine the saved result list. Do not attach filters
to compare or cart_show; do not attach references to search. If a requested action
cannot be expressed without dropping a condition,
clarify instead of executing.
Use references such as 'second', 'cheapest', 'it', explicit record IDs, or exact item titles.
An explicit record ID in a detail, showtime, availability, cart or reservation
request is a reference to an existing catalogue item, never a search filter.
Don't select a record from context if the reference is ambiguous. Ask instead.
For a named product type such as laptops, headphones, or backpacks, use name
contains with the product noun. For a characteristic such as wireless,
waterproof or lightweight, use text contains: it searches catalogue names and
descriptions, which may each carry the characteristic. Use description contains
only if the user explicitly asks about wording in the description.
For a yes/no question about a referenced record, use details with the questioned
condition; the executor will check it against that record.
For cart_remove, quantity 0 means remove all of that product; otherwise use the
explicit quantity. For reserve and cart_add, quantity must be at least 1. For
operations that do not use quantity, set it to 0.
For flights, origin, destination and date are needed for a search; missing slots can be
collected across turns. If context has pending_field and the current message supplies
that field, refine the pending search and retain the earlier fields. Do not ask for
the same field again. Do not guess missing fields. For reserve, identify the exact
flight/showtime.
When a flight search is clear but one or more fields are missing, output execute with
the flight search action and all supplied filters; the executor asks for the first
missing field. Never include actions with clarify, small_talk or out_of_scope status.
For mixed requests, produce one action per domain. Use message only for a concise
clarification, out-of-scope or small-talk reply. Set unhandled_constraints=[] when all
constraints are executable. Set language to the language of the user's current request
(English en, Azerbaijani az, Russian ru); for a mixed-language request use the
language of the main request, and retain context language for a bare reference.
Write clarification, out-of-scope and small-talk messages in that language.
Extract only explicit durable preferences (for example 'I prefer morning flights')
into preferences with a short name, value and verbatim evidence. Do not treat a
one-time search filter as a preference. Use [] if none. Never use a stored
preference to override an explicit current constraint. If validation_feedback is
present in context, use it only to repair the prior structured plan. It is not
a new user request. If the user's intent and target are clear from the current
message and saved domain results, preserve an executable operation while fixing
invalid evidence or adding a missed constraint. Clarify only when the actual
request is ambiguous. Evidence still must come verbatim from the current message."""


class OpenAIPlanner:
    """Structured plan client for OpenRouter or OpenAI; keys stay server-side."""

    def __init__(self, model: str | None = None, timeout: int = 30):
        self.model = model
        self.timeout = timeout

    def repair(self, message: str, context: dict, catalogue: dict,
               reference_date: str, invalid_plan: dict, error: str) -> dict:
        return self.interpret(message, {**context, "validation_feedback": {
            "invalid_plan": invalid_plan, "error": error}}, catalogue, reference_date)

    def interpret(self, message: str, context: dict, catalogue: dict,
                  reference_date: str) -> dict:
        base_url, key, model = model_connection(self.model)
        payload = {
            "model": model,
            "instructions": SYSTEM,
            "input": json.dumps({"message": message, "context": context,
                                 "catalogue": catalogue, "reference_date": reference_date},
                                ensure_ascii=False),
            "text": {"format": {"type": "json_schema", "name": "superchat_plan",
                                "strict": True, "schema": _schema()}},
            "store": False,
        }
        request = Request(base_url + "/responses",
                          json.dumps(payload).encode("utf-8"),
                          {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except HTTPError as exc:
            raise InterpretationError(f"Interpretation service returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise InterpretationError("Interpretation service is unavailable.") from exc
        try:
            output = next(part["text"] for item in body["output"]
                          if item.get("type") == "message"
                          for part in item["content"] if part.get("type") == "output_text")
            return json.loads(output)
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise InterpretationError("The interpreter returned an unreadable plan.") from exc


def validate_plan(raw: dict, message: str) -> dict:
    """Reject unsupported fields, actions and omitted numeric constraints."""
    if not isinstance(raw, dict) or raw.get("status") not in {
            "execute", "clarify", "out_of_scope", "small_talk"}:
        raise InterpretationError("The interpreter returned an invalid plan.")
    if raw.get("language") not in {None, "en", "az", "ru"}:
        raise InterpretationError("The interpreter returned an unsupported language.")
    preferences = raw.get("preferences", [])
    if not isinstance(preferences, list) or len(preferences) > 10:
        raise InterpretationError("The interpreter returned invalid preferences.")
    for preference in preferences:
        if (not isinstance(preference, dict) or
                not all(isinstance(preference.get(key), str) for key in
                        ("name", "value", "evidence")) or
                not 0 < len(preference["name"].strip()) <= 50 or
                not 0 < len(preference["value"].strip()) <= 100 or
                not preference["evidence"].strip() or
                preference["evidence"].casefold() not in message.casefold()):
            raise InterpretationError("The interpreter returned invalid preferences.")
    actions = raw.get("actions")
    if not isinstance(actions, list) or len(actions) > 3:
        raise InterpretationError("The interpreter returned invalid actions.")
    if raw["status"] == "execute" and (not actions or raw.get("unhandled_constraints")):
        raise InterpretationError("A requested constraint could not be applied.")
    if raw["status"] != "execute" and actions:
        # Some providers attach a speculative action to a clarification. Never
        # execute it: preserve the model's question and keep domain state intact.
        raw = {**raw, "actions": []}
    if raw["status"] != "execute" and preferences:
        raw = {**raw, "preferences": []}
    if raw["status"] != "execute":
        return raw
    evidence_parts: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            raise InterpretationError("Invalid action.")
        domain, operation = action.get("domain"), action.get("operation")
        if domain not in DOMAINS or operation not in OPERATIONS:
            raise InterpretationError("Unsupported domain operation.")
        if operation.startswith("cart_") and domain != "shopping":
            raise InterpretationError("Cart operation requires shopping.")
        if operation == "showtimes" and domain != "cinema":
            raise InterpretationError("Showtimes require cinema.")
        if operation == "reserve" and domain == "shopping":
            raise InterpretationError("Products cannot be reserved.")
        if action.get("mode") not in {"new", "refine", "previous"}:
            raise InterpretationError("Invalid context mode.")
        if action.get("sort_field", "") not in SORTS[domain] | {""}:
            raise InterpretationError("Unsupported sort field.")
        if action.get("sort_field") and operation not in {"search", "showtimes"}:
            raise InterpretationError("Sort cannot be applied to that operation.")
        if not isinstance(action.get("sort_desc"), bool):
            raise InterpretationError("Invalid sort order.")
        if action["sort_desc"] and not action.get("sort_field"):
            raise InterpretationError("Sort direction has no sort field.")
        if (type(action.get("quantity")) is not int or action["quantity"] < 0 or
                (action["quantity"] == 0 and operation in {"reserve", "cart_add"})):
            raise InterpretationError("Invalid quantity.")
        if not isinstance(action.get("references"), list) or not all(
                isinstance(ref, str) for ref in action["references"]):
            raise InterpretationError("Invalid references.")
        groups = action.get("filter_groups")
        if not isinstance(groups, list) or len(groups) > 8:
            raise InterpretationError("Invalid filters.")
        if groups and operation in {"compare", "cart_show"}:
            raise InterpretationError("A constraint would be ignored by that operation.")
        # A reference can revisit earlier results and ask a constrained yes/no
        # question. Details, availability, reservations and cart changes apply
        # their conditions in the executor regardless of the context mode.
        if action["references"] and operation == "search":
            raise InterpretationError("A search reference needs a specific operation.")
        for group in groups:
            if not isinstance(group, list) or len(group) > 16:
                raise InterpretationError("Invalid filter group.")
            for condition in group:
                if not isinstance(condition, dict):
                    raise InterpretationError("Invalid condition.")
                field, op = condition.get("field"), condition.get("op")
                if field not in FIELDS[domain] or op not in OPERATORS:
                    raise InterpretationError("Unsupported constraint.")
                if op in {"lt", "lte", "gt", "gte", "between"} and field not in NUMERIC | {
                        "travel_date", "showing_on", "departure_time", "showtime"}:
                    raise InterpretationError("Unsupported comparison.")
                if op == "contains" and field in NUMERIC:
                    raise InterpretationError("Unsupported numeric text search.")
                if not isinstance(condition.get("value"), str) or not condition["value"].strip():
                    raise InterpretationError("Missing constraint value.")
                if op == "between" and not str(condition.get("other", "")).strip():
                    raise InterpretationError("Missing range endpoint.")
                evidence = condition.get("evidence")
                if not isinstance(evidence, str):
                    raise InterpretationError("Constraint lacks evidence in the user's message.")
                evidence = evidence.strip().strip("\"'“”‘’")
                if not evidence or evidence.casefold() not in message.casefold():
                    raise InterpretationError("Constraint lacks evidence in the user's message.")
                condition["evidence"] = evidence
                evidence_parts.append(evidence)
    # Independent coverage check: a dropped number often turns a constrained
    # search into an unrestricted list. Dates and quantities count too.
    covered = " ".join(evidence_parts +
                       [preference["evidence"] for preference in preferences] +
                       [str(ref) for action in actions for ref in action["references"]])
    for number in re.findall(r"(?<!\w)\d+(?:[.,:]\d+)*(?:\+)?(?!\w)", message):
        if number not in covered and not any(
                action["operation"] in {"reserve", "cart_add", "cart_remove"} and
                number in str(action["quantity"]) for action in actions):
            raise InterpretationError("A numeric constraint was not accounted for.")
    # Content words must be represented by filter evidence, a reference, or a
    # supported sort. This catches missing qualitative constraints as well.
    stop = {"a", "an", "and", "are", "at", "be", "by", "can", "could", "do",
            "does", "for", "from", "give", "have", "i", "in", "is", "it",
            "list", "me", "of", "on", "only", "or", "please", "show", "the",
            "them", "these", "those", "to", "want", "which", "with", "you",
            "my", "find", "search", "about", "what", "would", "like", "that",
            "one", "ones", "films", "film", "movies", "movie", "flights", "flight",
            "products", "product", "items", "item", "tickets", "ticket", "seats",
            "seat", "cinemas", "cinema", "sort", "sorted", "order", "book",
            "reserve", "add", "remove", "cart", "compare", "check", "availability",
            "available", "stock", "details", "back", "previous", "again", "return",
            "showtimes", "showtime", "playing", "showing", "where", "when", "how",
            "price", "priced", "cost", "rating", "rated", "age", "ages",
            "cheapest", "cheaper", "earliest", "latest", "lowest", "highest",
            "first", "second", "third", "fourth", "two", "three", "four",
            "five", "than", "under", "over", "below", "above", "least", "most",
            "between", "up", "good", "support", "suitable", "year", "old",
            "azn", "manat"}
    accounted = (covered + " " + " ".join(str(action["sort_field"]) for action in actions)).casefold()
    if raw.get("language") in (None, "en"):
        for word in re.findall(r"[^\W_]+", message.casefold(), flags=re.UNICODE):
            if len(word) > 2 and word not in stop and word not in accounted:
                raise InterpretationError(f"The constraint '{word}' was not accounted for.")
    return raw
