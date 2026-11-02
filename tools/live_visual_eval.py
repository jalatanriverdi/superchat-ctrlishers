"""Exercise OpenRouter/OpenAI image interpretation with a synthetic 1-pixel fixture."""

from __future__ import annotations

import json
import os
import base64
import struct
import zlib
from pathlib import Path
from urllib.error import HTTPError

from superchat.repositories import load_repositories
from superchat.settings import load_local_env
from superchat.visual import VisualSearchService
from superchat.semantic import InterpretationError


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data +
            struct.pack(">I", zlib.crc32(kind + data)))


def _test_image() -> str:
    """A valid red square used only to test the image API, not a product record."""
    width = height = 128
    pixels = (b"\x00" + b"\xff\x00\x00" * width) * height
    png = (b"\x89PNG\r\n\x1a\n" +
           _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
           _chunk(b"IDAT", zlib.compress(pixels)) + _chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def main() -> int:
    load_local_env()
    service = VisualSearchService(load_repositories(
        Path(__file__).resolve().parents[1] / "SuperChat_Mock_Data").products)
    try:
        confidence, rows = service.search(_test_image())
    except InterpretationError as exc:
        print("Visual API check failed:", exc)
        if isinstance(exc.__cause__, HTTPError):
            try:
                body = json.loads(exc.__cause__.read())
                message = json.dumps(body, ensure_ascii=False)
                for key in (os.environ.get("OPENROUTER_API_KEY"), os.environ.get("OPENAI_API_KEY")):
                    if key:
                        message = message.replace(key, "[redacted]")
                print("Provider error:", message[:1500])
            except (ValueError, TypeError, AttributeError):
                pass
        return 1
    print("Visual API accepted image; confidence:", confidence,
          "verified record IDs:", [row["id"] for row in rows])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
