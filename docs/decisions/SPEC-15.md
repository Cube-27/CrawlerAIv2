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
