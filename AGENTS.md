# AGENTS.md

Rules for coding agents working on rentsmart. The full spec is
`docs/problem_statement.md`; this file is the part you must not break.

## Rules that protect the user (spec §5.4)

1. **Asking vs leased.** Comps from listings are asking prices. Label every comp
   `asking` or `leased`. The rent estimate's limitations must state its basis.
2. **Address resolution first.** Return the resolved address and match
   confidence. If more than one property matches, raise `AmbiguousAddress` with
   the candidates. Never guess.
3. **No invented day counts.** Days on market is zip-level only. Scenarios give
   direction ("likely faster than the zip median"), never a number of days.
4. **Evidence-backed advice only.** Suggestions and agent questions come from
   rules in `core/rules.py` that cite facts already in the brief. No evidence,
   no advice. An LLM may rephrase wording but may never add advice or facts.
5. **Freshness is visible.** Data older than the threshold is flagged `stale`.

Every value is an `Envelope` (`contracts.py`). Validators enforce
`low <= value <= high`, a non-empty `source` and an `as_of` date, and at least
one limitation for kinds `estimated`, `modeled`, `predicted`, and `advised`. Don't
weaken the validators to make data fit; fix the data or omit the value.

## Architecture (spec §9)

- `core/` holds pricing, scenarios, and rules. It must not import from
  `providers/rentcast.py` or know any vendor's field names.
- Providers implement the `Provider` protocol in `providers/base.py` and return
  provider-neutral records. A new provider (ATTOM, county records) is a new
  adapter, with no core changes.
- `core/engine.py::build_brief` is the one engine. `cli.py` is a thin wrapper
  over it: parse flags, call the engine, print, exit. The local UI (`web/`) wraps
  the same engine.
- `web/` is a view, like `render.py`: it never adds advice or facts. Check chips
  restate brief values using constants from `core/rules.py`.
- In the local app only `POST /brief` may spend API calls; GET routes build briefs
  with the provider in `offline` mode. Keep the 127.0.0.1 bind, the Host check, and
  the Origin check on POST. No hosted or multi-user web interface.
- Before a paid address lookup, the CLI and the UI's GET routes check saved lookups
  (`check_similar`): the same address in other words reuses the saved one; a near
  match raises `SimilarAddress` with no call made. Matching lives in `core/address.py`
  and never treats a different house number or unit as the same property.
- Named failures are `RentsmartError` subclasses with distinct exit codes
  (`ExitCode`). Too-few-comps and stale data still return a brief, flagged.

## Engineering standards (spec §10)

- uv for environment and lockfile (`uv add`, never pip). Python 3.12.
- ruff for lint and format, pyright (strict on `src/`), pytest.
- UI behavior that needs a real browser (`app.js`, navigation, storage) gets a
  Playwright test in `tests/ui/`, marked `ui` and run with `pytest -m ui`.
- pre-commit runs these, plus a conventional-commit message check.
- **Tests never call the live RentCast API.** HTTP is mocked for every test
  (`tests/conftest.py`). Use the recorded fixtures in `tests/fixtures/rentcast/`,
  or `FakeProvider`. The free tier has a small monthly quota.
- The CLI caches RentCast responses (`providers/cache.py`). Keep errors and quota
  failures out of the cache, and keep `as_of` dates honest for cached data.
- The API key comes only from the `RENTCAST_API_KEY` env var. Never log it,
  print it, put it in a URL, or commit it. `.env` is git-ignored.
- Golden set: `uv run rentsmart-eval --check` must pass. Only run
  `--update-baseline` when the golden set changed or a metric change is
  understood and intended; say why in the commit message.
- Never hand-edit the version or `CHANGELOG.md`; the Release workflow owns both.
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
  `chore:`, `ci:`, `build:`.

## Out of scope (spec §11)

- Not an appraisal; not financial, legal, or tax advice.
- No neighborhood quality judgments, demographics, or crime data (Fair Housing
  risk). Property facts and transactions only.
- No owner contact or personal data. Adapters must not read owner fields, and
  `scripts/record_fixtures.py` strips them before writing fixtures.
- No scraping of sites whose terms forbid it. No Zillow API use or scraping.
  The UI may show plain address-search links (web search, Zillow) that open in
  the user's browser; the app never fetches them, and they are look-ups, not
  listing evidence. It may read a ZORI CSV the user downloaded from Zillow
  Research (`RENTSMART_ZORI_CSV`) for zip rent trend only, credited to Zillow.
  Never fetch it, and never commit the real file (tests use a made-up sample).
