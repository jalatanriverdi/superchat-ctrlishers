# SuperChat routing and result test log

**Date:** 2 November 2026. **Reference date:** 2 November 2026. **Data:** the five supplied JSON files. The live app uses a hosted structured interpreter plus deterministic repository operations. Each scored case checks the route and the exact returned record IDs; the multi-turn set also checks that out-of-scope requests preserve domain state.

| Evaluation | Model / pipeline | Correct | Accuracy |
| --- | --- | ---: | ---: |
| Numeric, filter, out-of-scope and ambiguity cases (`tools.live_eval`) | OpenRouter `openai/gpt-5-mini` | 13/13 | 100.0% |
| Nine-turn domain-switch conversation (`tools.live_conversation_eval`) | OpenRouter `openai/gpt-5-mini` | 9/9 | 100.0% |
| English, Azerbaijani and Russian cases (`tools.live_multilingual_eval`) | OpenRouter `openai/gpt-5-mini` | 12/12 | 100.0% |
| Focused English → Russian → earlier-shopping return (`tools.live_return_eval`) | OpenRouter `openai/gpt-5-mini` | 3/3 | 100.0% |
| Same 13 independent cases (`tools.live_eval --model google/gemini-2.5-flash`) | OpenRouter `google/gemini-2.5-flash` | 10/13 | 76.9% |
| Older rule-based router (`tools.evaluate_routing`) | Legacy comparison only | 45/45 | 100.0% |

The first three live sets total **34/34 (100.0%)** authored checks for the configured model in the final recorded runs. This is an observed sample score, not a guarantee on unseen requests. The focused rerun is separate because it repeats a scenario. The legacy 45/45 score does not measure the running interpreter.

## Error analysis

- In two earlier multilingual runs, `Вернись к наушникам` became a clarification after a shopping → Russian cinema switch, although shopping state stayed intact. Diagnostics revealed that the model copied the earlier English filters into the new Russian plan with evidence from the old message. The conversation layer now removes only filters that exactly match saved criteria and cite an earlier message; new filters still require current-turn evidence. The focused rerun and final 12-case multilingual run passed. Model variation remains possible beyond this authored set.
- Earlier live multi-turn checks exposed two deterministic contract problems. `The cheaper one, is it direct?` was rejected because validation incorrectly disallowed a filter on a referenced item. `Show wireless headphones under 100 AZN` initially searched only the description for “wireless,” although that word appears in P001's official name. The validator and product-characteristic mapping were corrected. The rerun scored 9/9.
- Gemini 2.5 Flash mapped “age support 12” to `age_rating = 12` rather than `<= 12` in one run, resolved Friday to 7 November rather than 6 November, and asked for clarification about purple headphones where the scored behavior was an empty result. These are semantic errors in valid-looking plans. The repository still prevented fabricated records, but it cannot by itself prove that the model chose the intended operator or date. The better-tested `openai/gpt-5-mini` remains the default.
- A first live card-button request for `F001` was interpreted as an unsupported ID filter. After the interpreter prompt was improved, a rerun returned F001 details. Visible card buttons now use a separate validated structured action endpoint, so clicking them does not depend on another model interpretation.

## Other verification

The automated suite covers all three domain operations, constraints, cart totals, seat limits, missing data, mixed requests, history, out-of-scope state preservation, card data and card actions, visual-search confidence, and HTTP responses. `node tests/voice_ui_smoke.cjs` checks the microphone's continuous transcription and restart path with a mocked browser recognizer. A real photo call with an unrelated generated image returned low confidence and prompted for a description; the recognizer never displayed an invented product. Physical microphone quality and arbitrary product photos have not been exhaustively evaluated.

To reproduce the scores, configure a server-side key in `.env`, then run the commands above with `python -B -m` before each `tools.*` module. Live scores can vary between runs because the interpreter is hosted and nondeterministic. Set `SUPERCHAT_DEBUG=1` to inspect model plans, validated actions, and returned IDs without exposing the key.
