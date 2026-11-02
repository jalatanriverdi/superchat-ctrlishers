"""Film discovery, linked showtimes, and mock ticket reservations."""

from __future__ import annotations

from datetime import date

from ..repositories import CinemaRepository, MovieRepository, ShowtimeRepository
from .common import InvalidRequest, Reservation, ReservationLedger, UnknownItem


def _valid_date(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (TypeError, ValueError):
        pass
    raise InvalidRequest("Date must be YYYY-MM-DD.")


class CinemaService:
    def __init__(
        self, movies: MovieRepository, cinemas: CinemaRepository,
        showtimes: ShowtimeRepository, reservations: ReservationLedger,
    ):
        self._movies = movies
        self._cinemas = cinemas
        self._showtimes = showtimes
        self._reservations = reservations

    def get_movie(self, movie_id: str) -> dict:
        movie = self._movies.get(movie_id)
        if movie is None:
            raise UnknownItem(f"Unknown film: {movie_id}")
        return movie

    def find_movies(
        self, *, genre: str | None = None, min_rating: object | None = None,
        language: str | None = None, showing_on: str | None = None,
    ) -> list[dict]:
        if showing_on is not None:
            showing_on = _valid_date(showing_on)
        if min_rating is not None:
            try:
                rating = float(min_rating)
            except (TypeError, ValueError) as exc:
                raise InvalidRequest("Rating must be a number from 0 to 10.") from exc
            if not 0 <= rating <= 10:
                raise InvalidRequest("Rating must be a number from 0 to 10.")
        else:
            rating = None
        showing_ids = (
            {show["movie_id"] for show in self._showtimes.list_all() if show["date"] == showing_on}
            if showing_on else None
        )
        results = []
        for movie in self._movies.list_all():
            if genre and not any(value.casefold() == genre.strip().casefold() for value in movie["genre"]):
                continue
            if rating is not None and movie["rating"] < rating:
                continue
            if language and movie["language"].casefold() != language.strip().casefold():
                continue
            if showing_ids is not None and movie["id"] not in showing_ids:
                continue
            results.append(movie)
        return results

    def get_showtime(self, showtime_id: str) -> dict:
        showtime = self._showtimes.get(showtime_id)
        if showtime is None:
            raise UnknownItem(f"Unknown showtime: {showtime_id}")
        showtime["movie"] = self.get_movie(showtime["movie_id"])
        showtime["cinema"] = self._cinemas.get(showtime["cinema_id"])
        showtime["seats_available"] = self._reservations.remaining(
            "showtime", showtime_id, showtime["seats_available"]
        )
        return showtime

    def showtimes_for(self, movie_id: str, *, showing_on: str | None = None) -> list[dict]:
        self.get_movie(movie_id)
        if showing_on is not None:
            showing_on = _valid_date(showing_on)
        return [self.get_showtime(show["id"]) for show in self._showtimes.list_all()
                if show["movie_id"] == movie_id and
                (showing_on is None or show["date"] == showing_on)]

    def reserve_tickets(self, showtime_id: str, quantity: int = 1) -> Reservation:
        showtime = self._showtimes.get(showtime_id)
        if showtime is None:
            raise UnknownItem(f"Unknown showtime: {showtime_id}")
        return self._reservations.reserve(
            "showtime", showtime_id, showtime["seats_available"],
            quantity, showtime["price_azn"],
        )
