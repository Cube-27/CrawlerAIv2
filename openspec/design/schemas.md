# Schemas as data

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 5. Schemas as data

A **schema** is a row in the database. Code knows about field **types**, never about "price on a product page".

### 5.1 Field types

| Type | Value |
|---|---|
| `text`, `long_text` | string; long text built from main-content extraction |
| `money` | {amount: decimal, currency: ISO 4217}, atomic |
| `enum` | code from a referenced vocabulary (e.g. schema.org `ItemAvailability`) |
| `url`, `image_url` | absolute, canonicalized |
| `identifier` | {scheme: gtin \| isbn \| mpn \| sku \| custom, value} |
| `date`, `datetime` | ISO 8601 |
| `location` | {text, locality, region, country ISO 3166-1 alpha-2, remote_flag}: what the page states (§9) |
| `range` | {min, max, currency or unit, period}; covers salary |
| `count` | non-negative integer, such as a stock quantity (Appendix A #39) |
| `number` | decimal as the page states it, such as a rating value (Appendix A #42) |
| `list<T>`, `object{…}` | nesting, depth ≤ 3 |

Types not in this table are added when a schema needs them, each with its one normalizer (C8).

### 5.2 Schema definition

```jsonc
{
  "name": "commerce_detail", "page_kind": "detail",
  "required_groups": [["sku", "gtin"]],
  "fields": {
    "title":  { "type": "text",  "required": true, "scope": "row",
                "description": "Product name shown to the buyer, without store name", "schema_org": "Product.name" },
    "price":  { "type": "money", "required": true, "description": "Current price, when every variant has the same one",
                "schema_org": "Offer.price+priceCurrency" },
    "availability": { "type": "enum", "vocab": "schema:ItemAvailability", "required": true, "schema_org": "Offer.availability" },
    "sku":    { "type": "identifier", "scheme": "sku",  "schema_org": "Product.sku" },
    "gtin":   { "type": "identifier", "scheme": "gtin", "schema_org": "Product.gtin" }
  }
}
```

- **Required fields.** "Core fields" means fields with `required: true`, plus `required_groups`, where at least one
  field of each group must publish.
- **Scope.** `scope` ∈ {`row`, `page`}, default `row`. On detail pages everything is `row`; on listings,
  `page` fields such as `next_page_url` belong to the page.
- **`description`** is required on every field; LLM roles read it.
- **`schema_org`** is a dotted path from a schema.org type. `+` joins two properties into one atomic value. `|`
  separates alternatives, whose candidates are pooled and resolved as usual (Appendix A #37).
- **Rows.** A `list` of `object` with a `schema_org` path is row-mapped: the path names the row nodes from the
  target, each sub-field maps by its own path within its row, and `key` names the identifier or url sub-fields
  that match one row across sources (SPEC-13).
- **No versions.** One schema per name, edited in place (Appendix A #43). Records and configs reference
  `schema_id`. An edit suspends the schema's active site configs and sends its progressive states back to
  `cold`, so its sites learn again; a job runs with the document it pinned at submit (INV-28).
- Full rules: SPEC-04.

### 5.3 Presets

| Preset | Required fields |
|---|---|
| `commerce_detail` | `title`, `price`, `availability`, `url`, `image_url`; group (`sku` \| `gtin`); `brand` when shown |
| `commerce_listing` | row: `title`, `url`; `price` when shown; page: `next_page_url` |
| `job_detail` | `title`, `company`, `locations`, `description`, `apply_url`, `date_posted` |
| `job_listing` | row: `title`, `url`; `location` when shown; page: `next_page_url` |

"When shown" fields are optional fields in the preset: `required` can't express a condition.
`commerce_detail` has the optional `variants` list, one row per variant with its sku, gtin, price,
availability, url, name and distinguishing attributes (Appendix A #37, SPEC-13), and the optional
`stock_quantity` (count), at the top level and in each variant row (Appendix A #39). The owner added, in place,
optional fields the page states, each mapped to its schema.org property: `description`, `additional_images`,
`color`, `material`, `gender`, `condition` (`itemCondition`), `rating` (`aggregateRating.ratingValue`, a
`number`), `review_count`, `mpn` and `product_id` (`productID`), and `variant_id` in each variant row. Nothing is
derived: no counts or values the page doesn't state (Appendix A #42). A preset changes by editing its file;
`crawlerai schemas sync` updates the stored preset in place.
Optional fields are added when a user needs them (OPEN_QUESTIONS #3). The presets map onto Google Merchant Center
and Google-for-Jobs `JobPosting` required properties **[verified]**. `apply_url` has no direct schema.org property;
its mapping is chosen in SPEC-04.

### 5.4 Custom schemas and prompts

- Custom schemas are created through the API or UI.
- A **prompt** without a schema is turned into a draft schema by LLM role S (§11), from the prompt plus 1–3 sample
  pages. The draft is stored, returned with the results for editing, and reused, so one prompt gives one stable
  schema.
- **Field names** (a request's `schema.fields`, on every run type) are drafted by role S into a schema with exactly
  those top-level fields for the request's page kind, from the names alone, before the job is stored. The same names
  and page kind give the same stored draft. `POST /v1/schemas/draft` returns that draft, so a client shows it for
  editing before the run (Appendix A #41).

### 5.5 Page kind

- `detail`: one primary entity, possibly with nested lists.
- `listing`: rows plus page-level fields.

The caller chooses per request, or per URL pattern in crawls (§13.2).
