# Data sources

rentsmart v0 uses one provider, the [RentCast API](https://www.rentcast.io/api).
Each brief costs about 3 requests on a first run and none when served from the local
cache.

## Where each part of the brief comes from

| Brief section | RentCast endpoint | Fields used | `kind` | `as_of` means |
|---|---|---|---|---|
| Resolved address and facts | `GET /properties?address=` | `formattedAddress`, `zipCode`, `propertyType`, `bedrooms`, `bathrooms`, `squareFootage`, `yearBuilt` | `fetched` | Date retrieved (the record has no update date) |
| Property tax | same response | `propertyTaxes` (latest year), `taxAssessments` | `fetched` | Dec 31 of the tax year |
| Rent estimate | `GET /avm/rent/long-term` | `rent`, `rentRangeLow`, `rentRangeHigh` | `estimated` | Date retrieved |
| Rental comps | same response | `comparables[]`: address, distance, beds, baths, sqft, `price`, `status`, `listedDate`, `lastSeenDate` | `fetched` | Comp's `lastSeenDate` |
| Market speed | `GET /markets?zipCode=&dataType=Rental` | `rentalData.medianDaysOnMarket`, monthly `history` | `fetched` | `rentalData.lastUpdatedDate` |
| Trend, recent support, scenarios, listing check | none | computed from the above | `computed` | Date of the inputs |
| Suggestions, agent questions | none | rules in `core/rules.py` | `advised` | Brief date |

Owner-supplied flags (`--beds`, `--asking`, …) are `user_supplied` and override
vendor facts. The rent estimate request includes the overridden beds, baths, and
square footage.

## What the vendor data means

- **Comp `price` is an asking price.** A comp that is no longer listed (`inactive`)
  often rented, but it may have been withdrawn instead. Either way its price is
  what was asked, not what was signed.
- **`lastSeenDate`** is when RentCast last saw the listing. For a delisted comp it is
  about the removal date, so an old date means an old price. For a comp still marked
  active, an old date means RentCast hasn't confirmed it's still available; rentsmart
  marks it `UNCONFIRMED` after 14 days.
- **The rent AVM is a vendor model.** RentCast does not publish how it weights comps.
  rentsmart shows its range unchanged and adds its own "recent support" (median
  asking price of comps seen in the last 90 days) beside it for comparison.
- **Market statistics are zip-level** and cover all rental listings in the zip, not
  just homes like yours.
- **Tax records lag.** The newest bill is often last year's. Tax data is flagged
  stale only after 550 days because bills are annual.

## Freshness

| Data | Flagged stale after | Setting |
|---|---|---|
| Rent estimate, comps, market statistics | 90 days | `RENTSMART_STALE_AFTER_DAYS` |
| Property tax | 550 days | fixed |
| Cached responses | reused for 7 days | `RENTSMART_CACHE_DAYS` (`0` disables), `--refresh` |
| API usage count | per calendar month | `~/.cache/rentsmart/usage.json` (counts only) |

The usage file holds monthly counts of live API responses made from this machine,
nothing else.

A brief built from cached responses says when they were retrieved.

## Not used

- **MLS**: not available to rentsmart. Agents may see newer listings and closed
  leases.
- **Zillow**: no open API; rentsmart does not scrape it or any site whose terms
  forbid it.
- **Owner and personal data**: RentCast can return owner names and mailing
  addresses. The adapter never reads them, and `scripts/record_fixtures.py` strips
  them before saving test fixtures.
- **Neighborhood, demographic, or crime data**: excluded for fair housing reasons.

## Adding a provider

Providers implement the `Provider` protocol in `src/rentsmart/providers/base.py`
and return provider-neutral records. The core never sees vendor field names, so a
new source (ATTOM, county records) is a new adapter with no core changes.
