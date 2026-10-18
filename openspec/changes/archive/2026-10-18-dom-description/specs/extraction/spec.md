## ADDED Requirements

### Requirement: DOM description block
On a detail page the system SHALL propose for each `long_text` field the prose block of the page's main region
(`collect/dom_text.py`; as the structural DOM values, outside chrome, dialogs and media fallback, and outside reviews
and related items marked by schema.org `review`, `isRelatedTo`, `isSimilarTo` or a Review `itemtype`) that states it in
full: the outermost block, with no table, form control, button, image, media or frame, whose text begins with a
candidate another collector proposed for the field (or its ellipsis-cut form, white space aside), and the block equal
to a non-Open-Graph value in place of that value's wider blocks; else the section after a heading, or named by
`aria-label` or `aria-labelledby`, whose words are the field's or its schema.org property's; else, for a field whose
path names `description` that only Open Graph (or nothing) states, the longest maximal prose block that is not mostly
links, without its opening heading. Blocks that differ are ambiguous: none. The candidate is `dom`, independent, in
the `dom` evidence bucket. Refs: C2, C4, D-1700..D-1704. Enforced by: unit and replay tests; active.
#### Scenario: Summary and full text
- **WHEN** `og:description` is the first sentence of a paragraph block that goes on, and no other kind states a
  description
- **THEN** `description` publishes the block's text, from `dom`
#### Scenario: Labelled section
- **WHEN** a heading reads "Description" and prose follows it up to the next heading
- **THEN** that prose is a `description` candidate
#### Scenario: Not the item's own text
- **WHEN** a block that begins with the stated description sits in an `aside`, a dialog or a review
- **THEN** it is not a candidate
