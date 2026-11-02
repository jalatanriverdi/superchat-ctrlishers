"""Map presentation-language catalogue values back to official JSON values."""

from __future__ import annotations

from .localization import LABELS


ALIASES = {
    "чёрные": "black", "черные": "black", "чёрный": "black", "черный": "black",
    "белые": "white", "белый": "white",
    "серебристые": "silver", "серебристый": "silver",
    "серые": "grey", "серый": "grey",
    "синие": "blue", "синий": "blue",
    "разноцветные": "multicolor", "разноцветный": "multicolor",
}
for official, languages in LABELS.items():
    for translated in languages.values():
        ALIASES[translated.casefold()] = official


def canonical_value(field: str, value: str) -> str:
    if field not in {"color", "genre", "language"}:
        return value
    return ALIASES.get(value.strip().casefold(), value)


def canonicalize_plan(plan: dict) -> dict:
    for action in plan.get("actions", []):
        for group in action.get("filter_groups", []):
            for condition in group:
                if isinstance(condition, dict) and isinstance(condition.get("value"), str):
                    condition["value"] = canonical_value(condition.get("field", ""),
                                                         condition["value"])
    return plan
