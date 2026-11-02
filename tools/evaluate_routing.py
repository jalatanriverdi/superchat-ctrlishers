"""Measure routing on authored multi-turn cases, without network access."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

from superchat.conversation import ConversationEngine
from superchat.repositories import load_repositories


ROOT = Path(__file__).resolve().parent.parent
cases = json.loads((ROOT / "tests" / "routing_cases.json").read_text(encoding="utf-8"))
engine = ConversationEngine(load_repositories(ROOT / "SuperChat_Mock_Data"), date(2026, 11, 2))
counts = Counter()
errors = []
for scenario in cases:
    session = engine.sessions.get_or_create(None)
    for message, expected_category, expected_domains in scenario["turns"]:
        result = engine.respond(session, message)
        actual_domains = ",".join(result["domains"])
        counts["total"] += 1
        counts[expected_category] += 1
        if result["route"] == expected_category and actual_domains == expected_domains:
            counts["correct"] += 1
        else:
            errors.append({
                "scenario": scenario["name"], "message": message,
                "expected": f"{expected_category} [{expected_domains}]",
                "actual": f"{result['route']} [{actual_domains}]",
            })

print(f"Routing accuracy: {counts['correct']}/{counts['total']} "
      f"({100 * counts['correct'] / counts['total']:.1f}%)")
print("Expected categories:", dict(sorted((key, value) for key, value in counts.items()
                                          if key not in {"total", "correct"})))
for error in errors:
    print(f"ERROR {error['scenario']}: {error['message']!r} "
          f"expected {error['expected']}, got {error['actual']}")
