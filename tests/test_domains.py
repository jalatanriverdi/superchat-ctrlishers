import unittest
from decimal import Decimal
from pathlib import Path

from superchat.domains.cinema import CinemaService
from superchat.domains.common import InvalidRequest, ReservationLedger, Unavailable, UnknownItem
from superchat.domains.flights import FlightService
from superchat.domains.shopping import Cart, ShoppingService
from superchat.repositories import load_repositories


DATA_DIR = Path(__file__).resolve().parent.parent / "SuperChat_Mock_Data"


class DomainTests(unittest.TestCase):
    def setUp(self):
        repos = load_repositories(DATA_DIR)
        ledger = ReservationLedger()
        self.flights = FlightService(repos.flights, ledger)
        self.shopping = ShoppingService(repos.products)
        self.cart = Cart(repos.products)
        self.cinema = CinemaService(repos.movies, repos.cinemas, repos.showtimes, ledger)

    def test_flights_search_filter_and_sort(self):
        flights = self.flights.search("Baku", "IST", "2026-11-06")
        self.assertEqual([item["id"] for item in flights], ["F013", "F002", "F001"])
        self.assertEqual(
            [item["id"] for item in self.flights.search(
                "GYD", "Istanbul", "2026-11-06", max_stops=0,
                max_price=300, sort_by="departure_time", descending=True,
            )],
            ["F002", "F001"],
        )
        self.assertEqual(
            [item["id"] for item in self.flights.search(
                "Baku", "Istanbul", "2026-11-06",
                airline="Caspian Air", departure_after="07:00",
                departure_before="12:00", min_price=200,
            )],
            ["F001"],
        )
        self.assertEqual(
            [item["id"] for item in self.flights.search(
                "Baku", "Istanbul", "2026-11-06", sort_by="stops",
            )],
            ["F002", "F001", "F013"],
        )
        self.assertEqual(
            [item["id"] for item in self.flights.search(
                "Baku", "Istanbul", "2026-11-06", sort_by="airline",
            )],
            ["F013", "F002", "F001"],
        )
        self.assertEqual(self.flights.search("Baku", "Paris", "2026-11-06"), [])

    def test_flight_details_comparison_and_booking(self):
        compared = self.flights.compare(["F013", "F002"])
        self.assertEqual([item["stops"] for item in compared], [1, 0])
        self.assertEqual(compared[0]["baggage_kg"], 15)
        self.assertEqual(compared[1]["duration_min"], 220)
        reservation = self.flights.reserve("F002", 2)
        self.assertEqual(reservation.total_azn, Decimal("490.0"))
        self.assertEqual(self.flights.get("F002")["seats_available"], 1)
        with self.assertRaises(Unavailable):
            self.flights.reserve("F002", 2)
        self.assertEqual(self.flights.get("F002")["seats_available"], 1)

    def test_flight_invalid_requests(self):
        with self.assertRaises(InvalidRequest):
            self.flights.search("Baku", "Istanbul", "Friday")
        with self.assertRaises(InvalidRequest):
            self.flights.search(None, "Istanbul", "2026-11-06")
        with self.assertRaises(InvalidRequest):
            self.flights.compare(["F001", "F001"])
        with self.assertRaises(UnknownItem):
            self.flights.reserve("F999")

    def test_product_search_all_filters_and_comparison(self):
        self.assertEqual(
            [item["id"] for item in self.shopping.search(text="laptops")],
            ["P003", "P004", "P010"],
        )
        self.assertEqual(
            [item["id"] for item in self.shopping.search(
                text="laptop", category="computers", brand="Nexar",
                min_price=1200, max_price=1300, color="grey",
            )],
            ["P004"],
        )
        self.assertEqual(self.shopping.stock("P002"), 0)
        self.assertEqual(
            [item["id"] for item in self.shopping.compare(["P003", "P004"])],
            ["P003", "P004"],
        )
        self.assertEqual(self.shopping.get("P001")["description"],
                         "Over-ear Bluetooth headphones, 30h battery")
        self.assertEqual(self.shopping.search(text="nonexistent item"), [])

    def test_cart_stock_add_remove_and_total(self):
        with self.assertRaises(Unavailable):
            self.cart.add("P002")
        self.cart.add("P001", 2)
        summary = self.cart.add("P010")
        self.assertEqual(summary["total_azn"], Decimal("244.80"))
        self.assertEqual(len(summary["items"]), 2)
        self.assertEqual(self.cart.remove("P001", 1)["total_azn"], Decimal("154.90"))
        self.assertEqual(self.cart.remove("P010")["total_azn"], Decimal("89.90"))
        with self.assertRaises(InvalidRequest):
            self.cart.remove("P010")

    def test_cinema_filters_and_linked_showtimes(self):
        films = self.cinema.find_movies(genre="sci-fi", showing_on="2026-11-07")
        self.assertEqual([item["id"] for item in films], ["M001", "M008"])
        self.assertEqual(
            [item["id"] for item in self.cinema.find_movies(
                language="English", min_rating=8.2, showing_on="2026-11-07",
            )],
            ["M008"],
        )
        showtimes = self.cinema.showtimes_for("M008", showing_on="2026-11-07")
        self.assertEqual([item["id"] for item in showtimes], ["S011"])
        self.assertEqual(showtimes[0]["cinema"]["name"], "CinemaPlus Ganjlik")
        self.assertEqual(showtimes[0]["price_azn"], 11)
        self.assertEqual(showtimes[0]["seats_available"], 67)
        self.assertEqual(self.cinema.find_movies(showing_on="2026-12-01"), [])

    def test_cinema_reservations_and_sold_out_show(self):
        reservation = self.cinema.reserve_tickets("S011", 2)
        self.assertEqual(reservation.total_azn, Decimal("22.0"))
        self.assertEqual(self.cinema.get_showtime("S011")["seats_available"], 65)
        with self.assertRaises(Unavailable):
            self.cinema.reserve_tickets("S003")
        with self.assertRaises(Unavailable):
            self.cinema.reserve_tickets("S012", 6)
        with self.assertRaises(UnknownItem):
            self.cinema.reserve_tickets("S999")


if __name__ == "__main__":
    unittest.main()
