# Design: structural ownership of array rows in embedded state

## Shape

- **Rows** (`collect/admission.py`): the walk over a state document carries, for each string and number, the paths of
  the array rows holding it (outermost first). `_Rows` notes each row's written URLs and, for a value admitted by
  visibility, makes its innermost row the owner, creating an `array_row` entity for it and each enclosing row (parent:
  the enclosing row, else `page`). URLs are canonicalized only for those rows.
- **Ownership** (`resolve/ownership.py`): `EntityGraph` holds the page URLs (request, final, canonical, canonicalized,
  as the pipeline already computes for SPEC-13 §4.4); `owned_by` answers an `array_row` owner with `_names_target`.
  `names_any` moves here from `resolve/intent.py`, which imports it (C8).
- No new reason: another row's candidate is `not_owned`, as a related entity's is. A lone state value still has no
  evidence bucket (§10), so a target row's value is kept and abstains `no_bucket` unless another kind agrees.

## Decisions

### D-1250 — An array row is an object item of an array of two or more objects
- Date: 2026-10-17 · Change/PR: array-row-ownership (#243) · Status: decided (owner-delegated 2026-10-17)
- Decision: rows are the object items of a JSON array holding at least two objects; one object in an array (with or
  without scalars beside it) is its holder's own item and stays in its holder's scope. Rows nest: a row inside a row
  has the outer row as its parent.
- Alternatives: every object in an array (a lone `offers: [{…}]` of the target would need a URL to publish); three or
  more, as listings' repeated items (a pair of related items would still leak).
- Why: two objects in one array are already a set the page did not single out; structure only (JSON keys follow no
  standard, §8.1).
- Reversible: yes

### D-1251 — Only a value admitted by visibility moves to its row
- Date: 2026-10-17 · Change/PR: array-row-ownership (#243) · Status: decided (owner-delegated 2026-10-17)
- Decision: a value admitted by equality keeps the owner of the candidate it equals (D-0419), wherever it sits; only an
  independent value, which was the page's, is given to its innermost row.
- Alternatives: give every state value inside a row to the row (would drop agreement values the other collectors'
  entities already own correctly).
- Why: an equal value never changes what publishes (it agrees, and is not independent); the leak was the page owning
  a visible value.
- Reversible: yes

### D-1252 — A row's URLs are the URLs written in its scope
- Date: 2026-10-17 · Change/PR: array-row-ownership (#243) · Status: decided (owner-delegated 2026-10-17)
- Decision: an `array_row` entity's `urls` are the strings in the row, outside its nested rows, that start as an
  http(s) URL or a path-absolute or network-path reference (RFC 3986 §3.1, §4.2) and canonicalize against the
  document base URL (§5.2). No key is read.
- Alternatives: absolute URLs only (state often links items by path); any string resolved as a relative reference
  (a slug would name a document it does not).
- Why: SPEC-13 §4.3 scopes a row up to its nested rows; image URLs in a row name other documents but only a positive
  match is read (D-1253).
- Reversible: yes

### D-1253 — A row is the target's when it and its enclosing rows name the target
- Date: 2026-10-17 · Change/PR: array-row-ownership (#243) · Status: decided (owner-delegated 2026-10-17)
- Decision: where page values are the target's (a detail page, a listing's page fields), an `array_row` candidate is
  owned when the row and every row enclosing it has a URL equal (url type equality, query included) to a page URL or
  one of the target's URLs. A row naming only other documents, or none, is `not_owned`, and so is any row inside one.
  A listing row never owns a state row.
- Alternatives: compare documents without the query, as intent's "own" test does (items addressed by a query on one
  path would all name the page); own a row naming no URL (price tiers and URL-less recommendations would leak).
- Why: owner, "never leak": a row's value publishes only when the row says it is the page's subject. A variant row
  that names the page only with a variant query is not owned; varying values belong to `variants` anyway (D-1057).
- Reversible: yes

### D-1254 — The row entity's id and type
- Date: 2026-10-17 · Change/PR: array-row-ownership (#243) · Status: decided (owner-delegated 2026-10-17)
- Decision: id `<kind>:<document index>:<row path>` (the document's position among the collector's documents, since one
  script can hold several and their paths can repeat); type `array_row` (`collect.base.ARRAY_ROW`), no schema.org type,
  so a row is never a primary entity, an Offer or a listing row.
- Alternatives: the row's locator as id (two documents of one script share an address, D-0943's locator spelling).
- Why: ids must be unique for `EntityGraph.of`; the candidate keeps its own locator, which reads back to the value.
- Reversible: yes

### D-1255 — Structured related items keep their entity ownership; no new rule there
- Date: 2026-10-17 · Change/PR: array-row-ownership (#243) · Status: decided (owner-delegated 2026-10-17)
- Decision: JSON-LD and microdata related items (`isRelatedTo`, `isSimilarTo`), an `ItemList` on a detail page and
  another product's Offers already own their values by entity (`owned_by`); this change adds behaviour tests for them
  and no code. Label-value pairs (`dom`) inside repeated page structures stay page values (follow-up).
- Why: the leak was in state, whose keys carry no standard; structured data already says which item a value is of.
- Reversible: yes
