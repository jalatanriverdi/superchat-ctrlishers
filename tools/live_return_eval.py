"""Focused live-model check for switching language and returning to a topic."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from superchat.repositories import load_repositories
from superchat.semantic_conversation import SemanticConversationEngine
from superchat.settings import load_local_env


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_local_env()
    os.environ["SUPERCHAT_DEBUG"] = "1"
    root = Path(__file__).resolve().parents[1]
    engine = SemanticConversationEngine(load_repositories(root / "SuperChat_Mock_Data"))
    session = engine.sessions.get_or_create(None)
    cases = [
        ("Show me headphones under 100 AZN", "shopping", {"P001"}),
        ("Что идёт сегодня в кино?", "cinema", None),
        ("Вернись к наушникам", "shopping", {"P001"}),
    ]
    passed = 0
    for message, route, expected in cases:
        result = engine.respond(session, message)
        ids = {item for batch in result["diagnostics"]["returned_ids"]
               for item in batch["ids"]}
        ok = result["route"] == route and (expected is None or ids == expected)
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} {message}: {result['route']} {sorted(ids)}",
              flush=True)
        if not ok:
            print(f"  diagnostics={result['diagnostics']}", flush=True)
    print(f"Return check: {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
