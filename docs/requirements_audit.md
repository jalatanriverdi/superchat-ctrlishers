# Phase 1 requirements audit

This audit maps the mandatory brief to code and verification. The five official datasets in `SuperChat_Mock_Data/` are the only source of catalogue facts. The current reference date is 2 November 2026.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| One chat, complete history, automatic routing | `superchat/static/`, `semantic.py`, `semantic_conversation.py`, HTTP cookie session | `test_semantic_pipeline.py`, `test_http.py`, live conversation 9/9 |
| Flights, Shopping, Cinema, mixed, follow-up, ambiguous, out of scope, small talk | Structured interpreter with validated domain actions | `test_semantic_pipeline.py`, `tools.live_eval`, `tools.live_conversation_eval` |
| Separate domain and shared session state, switching and returning | `conversation.py` Session/DomainContext; `semantic_conversation.py` context and executor | `test_semantic_pipeline.py`, `test_conversation.py`, live conversation and multilingual logs |
| Targeted clarification and retained search slots | Flight pending field and merged filters; validated clarify plans | `test_semantic_pipeline.py`, `test_conversation.py` |
| Flight search by origin, destination and date; price, stops, departure and airline filters/sorts | `semantic_conversation.py`, `query.py`, `domains/flights.py` | `test_semantic_pipeline.py`, `test_domains.py`, live filters |
| Flight details, comparison and mock reservation | Flight service, response formatter, reservation ledger | `test_semantic_pipeline.py`, `test_domains.py` |
| Product text/category/brand/price/color search, details, comparison and stock | `query.py`, `domains/shopping.py`, card presentation | `test_semantic_pipeline.py`, `test_domains.py`, live product cases |
| Add/remove cart items and correct total | Session cart and shopping executor | `test_semantic_pipeline.py`, `test_domains.py`, card-action HTTP test |
| Film genre/rating/language/date search; cinema/showtimes/prices/seats; mock tickets | `query.py`, `domains/cinema.py`, showtime-linked cards and ledger | `test_semantic_pipeline.py`, `test_domains.py`, live numeric cases |
| No invented results, empty results, data errors | Five validated JSON repositories; constrained plan and deterministic result rendering | `test_repositories.py`, `test_semantic_pipeline.py`, `test_http.py` |
| Replaceable mock repositories, no Phase 2 APIs or payment | `repositories.py`, `data_validation.py`, in-memory reservations | `test_repositories.py`, `test_domains.py` |
| Setup, one start command, report ≤4 pages, routing accuracy/error analysis, five-minute demo with ≥3 switches | `README.md`, `docs/technical_report.md`, `docs/routing_test_log.md`, `docs/demo_flow.md` | Documentation review and commands in README |

## Bonuses requested later

| Bonus | Status and location | Verification / limit |
| --- | --- | --- |
| Voice input with automatic speech boundaries | Browser SpeechRecognition in `static/app.js`; final transcripts use normal chat | `tests/voice_ui_smoke.cjs`; physical microphone and browser language quality vary |
| Visual product search | `visual.py`, `/api/visual-search`, confidence and verified-ID checks | `test_visual.py`, `test_semantic_pipeline.py`, live low-confidence image check; matching accuracy on arbitrary photos is unmeasured |
| English, Azerbaijani and Russian text, including switches | `semantic.py` language plan, `canonical.py`, `localization.py`, response formatting | 12/12 final multilingual live cases; earlier return failure and correction documented in routing log |

The running application remains dependent on an OpenRouter or OpenAI key and internet access for natural-language interpretation. The routing scores are samples, and the bonus limits above remain part of the current implementation.
