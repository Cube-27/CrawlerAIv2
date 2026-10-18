# Design: plan phase 3a, role C on detail pages

- Shape: `content.text.Mark(kind, start, end, path, target, name)`, recorded in the cleaned-text walk
  (`CleanedText.marks`); `llm.marked.MarkedText(text, cleaned, elements, inserted, lengths)`, the text the model reads
  with its ids, the cut cleaned text it maps back to, and the marks by id; the detail claim
  `{shown, ref, value, start, end}`; `llm.grounding.GroundedElement(value, path)` with a `dom:<path>` locator.
- A claim with a `ref` is grounded in the element; one without is a span, its offsets mapped from the marked text to
  the cleaned text before alignment, so every `text:` locator still points into the cleaned text.

## Decisions

### D-1620 — Role C on a detail page asks every missing field; a listing's page fields keep the required gate
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: On a detail page role C is asked, in its one call, for every `missing` field the config does not run,
  optional ones included (supersedes D-0025's required-only gate). A listing's page-field call, a second call on a
  listing, keeps the gate (listings spec "Role C rows" unchanged): the task is detail pages.
- Why: optional fields the page shows (color, review_count) stayed missing whenever every required field published.
  Golden set, live fast model: detail calls 14 → 39 (all calls 36 → 61), one per page as before.
- Reversible: yes (`resolve/pipeline._missing`)

### D-1621 — Links and images are marked inline, for the kinds the asked fields take
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: The detail text reads `[L<n>]` after a link's text, `[L<n>: <name>]` when the link announces a name its
  text does not show (`aria-label`, `title`, else the `alt` of its image), and `[I<n>]` or `[I<n>: <alt>]` at an
  image; ids are numbered by kind in document order. Links are marked only when a url field is asked, images only
  when an image_url field is; the 40,000-character cut applies to the cleaned text before the ids. A list of urls is
  not offered elements (one claim is one value).
- Why: inline ids keep the context that picks the right link (an "Apply" link beside the posting); asking-kind gating
  keeps the input of a page without such fields unchanged.
- Reversible: yes (`llm/marked.py`)

### D-1622 — Only a link to another http(s) resource gets an id
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: A link or image whose target, resolved against the document base URL, is not an http(s) URL, or is a
  same-document reference (RFC 3986 §4.4: the base URL up to its fragment, as `#apply` or an empty `href`), gets no
  id.
- Why: such a target gives no url value (`normalize.url`), or gives the page's own URL, which is the derived
  `apply_url` this change deletes.
- Reversible: yes

### D-1623 — An element claim names its id in a `ref` property; its value is read from the DOM
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: The detail claim is `{shown, ref, value, start, end}`, `ref` required and empty for a span (no optional
  properties in the providers' subsets). A url field may claim only a link, an image_url field only an image; any
  other id is dropped as ungrounded. The candidate's raw value is the element's `href` or `src` attribute recorded in
  the cleaned-text walk, normalized like a collector's, with a `dom:<path>` locator; the model's `value` is ignored.
- Why: the INV-12 extension the task asks: a claimed element must exist on the page, and its target never comes from
  model text.
- Reversible: yes

### D-1624 — Links and images are recorded in the cleaned-text walk
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: `content.text.render` records each shown `a[href]` and `img[src]` as a `Mark` (span, path, target, name)
  in `CleanedText.marks`, under the same visibility rules as the text. An element that renders no text takes the text
  offset where the walk reached it.
- Why: one walk (parse once, INV-26) gives the offsets the ids are inserted at; a second DOM walk could not place a
  textless element in the text.
- Reversible: yes

### D-1625 — The page URL stands in only for a field whose every alternative is `T.url`
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: `resolve.derive.is_page_url_field` requires `T.url` in every alternative of the field's path; the
  last-rank rule (D-1493) is deleted, so `apply_url` is never the canonical link or final URL.
- Why: the task; on the golden set 8 of the 11 derived `apply_url` values were wrong.
- Reversible: yes

### D-1626 — `job_detail.apply_url` is `JobPosting.potentialAction.target` only
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: The preset drops the `>JobPosting.url` rank: a posting's `url` is the posting's own URL (schema.org
  Thing.url), not where a candidate applies.
- Why: the task's rule (an apply link the page states, else absent). On the golden set that rank published 3 wrong
  values and 1 right one, and two adapter postings' URLs; it also kept role C from being asked for the apply link.
- Reversible: yes (the preset)

### D-1627 — Ids name the page by its own URL, take at most 10,000 characters, and skip hidden images' alts
- Date: 2026-10-18 · Change/PR: plan-phase-3a (#283) · Status: decided (owner-delegated 2026-10-17)
- Decision: A link is unmarked when its target is the page's own URL (the final URL; the base URL only when the page
  URL is unknown), so a `<base href>` elsewhere moves resolution but not page identity. The ids of a detail page
  take at most 10,000 characters together, the marks past that unshown. A link's name falls back to the alt of the
  first image in it that is shown, never a hidden one.
- Why: review findings on #283: the base URL may differ from the page; labels past the 40,000-character cut were
  unbounded; a hidden image's alt is not what the link announces.
- Reversible: yes
