"""UI cards assembled only from verified mock repository records."""

from __future__ import annotations

from .conversation import _amount, _duration, _say
from .localization import MOVIE_SYNOPSIS, PRODUCT_DESCRIPTIONS, label, translated


def result_cards(domain: str, ids: list[str], language: str,
                 flights, shopping, cinema) -> list[dict]:
    """Return compact, language-aware display data for already executed IDs."""
    cards = []
    for item_id in ids:
        if domain == "flights":
            row = flights.get(item_id)
            cards.append({
                "domain": domain, "kind": "flight", "id": row["id"],
                "title": f"{row['origin']['code']} → {row['destination']['code']}",
                "subtitle": f"{row['airline']} · {row['flight_number']}",
                "price": _amount(row["price_azn"]),
                "facts": [
                    f"{row['departure_local'].replace('T', ' ')} → {row['arrival_local'].replace('T', ' ')}",
                    _duration(row["duration_min"]),
                    _say(language, "Direct", "Birbaşa", "Прямой") if row["stops"] == 0 else
                    f"{row['stops']} " + _say(language, "stop(s)", "dayanacaq", "пересадка"),
                    f"{_say(language, 'Baggage', 'Baqaj', 'Багаж')} {row['baggage_kg']} kg",
                    f"{row['seats_available']} " + _say(language, "seats left", "boş yer", "свободных мест"),
                ],
                "detail": (f"{_say(language, 'Via', 'Vasitəsilə', 'Через')} {row['via']}"
                           if row["via"] else ""),
                "action_label": _say(language, "View flight", "Uçuşa bax", "Смотреть рейс"),
                "action": "details",
            })
        elif domain == "shopping":
            row = shopping.get(item_id)
            cards.append({
                "domain": domain, "kind": "product", "id": row["id"],
                "title": row["name"].get(language, row["name"]["en"]),
                "subtitle": f"{row['brand']} · {label(row['color'], language)}",
                "price": _amount(row["price_azn"]),
                "facts": [
                    f"★ {row['rating']}",
                    f"{row['stock']} " + _say(language, "in stock", "stokda", "в наличии"),
                    row["category"],
                ],
                "detail": translated(PRODUCT_DESCRIPTIONS, row["id"], language,
                                     row["description"]),
                "action_label": _say(language, "Add to cart", "Səbətə əlavə et", "В корзину"),
                "action": "cart_add",
            })
        elif item_id.startswith("S"):
            row = cinema.get_showtime(item_id)
            cards.append({
                "domain": domain, "kind": "showtime", "id": row["id"],
                "title": row["movie"]["title"],
                "subtitle": row["cinema"]["name"],
                "price": _amount(row["price_azn"]),
                "facts": [
                    f"{row['date']} · {row['time']}",
                    row["hall"],
                    f"{row['seats_available']} " + _say(language, "seats left", "boş yer", "свободных мест"),
                ],
                "detail": row["cinema"]["address"],
                "action_label": _say(language, "View showtime", "Seansa bax", "Смотреть сеанс"),
                "action": "details",
            })
        else:
            row = cinema.get_movie(item_id)
            cards.append({
                "domain": domain, "kind": "movie", "id": row["id"],
                "title": row["title"],
                "subtitle": ", ".join(label(genre, language) for genre in row["genre"]),
                "price": "",
                "facts": [
                    f"★ {row['rating']}", row["age_rating"],
                    label(row["language"], language),
                    _duration(row["duration_min"]),
                ],
                "detail": translated(MOVIE_SYNOPSIS, row["id"], language, row["synopsis"]),
                "action_label": _say(language, "See showtimes", "Seanslara bax", "Посмотреть сеансы"),
                "action": "showtimes",
            })
    return cards
