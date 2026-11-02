import json
import tempfile
import unittest
from pathlib import Path

from superchat.data_validation import DataSourceError
from superchat.repositories import JsonRepository, load_repositories


DATA_DIR = Path(__file__).resolve().parent.parent / "SuperChat_Mock_Data"


class RepositoryTests(unittest.TestCase):
    def test_official_data_loads_with_expected_counts_and_links(self):
        repos = load_repositories(DATA_DIR)
        self.assertEqual(
            [len(getattr(repos, name).list_all()) for name in
             ("flights", "products", "movies", "cinemas", "showtimes")],
            [17, 12, 8, 3, 16],
        )
        self.assertEqual(repos.flights.get("F001")["destination"]["city"], "Istanbul")
        self.assertIsNone(repos.flights.get("not-a-flight"))

    def test_callers_cannot_change_loaded_records(self):
        repo = JsonRepository(DATA_DIR, "products")
        product = repo.get("P001")
        product["stock"] = 0
        repo.list_all()[0]["name"]["en"] = "Changed"
        self.assertEqual(repo.get("P001")["stock"], 23)
        self.assertEqual(repo.get("P001")["name"]["en"], "Wireless Headphones")

    def test_missing_and_malformed_files_raise_data_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaisesRegex(DataSourceError, "Cannot load"):
                JsonRepository(path, "flights")
            (path / "flights.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(DataSourceError, "Cannot load"):
                JsonRepository(path, "flights")

    def test_invalid_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for source in DATA_DIR.glob("*.json"):
                records = json.loads(source.read_text(encoding="utf-8"))
                if source.name == "showtimes.json":
                    records[0]["movie_id"] = "missing-movie"
                (path / source.name).write_text(json.dumps(records), encoding="utf-8")
            with self.assertRaisesRegex(DataSourceError, "unknown movie_id"):
                load_repositories(path)

    def test_missing_required_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            records = json.loads((DATA_DIR / "products.json").read_text(encoding="utf-8"))
            del records[0]["stock"]
            (path / "products.json").write_text(json.dumps(records), encoding="utf-8")
            with self.assertRaisesRegex(DataSourceError, "missing fields: stock"):
                JsonRepository(path, "products")


if __name__ == "__main__":
    unittest.main()
