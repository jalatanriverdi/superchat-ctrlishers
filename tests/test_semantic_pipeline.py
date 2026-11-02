"""Full conversation pipeline tests with controlled structured model output.

These verify validation, execution and state; they do not claim live-model accuracy.
"""

import json
import os
import http.cookiejar
import io
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from superchat.__main__ import make_handler
from superchat.repositories import load_repositories
from superchat.semantic_conversation import SemanticConversationEngine
from superchat.semantic import OpenAIPlanner, InterpretationError


DATA = Path(__file__).resolve().parents[1] / "SuperChat_Mock_Data"


def condition(field, op, value, evidence, other=""):
    return {"field": field, "op": op, "value": str(value), "other": str(other),
            "evidence": evidence}


def action(domain, operation="search", groups=None, mode="new", refs=None,
           sort="", desc=False, quantity=1):
    return {"domain": domain, "operation": operation, "mode": mode,
            "filter_groups": groups if groups is not None else [],
            "sort_field": sort, "sort_desc": desc,
            "references": refs or [], "quantity": quantity}


def plan(*actions, status="execute", message="", language=None, preferences=None):
    return {"status": status, "actions": list(actions), "message": message,
            "language": language, "preferences": preferences or [],
            "unhandled_constraints": []}


class ScriptedPlanner:
    def __init__(self, scripts):
        self.scripts = scripts
        self.contexts = []

    def interpret(self, message, context, catalogue, reference_date):
        self.contexts.append(context)
        return self.scripts[message]


