# Extraction

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 8. Extraction

**Parse once (Appendix A #31).** A capture body is parsed at most once per parser in a pipeline run. One
`ParsedPage` per capture holds the selectolax tree, the lxml tree (built lazily, and only when an XPath step or
trafilatura needs it), the extracted `<script>` blocks, the cleaned text and the visibility index. Collectors,
cleaned text, content formats, pagination and the config executor all read that object, never the raw body. The
release executor (§12.3) is the one exception: it parses on its own by design, and runs only at release check.

### 8.1 Collectors

```
capture (blocked/shell → stop)
  → adapter / API recipe
  → structured: JSON-LD, microdata (incl. RDFa Lite), Open Graph, embedded JSON state, captured XHR JSON
  → structural DOM: label–value pairs, the main image (detail pages)
  → site config (active extraction_config, deterministic)
  → normalize (§9) → resolve (§10)
  → fields still missing, in cold mode or not covered by the active config → LLM grounded extraction (§8.4)
  → publish / abstain
```

- **Structured collectors map through each field's `schema_org` mapping.** Open Graph maps through a fixed table
  justified by the OGP specification.
- **Embedded JSON state and XHR bodies** have no standard keys. A value becomes a candidate only when:
  - it equals a value from another source kind, in which case it is marked `independent=false` and never counts
    toward `agreed` (§10); or
  - it is visible in the page text (`independent=true`), and the field's type has a syntax its normalizer checks:
    money, enum, date, datetime, location, range, an identifier with a check digit (gtin, isbn), or a url given
    absolute. Any visible string normalizes as text, so text and the other opaque types admit by equality only
    (Appendix A #34).
- **Structural DOM values** (Appendix A #42). On a detail page, a two-cell table row whose first cell heads it and
  a description list's terms with their descriptions (HTML Standard §4.9, §4.4.9) give a candidate when the
  label's words are the field's name or the schema.org property its mapping names; the main region's first
  image outside navigation, headers, footers and asides fills an `image_url` field mapped to `image`. Values must
  be shown. They are independent page values with source kind `dom` and a `dom:` XPath locator, resolved like
  any other with no trust of their own.
- **Locator.** Every candidate carries a locator: `<scheme>:<address>`. Schemes are `jsonld`, `microdata`, `dom`, `meta`,
  `js_state`, `xhr`, `adapter`, `api`, `config`, `text` (character offsets) and `derived` (a page-URL derivation,
  §10: the canonical link or the final URL). The exact format is in SPEC-05.
  Induction (§8.3) generalizes locators.
- **No generic DOM heuristics.** There is no `[class*=price]`, no bare `h1`, no card-selector lists (C2). The only
  DOM selectors are per-site ones in configs (§8.3) and the structural rules above, each named by the HTML
  structure it reads. Repeated-structure and typed value spotting collectors remain a candidate (§22).

### 8.2 Rules

1. **Run every cheap collector.** Skipping only ever means skipping the LLM or the browser.
2. **Shells are not observations.** Blocked, challenge and empty-shell pages end with zero records.
3. **Ownership comes from structure.** A candidate belongs to the entity whose JSON object or DOM subtree contains
   it. When a page carries several primary-type entities, entities nested in `ItemList` or schema.org relation
   properties are excluded, and so are a primary entity's variants (schema.org `hasVariant`: members of a
   `ProductGroup`). Of the rest, the target is the one matching the request, final or canonical URL. If none
   matches uniquely, every field is `conflict` (`intent_ambiguous`), never a guess. An Offer of one of the
   target's variants is the target's, like its own Offers (atomic offers, §10); the variant's other values stay
   the variant's (Appendix A #36).
4. **URL parameter values are never published** unless they are visible on the page.

### 8.3 Learning a site config

Learning runs per (site, schema, page_kind) once **8 pages have been extracted**, meaning pages with outcome
`extracted` or `partial`. Five are the learning sample and at least three are held out for validation. Later pages
join the held-out set.

1. **Induce without an LLM.** For fields where the published candidate's locator follows the same pattern on all 5
   sample pages, generalize it: strip positional indices and keep stable anchors (`id`, `data-*`, `itemprop`,
   unhashed class tokens). Keep a selector only if it selects exactly the published value on every sample page.
2. **Synthesize the rest** (LLM role A, §11). Input: field descriptions, the 5 cleaned sample pages, and the values
   already published on them. Output: a selector or JSONPath map. Up to 3 repair rounds with diagnostics.
3. **Validate on held-out pages.**
   - Exactly one match for single-valued fields, and at least 3 rows on listings.
   - Every value accepted by its type normalizer.
   - The independent release executor (§12.3) reproduces the same values.
4. **Record corroboration per field.**
   - `corroborated`: the config's values match structured-data or adapter values for that field. The comparison
     uses only **comparable** held-out pages, meaning pages that have such a value for the field. At least 3
     comparable pages are required. The values must match on every comparable page while there are fewer than 10,
     and on ≥ 90% from 10 on.
   - `operator`: confirmed or corrected through the API (C5).
   - `uncorroborated`: everything else, including fields with fewer than 3 comparable pages.
   - `suspended`: set by drift (below).

   §16 measures precision separately for each status.
5. **Activate.** The config becomes `active`, and the site enters `active` mode.

**Drift.** Each run of an active config tracks per-field yield and validity against the config's validation report.
If a field drops below it (margins fitted on dev), its status becomes `suspended`: its pages fall back to cold-mode
extraction, and a `learn` job re-runs.

### 8.4 Progressive mode (Appendix A #23)

| Mode | Entered when | Path | Record `mode` |
|---|---|---|---|
| `cold` | A new (site, schema, page_kind), or its schema was edited | Collectors → resolve. Required fields still missing → **LLM role C**: grounded extraction from cleaned page text. Values must be verbatim substrings with offsets and must pass their type normalizer. | `adhoc` |
| `learning` | 8 pages extracted, or an explicit `learn` job | §8.3 runs in the background; pages keep being served in cold mode. | `adhoc` |
| `active` | A config activates | Collectors + config → resolve. Role C only for fields the config doesn't cover. | `config` |

### 8.5 Page content outputs

For `scrape` formats:
- `markdown`: main content via trafilatura **[verified: Apache-2.0]**;
- cleaned `html`, `raw_html`;
- `links`: absolutized;
- `metadata`: title, description, language, canonical, Open Graph, structured-data types present.

All generic; no per-site cleaning (C2).

### 8.6 Listings and pagination

- **Cold listings.** Rows come from structured data (`ItemList`, or several top-level primary-type entities) or from
  role C, which returns rows grounded in page text.
- **Learned configs** carry a row selector and a next-page selector.
- **Pagination.** `rel=next` is a standard and core. A structural rule for numbered page links, matching no
  particular parameter name, is defined in SPEC-05. Infinite scroll goes through §7.2.
