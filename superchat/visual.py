"""Optional photo interpretation, constrained to official product records."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .repositories import ProductRepository
from .semantic import InterpretationError, model_connection


MAX_IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def decode_image(data_url: str) -> tuple[bytes, str]:
    if not isinstance(data_url, str) or len(data_url) > 6_000_000:
        raise InterpretationError("Choose a JPEG, PNG or WebP image under 4 MB.")
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)", data_url)
    if not match:
        raise InterpretationError("Choose a JPEG, PNG or WebP image under 4 MB.")
    try:
        image = base64.b64decode(match.group(2), validate=True)
    except binascii.Error as exc:
        raise InterpretationError("The image could not be read.") from exc
    mime = match.group(1)
    signatures = {"image/jpeg": image.startswith(b"\xff\xd8\xff"),
                  "image/png": image.startswith(b"\x89PNG\r\n\x1a\n"),
                  "image/webp": image.startswith(b"RIFF") and image[8:12] == b"WEBP"}
    if not image or len(image) > MAX_IMAGE_BYTES or not signatures[mime]:
        raise InterpretationError("Choose a valid JPEG, PNG or WebP image under 4 MB.")
    return image, mime


class ImageAnalyzer(Protocol):
    def analyze(self, image: bytes, mime: str, catalogue: list[dict]) -> dict: ...


class OpenRouterImageAnalyzer:
    def __init__(self, timeout: int = 45):
        self.timeout = timeout

    def analyze(self, image: bytes, mime: str, catalogue: list[dict]) -> dict:
        base_url, key, model = model_connection()
        ids = [row["id"] for row in catalogue]
        categories = sorted({row["category"] for row in catalogue})
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {
                      "confidence": {"type": "number"},
                      "category": {"type": "string", "enum": ["", *categories]},
                      "candidate_ids": {"type": "array", "items": {"type": "string", "enum": ids}},
                  }, "required": ["confidence", "category", "candidate_ids"]}
        data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "Identify the visible product type from the photo. Select only plausible "
                    "matches from the supplied catalogue. Do not assume an exact brand or "
                    "model unless visible evidence supports it. If uncertain, return no IDs "
                    "and a confidence below 0.6. Confidence is an estimate from 0 to 1. "
                    "Return JSON only.")},
                {"role": "user", "content": [
                    {"type": "text", "text": "Catalogue: " + json.dumps(catalogue, ensure_ascii=False)},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "superchat_visual_match", "strict": True, "schema": schema}},
        }
        if "openrouter.ai" in base_url:
            payload["provider"] = {"require_parameters": True}
        request = Request(base_url + "/chat/completions",
                          json.dumps(payload).encode("utf-8"),
                          {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
            return json.loads(body["choices"][0]["message"]["content"])
        except HTTPError as exc:
            raise InterpretationError(f"Image service returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise InterpretationError("The image could not be analyzed right now.") from exc


class VisualSearchService:
    def __init__(self, products: ProductRepository, analyzer: ImageAnalyzer | None = None):
        self.products = products
        self.analyzer = analyzer or OpenRouterImageAnalyzer()

    def search(self, data_url: str) -> tuple[float, list[dict]]:
        image, mime = decode_image(data_url)
        products = self.products.list_all()
        catalogue = [{"id": row["id"], "name": row["name"]["en"],
                      "category": row["category"], "brand": row["brand"],
                      "color": row["color"], "description": row["description"]}
                     for row in products]
        answer = self.analyzer.analyze(image, mime, catalogue)
        if not isinstance(answer, dict):
            raise InterpretationError("The image match was not reliable.")
        confidence = answer.get("confidence")
        category = answer.get("category")
        ids = answer.get("candidate_ids")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or
                not 0 <= confidence <= 1 or not isinstance(category, str) or
                not isinstance(ids, list) or not all(isinstance(item, str) for item in ids)):
            raise InterpretationError("The image match was not reliable.")
        valid_categories = {row["category"] for row in products}
        by_id = {row["id"]: row for row in products}
        valid_ids = set(by_id)
        if category and category not in valid_categories or any(item not in valid_ids for item in ids):
            raise InterpretationError("The image match was not reliable.")
        if category and any(by_id[item]["category"] != category for item in ids):
            raise InterpretationError("The image match was not reliable.")
        if not ids and not category:
            return min(confidence, 0.59), []
        if confidence < 0.6:
            return confidence, []
        if ids:
            matches = [self.products.get(item) for item in dict.fromkeys(ids[:3])]
        else:
            matches = [row for row in products if row["category"] == category]
        return confidence, matches
