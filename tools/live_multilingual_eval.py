"""Live English/Azerbaijani/Russian routing and result checks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from superchat.repositories import load_repositories
from superchat.semantic_conversation import SemanticConversationEngine
from superchat.settings import load_local_env


DATA = Path(__file__).resolve().parents[1] / "SuperChat_Mock_Data"
CASES = [
    ("az", "Bakıdan İstanbula 6 noyabrda uçuşları göstər", "flights",
     {"F001", "F002", "F013"}),
    ("ru", "Покажи рейсы из Баку в Стамбул 6 ноября", "flights",
     {"F001", "F002", "F013"}),
    ("az", "1500 AZN-dən ucuz noutbukları göstər", "shopping", {"P004"}),
    ("ru", "Покажи чёрные наушники дешевле 200 AZN", "shopping", {"P001"}),
    ("az", "12 yaşlı uşaq üçün uyğun filmlər", "cinema",
     {"M001", "M002", "M003", "M005", "M007", "M008"}),
    ("ru", "Фильмы с рейтингом ниже 8", "cinema",
     {"M002", "M003", "M004", "M005", "M006", "M007"}),
    ("ru", "Расскажи анекдот про кино", "out_of_scope", set()),
    ("az", "Mənə şeir yaz", "out_of_scope", set()),
    ("en", "Find black headphones under 200 AZN and flights from Bakı to Istanbul on 6 noyabr",
     "mixed", {"P001", "F001", "F002", "F013"}),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_local_env()
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("Configure an API key in .env before running live multilingual checks.")
        return 2
    os.environ["SUPERCHAT_DEBUG"] = "1"
    engine = SemanticConversationEngine(load_repositories(DATA))
    passed = 0
    by_language = {"en": [0, 0], "az": [0, 0], "ru": [0, 0]}
    for language, message, expected_route, expected_ids in CASES:
        session = engine.sessions.get_or_create(None)
        result = engine.respond(session, message)
        ids = {item for batch in result["diagnostics"]["returned_ids"]
               for item in batch["ids"]}
        ok = (result["route"] == expected_route and ids == expected_ids and
              session.language == language)
        by_language[language][0] += int(ok)
        by_language[language][1] += 1
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} [{language}] {message}", flush=True)
        print(f"  route={result['route']} language={session.language} ids={sorted(ids)}"
              f" expected={sorted(expected_ids)}", flush=True)
        if not ok:
            print(f"  diagnostics={result['diagnostics']}", flush=True)
    sequence = engine.sessions.get_or_create(None)
    sequence_checks = [
        ("Show me headphones under 100 AZN", "shopping", "en", {"P001"}),
        ("Что идёт сегодня в кино?", "cinema", "ru", None),
        ("Вернись к наушникам", "shopping", "ru", {"P001"}),
    ]
    for message, expected_route, language, expected_ids in sequence_checks:
        result = engine.respond(sequence, message)
        ids = {item for batch in result["diagnostics"]["returned_ids"]
               for item in batch["ids"]}
        ok = (result["route"] == expected_route and sequence.language == language and
              (expected_ids is None or ids == expected_ids))
        passed += int(ok)
        by_language[language][0] += int(ok)
        by_language[language][1] += 1
        print(f"{'PASS' if ok else 'FAIL'} [{language}] {message}", flush=True)
        print(f"  route={result['route']} language={sequence.language} ids={sorted(ids)}",
              flush=True)
        if not ok:
            print(f"  diagnostics={result['diagnostics']}", flush=True)
    total_cases = len(CASES) + len(sequence_checks)
    print(f"Multilingual live checks: {passed}/{total_cases}")
    for language, (correct, total) in by_language.items():
        print(f"  {language}: {correct}/{total}")
    return 0 if passed == total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
