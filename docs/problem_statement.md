# rentsmart — Problem Statement (v0)

## 1. Problem

Homeowners who rent out a house often rely on a real estate agent to set the
asking rent. Agents don't always act in the owner's best interest: they may
not present the full picture of the market, or may lack the initiative to
dig into the data. Owners rarely have an independent, evidence-backed view of
what their house should rent for and why.

## 2. Product goal

Given a US address, give the owner an independent rental pricing brief in
which every number shows its range, source, date, and how much to trust it.
The brief is a second opinion that helps the owner check their agent's
advice. It does not replace the agent.

## 3. v0 user and scope

- Primary user: a property owner deciding what to ask when renting out
  their house.
- Front door: a command-line tool named `rentsmart`.
- Not in v0: home buyers, agents, sale pricing, mortgage calculations,
  buyer-side repair cost forecasts, any web or mobile interface.

> **Amendment (2026-10-26):** a local-only UI was added after v0 on purpose:
> `rentsmart --html` (a self-contained brief page) and `rentsmart-ui` (a localhost app).
> No hosting, accounts, or LAN access. It is a view on the same engine. Design:
> `docs/superpowers/specs/2026-10-26-local-ui-design.md`.

## 4. Input

- Required: a full US street address.
- Optional owner-supplied facts, given as CLI flags:
  `--beds`, `--baths`, `--sqft`, `--roof-year`, `--hvac-year`.
- Owner-supplied facts override vendor data and are marked as
  user-supplied in the output.

## 5. Output contract

### 5.1 The envelope

Every value in the brief uses the same envelope:

| Field         | Meaning                                             |
|---------------|-----------------------------------------------------|
| `value`       | Point estimate, if one makes sense                  |
| `low`, `high` | Range; more important than the point estimate       |
| `kind`        | How it was produced (see 5.2)                       |
| `source`      | e.g. "RentCast AVM", "county assessor", "computed"  |
| `as_of`       | Date of the underlying data                         |
| `evidence`    | What supports it, e.g. the comps used               |
| `limitations` | What it does NOT account for                        |

Invariants:
- `low <= value <= high` whenever these are present.
- Every value has a `source` and an `as_of` date.
- Anything of kind estimated, modeled, predicted, or advised has at least
  one limitation.

### 5.2 Kinds

| Kind        | Meaning                                       | Trust            |
|-------------|-----------------------------------------------|------------------|
| `fetched`   | Retrieved from records (tax, sales, listings) | High, may lag    |
| `estimated` | A vendor model's output (rent AVM)            | Medium, use range|
| `computed`  | Our own arithmetic on known inputs            | Exact given input|
| `modeled`   | Our model built on assumptions                | Low without facts|
| `predicted` | A forecast                                    | Low              |
| `advised`   | A suggestion derived from evidence            | Shows reasoning  |

### 5.3 Sections of the brief

| Section                         | Kind               | Notes                                                 |
|---------------------------------|--------------------|-------------------------------------------------------|
| Resolved address and facts      | fetched / user     | Includes address match confidence                     |
| Rent estimate (low, mid, high)  | estimated          | Lists the comps used; states asking vs leased basis   |
| Rental comps                    | fetched            | Distance, beds/baths, sqft, price, date, status       |
| Market speed for the zip        | fetched            | Median days on market and trend; zip level only       |
| Property tax                    | fetched            | Relevant to the owner's net rental income             |
| Pricing scenarios               | computed           | Low/mid/high asking rent with direction of speed only |
| Suggestions to rent faster      | advised            | Each must cite evidence in the brief                  |
| Questions to ask your agent     | advised            | Where agent advice would fall outside the evidence    |

### 5.4 Rules that protect the user

1. **Asking vs leased.** Rental comps from listings are asking prices, not
   signed lease prices. Every comp is labeled `asking` or `leased`, and the
   rent estimate's limitations state which basis it uses.
2. **Address resolution first.** Return the resolved address and match
   confidence. If more than one property plausibly matches (e.g. unit
   numbers), stop and return the candidates; never guess.
3. **No invented day counts.** Days on market is zip-level only. Pricing
   scenarios describe direction ("likely faster than the zip median"),
   never a specific predicted number of days.
4. **Evidence-backed advice only.** Suggestions are generated by rules that
   reference facts in the brief. If the evidence isn't there, the
   suggestion isn't made. An LLM may rephrase wording but may never add a
   suggestion or a fact.
5. **Freshness is visible.** Data older than a configured threshold is
   flagged.

## 6. Named failures

Each failure returns a distinct exit code and a plain-language message.

