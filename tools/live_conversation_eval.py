"""Live multi-turn routing, state, and mixed-intent regression check."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

from superchat.repositories import load_repositories
from superchat.semantic_conversation import SemanticConversationEngine
from superchat.settings import load_local_env


DATA = Path(__file__).resolve().parents[1] / "SuperChat_Mock_Data"
CASES = [
    ("Find flights from Baku to Istanbul on Friday.", "flights",
     {"F001", "F002", "F013"}),
    ("The cheaper one, is it direct?", "flights", {"F013"}),
    ("Write a poem about Istanbul flights.", "out_of_scope", set()),
    ("Back to the flights.", "flights", {"F001", "F002", "F013"}),
    ("What is playing tonight?", "cinema", None),
    ("Show wireless headphones under 100 AZN.", "shopping", {"P001"}),
    ("The first one, is it in stock?", "shopping", {"P001"}),
    ("Back to the movies.", "cinema", None),
    ("Find a flight from Baku to Istanbul on 6 November and a backpack.", "mixed",
     {"F001", "F002", "F013", "P010"}),
]


def _state(session):
    return deepcopy((session.active_domain, session.pending_domain, session.pending_field,
                     session.flights.criteria, session.flights.result_ids, session.flights.selected_id,
                     session.shopping.criteria, session.shopping.result_ids,
                     session.shopping.selected_id, session.cinema.criteria,
                     session.cinema.result_ids, session.cinema.selected_id))


def main() -> int:
    load_local_env()
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("Configure an API key in .env before running live conversation checks.")
        return 2
    os.environ["SUPERCHAT_DEBUG"] = "1"
    engine = SemanticConversationEngine(load_repositories(DATA))
    session = engine.sessions.get_or_create(None)
    passed = 0
    for message, expected_route, expected_ids in CASES:
        before = _state(session)
        result = engine.respond(session, message)
        ids = {item for batch in result["diagnostics"]["returned_ids"]
               for item in batch["ids"]}
        state_preserved = expected_route != "out_of_scope" or _state(session) == before
        ok = (result["route"] == expected_route and state_preserved and
              (expected_ids is None or ids == expected_ids))
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} {message}", flush=True)
        print(f"  route={result['route']} ids={sorted(ids)} state_preserved={state_preserved}",
              flush=True)
        if not ok:
            print(f"  diagnostics={result['diagnostics']}", flush=True)
    print(f"Live conversation: {passed}/{len(CASES)}")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
