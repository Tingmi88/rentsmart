# CHANGELOG

<!-- version list -->

## v0.4.0 (2026-11-05)

### Features

- Ask "did you mean" before paying for a near-match address
  ([`d724d62`](https://github.com/Tingmi88/rentsmart/commit/d724d62c7aea990d0c3d605f9005ac4779c6e6c9))

- Link each comp to a web search and Zillow lookup
  ([`5140f06`](https://github.com/Tingmi88/rentsmart/commit/5140f06570a926e7a6815d086d8c8ff2d74fe3b5))

- Local UI opens old saved briefs with a dated Refresh offer
  ([`e014442`](https://github.com/Tingmi88/rentsmart/commit/e01444206e95aa31dd4c07df6d674feb96cf4bdd))

- Remember the last address entry in the local UI
  ([`bc70ac8`](https://github.com/Tingmi88/rentsmart/commit/bc70ac833a95ff318671480519ad8e90324b5151))

### Testing

- Add Playwright browser tests for the local UI
  ([`c384c40`](https://github.com/Tingmi88/rentsmart/commit/c384c40b7c62f5b8880be7ec9444bbc4798bb5df))

- Wait for the saved entry before reopening the form
  ([`fd8e207`](https://github.com/Tingmi88/rentsmart/commit/fd8e207d25fa22098775c0d6825eff829e2da42b))


## v0.3.0 (2026-11-02)

### Bug Fixes

- Cache hits ignore commas and periods in addresses
  ([`5ba93f6`](https://github.com/Tingmi88/rentsmart/commit/5ba93f6a5fadc61ad10678365b491ea2880bf1a2))

- Never re-spend API calls on a double Run or an unwritable cache
  ([`3ad6385`](https://github.com/Tingmi88/rentsmart/commit/3ad6385cda70fc7d0139a10a1dc04e3948f3d45d))

### Documentation

- Design spec for local UI and HTML brief
  ([`966ee2c`](https://github.com/Tingmi88/rentsmart/commit/966ee2c70ba41994ad7ca43d6d6f3c2d3180f614))

- Implementation plan for local UI
  ([`683f0d3`](https://github.com/Tingmi88/rentsmart/commit/683f0d3019f16c304b91941ff5fd455bee7880b9))

- Local UI, --html, and usage counter
  ([`9c84a55`](https://github.com/Tingmi88/rentsmart/commit/9c84a55a78fcd237231e610e6269c71dbf6f2f0b))

### Features

- --html writes a self-contained brief page
  ([`00bf83c`](https://github.com/Tingmi88/rentsmart/commit/00bf83c2b1ff336274c90d59855197d2a8e7d1ca))

- Display data for the HTML brief
  ([`99062a2`](https://github.com/Tingmi88/rentsmart/commit/99062a244fd5fe0ecb5f5b13ad8321ca3a3c7079))

- HTML brief templates with summary, tabs, and price line
  ([`b356720`](https://github.com/Tingmi88/rentsmart/commit/b356720a6ce0bf154f0def2af6004e5d0b430cc1))

- Local web app with cache-only browsing and explicit runs
  ([`ce4660a`](https://github.com/Tingmi88/rentsmart/commit/ce4660a06670722cda7a10643e9f0be981221eae))

- Offline provider mode and a local API usage counter
  ([`13aac6e`](https://github.com/Tingmi88/rentsmart/commit/13aac6ede106340e97f0d6da7582b0974ebbaafe))

- Rentsmart-ui command for the local app
  ([`b22e700`](https://github.com/Tingmi88/rentsmart/commit/b22e7004cbf8824b9d61c66014730a3d3cabd177))

### Refactoring

- Move env settings out of the CLI so the UI can share them
  ([`2c00b83`](https://github.com/Tingmi88/rentsmart/commit/2c00b83349e88dd1a6df4f8198989f013798ee00))

### Testing

- Add four pending golden-set entries
  ([`e139d14`](https://github.com/Tingmi88/rentsmart/commit/e139d145f9de5bb36a21d43d27cf9a2c61d9d227))

- Add list dates to new golden-set entries
  ([`113b62c`](https://github.com/Tingmi88/rentsmart/commit/113b62c2e87342bbaacc6b4f2862026e74c70575))

- Pin cache clock in cached-date test
  ([`c8d000a`](https://github.com/Tingmi88/rentsmart/commit/c8d000ac91a07151f6143514f226c4c05489d34b))


## v0.2.0 (2026-10-20)

### Bug Fixes

- Make listing advice account for an owner already priced at or below mid
  ([`0b82553`](https://github.com/Tingmi88/rentsmart/commit/0b825535722b86bd5f091d13eb3f5f6248e04b0d))

- Show RentCast's reason when it refuses a request
  ([`24a2fac`](https://github.com/Tingmi88/rentsmart/commit/24a2facf82e9649a720bfa6f534105c06d84c3bc))

- Turn malformed or unreachable provider responses into named failures
  ([`b3bee76`](https://github.com/Tingmi88/rentsmart/commit/b3bee761345fad6f4738bffd110de42f1cf1a296))

### Build System

- Generate versions and changelog from commits
  ([`eaece68`](https://github.com/Tingmi88/rentsmart/commit/eaece68390b0f41d600ee647d78bd499ddeaf0eb))

### Documentation

- Reader guide, disclaimer, and data-source notes
  ([`79fa3c3`](https://github.com/Tingmi88/rentsmart/commit/79fa3c3a98e89879af676a19fa8357ca6f14d462))

### Features

- Cache RentCast responses locally to save API calls
  ([`05e24c7`](https://github.com/Tingmi88/rentsmart/commit/05e24c7f76190b3e2d6dbd34413f770ff0faad77))

- Check the owner's current listing with --asking
  ([`d8f9c7e`](https://github.com/Tingmi88/rentsmart/commit/d8f9c7ee26af1ccd9d7bf00f70862fa47bc36cc0))

- Golden-set evaluation harness with CI regression gate
  ([`7ecac23`](https://github.com/Tingmi88/rentsmart/commit/7ecac23f9d645d0f2601eb7811460e313d9b9e7b))

- Rank comps by recency and flag unconfirmed active listings
  ([`e008c95`](https://github.com/Tingmi88/rentsmart/commit/e008c9506617e3f3eb62ec5637eb1ad3a598e09c))

### Testing

- Add listing details for gainesville-sw73rd golden entry
  ([`9a33906`](https://github.com/Tingmi88/rentsmart/commit/9a3390681973cc373693362720a82bb6744cacd0))

- Force plain CLI output so CI color doesn't break text asserts
  ([`402de38`](https://github.com/Tingmi88/rentsmart/commit/402de38cc63b13754fe3e8a93b512291af6826a1))

- Record gainesville-sw73rd for the golden set
  ([`89d3461`](https://github.com/Tingmi88/rentsmart/commit/89d346181031327b5b8f6b5bdde4bb9e3d493736))

- Replay real RentCast responses for an Austin address
  ([`a47821b`](https://github.com/Tingmi88/rentsmart/commit/a47821b64824757df1762010228feb3d2c9c7f7a))


## v0.1.0 (2026-10-20)

- Initial Release
