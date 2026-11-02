# SuperChat — Phase 1

SuperChat is a web chat for the official Flights, Shopping and Cinema mock datasets. A language model through OpenRouter or OpenAI interprets messages into structured operations; the local backend validates those operations and retrieves facts only from the five official JSON files. Cart and reservations are mock state. There are no real flight, commerce or cinema API integrations or payments.

The single chat now shows verified results as cards, with clear prices, times and availability. The sidebar offers optional example prompts; typing naturally still routes requests automatically. Card buttons use validated backend actions for details, cart additions and showtimes.

Rendered previews: [desktop](docs/ui_desktop.png) and [narrow layout](docs/ui_mobile.png).

## Requirements

- Python 3.10 or newer
- The five official JSON files in `SuperChat_Mock_Data/`: `flights.json`, `products.json`, `movies.json`, `cinemas.json`, `showtimes.json`
- An OpenRouter or OpenAI API key and internet connection for language interpretation. Python runtime uses only the standard library.

## Start the app

Open `.env` in this project folder and paste your OpenRouter key after `OPENROUTER_API_KEY=`. If `.env` does not exist, copy `.env.example` to `.env` first. For example, the file should contain these lines (replace the example value with your own key):

```text
OPENROUTER_API_KEY=your-key-here
OPENROUTER_MODEL=openai/gpt-5-mini
```

Save the file. Then, from this directory, run **one command**:

```powershell
python -m superchat
```

Keep that terminal open. Then open **http://127.0.0.1:8000/** in a browser on the same computer. The `/health` URL only checks whether the server and data loaded; the chat is at `/`. If the browser says *connection refused*, check that the command is still running and that port 8000 is free. Stop the app with `Ctrl+C`.

`openai/gpt-5-mini` remains the default OpenRouter model after live evaluation. You can set `OPENROUTER_MODEL=google/gemini-2.5-flash` to try Gemini, but the recorded 13-case check scored 10/13 with that model versus 13/13 with the default. See `docs/routing_test_log.md` before changing the demo model.

If you previously ran SuperChat before adding the key, stop that older process and start it again. The new `/ready` endpoint returns `{"status":"ready"}` once the server has loaded the configured key. A previous browser conversation may still show old error messages until **New chat** is clicked; new replies use the current server.

Do not put the key in source code, the browser, a URL or chat. `.env` is ignored by Git. If the key is absent, the page still loads but chat explains that a key must be set. Existing PowerShell environment variables take precedence over `.env`. OpenAI direct access remains available with `OPENAI_API_KEY` and optional `OPENAI_MODEL` instead.

To use another port: `python -m superchat --port 8080`. To bind on an interface for a hosting environment: `python -m superchat --host 0.0.0.0` (the `PORT` environment variable is also supported). Binding alone does not create a public URL; that requires a Python-capable host.

## Try a conversation

1. `Find me a flight from Baku to Istanbul on Friday.`
2. `The cheaper one, is it direct?`
3. `What is playing tonight?`
4. `Show me laptops.`
5. `The second one, is it in stock?`
6. `Okay, and the sci-fi one, any seats on Saturday?`

The dataset reference date is **2 November 2026**. Friday resolves to 6 November and Saturday to 7 November. The two sci-fi films in the official data both have Saturday shows, so SuperChat lists both rather than guessing which film you meant.

## Bonus controls

- **Voice:** Choose a voice language and enable the microphone once. In browsers with Web Speech recognition, speech detection and transcription continue without holding a button. Final transcripts enter the same chat pipeline. The browser may request microphone permission and may use its own online speech service. Browser support and Azerbaijani speech quality vary; the text chat remains available.
- **Photo search:** Use the photo button to upload a JPEG, PNG or WebP image up to 4 MB. The configured model estimates a match and confidence; the backend displays only verified products from the official catalogue. Low-confidence images prompt a question. The photo is sent to the configured model provider for analysis and is not stored in session history or the official data files.
- **Languages:** Text requests can switch among English, Azerbaijani and Russian. The interpreter selects the reply language for each turn, and the app uses catalogue names plus presentation-only translations for descriptions and synopses. Mixed-language requests use the language of the main request. The official five JSON files remain the source of all records, prices and availability.

## Tests

```powershell
python -B -m unittest discover -s tests -v
python -B -m tools.evaluate_routing
python -B -m tools.live_eval
python -B -m tools.live_multilingual_eval
python -B -m tools.live_conversation_eval
python -B -m tools.live_return_eval
python -B -m tools.live_visual_eval
node tests/voice_ui_smoke.cjs
```

The first command covers repositories, deterministic domain operations, validated structured plans, conversation state, HTTP sessions, card actions, and photo-search validation. Semantic pipeline tests use a controlled test interpreter; they do not measure live model accuracy. The second command measures the older deterministic router only and is retained for comparison. The `live_` commands use the configured model and may make several API calls. On Windows, run multilingual checks with `python -X utf8 -B -m tools.live_multilingual_eval` if the terminal uses a legacy encoding. The Node check uses a mocked browser recognizer; it does not test a physical microphone.

To inspect interpreted operations and returned record IDs while developing, set `$env:SUPERCHAT_DEBUG = '1'` before starting the server. `/api/chat` responses then include `diagnostics`. The key is never included in diagnostics.

## Code map

| Path | Purpose |
| --- | --- |
| `superchat/__main__.py` | Local web server, browser files and JSON endpoints |
| `superchat/semantic.py` | OpenRouter/OpenAI structured interpreter and plan validation |
| `superchat/visual.py` | Optional photo interpretation with catalogue ID and confidence validation |
| `superchat/localization.py` | Presentation-only Azerbaijani and Russian catalogue translations |
| `superchat/presentation.py` | Verified, localized cards for the browser UI |
| `superchat/query.py` | Deterministic filters, comparisons and sorting |
| `superchat/semantic_conversation.py` | Session orchestration and tool execution |
| `superchat/conversation.py` | Shared session data and legacy formatting helpers |
| `superchat/routing.py`, `superchat/parsing.py` | Earlier deterministic implementation, retained for comparison |
| `superchat/domains/` | Flights, Shopping, Cinema and mock reservation operations |
| `superchat/repositories.py` | Replaceable repository contracts and JSON adapters |
| `superchat/data_validation.py` | Official schema and cross-file validation |
| `superchat/static/` | Single chat page, CSS and browser JavaScript |

The domain services depend on repository contracts rather than file paths. In Phase 2, API-backed repository implementations can replace the JSON adapters without changing routing or conversation handling.

## Current limits

- Language understanding and photo interpretation require the configured model and internet access. Browser voice recognition is unavailable in some browsers and may have different language support.
- Controlled pipeline tests verify execution and safety gates. Live evaluation samples are limited and do not prove accuracy on all unseen wording or images.
- Sessions, carts and mock seat deductions live in memory. Restarting the server clears them. **New chat** clears conversation and cart state; it does not undo mock reservations made by the running server.
- Only one-way flights are supported. There are no real bookings, payments or external provider calls.
- Results and prices come only from the supplied JSON files. A missing or invalid data file stops startup with a readable data error.
- The official product file has no image URLs, so result cards use neutral icons instead of invented product photos.

The `docs/` folder contains the technical report, routing test log, requirements audit, five-minute demo flow and UI previews.