class SemanticPipelineTests(unittest.TestCase):
    def setUp(self):
        self.scripts = {}
        self.planner = ScriptedPlanner(self.scripts)
        self.engine = SemanticConversationEngine(load_repositories(DATA), self.planner)
        self.session = self.engine.sessions.get_or_create(None)
        self.previous_debug = os.environ.get("SUPERCHAT_DEBUG")
        os.environ["SUPERCHAT_DEBUG"] = "1"

    def tearDown(self):
        if self.previous_debug is None:
            os.environ.pop("SUPERCHAT_DEBUG", None)
        else:
            os.environ["SUPERCHAT_DEBUG"] = self.previous_debug

    def ask(self, message, output):
        self.scripts[message] = output
        return self.engine.respond(self.session, message)

    def test_plural_product_term_and_unused_quantity_zero(self):
        result = self.ask("Find laptops cheaper than 1500 AZN", plan(action(
            "shopping", groups=[[
                condition("name", "contains", "laptops", "laptops"),
                condition("price_azn", "lt", 1500, "cheaper than 1500 AZN"),
            ]], quantity=0)))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P004"])

    def test_product_characteristic_searches_name_and_description(self):
        result = self.ask("Show wireless headphones under 100 AZN", plan(action(
            "shopping", groups=[[
                condition("name", "contains", "headphones", "headphones"),
                condition("text", "contains", "wireless", "wireless"),
                condition("price_azn", "lt", 100, "under 100 AZN"),
            ]], quantity=0)))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P001"])

    def test_result_cards_use_verified_records_and_persist_in_history(self):
        flight = self.ask("Flights from Baku to Istanbul on Friday", plan(action(
            "flights", groups=[[
                condition("origin", "eq", "Baku", "Baku"),
                condition("destination", "eq", "Istanbul", "Istanbul"),
                condition("travel_date", "eq", "2026-11-06", "Friday"),
            ]])))
        flight_cards = flight["history"][-1]["card_sections"][0]["items"]
        self.assertEqual([card["id"] for card in flight_cards],
                         flight["diagnostics"]["returned_ids"][0]["ids"])
        self.assertEqual(flight_cards[0]["price"], "289.00 AZN")
        self.assertTrue(any("Baggage" in fact for fact in flight_cards[0]["facts"]))

        product = self.ask("Show wireless headphones under 100 AZN", plan(action(
            "shopping", groups=[[
                condition("name", "contains", "headphones", "headphones"),
                condition("text", "contains", "wireless", "wireless"),
                condition("price_azn", "lt", 100, "under 100 AZN"),
            ]])))
        product_card = product["history"][-1]["card_sections"][0]["items"][0]
        self.assertEqual((product_card["id"], product_card["price"]),
                         ("P001", "89.90 AZN"))

        cinema = self.ask("Show showtimes tonight", plan(action(
            "cinema", "showtimes", [[
                condition("showing_on", "eq", "2026-11-02", "tonight")]],
            quantity=0)))
        show_cards = cinema["history"][-1]["card_sections"][0]["items"]
        self.assertEqual({card["id"] for card in show_cards}, {"S001", "S002", "S003"})
        self.assertTrue(all(card["kind"] == "showtime" for card in show_cards))
        self.assertEqual(self.session.history[-1]["card_sections"][0]["items"], show_cards)

    def test_clarification_with_speculative_action_does_not_execute(self):
        result = self.ask("give me flights", plan(
            action("flights"), status="clarify",
            message="Which city are you flying from?"))
        self.assertEqual(result["reply"], "Which city are you flying from?")
        self.assertEqual(result["route"], "clarify")
        self.assertIsNone(self.session.active_domain)
        self.assertEqual(self.session.flights.result_ids, [])

    def test_language_can_switch_across_domains(self):
        first = self.ask("Mənə uçuşlar göstər", plan(action("flights", groups=[[]], quantity=0),
                                                      language="az"))
        self.assertEqual(first["reply"], "Hansı şəhərdən uçursunuz?")
        second = self.ask("Покажи товары", plan(action("shopping", groups=[[]], quantity=0),
                                                 language="ru"))
        self.assertIn("Подходящие товары", second["reply"])
        self.assertIn("Полноразмерные Bluetooth-наушники", second["reply"])
        self.assertEqual(self.session.language, "ru")
        third = self.ask("Elmi fantastika filmləri", plan(action("cinema", groups=[[
            condition("genre", "eq", "sci-fi", "Elmi fantastika")]], quantity=0),
            language="az"))
        self.assertIn("Sıradan çıxan kosmik stansiyanın", third["reply"])

    def test_translated_catalogue_value_is_canonicalized_before_filtering(self):
        result = self.ask("Покажи чёрные наушники дешевле 200 AZN", plan(
            action("shopping", groups=[[
                condition("name", "contains", "наушники", "наушники"),
                condition("color", "eq", "чёрные", "чёрные"),
                condition("price_azn", "lt", 200, "дешевле 200 AZN"),
            ]], quantity=0), language="ru"))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P001"])

    def test_azerbaijani_product_inflection_matches_catalogue_name(self):
        result = self.ask("1500 AZN-dən ucuz noutbukları göstər", plan(
            action("shopping", groups=[[
                condition("name", "contains", "noutbukları", "noutbukları"),
                condition("price_azn", "lt", 1500, "1500 AZN-dən ucuz"),
            ]], quantity=0), language="az"))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P004"])

    def test_explicit_preference_is_shared_across_domain_switch(self):
        self.ask("I prefer direct flights from Baku to Istanbul on Friday", plan(
            action("flights", groups=[[
                condition("origin", "eq", "Baku", "Baku"),
                condition("destination", "eq", "Istanbul", "Istanbul"),
                condition("travel_date", "eq", "2026-11-06", "Friday"),
                condition("stops", "eq", "0", "direct"),
            ]]), preferences=[{"name": "flight_stops", "value": "direct",
                              "evidence": "I prefer direct flights"}]))
        self.ask("Show movies", plan(action("cinema", groups=[[]])))
        self.assertEqual(self.session.preferences["flight_stops"], "direct")
        self.assertEqual(self.planner.contexts[-1]["preferences"]["flight_stops"], "direct")

    def test_return_filter_refines_saved_results_across_language_switch(self):
        self.ask("Show me headphones under 100 AZN", plan(action(
            "shopping", groups=[[
                condition("name", "contains", "headphones", "headphones"),
                condition("price_azn", "lt", 100, "under 100 AZN"),
            ]])))
        self.ask("Что идёт в кино?", plan(action("cinema", groups=[[]]), language="ru"))
        result = self.ask("Вернись к наушникам", plan(action(
            "shopping", operation="return", mode="previous", groups=[[
                condition("name", "contains", "наушникам", "наушникам")]],
            quantity=0), language="ru"))
        self.assertEqual(result["route"], "shopping")
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P001"])
        self.assertEqual(self.session.active_domain, "shopping")

    def test_return_discards_only_filters_copied_from_saved_context(self):
        old = [
            condition("name", "contains", "headphones", "headphones"),
            condition("price_azn", "lt", 100, "under 100 AZN"),
        ]
        self.ask("Show me headphones under 100 AZN", plan(action(
            "shopping", groups=[old], quantity=0)))
        self.ask("Что идёт сегодня в кино?", plan(action(
            "cinema", groups=[[condition("showing_on", "eq", "2026-11-02",
                                               "сегодня")]], quantity=0), language="ru"))
        result = self.ask("Вернись к наушникам", plan(action(
            "shopping", operation="search", mode="previous", groups=[[
                condition("name", "contains", "headphones", "Show me headphones under 100 AZN"),
                condition("price_azn", "lt", 100, "Show me headphones under 100 AZN"),
            ], [condition("name", "contains", "headphones", "Вернись к наушникам")]],
            quantity=0), language="ru"))
        self.assertEqual(result["route"], "shopping")
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P001"])
        self.assertFalse(result["diagnostics"]["repair_attempted"])
        self.assertEqual(self.session.shopping.result_ids, ["P001"])

    def test_return_keeps_unverified_new_constraint_for_validation(self):
        self.ask("Show headphones", plan(action("shopping", groups=[[
            condition("name", "contains", "headphones", "headphones")]])))
        previous = self.session.shopping.result_ids.copy()
        result = self.ask("Back to the headphones", plan(action(
            "shopping", operation="return", mode="previous", groups=[[
                condition("name", "contains", "headphones", "Show headphones"),
                condition("color", "eq", "purple", "purple"),
            ]])))
        self.assertEqual(result["route"], "clarify")
        self.assertEqual(self.session.shopping.result_ids, previous)

    def test_unmatched_return_filter_keeps_saved_results(self):
        self.ask("Show headphones", plan(action("shopping", groups=[[
            condition("name", "contains", "headphones", "headphones")]])))
        previous = self.session.shopping.result_ids.copy()
        result = self.ask("Back to purple headphones", plan(action(
            "shopping", operation="return", mode="previous", groups=[[
                condition("color", "eq", "purple", "purple"),
                condition("name", "contains", "headphones", "headphones")]])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], [])
        self.assertEqual(self.session.shopping.result_ids, previous)

    def test_invalid_model_evidence_gets_one_validated_repair_attempt(self):
        message = "Покажи чёрные наушники"
        invalid = plan(action("shopping", groups=[[
            condition("name", "contains", "наушники", "headphones"),
            condition("color", "eq", "чёрные", "чёрные")]], quantity=0),
            language="ru")
        corrected = plan(action("shopping", groups=[[
            condition("name", "contains", "наушники", "наушники"),
            condition("color", "eq", "чёрные", "чёрные")]], quantity=0),
            language="ru")

        class RepairPlanner:
            repairs = 0

            def interpret(self, *args):
                return invalid

            def repair(self, *args):
                self.repairs += 1
                return corrected

        planner = RepairPlanner()
        engine = SemanticConversationEngine(load_repositories(DATA), planner)
        session = engine.sessions.get_or_create(None)
        result = engine.respond(session, message)
        self.assertEqual(planner.repairs, 1)
        self.assertTrue(result["diagnostics"]["repair_attempted"])
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P001"])

    def test_previous_result_can_answer_constrained_details_question(self):
        self.ask("Flights from Baku to Istanbul on Friday", plan(action(
            "flights", groups=[[
                condition("origin", "eq", "Baku", "Baku"),
                condition("destination", "eq", "Istanbul", "Istanbul"),
                condition("travel_date", "eq", "2026-11-06", "Friday"),
            ]])))
        result = self.ask("The cheaper one, is it direct?", plan(action(
            "flights", operation="details", mode="previous",
            refs=["cheaper"], groups=[[
                condition("stops", "eq", "0", "direct")]], quantity=0)))
        self.assertEqual(result["route"], "flights")
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["F013"])
        self.assertTrue(result["reply"].startswith("No."))

    def test_age_suitability_and_exact_vs_below_rating(self):
        result = self.ask("Give me movies which age support 12", plan(action(
            "cinema", groups=[[condition("age_rating", "lte", 12, "age support 12")]])))
        self.assertEqual(set(result["diagnostics"]["returned_ids"][0]["ids"]),
                         {"M001", "M002", "M003", "M005", "M007", "M008"})
        result = self.ask("Movies which have 8 rating", plan(action(
            "cinema", groups=[[condition("rating", "eq", 8, "8 rating")]])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], [])
        self.assertIn("No matching", result["reply"])
        result = self.ask("Movies rated below 8", plan(action(
            "cinema", groups=[[condition("rating", "lt", 8, "rated below 8")]])))
        self.assertEqual(set(result["diagnostics"]["returned_ids"][0]["ids"]),
                         {"M002", "M003", "M004", "M005", "M006", "M007"})

    def test_multicondition_cinema_and_showtimes(self):
        result = self.ask("Sci-fi movies over 8 for age 12", plan(action(
            "cinema", groups=[[condition("genre", "eq", "sci-fi", "Sci-fi"),
                               condition("rating", "gt", 8, "over 8"),
                               condition("age_rating", "lte", 12, "age 12")]])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["M001", "M008"])
        result = self.ask("Show sci-fi showtimes on 7 November 2026", plan(action(
            "cinema", "showtimes", [[condition("genre", "eq", "sci-fi", "sci-fi"),
                                     condition("showing_on", "eq", "2026-11-07", "7 November 2026")]])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["S011", "S012"])

    def test_missing_constraint_plan_is_rejected(self):
        result = self.ask("Show purple headphones", plan(action("shopping", groups=[[
            condition("text", "contains", "headphones", "headphones")]])))
        self.assertEqual(result["route"], "clarify")
        self.assertIn("purple", result["diagnostics"]["error"])
        self.assertEqual(self.session.shopping.result_ids, [])
        result = self.ask("Movies rated below 8", plan(action("cinema", groups=[[]])))
        self.assertEqual(result["route"], "clarify")
        self.assertEqual(self.session.cinema.result_ids, [])

    def test_flight_clarification_keeps_slots_and_filters(self):
        result = self.ask("Flights to Istanbul on Friday", plan(action("flights", groups=[[
            condition("destination", "eq", "Istanbul", "to Istanbul"),
            condition("travel_date", "eq", "2026-11-06", "Friday")]])))
        self.assertIn("flying from", result["reply"])
        self.assertEqual(self.session.pending_field, "origin")
        result = self.ask("Baku", plan(action("flights", groups=[[
            condition("origin", "eq", "Baku", "Baku")]], mode="new")))
        self.assertEqual(set(result["diagnostics"]["returned_ids"][0]["ids"]),
                         {"F001", "F002", "F013"})
        self.assertIsNone(self.session.pending_field)

    def test_out_of_scope_preserves_state_and_return(self):
        self.ask("Flights from Baku to Istanbul on Friday", plan(action("flights", groups=[[
            condition("origin", "eq", "Baku", "from Baku"),
            condition("destination", "eq", "Istanbul", "to Istanbul"),
            condition("travel_date", "eq", "2026-11-06", "Friday")]])))
        snapshot = json.dumps(self.session.flights.__dict__, sort_keys=True)
        result = self.ask("Write a poem about Istanbul flights", plan(
            status="out_of_scope", message="I can't write poems, but I can help with flights, shopping and cinema."))
        self.assertEqual(result["route"], "out_of_scope")
        self.assertEqual(json.dumps(self.session.flights.__dict__, sort_keys=True), snapshot)
        self.assertEqual(self.session.active_domain, "flights")
        result = self.ask("Back to the flights", plan(action("flights", "return", mode="previous")))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"],
                         ["F001", "F002", "F013"])
        for phrase in ("What is the weather in Ganja?", "Hi", "Thanks"):
            status = "small_talk" if phrase in {"Hi", "Thanks"} else "out_of_scope"
            self.ask(phrase, plan(status=status, message="Hello." if status == "small_talk" else "Outside scope."))
        self.assertEqual(json.dumps(self.session.flights.__dict__, sort_keys=True), snapshot)

    def test_references_stock_and_flight_comparison(self):
        self.ask("Show products", plan(action("shopping", groups=[[]])))
        result = self.ask("The second one, is it in stock?", plan(action(
            "shopping", "availability", refs=["second"])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P002"])
        self.ask("Flights from Baku to Istanbul on Friday", plan(action("flights", groups=[[
            condition("origin", "eq", "Baku", "from Baku"),
            condition("destination", "eq", "Istanbul", "to Istanbul"),
            condition("travel_date", "eq", "2026-11-06", "Friday")]])))
        result = self.ask("The cheaper one, is it direct?", plan(action(
            "flights", "details", [[condition("stops", "eq", 0, "direct")]],
            refs=["cheaper"])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["F013"])
        self.assertTrue(result["reply"].startswith("No."))
        result = self.ask("Compare the first and second flights", plan(action(
            "flights", "compare", refs=["first", "second"])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["F001", "F002"])

    def test_mixed_cart_reservations_and_domain_return(self):
        result = self.ask("Flights from Baku to Istanbul on Friday and backpacks", plan(
            action("flights", groups=[[condition("origin", "eq", "Baku", "from Baku"),
                                        condition("destination", "eq", "Istanbul", "to Istanbul"),
                                        condition("travel_date", "eq", "2026-11-06", "Friday")]]),
            action("shopping", groups=[[condition("text", "contains", "backpack", "backpacks")]])))
        self.assertEqual(result["route"], "mixed")
        self.assertEqual(set(result["domains"]), {"flights", "shopping"})
        result = self.ask("Add P001 to cart", plan(action("shopping", "cart_add", refs=["P001"])))
        self.assertIn("Total:", result["reply"])
        result = self.ask("Remove P001 from cart", plan(action("shopping", "cart_remove", refs=["P001"], quantity=0)))
        self.assertIn("empty", result["reply"])
        result = self.ask("Reserve F001", plan(action("flights", "reserve", refs=["F001"])))
        self.assertIn("No payment taken", result["reply"])
        result = self.ask("Show S001", plan(action("cinema", "availability", refs=["S001"])))
        self.assertIn("34 seats left", result["reply"])
        result = self.ask("Reserve S001", plan(action("cinema", "reserve", refs=["S001"])))
        self.assertIn("No payment taken", result["reply"])
        result = self.ask("Show S001 again", plan(action("cinema", "availability", refs=["S001"])))
        self.assertIn("33 seats left", result["reply"])

    def test_sort_price_brand_color_and_cinema_return_after_shopping(self):
        result = self.ask("Find direct flights from Baku to Istanbul on Friday sorted by price", plan(action(
            "flights", groups=[[condition("origin", "eq", "Baku", "from Baku"),
                                 condition("destination", "eq", "Istanbul", "to Istanbul"),
                                 condition("travel_date", "eq", "2026-11-06", "Friday"),
                                 condition("stops", "eq", 0, "direct")]], sort="price_azn")))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["F002", "F001"])
        result = self.ask("Black Sonivo audio products under 100 AZN", plan(action(
            "shopping", groups=[[condition("color", "eq", "black", "Black"),
                                 condition("brand", "eq", "Sonivo", "Sonivo"),
                                 condition("category", "eq", "audio", "audio"),
                                 condition("price_azn", "lt", 100, "under 100")]])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["P001", "P008"])
        self.ask("Movies showing on Friday", plan(action("cinema", groups=[[
            condition("showing_on", "eq", "2026-11-06", "Friday")]])))
        self.ask("Show laptops", plan(action("shopping", groups=[[
            condition("text", "contains", "laptop", "laptops")]])))
        result = self.ask("What about the sci-fi one?", plan(action(
            "cinema", "details", refs=["sci-fi"])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["M008"])
        self.assertIn("Deep Signal", result["reply"])

    def test_ambiguous_and_unavailable_records(self):
        for message in ("Show me something good", "Book two seats"):
            result = self.ask(message, plan(status="clarify", message="Which domain or item do you mean?"))
            self.assertEqual(result["route"], "clarify")
        result = self.ask("Purple headphones", plan(action("shopping", groups=[[
            condition("color", "eq", "purple", "Purple"),
            condition("text", "contains", "headphones", "headphones")]])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], [])
        self.assertIn("No matching", result["reply"])

    def test_constraints_cannot_be_ignored_by_action_or_booking(self):
        self.ask("Flights from Baku to Istanbul on Friday", plan(action("flights", groups=[[
            condition("origin", "eq", "Baku", "from Baku"),
            condition("destination", "eq", "Istanbul", "to Istanbul"),
            condition("travel_date", "eq", "2026-11-06", "Friday")]])))
        before = self.engine.flights.get("F013")["seats_available"]
        result = self.ask("Reserve the cheaper direct flight", plan(action(
            "flights", "reserve", [[condition("stops", "eq", 0, "direct")]],
            refs=["cheaper"])))
        self.assertEqual(result["route"], "clarify")
        self.assertEqual(self.engine.flights.get("F013")["seats_available"], before)
        result = self.ask("Back to direct flights", plan(action(
            "flights", "return", [[condition("stops", "eq", 0, "direct")]],
            mode="previous")))
        self.assertEqual(result["route"], "flights")
        self.assertEqual(self.session.flights.result_ids, ["F001", "F002"])

    def test_showtimes_for_referenced_movie(self):
        self.ask("Movies showing on Friday", plan(action("cinema", groups=[[
            condition("showing_on", "eq", "2026-11-06", "Friday")]])))
        result = self.ask("Showtimes for that film", plan(action(
            "cinema", "showtimes", refs=["it"])))
        self.assertEqual(result["diagnostics"]["returned_ids"][0]["ids"], ["S003", "S010", "S011"])


class SemanticHttpTests(unittest.TestCase):
    def test_card_action_endpoint_uses_verified_ids_without_model_call(self):
        planner = ScriptedPlanner({})
        engine = SemanticConversationEngine(load_repositories(DATA), planner)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            url = f"http://127.0.0.1:{server.server_port}/api/card-action"

            def post(domain, item_id, action_name):
                request = urllib.request.Request(url, data=json.dumps({
                    "domain": domain, "id": item_id, "action": action_name,
                }).encode("utf-8"), headers={"Content-Type": "application/json"})
                return json.load(client.open(request))

            detail = post("flights", "F001", "details")
            self.assertEqual(detail["route"], "flights")
            self.assertIn("CA101", detail["reply"])
            cart = post("shopping", "P001", "cart_add")
            self.assertIn("89.90 AZN", cart["reply"])
            shows = post("cinema", "M001", "showtimes")
            self.assertEqual(shows["route"], "cinema")
            self.assertTrue(shows["history"][-1]["card_sections"])
            self.assertEqual(planner.contexts, [])
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                post("shopping", "P999", "cart_add")
            self.assertEqual(invalid.exception.code, 400)
            invalid.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_browser_api_uses_semantic_pipeline_and_keeps_session(self):
        prompt = "Movies rated below 8"
        planner = ScriptedPlanner({prompt: plan(action("cinema", groups=[[
            condition("rating", "lt", 8, "rated below 8")]])),
                                   "Thanks": plan(status="small_talk", message="You're welcome.")})
        engine = SemanticConversationEngine(load_repositories(DATA), planner)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            url = f"http://127.0.0.1:{server.server_port}"

            def post(message):
                request = urllib.request.Request(url + "/api/chat",
                    data=json.dumps({"message": message}).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                return json.load(client.open(request))

            first = post(prompt)
            self.assertIn("M004", first["reply"])
            self.assertNotIn("M001", first["reply"])
            second = post("Thanks")
            self.assertEqual(second["route"], "small_talk")
            self.assertNotIn("M004", second["reply"])
            self.assertEqual(len(json.load(client.open(url + "/api/session"))["history"]), 4)
            self.assertEqual(engine.sessions._sessions[next(iter(engine.sessions._sessions))].cinema.result_ids,
                             ["M002", "M003", "M004", "M005", "M006", "M007"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


class OpenAIClientTests(unittest.TestCase):
    def test_responses_api_request_and_json_plan_parsing(self):
        expected = plan(status="small_talk", message="Hi!")
        output = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(expected)}]}]}
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps(output).encode("utf-8"))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"}, clear=True), \
                patch("superchat.semantic.urlopen", fake_urlopen):
            result = OpenAIPlanner().interpret("Hi", {}, {}, "2026-11-02")
        self.assertEqual(result, expected)
        body = json.loads(requests[0].data)
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertFalse(body["store"])
        self.assertEqual(requests[0].full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(body["model"], "gpt-5-mini")

    def test_openrouter_key_uses_openrouter_endpoint_and_model(self):
        expected = plan(status="small_talk", message="Hi!")
        output = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(expected)}]}]}
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps(output).encode("utf-8"))

        environment = {"OPENROUTER_API_KEY": "router-placeholder",
                       "OPENROUTER_MODEL": "openai/gpt-5-mini",
                       "OPENAI_API_KEY": "other-placeholder"}
        with patch.dict(os.environ, environment, clear=True), \
                patch("superchat.semantic.urlopen", fake_urlopen):
            result = OpenAIPlanner().interpret("Hi", {}, {}, "2026-11-02")
        self.assertEqual(result, expected)
        self.assertEqual(requests[0].full_url, "https://openrouter.ai/api/v1/responses")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer router-placeholder")
        self.assertEqual(json.loads(requests[0].data)["model"], "openai/gpt-5-mini")

    def test_missing_key_is_controlled(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(InterpretationError, "OPENROUTER_API_KEY"):
                OpenAIPlanner().interpret("Hi", {}, {}, "2026-11-02")


if __name__ == "__main__":
    unittest.main()
