"""Evaluate the real OpenAI interpretation and execution path.

Run after setting OPENROUTER_API_KEY or OPENAI_API_KEY. Prints plan fields and record IDs, never the key.
"""

from __future__ import annotations

import os
import argparse
from pathlib import Path

from superchat.repositories import load_repositories
from superchat.semantic_conversation import SemanticConversationEngine
from superchat.semantic import OpenAIPlanner
from superchat.settings import load_local_env


DATA = Path(__file__).resolve().parents[1] / "SuperChat_Mock_Data"

# Distinct scenarios avoid carrying context between unrelated search checks.
CASES = [
    ("Give me movies which age support 12", "cinema",
     {"M001", "M002", "M003", "M005", "M007", "M008"}),
    ("Movies which have 8 rating", "cinema", set()),
    ("Movies rated below 8", "cinema",
     {"M002", "M003", "M004", "M005", "M006", "M007"}),
    ("English sci-fi films rated above 8", "cinema", {"M001", "M008"}),
    ("List films suitable for a 6-year-old", "cinema", {"M003", "M005"}),
    ("Find direct flights from Baku to Istanbul on Friday under 300 AZN",
     "flights", {"F001", "F002"}),
    ("Find black headphones under 200 AZN", "shopping", {"P001"}),
    ("Show waterproof speakers", "shopping", {"P008"}),
    ("Find laptops cheaper than 1500 AZN", "shopping", {"P004"}),
    ("Find purple headphones", "shopping", set()),
    ("Write a poem about Istanbul flights", "out_of_scope", set()),
    ("What is the weather in Ganja?", "out_of_scope", set()),
    ("Show me something good", "clarify", set()),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="OpenRouter or OpenAI model ID to test")
    parser.add_argument("--limit", type=int, default=len(CASES))
    args = parser.parse_args()
    load_local_env()
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("Set OPENROUTER_API_KEY or OPENAI_API_KEY in this PowerShell terminal before running the live evaluation.")
        return 2
    os.environ["SUPERCHAT_DEBUG"] = "1"
    engine = SemanticConversationEngine(load_repositories(DATA),
                                        planner=OpenAIPlanner(model=args.model))
    passed = 0
    cases = CASES[:args.limit]
    for index, (message, expected_route, expected_ids) in enumerate(cases, 1):
        session = engine.sessions.get_or_create(None)
        result = engine.respond(session, message)
        actual_ids = {item for batch in result["diagnostics"]["returned_ids"]
                      for item in batch["ids"]}
        ok = result["route"] == expected_route and actual_ids == expected_ids
        passed += ok
        print(f"{index:02d} {'PASS' if ok else 'FAIL'} | {message}")
        print(f"   route={result['route']} ids={sorted(actual_ids)} expected={sorted(expected_ids)}")
        if not ok:
            print(f"   actions={result['diagnostics']['actions']}")
            print(f"   reply={result['reply']}")
    print(f"Live interpreter: {passed}/{len(cases)} cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
