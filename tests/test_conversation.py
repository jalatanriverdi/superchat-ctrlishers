import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from superchat.conversation import ConversationEngine
from superchat.repositories import load_repositories


DATA_DIR = Path(__file__).resolve().parent.parent / "SuperChat_Mock_Data"


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.engine = ConversationEngine(load_repositories(DATA_DIR), date(2026, 11, 2))
        self.session = self.engine.sessions.get_or_create(None)

    def ask(self, message):
        return self.engine.respond(self.session, message)

    def test_three_domain_switches_and_return_to_shopping(self):
        self.assertEqual(self.ask("Find me a flight from Baku to Istanbul on Friday.")["route"], "flights")
        self.assertEqual(self.ask("What is playing tonight?")["route"], "cinema")
        self.assertEqual(self.ask("Do you have wireless headphones under 100 AZN?")["route"], "shopping")
        self.assertIn("P001", self.session.history[-1]["content"])
        self.ask("Showtimes for Orbit Zero on Saturday")
        self.assertEqual(self.ask("Back to headphones")["route"], "followup")
        self.assertIn("P001", self.session.history[-1]["content"])
        self.assertEqual(self.session.flights.criteria["travel_date"], "2026-11-06")

    def test_return_to_cinema_after_laptops(self):
        self.ask("What is playing tonight?")
        self.ask("Show me laptops.")
        result = self.ask("Okay, and the sci-fi one, any seats on Saturday?")
        self.assertEqual(result["route"], "followup")
        self.assertIn("Orbit Zero", result["reply"])
        self.assertIn("Deep Signal", result["reply"])
        self.assertIn("2026-11-07", result["reply"])

    def test_second_product_stock_and_cart(self):
        self.ask("Show me laptops.")
        answer = self.ask("The second one, is it in stock?")
        self.assertIn("Laptop 14", answer["reply"])
        self.assertIn("12 in stock", answer["reply"])
        self.assertIn("1249.00 AZN", self.ask("Add it to cart")["reply"])
        self.assertIn("empty", self.ask("Remove it")["reply"])

    def test_missing_origin_preserved_and_cheapest_followup(self):
        self.assertIn("flying from", self.ask("Flights to Istanbul on 6 November.")["reply"])
        self.assertIn("F013", self.ask("From Baku")["reply"])
        response = self.ask("The cheaper one, is it direct?")
        self.assertIn("not direct", response["reply"])
        self.assertEqual(self.session.flights.selected_id, "F013")

    def test_bare_city_fills_requested_flight_detail(self):
        self.assertIn("flying from", self.ask("list my flight for the istanbul")["reply"])
        self.assertEqual(self.session.flights.criteria["destination"], "Istanbul")
        self.assertEqual(self.session.pending_field, "origin")
        self.assertIn("What date", self.ask("baku")["reply"])
        self.assertEqual(self.session.flights.criteria["origin"], "Baku")
        self.assertEqual(self.session.pending_field, "travel_date")
        self.assertIn("F013", self.ask("6 November")["reply"])
        self.assertIsNone(self.session.pending_field)

        other = self.engine.sessions.get_or_create(None)
        self.assertIn("destination", self.engine.respond(other, "Flights from Baku on 6 November")["reply"])
        self.assertIn("F013", self.engine.respond(other, "Istanbul")["reply"])

    def test_mixed_request_and_clarification(self):
        answer = self.ask("I need a flight to Istanbul on 6 November and a backpack for the trip.")
        self.assertEqual(answer["route"], "mixed")
        self.assertIn("flying from", answer["reply"])
        self.assertIn("Backpack 25L", answer["reply"])
        self.assertIn("F013", self.ask("From Baku")["reply"])

    def test_ambiguous_out_of_scope_and_booking_without_context(self):
        self.assertEqual(self.ask("Show me something good.")["route"], "ambiguous")
        self.assertEqual(self.ask("What is the weather in Ganja?")["route"], "out_of_scope")
        self.assertIn("Which flight", self.ask("Book two seats.")["reply"])

    def test_mock_reservations_and_no_overbooking(self):
        self.ask("Find a flight from Baku to Istanbul on 6 November")
        self.ask("The second one")
        self.assertIn("R000001", self.ask("Book two seats")["reply"])
        self.assertIn("Only 1 seat", self.ask("Book two seats")["reply"])
        self.ask("Showtimes for Orbit Zero on Saturday")
        self.assertIn("R000002", self.ask("Book two tickets")["reply"])

    def test_empty_results_do_not_invent_records(self):
        response = self.ask("Find a flight from Baku to Paris on 6 November")
        self.assertIn("No flights", response["reply"])
        self.assertNotIn("F001", response["reply"])

    def test_free_text_product_search(self):
        response = self.ask("Show me waterproof products")
        self.assertIn("Portable Speaker", response["reply"])
        self.assertNotIn("Laptop 15", response["reply"])

    def test_film_rating_language_and_date_filters(self):
        response = self.ask("Show me English films rated above 8 on Saturday")
        self.assertIn("Orbit Zero", response["reply"])
        self.assertIn("Deep Signal", response["reply"])
        self.assertNotIn("Laugh Track", response["reply"])

    def test_unrelated_questions_do_not_repeat_or_change_shopping_state(self):
        self.assertIn("P009", self.ask("Show me running shoes")["reply"])
        before = (self.session.active_domain, deepcopy(self.session.shopping),
                  deepcopy(self.session.flights), deepcopy(self.session.cinema),
                  self.session.pending_domain, self.session.pending_field)
        for message in ("who is donalt trump", "Who is Donald Trump?",
                        "Tell me a joke about cinemas", "Translate this"):
            answer = self.ask(message)
            self.assertEqual(answer["route"], "out_of_scope", message)
            self.assertEqual(answer["domains"], [], message)
            self.assertIn("outside my scope", answer["reply"], message)
            self.assertNotIn("P009", answer["reply"], message)
            self.assertEqual((self.session.active_domain, self.session.shopping,
                              self.session.flights, self.session.cinema,
                              self.session.pending_domain, self.session.pending_field),
                             before, message)
        self.assertEqual(len(self.session.history), 10)

    def test_poem_and_small_talk_preserve_flight_state(self):
        self.assertIn("F013", self.ask("Find flights from Baku to Istanbul on 6 November")["reply"])
        before = (self.session.active_domain, deepcopy(self.session.flights))
        for message in ("Write me a poem", "Write a poem about Istanbul flights"):
            answer = self.ask(message)
            self.assertEqual(answer["route"], "out_of_scope")
            self.assertNotIn("F013", answer["reply"])
            self.assertEqual((self.session.active_domain, self.session.flights), before)
        for message in ("Hi", "Thanks", "Okay", "What can you do?"):
            answer = self.ask(message)
            self.assertEqual(answer["route"], "small_talk")
            self.assertNotIn("F013", answer["reply"])
            self.assertEqual((self.session.active_domain, self.session.flights), before)
        self.assertEqual(self.ask("42")["route"], "out_of_scope")
        self.assertEqual((self.session.active_domain, self.session.flights), before)


if __name__ == "__main__":
    unittest.main()
