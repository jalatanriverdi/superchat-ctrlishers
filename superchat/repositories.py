"""Replaceable read-only repositories for the five official JSON collections."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .data_validation import DataSourceError, REQUIRED_FIELDS, validate_record, validate_references


class RecordRepository(Protocol):
    def list_all(self) -> list[dict]: ...
    def get(self, record_id: str) -> dict | None: ...


class FlightRepository(RecordRepository, Protocol): ...
class ProductRepository(RecordRepository, Protocol): ...
class MovieRepository(RecordRepository, Protocol): ...
class CinemaRepository(RecordRepository, Protocol): ...
class ShowtimeRepository(RecordRepository, Protocol): ...


class JsonRepository:
    """Load one collection once and return detached records to callers."""

    def __init__(self, data_dir: Path, collection: str):
        if collection not in REQUIRED_FIELDS:
            raise ValueError(f"Unknown collection: {collection}")
        path = data_dir / f"{collection}.json"
        try:
            with path.open(encoding="utf-8") as file:
                records = json.load(file)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DataSourceError(f"Cannot load {path}: {exc}") from exc
        if not isinstance(records, list):
            raise DataSourceError(f"{path}: expected a JSON array")
        ids: set[str] = set()
        for index, record in enumerate(records, start=1):
            validate_record(collection, record, index)
            record_id = record["id"]
            if record_id in ids:
                raise DataSourceError(f"{path}: duplicate id {record_id}")
            ids.add(record_id)
        self._records = records
        self._by_id = {record["id"]: record for record in records}

    def list_all(self) -> list[dict]:
        return deepcopy(self._records)

    def get(self, record_id: str) -> dict | None:
        record = self._by_id.get(record_id)
        return deepcopy(record) if record is not None else None


@dataclass(frozen=True)
class Repositories:
    flights: FlightRepository
    products: ProductRepository
    movies: MovieRepository
    cinemas: CinemaRepository
    showtimes: ShowtimeRepository


def load_repositories(data_dir: Path) -> Repositories:
    """Construct the JSON adapters and reject broken cross-file references."""
    repos = Repositories(**{
        name: JsonRepository(data_dir, name)
        for name in REQUIRED_FIELDS
    })
    validate_references(
        repos.movies.list_all(), repos.cinemas.list_all(), repos.showtimes.list_all()
    )
    return repos


