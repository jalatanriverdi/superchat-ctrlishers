"""Load optional local secrets without adding a runtime dependency."""

from __future__ import annotations

import os
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ALLOWED_KEYS = {"OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL"}


def load_local_env(path: Path = ENV_FILE) -> None:
    """Read simple KEY=VALUE entries; existing process variables take precedence."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, value = (part.strip() for part in entry.split("=", 1))
        if key not in ALLOWED_KEYS or not value:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
