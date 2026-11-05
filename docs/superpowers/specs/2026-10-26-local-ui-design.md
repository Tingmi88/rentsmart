# Local UI and shareable HTML brief: design

Date: 2026-10-26. Status: approved in conversation, pending spec review.

## Why

The terminal brief is complete but dense, and the owner's live question is "what if I
change my asking price?". This adds two views on the existing engine:

1. **`rentsmart --html PATH`**: one self-contained HTML file per brief, easier to read
   than the terminal output and safe to send to the few people the owner shares with.
2. **`rentsmart-ui`**: a local web app for the owner only, to try asking prices and run
   new addresses without the terminal.

The v0 spec (§3, which lists "any web or mobile interface" as out of scope) is amended: this UI is a
deliberate post-v0 addition, **local only**: no hosting, accounts, or access from other
devices.

## Users and goals

| Who | Gets | Does |
|---|---|---|
| Owner | `rentsmart-ui` on their laptop | Reads briefs, tries asking prices (no API cost), runs new addresses (with a cost prompt) |
| People the owner shares with | An `--html` file the owner sends | Read it; no install, no key |

Success: the owner can answer "what happens at $2,250?" in seconds at zero API cost, and
a shared brief is readable on a phone without the terminal.

Not in scope: a list of saved briefs, maps, login or hosting, LAN access, editing
beds/baths/sqft in the UI (CLI flags remain).

## Architecture

The engine, rules, and providers keep their roles. The UI is a third view on
`core/engine.py::build_brief`, beside `render.py` (text) and `--json` (spec §9).

```
src/rentsmart/
  core/ ...                 unchanged
  providers/
    rentcast.py             + offline mode (raises CacheMiss), + usage counting
    cache.py                + CacheMiss, + UsageLog
  settings.py               new: cache and stale-threshold settings from env
                            (moved from cli.py so cli and web share them)
  cli.py                    + --html PATH
  web/
    render.py               Brief (+ view options) -> HTML via Jinja2
    templates/brief.html    full page
    templates/_sections.html  summary + Advice fragments for the what-if
    templates/_error.html   named-failure box
    templates/index.html    address form (app only)
    static/app.css, app.js  inlined into --html output; served by the app
    app.py                  FastAPI app
```

Entry point: `rentsmart-ui = rentsmart.web.app:main` (Typer), options `--port`
(default 8765) and `--no-open` (by default it opens the browser). It starts uvicorn
on `127.0.0.1` only. `rentsmart "<address>"` stays a single command.

New runtime dependencies: `fastapi`, `uvicorn`, `jinja2`. No Node, no build step, no
CDN or external URLs in any page.

## Page layout

The same template serves the app and the `--html` file; only the asking-price control
differs (editable in the app, static text in the file).

```
Header: resolved address · facts · match confidence · data date
Warning: Not an appraisal. Asking prices, not leases. No MLS.
Asking-price control (app only): number box + slider, listed date
SUMMARY
  Range low – high · mid
  Price line: estimate band, mid, asking, recent-comps median, comp dots
  Check chips (only when an asking price is given)
  "N suggestions · M questions for your agent"
Tabs: [Advice] [Comps N] [Market & tax] [Scenarios] [Details]
Footer: notices
```

- **Check chips** restate values the brief already computed, coloured with the existing
  constants from `core/rules.py`; they add no advice:
  - range position: orange when `above range` or `below range`;
  - vs recent comps: orange when `|gap| >= RECENT_GAP`;
  - days listed: orange when days listed exceeds the zip median.
- **Advice** (default tab): suggestions, then agent questions; each `because` evidence
  list is a collapsed `<details>`. An empty list shows the existing "None: ... not an
  all-clear" line.
- **Comps**: table, newest first, 90-day divider, badges `active`/`inactive`,
  `asking`/`leased`, `UNCONFIRMED`, `STALE`.
- **Market & tax**: zip median days on market with its monthly line, trend; tax card.
- **Scenarios**: low/mid/high with direction only.
- **Details**: every value with `kind · source · as_of`, evidence and limitations.
- **Banners** for `too_few_comps` and `stale`, above the summary.
- **Price line** uses HTML-positioned labels over a thin bar (not text inside a scaled
  SVG) so labels stay legible at phone width; comps at the same price stack.
- **What-if**: slider from 15% below the estimate low to 15% above the high, $25 steps,
  plus a number box. Requests are debounced by 250 ms. When the value differs from the
  entered asking price, the summary says "what-if $X (entered $Y)".
- **Tabs** in the `--html` file use a small inline script. Without JavaScript all
  sections render stacked, so nothing is hidden. Print CSS shows every section.
- Light and dark themes via CSS tokens; 16px side gutter; no page-level horizontal
  scroll (the comps table scrolls inside its own container).

## Routes and data flow

