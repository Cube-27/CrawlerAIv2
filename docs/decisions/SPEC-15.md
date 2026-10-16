# SPEC-15 decisions

Decisions for [SPEC-15 — Shopify adapter](../specs/SPEC-15-shopify-adapter.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-1076 — The Shopify adapter is admitted from §22
- Date: 2026-10-16 · Spec/PR: SPEC-15 (#219) · Status: decided (owner)
- Context: ARCHITECTURE §22 listed "Shopify JSON" under "More platform adapters". The owner admitted a Shopify adapter on 2026-10-16.
- Decision: SPEC-15. ARCHITECTURE rev 25 and Appendix A #46: §7.1 names Shopify after Greenhouse and Lever, §22 drops it from the candidates, Appendix A #37 notes the supersession. OPEN_QUESTIONS #2 records the admission.
- Alternatives: keep the generic path only for storefront pages.
- Why: The owner's admission.
- Reversible: yes

### D-1077 — Storefront API, tokenless, pinned version 2026-10
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.1, PR 2 (#219) · Status: decided
- Context: A storefront offers the Ajax product JSON (`/products/<handle>.js`), an undocumented `products.json`, and the documented Storefront GraphQL API, which answers tokenless requests for public product data.
- Decision: `POST {origin}/api/2026-10/graphql.json` with the handle as a GraphQL variable. Prices are `MoneyV2` (`amount`, `currencyCode`).
- Alternatives: the Ajax JSON (integer prices without a currency, so C7 would decline every price); `products.json` (undocumented).
- Why: Documented, versioned, and states the currency with every price.
- Reversible: yes

### D-1078 — Detection by route, confirmation by the version header, a 24-hour decline per host
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.2, PR 2 (#219) · Status: decided
- Context: Shops run on their own domains, so no host list can detect them (C3 also forbids one outside `adapters/`).
- Decision: The adapter detects the platform's documented page routes (`/products/{handle}`, `/collections/{c}/products/{handle}`, `/collections/{handle}` without a query) and confirms the platform by the documented `X-Shopify-API-Version` response header. An answer without it is `not_platform`: the page falls back and the host is declined for 24 hours in-process (at most 10,000 hosts, oldest dropped). A platform answer without the product (null, errors) is `not_served`: the page falls back, the host is kept.
- Alternatives: probe a page's HTML for platform markers (an extra request and a marker list); persist declines in the database.
- Why: One request per non-platform host per day at most; no list of markers or hosts.
- Reversible: yes

### D-1079 — Adapters declare schema.org shapes instead of a field map
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.4, PR 1 (#219) · Status: decided
- Context: `map(schema) -> {field: JSONPath}` gave one value per field, so an adapter could not give variant rows or listing rows, and every adapter repeated the schema.org mapping by hand.
- Decision: `shapes(page_kind)` declares schema.org node shapes over the adapter's JSON (type, path, properties, nested nodes, stated values, an anchor member). The collector walks them and maps values through `schema_org_map` like the structured collectors, with source kind `adapter`. Greenhouse and Lever are converted; their candidates are unchanged.
- Alternatives: keep `map` and add a row map beside it.
- Why: One mapping path for every source (C8); rows come from the existing row rules.
- Reversible: yes

### D-1080 — A variant's availability from its two documented booleans
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5, PR 2 (#219) · Status: decided
- Context: `ProductVariant` states `availableForSale` and `currentlyNotInStock` ("out of stock but still available for purchase (used for backorders)").
- Decision: false → `OutOfStock`; true and `currentlyNotInStock` true → `BackOrder`; true and false → `InStock`; anything else states nothing.
- Alternatives: `InStock` for every purchasable variant.
- Why: The platform's statement in schema.org's `ItemAvailability` vocabulary (C2).
- Reversible: yes

### D-1081 — A listed product's price only when its price range is one price
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5, PR 2 (#219) · Status: decided
- Context: A collection answer states each product's `priceRange` (min and max variant price), not one price.
- Decision: Two Offers per listed product, one at each bound; the row's `price` publishes only when they agree (INV-14).
- Alternatives: publish the minimum as the price.
- Why: A range is not a price; choosing a bound would be a default (C7).
- Reversible: yes

### D-1082 — Every adapter falls back to the page rungs
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.6, PR 1 (#219) · Status: decided
- Context: An adapter result that is not `ok` used to be the page's result.
- Decision: `acquire` keeps an adapter (or recipe) result that is `ok` or asks for fewer requests (`slow_down`), or when the site's rate does not admit another request; otherwise it fetches the page with the page rungs, and the result lists every attempt (INV-40). An API recipe is not tried after an adapter. No adapter runs without a `send` from the caller.
- Alternatives: fall back only for Shopify.
- Why: An unserved page is still a page; the rule is the same for every adapter.
- Reversible: yes

### D-1083 — An `api` capture belongs to the adapter that detects its page and serves its endpoint
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.7, PR 1 (#219) · Status: decided
- Context: Capture readers attributed an `api` capture to the adapter that detects the page URL, so an API recipe's capture of a Shopify page URL would be read as the adapter's.
- Decision: `Registry.reader(url, final_url)` returns the adapter only when it detects `url` and `serves(final_url)` (INV-39). Declines do not apply to reading.
- Alternatives: a capture field naming the adapter (a manifest change).
- Why: The endpoint already tells the two apart; no new stored field.
- Reversible: yes

### D-1084 — `CRAWLERAI_ADAPTERS` names the adapters that run; adapter requests are polite
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.8, PR 3 (#219) · Status: decided
- Context: Adapters were never wired into scrape or the worker, and C6 requires measurement before an adapter is active.
- Decision: A comma-separated setting, empty by default (none run); an unknown or repeated name is refused at startup. Scrape and the worker's page step send adapter requests through `services/fetching.adapter_send`: the endpoint host's robots.txt, its rate, and the first request on the caller's admitted turn.
- Alternatives: a per-site flag in the database.
- Why: The smallest switch that keeps adapters off until measured; the requests follow the same politeness as pages.
- Reversible: yes

### D-1085 — The placeholder variant title is no name
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5, PR 2 (#219) · Status: decided
- Context: A product without options has one variant titled `Default Title`, documented by the platform as the placeholder.
- Decision: That variant has no `name`.
- Alternatives: publish it as the variant's name.
- Why: It names no variant; it is the platform's documented placeholder, not page text.
- Reversible: yes

### D-1086 — The featured image only
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5, PR 2 (#219) · Status: decided
- Context: Mapping every image to `image` gives one property several values, and `image_url` publishes only when its values agree.
- Decision: `image` ← `featuredImage.url`. More images are an open issue (SPEC-15 §9).
- Alternatives: every image, with the first as the main one (an order rule for one source).
- Why: The platform states which image is featured.
- Reversible: yes

### D-1087 — An adapter's row field has evidence `adapter`
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5, PR 1 (#219) · Status: decided
- Context: A row-valued field published with evidence `structured` whatever its source, so adapter rows read as structured data.
- Decision: `agreed` when every published sub-field is, `adapter` when every one is an adapter's, else `structured` as before.
- Alternatives: whatever bucket every sub-field shares (also changes `dom`, `config_*` and `llm_*` rows, outside this spec).
- Why: The evidence follows the values; other buckets keep their rule.
- Reversible: yes

### D-1088 — C6 measurement: listings gain rows, detail pages lose page-only fields
- Date: 2026-10-16 · Spec/PR: SPEC-15 PR 4 (#219) · Status: decided
- Context: C6 asks for ≥ 3 tenants not used to build the adapter. Four shops, chosen from public knowledge and outside the reference eval set, one collection and two product pages each, adapter vs the generic HTTP path, no LLM.
- Decision: Record the result and keep the adapter off by default. Listings: the generic path gave 0 rows on 4/4 collection pages; the adapter gave 437 rows (29 to 250 per page; one page reached the 250 cap), 394 of them with a price. Detail (8 pages): the adapter published 7.4 schema fields per page on average, plus `variants` on 8/8 (62 rows); the generic path 10.3, plus `variants` on 6/8 (51 rows). The generic path's extra fields are those only the page states (brand on 8/8, rating, review count, condition, color, material); the adapter adds `product_id` on 8/8.
- Alternatives: activate by default now.
- Why: The adapter is clearly better on listings and loses page-only fields on detail; turning it on per deployment is the operator's choice until dev labels measure both.
- Reversible: yes

### D-1111 — A storefront 429 or 5xx says nothing of the platform; the page falls back on its turn
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.2, §4.6, §4.9 (#221) · Status: decided
- Context: Round-3 reference eval: an edge in front of a shop answered the Storefront endpoint 429 without the API's version header; it was read as `not_platform`, the host was declined for 24 h, and `acquire` kept the 429 (`slow_down`), so the task failed with no page fallback.
- Decision: A 429 or 5xx (RFC 6585 §4, RFC 9110 §15.6) is kept as it is by the adapter, header or not, and declines no host. `acquire` no longer keeps an adapter's slow-down: the page falls back after `admit_next`. The polite JSON send pauses the endpoint host by the answer's `Retry-After`, else by the first backoff (30 s, SPEC-02 §4.6), at most `BACKOFF_MAX`, so the page waits it out on the host's rate, or is not sent when the worker's wait bound refuses it (the 429 is kept, and the task retries as before). A worker task whose kept outcome is `ok` after an earlier slow-down keeps its page. An API recipe's slow-down is still kept (its HTML page request can be the one that asked). INV-40 reads "an outcome other than `ok`", "when the site's rate admits it".
- Alternatives: keep the 429 and let the worker retry (the eval's failure mode for scrape); fall back at once, ignoring `Retry-After`.
- Why: The endpoint is not the page; a slow-down asks for a pause, which the host's rate already enforces.
- Reversible: yes

### D-1112 — `serves(match, endpoint)`: an adapter serves only its own page's endpoints
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.7, INV-39 (#221) · Status: decided
- Context: #219 review: `Shopify.serves` checked only the path, on any host, against SPEC-15 §4.7 ("on the page's host").
- Decision: `serves` takes the page's `AdapterMatch`. Shopify: the Storefront path on the page's own host. Greenhouse and Lever: the board's or site's own endpoints on their API hosts.
- Alternatives: pass the page URL; keep path-only matching and change the spec.
- Why: The spec's rule; the match already names the tenant, so no adapter needs the URL again.
- Reversible: yes

### D-1113 — A storefront product's `vendor` is its schema.org `brand`
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5 (#221); supersedes the "Brand" out-of-scope line of SPEC-15 §2 · Status: decided
- Context: Round-3 eval: brand lost on 4/9 detail pages. The Help Center describes Vendor as "The manufacturer, wholesaler, or other vendor for the product"; the platform's Liquid `structured_data` filter, its own schema.org output, gives the example shop's vendor as the product's brand.
- Decision: `ProductGroup.brand` ← `vendor` on detail answers.
- Alternatives: leave brand to the page (the generic path reads the same value from the theme's JSON-LD); `manufacturer`.
- Why: The adapter states what the shop's own schema.org output states. Local re-measure: vendor equals the page's brand on 9/9 detail pages of 3 shops.
- Reversible: yes

### D-1114 — Prices only from a shop with one presentment currency
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.1, §4.5 (#221) · Status: decided
- Context: Round-3 eval: the adapter published a price in the shop's primary-market currency while the page stated another. A tokenless Storefront answer prices in the shop's primary market (checked on 5 shops: the answer's `localization` was the primary country whatever the vantage); the page shows its visitor's market. `@inContext(country:)` needs the page's country, which only the page states (a second request); reading it from the URL is C7's "values taken from URL codes".
- Decision: Both queries ask for `shop.paymentSettings.enabledPresentmentCurrencies`. Exactly one currency: prices are read as before. Otherwise a product answer is `not_served` (the page falls back and its own price is read), and a collection answer keeps its rows without Offers (`shapes(page_kind, answer)` now sees the answer).
- Alternatives: compare against the page's stated currency (needs the page fetched too); `@inContext` from the page's localization markup (two requests and platform markup parsing); publish the primary-market price.
- Why: The most conservative reading of C7: a price is published only when the answer's currency is the one any page of the shop shows.
- Reversible: yes

### D-1115 — `Shape.every`: a list field reads every value, other fields the stated main one
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.4, §4.5 (#221) · Status: decided
- Context: Mapping every image to `image` made `image_url` a conflict (several values of one entity, D-0944); SPEC-15 §9 kept the featured image only.
- Decision: `Shape.every` names, for a property whose `properties` members hold the platform's stated main value, the members holding all its values. Schema.org nodes gain `every_value(prop)` (JSON-LD and microdata: `values`); `select` reads it for a list field. Shopify: `image` ← `featuredImage.url`, `every` `image` ← `images(first: 250)` in shop order.
- Alternatives: a first-value-is-main rule for every source (JSON-LD arrays are unordered, JSON-LD 1.1 §4.3.1).
- Why: The platform states which image is the main one; only a source that states it says so.
- Reversible: yes

### D-1116 — Top-level sku and gtin of a multi-variant product stay unpublished
- Date: 2026-10-16 · Spec/PR: SPEC-15 §4.5 (#221) · Status: decided
- Context: Round-3 eval: sku and gtin lost on one page. The variants' `sku` and `barcode` were already mapped; the page's JSON-LD stated one variant's sku at the top level, which the adapter does not choose (no default variant, Appendix A #44, D-1057).
- Decision: No change: each variant row carries its sku and gtin; a barcode is a gtin only with a valid GS1 check digit (the gtin normalizer declines otherwise; replay test added).
- Alternatives: fill the top level from the first variant (a default variant).
- Why: The owner's no-default-variant rule.
- Reversible: yes

### D-1117 — C6 re-measure after the round-3 fixes
- Date: 2026-10-16 · Spec/PR: SPEC-15 §7 (#221) · Status: decided
- Context: Five shops outside the reference set (three with one presentment currency, two with several), one collection and three product pages each, adapter vs the generic HTTP path, no LLM, aggregate only.
- Decision: Listings: generic 0 rows on 5/5; adapter 509 rows, 509 with a URL, 352 with a price (none on the two multi-currency shops, by D-1114). Detail, one-currency shops (9 pages): brand agrees 9/9, price agrees 6/6 (3 pages neither), url 8/9; adapter-only product_id 9, gtin 2; generic-only sku 6 (a theme's default variant), condition 6, rating 3, review count 3; additional images: adapter more on 4. Detail, multi-currency shops (6 pages): `not_served`, so the page path's result. The adapter stays off by default; a listing-only default is the owner's call (recommendation in the PR).
- Alternatives: none.
- Why: C6 evidence for the changed adapter.
- Reversible: yes
