# Design: the DOM description block

- Shape: `DescriptionCollector.collect(page, schema, ctx, others) -> CollectResult`, run in `collect_page` after the
  other standard collectors (it reads their candidates) and before the admitting ones. `_Blocks` holds the main
  region's prose elements with their cleaned text (`ParsedPage.text_spans`); `_extending`, `_labelled` and
  `_main_text` each return one block or none.

## Decisions

### D-1700 — A separate collector that reads the others' candidates
- Date: 2026-10-18 · Change/PR: dom-description (#286) · Status: decided (owner-delegated 2026-10-17)
- Decision: The description block is read by `DescriptionCollector`, not `DomCollector`, because the block that
  "extends" a description is defined against the values other collectors proposed for the field. It runs after them
  in `collect_page` and its candidates join `others` for the admitting collectors.
- Alternatives: re-reading Open Graph and JSON-LD inside `DomCollector` (a second path for the same logic, C8).
- Reversible: yes

### D-1701 — Extension: outermost block that begins with a stated value; equal to a non-Open-Graph value wins
- Date: 2026-10-18 · Change/PR: dom-description (#286) · Status: decided (owner-delegated 2026-10-17)
- Decision: Of the prose blocks whose text begins with a stated value (ellipsis cut off, white space not compared: a
  meta description joins paragraphs without a space), the outermost is the description. A block equal to a value of
  another kind than Open Graph is that value in full (it corroborates it, `agreed`) and wins over wider blocks;
  an Open Graph summary is not full, so its equal block is extended to the outer one.
- Why: golden set (fitted, C1): outermost without the equality rule absorbed the sections that follow a complete
  JSON-LD description; with it for Open Graph too, a paragraph equal to the summary hid the rest of the text.
- Reversible: yes

### D-1702 — Labelled sections use the schema's words
- Date: 2026-10-18 · Change/PR: dom-description (#286) · Status: decided (owner-delegated 2026-10-17)
- Decision: A heading (`h1`-`h6`, role `heading`) or an `aria-label`/`aria-labelledby` whose words are a `long_text`
  field's name or its schema.org property's (`field_labels`, as label-value pairs) labels the prose after it up to the
  next heading (climbing out of a wrapper that has none). No other words: a section labelled in another language, or
  "Overview", is not read by this rule (C4).
- Reversible: yes

### D-1703 — What is prose, and what is not the item's
- Date: 2026-10-18 · Change/PR: dom-description (#286) · Status: decided (owner-delegated 2026-10-17)
- Decision: A block is prose when it holds no table, form control, button, image, picture, media, frame, script or
  template, and is not inside or around `nav`, `header`, `footer`, `aside`, `dialog`, an element whose ARIA role is
  dialog, form, navigation, complementary, banner or contentinfo, or an element marked schema.org `review`,
  `isRelatedTo`, `isSimilarTo` or of a Review `itemtype`. The text is the page's cleaned text of the element; an
  opening heading is not part of it. The whole region is never a block.
- Reversible: yes

### D-1704 — Main-text fallback for a summary-only description
- Date: 2026-10-18 · Change/PR: dom-description (#286) · Status: decided (owner-delegated 2026-10-17)
- Decision: Beyond the two candidate forms of the task: for a field whose path names schema.org `description`, when
  only Open Graph (or no kind) states it, the longest maximal prose block (a prose block whose parent is not one) whose
  text is not mostly link text (list of links = navigation or related items), is a candidate; equal lengths: none.
  `og:description` is by definition a short summary, and on 6 of the 11 golden pages whose description was wrong it stood alone,
  the description being an unlabelled block (or under a heading in another language). Flagged for the owner: this is the one rule
  that is a ranking of blocks, not a match to a stated value or label.
- Alternatives: no fallback; those pages keep the Open Graph summary.
- Reversible: yes (`_main_text`)