| Route | Spends API calls | Behaviour |
|---|---|---|
| `GET /` | never | Address form with optional asking price and listed date |
| `GET /brief?address=&asking=&listed=` | never | Builds the brief with the provider in offline mode. Cached: full page. Not cached: page with "Not cached. About 3 RentCast calls · N used this month on this machine" and a **Run** button |
| `POST /brief` (form: address, asking, listed) | yes | Live fetch (fills the cache), then `303` redirect to `GET /brief?...` |
| `GET /brief/sections?address=&asking=&listed=` | never | Offline rebuild; returns the summary + Advice fragment for the what-if |
| `GET /static/...` | never | CSS and JS |

Only `POST /brief` can spend calls. Browsers may prefetch or repeat GETs; they never
cost anything.

**Offline mode.** `RentCastProvider(..., offline=True)`: in `_get`, a cache miss raises
`CacheMiss(path)` before any HTTP request. `CacheMiss` is not a `RentsmartError` and has
no exit code; only the web layer catches it.

**Usage log.** Every live request that gets an HTTP response, whatever its status, increments a
per-month counter in `<cache dir>/usage.json` (`{"2026-10": 18}`), whether from the CLI,
the app, or `scripts/record_fixtures.py`. Counting failures never break a brief. The UI
labels it "on this machine": calls made elsewhere or on the RentCast dashboard are not
counted. It contains counts only, no addresses or keys.

**Validation** matches the CLI: `asking > 0`; `listed` needs `asking` and can't be in
the future; bad input re-renders the form with the message. Settings
(`RENTSMART_CACHE_DAYS`, `RENTSMART_CACHE_DIR`, `RENTSMART_STALE_AFTER_DAYS`) are read
through `settings.py`.

## Security

- Bind `127.0.0.1` only.
- Reject requests whose `Host` isn't `127.0.0.1:<port>` or `localhost:<port>` (400): a
  DNS-rebinding guard.
- `POST /brief` requires `Origin` (or, if absent, `Referer`) to match the app's own
  origin (403). Otherwise any web page could post to the local app and spend calls.
- The API key stays in `RENTCAST_API_KEY`; it is never passed to a template, never
  logged, never in a response.
- Jinja autoescaping on; vendor strings (addresses) are untrusted.
- Shared `--html` files carry the disclaimer and asking/leased labels. Before the owner
  shares a brief outside their household, they confirm RentCast's terms allow it.

## Errors

| Failure | Page |
|---|---|
| `AddressNotFound` (10) | Error box: no property matched, with the input address |
| `AmbiguousAddress` (11) | Candidates as links to `GET /brief?address=<candidate>` |
| Too few comps (12), stale (13) | Brief with banner |
| `QuotaExceeded` (14) | Error box; no Run button |
| `ConfigError` (15) | "Set RENTCAST_API_KEY in .env" (never shows a key) |
| `ProviderError` (16) | Error box with RentCast's message |
| `CacheMiss` on `/brief` | "Not cached" page with Run button |
| `CacheMiss` on `/brief/sections` | "Data expired, reload the brief." No fetch |

`--html` with a failure writes no file and exits with the same code as today.

## CLI change

`rentsmart "<address>" --html PATH` writes the brief to `PATH` (one file, CSS and JS
inlined, no external URLs) and still prints the text (or `--json`) to stdout. The exit
code is unchanged.

## Testing

No test touches the network (`tests/conftest.py` mock stays autouse).

- `web/render.py`: all sections present for synthetic-austin and synthetic fixtures;
  chip colours flip exactly at `RECENT_GAP` and the zip median; badges and 90-day
  divider; no `<script src`, `<link href="http`, or `http(s)://` asset URL in
  `--html` output; vendor strings escaped.
- App (FastAPI `TestClient`): uncached `GET /brief` shows Run and makes zero HTTP calls;
  `POST` fetches, and later `GET /brief` and `/brief/sections` make zero calls; bad
  `Host` → 400; bad `Origin` on POST → 403; each named failure renders its box;
  ambiguous renders candidate links; the test key never appears in any response body;
  cache expiry during what-if shows "Data expired".
- Provider: offline mode raises `CacheMiss` with zero HTTP calls; usage counter
  increments once per live response (including 404 and 429), never on cache hits
  or network errors.
- CLI: `--html` writes a parseable file; works with and without `--json`.
- Existing 109 tests, `rentsmart-eval --check`, ruff, pyright (strict on `src/`) stay
  green.

## Docs and release

- `docs/problem_statement.md`: amendment note on the post-v0 local UI.
- AGENTS.md: UI is a view; advice only from `core/rules.py`; only `POST /brief` spends
  calls; localhost only.
- README: UI section, `--html`, screenshot from the synthetic fixture (not a real
  address), usage-counter caveat.
- `docs/data-sources.md`: the usage file.
- Conventional `feat:` commits; the owner runs the Release workflow (expected v0.3.0).
