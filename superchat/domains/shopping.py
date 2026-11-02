"""Product discovery and a session-owned mock cart."""

from __future__ import annotations

import re
from decimal import Decimal

from ..repositories import ProductRepository
from .common import InvalidRequest, Unavailable, UnknownItem, money, positive_quantity


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    return {word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
            for word in words}


class ShoppingService:
    def __init__(self, products: ProductRepository):
        self._products = products

    def get(self, product_id: str) -> dict:
        product = self._products.get(product_id)
        if product is None:
            raise UnknownItem(f"Unknown product: {product_id}")
        return product

    def search(
        self, *, text: str | None = None, category: str | None = None,
        brand: str | None = None, min_price: object | None = None,
        max_price: object | None = None, color: str | None = None,
    ) -> list[dict]:
        lower = money(min_price) if min_price is not None else None
        upper = money(max_price) if max_price is not None else None
        if lower is not None and upper is not None and lower > upper:
            raise InvalidRequest("Minimum price exceeds maximum price.")
        query_tokens = _tokens(text) if text else set()
        results = []
        for product in self._products.list_all():
            if category and product["category"].casefold() != category.strip().casefold():
                continue
            if brand and product["brand"].casefold() != brand.strip().casefold():
                continue
            if color and product["color"].casefold() != color.strip().casefold():
                continue
            price = money(product["price_azn"])
            if lower is not None and price < lower:
                continue
            if upper is not None and price > upper:
                continue
            searchable = " ".join((
                *product["name"].values(), product["category"], product["brand"],
                product["description"], product["color"],
            ))
            if not query_tokens <= _tokens(searchable):
                continue
            results.append(product)
        # Preserve catalogue order within each tier, while putting name matches
        # ahead of matches found only in a description or another field.
        results.sort(key=lambda product: not query_tokens <= _tokens(" ".join(product["name"].values())))
        return results

    def compare(self, product_ids: list[str]) -> list[dict]:
        if len(set(product_ids)) < 2 or len(set(product_ids)) != len(product_ids):
            raise InvalidRequest("Choose at least two different products to compare.")
        return [self.get(product_id) for product_id in product_ids]

    def stock(self, product_id: str) -> int:
        return self.get(product_id)["stock"]


class Cart:
    def __init__(self, products: ProductRepository):
        self._products = products
        self._items: dict[str, int] = {}

    def add(self, product_id: str, quantity: int = 1) -> dict:
        positive_quantity(quantity)
        product = self._products.get(product_id)
        if product is None:
            raise UnknownItem(f"Unknown product: {product_id}")
        if self._items.get(product_id, 0) + quantity > product["stock"]:
            raise Unavailable(f"Only {product['stock']} unit(s) are in stock.")
        self._items[product_id] = self._items.get(product_id, 0) + quantity
        return self.summary()

    def remove(self, product_id: str, quantity: int | None = None) -> dict:
        if product_id not in self._items:
            raise InvalidRequest("That product is not in the cart.")
        if quantity is None:
            del self._items[product_id]
        else:
            positive_quantity(quantity)
            remaining = self._items[product_id] - quantity
            if remaining < 0:
                raise InvalidRequest("Cannot remove more than the cart contains.")
            if remaining == 0:
                del self._items[product_id]
            else:
                self._items[product_id] = remaining
        return self.summary()

    def summary(self) -> dict:
        items = []
        total = Decimal("0")
        for product_id, quantity in self._items.items():
            product = self._products.get(product_id)
            if product is None:
                raise UnknownItem(f"Unknown product: {product_id}")
            subtotal = money(product["price_azn"]) * quantity
            items.append({"product": product, "quantity": quantity, "subtotal_azn": subtotal})
            total += subtotal
        return {"items": items, "total_azn": total}
