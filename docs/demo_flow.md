# SuperChat five-minute demo

Start `python -m superchat`, open `http://127.0.0.1:8000/`, confirm `/ready` reports `ready`, and click **New chat**. The reference date is 2 November 2026. Keep the server running so session context survives.

| Approx. time | User message | What to show |
| --- | --- | --- |
| 0:00 | `Find flights from Baku to Istanbul on Friday.` | Three official 6 November flight cards. Point out departure/arrival time, stops, baggage and seats; the View flight button opens verified details. |
| 0:30 | `The cheaper one, is it direct?` | The earlier flight list supplies the reference. F013 is cheapest and has one stop. |
| 1:00 | `What is playing tonight?` | **Switch 1, Flights → Cinema.** Film listings use 2 November. |
| 1:30 | `Show wireless headphones under 100 AZN.` | **Switch 2, Cinema → Shopping.** P001 is the catalogue match. |
| 2:00 | `Is it in stock?` | Availability uses P001 from the shopping context. |
| 2:25 | `Back to the flights.` | **Switch 3, Shopping → Flights.** The earlier flight result list is restored. |
| 2:55 | `Movies rated below 8.` | **Switch 4, Flights → Cinema.** Six films match the numeric threshold; higher-rated films do not appear. |
| 3:30 | `Back to the headphones.` | **Switch 5, Cinema → Shopping.** P001 remains in the earlier shopping context. |
| 4:00 | Click **Add to cart** on P001, or type `Add it to my cart.` | The cart uses official P001 price and shows the total. |
| 4:25 | `Покажи фильмы с рейтингом ниже 8.` | **Switch 6, Shopping → Cinema, and switch language to Russian.** Data filters stay the same while the reply language changes. |

If time remains, say `Write a poem about flights` to show out-of-scope handling, then `Back to the flights` to show preserved state. The microphone control can feed a spoken request into the same chat pipeline; the photo control can show a verified product match or a low-confidence clarification. Browser speech support and photo confidence depend on the device and submitted image, so prepare those bonus examples separately before presenting them live.
