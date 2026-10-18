# Tasks

## 1. Segment

- [ ] 1.1 `content/segment.py`: one ranker of the page's repeated item groups (rendered area with geometry, else
      structural evidence), unrendered blocks left out; cached as `ParsedPage.item_groups`; `item_blocks` and the
      paging driver's ranking deleted; markdown, item text, `xhr` and paging read it.
- [ ] 1.2 The browser rung records the rendered area of the listing's candidate blocks in the capture manifest
      (`item_areas`), and `ParsedPage.of` passes it to the ranker.

## 2. Align

- [ ] 2.1 `collect/items/align.py`: rows from the groups whose blocks lead to one item; per-field places aligned on
      `max(3, 60%)` of the blocks; name, item URL, image and typed value spotting (money, date, check-digit
      identifiers); `ambiguous_in_block`; `item_block` entities with located `dom` candidates.
- [ ] 2.2 `collect_page` runs the align step before the admitting collectors, so state and call values agree with the
      blocks' values.

## 3. Bind

- [ ] 3.1 `collect/items/bind.py`: stated rows and blocks bound by item URL or visible text; blocks as rows where stated
      rows are none or stubs, extending them otherwise; array rows bound by URL; values join where they fill or agree.
- [ ] 3.2 Per-page key→field induction over bound array rows, sharing `collect/induce.py` with learning's induction.
- [ ] 3.3 `resolve/call_rows.py` and `as_block_links` deleted; the pipeline takes its rows from the bind step.

## 4. Row key

- [ ] 4.1 A listing row's item URL field reads schema.org `url`, then `offers.url`, then `mainEntityOfPage`.
- [ ] 4.2 Role C on a listing with rows: asked when a row field publishes on no row; its rows fill the rows they bind
      to by item URL.

## 5. Specs

- [ ] 5.1 Spec deltas applied: extraction, listings (new), llm, acquisition; the change archived.
