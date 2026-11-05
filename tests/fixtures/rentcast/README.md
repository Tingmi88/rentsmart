# RentCast fixtures

`synthetic-*` directories are hand-written to match RentCast's documented response
shapes. They are not real properties. `synthetic-austin` is the exception: its
subject (4120 Sample Dr) is fictional, but its comps and zip market data come from
a real recording of public listings, so tests exercise realistic neighborhood data.
Once an API key is available, record real fixtures with `scripts/record_fixtures.py`
(about 3 requests per address).

Each directory holds the raw JSON for one endpoint per file:
`properties.json`, `rent_long_term.json`, `markets.json`.