| Failure             | Behavior                                         |
|---------------------|--------------------------------------------------|
| Address not found   | Say so; suggest checking the format              |
| Ambiguous address   | List candidate matches; ask to rerun with one    |
| Too few comps       | Say no reliable range is possible; show what exists |
| Stale data          | Return the brief with a prominent staleness flag |
| Provider quota used | Say so; no partial or fabricated output          |
| Similar address seen | Before a paid lookup, list saved look-alikes (missing city, mistyped zip, misspelled street); no calls made |

## 7. CLI

```
rentsmart "123 Example St, Gainesville, FL 32601"
rentsmart "123 Example St, ..." --beds 3 --baths 2 --roof-year 2019
rentsmart "123 Example St, ..." --json
```

- Default output: a human-readable summary rendered from the brief.
- `--json`: the full brief in the contract envelope. The readable output is
  always rendered from the same data, so the two can never disagree.
- The API key is read from the `RENTCAST_API_KEY` environment variable,
  never from a flag.
- Built with Typer.

## 8. Data

- v0 provider: RentCast API (rent and value estimates, rental comps,
  listings, tax assessments, zip-level market statistics). Its free
  developer tier has a small monthly request quota, so tests must not call
  the live API.
- Zillow has no open API; do not use or scrape it. The UI may link each
  comp to a Zillow address search that opens in the user's browser; the app
  never fetches Zillow. Optionally, the brief shows the 12-month change in
  Zillow's Observed Rent Index (ZORI) for the zip, read from a CSV the user
  downloaded and credited to Zillow. It is trend context only: never a price,
  and never an input to the rent estimate, scenarios, or rules.
- MLS data is not available to us; agents may see newer listings. State
  this in the output where relevant.
- Future providers (ATTOM, county records) must be addable without
  changing the core.

## 9. Architecture

- **Core vs adapters.** Pricing logic, scenarios, and suggestion rules live
  in a core that knows nothing about RentCast. Data providers implement a
  provider interface.
- **Contracts as typed models.** The envelope and brief are Pydantic models
  with validators enforcing the invariants in 5.1.
- **One engine, thin front door.** The CLI is a thin wrapper over the core,
  so a web interface can wrap the same engine later.

Suggested layout:

```
rentsmart/
├── src/rentsmart/
│   ├── contracts.py      # envelope, brief, comps, failures
│   ├── core/             # pricing, scenarios, suggestion rules
│   ├── providers/        # provider interface + RentCast adapter
│   └── cli.py            # Typer app
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/         # recorded RentCast responses
├── benchmarks/           # golden-set evaluation (later)
├── docs/
├── AGENTS.md
├── README.md
└── pyproject.toml
```

## 10. Engineering standards

- uv for environment and lockfile; ruff for lint and format; pyright for
  types; pytest for tests; pre-commit hooks; GitHub Actions CI.
- Tests replay recorded API responses as fixtures; no live API calls in CI.
- Conventional commit messages.
- AGENTS.md records these rules for coding agents.

## 11. Out of scope (state in README)

- Not an appraisal; not financial, legal, or tax advice.
- No neighborhood quality judgments, demographics, or crime data
  (Fair Housing risk). Property facts and transactions only.
- No owner contact or personal data, even if a provider offers it.
- No scraping of sites whose terms forbid it.

## 12. Evaluation (Phase 3)

- Golden set: 20–50 addresses with known actual lease price and days on
  market.
- Metrics: coverage (how often the actual rent falls in low–high) reported
  together with range width. A range that's always right because it's huge
  is a failure.
- CI fails if coverage or width regresses beyond a set tolerance.

## 13. Build phases

| Phase | Deliverable                                                  | Done when |
|-------|--------------------------------------------------------------|-----------|
| 0     | This contract                                                | Done |
| 1     | Walking skeleton                                             | One command on a real address returns every section in the envelope from RentCast; tests replay fixtures |
| 2     | Adapter boundary                                             | A fake provider can drive the whole brief in tests |
| 3     | Guardrails and evaluation                                    | Golden set, coverage/width report, CI gate |
| 4     | Unhappy paths                                                | Every named failure has a test that triggers it |
| 5     | Release automation                                           | Versioning and changelog generated from commits |
| 6     | Docs and trust                                               | README, disclaimer, data-source notes |

## 14. First task for the coding agent

1. Set up the project skeleton and tooling from section 10.
2. Implement `contracts.py` with validators for the invariants in 5.1.
3. Define the provider interface and a RentCast adapter.
4. Build the walking skeleton for one address end to end, with recorded
   fixtures, a thin version of every section, and the README disclaimer.
5. Write AGENTS.md capturing sections 5.4, 9, 10, and 11.