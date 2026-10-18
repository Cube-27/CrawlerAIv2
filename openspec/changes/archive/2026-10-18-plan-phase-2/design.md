# Design: plan phase 2, the item layer (segment, align, bind, row key)

## Decisions

### D-1560 — The segment step lives in `content/segment.py`
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: The ranker sits in `content/segment.py`, not `collect/items/segment.py` as the plan names it: the
  `ParsedPage` that caches the ranking and the formats that read it (`markdown`, role C's item text, render need) are
  in `content`, which the layering contract places under `collect`. The structural walk stays in `acquire/items.py`,
  which acquisition reads before any page is parsed.
- Why: import-linter layers; one ranker, read by every caller.
- Reversible: yes

### D-1561 — Typed value spotting covers money, dates and check-digit identifiers
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: Row fields of type money, date, datetime, and identifiers under a scheme with a check digit are spotted in
  blocks; enum and range are not (an enum vocabulary matches badge words, a range any two numbers).
- Why: the plan names price, date and identifier; the most conservative reading.
- Reversible: yes

### D-1562 — Struck-through text is no current value; several shown prices decline
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: Text inside `s` or `del` is not spotted (HTML Standard §4.5.4, §4.7.2); a block whose aligned places give
  several money values gives an `ambiguous_in_block` candidate, which publishes only as the option a bound stated row
  agrees with. A place giving one value in every block is the template's when another place gives varied values.
- Why: plan §5 risk on was/now prices; decline rather than guess (C7).
- Reversible: yes

### D-1563 — Names: content-labelled link, heading, image-stated text; never a URL or template text
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: Three name places are read: the first item link labelled by its shown one-line content, else the full
  accessible name (an attribute name narrowed to the block's longest shown text it contains, WCAG 2.1 SC 2.5.3); the
  block's one heading; the block's shown line that its image `alt` or its link `title` repeats. Of the places a quorum
  shares, the one with the most distinct values wins (rule order on a tie); a place with one value in every block is
  template text and names nothing; a name that is an absolute URL names nothing.
- Why: overlay links, call-to-action links and whole-card links on the golden set; each rule names its standard.
- Reversible: yes

### D-1564 — Which document a block leads to
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: A block's hyperlinks lead to its item when, leaving out the page itself in any query state, image files
  and the links of the item's own lists (groups lying inside one block of another group, recurring in two or more of
  its blocks that also link outside them), they lead to one document; else the bare document others refine with a
  query, else the one its headings link to, else the one whose links hold over half of the block's shown text.
- Why: seller and employer links, share buttons and pagers made blocks lead to several documents or to none.
- Reversible: yes

### D-1565 — A group needs `MIN_ITEMS` blocks showing more than their link
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: A group aligns only when `MIN_ITEMS` of its blocks show an image or two or more text runs; a quorum would
  reject a grid whose later cards a script fills.
- Why: footer, pager and related-search link lists aligned as rows when the true grid did not.
- Reversible: yes

### D-1566 — Group choice: aligned fields, then the group the stated rows name
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: The align step returns every aligned group, most fields aligned first, the segment order breaking ties;
  the bind step takes the group binding the most stated rows by URL (the first when none or a tie). Only the first
  group's values are admission anchors; the other groups' candidates are dropped at bind.
- Why: a profile or category group can align as many fields as the item grid; stated rows name the listing.
- Reversible: yes

### D-1567 — One row per item URL
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: Blocks of one group leading to the same item URL are one row (the first); a block any stated row names,
  bound or not (two rows naming it bind neither, C7), adds no row; a stub no block takes stays a row.
- Why: duplicated cards and duplicate stated items made rows appear twice.
- Reversible: yes

### D-1568 — Stated rows; config rows bind no blocks
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: The stated rows are structured data's, else the active config's, else the captured calls'. A config's
  rows bind no blocks: its row selector was validated against every item, and its fields keep their config buckets.
- Why: learning-configs spec; keeps config-mode extraction unchanged.
- Reversible: yes

### D-1569 — Item URL alternatives by rank
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: A listing row's item URL field reads its path's `url`, then a rank later `offers.url`, then a rank later
  `mainEntityOfPage` (a URL, or its `url`); a WebPage node's `@id` is not read (no locator form for a keyword member
  in the mapping).
- Why: plan §3.2 row key; the golden pages of the class state `offers.url`.
- Reversible: yes

### D-1570 — Binding URLs include item URL values; array rows writing a URL are entities
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: A row binds by its entity URLs and its item URL candidates' values (a call row states its URL as a
  value). Admission makes an array row that writes a URL an `array_row` entity even when it owns no value.
- Why: call rows and state rows carried no entity URLs, so they never bound.
- Reversible: yes

### D-1571 — Role C on listings with rows
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: Role C is also asked, with today's listing request, when the rows publish some row field on no row; its
  rows bind to the listing's rows by item URL and fill fields the rows lack or agree with. When the rows are blocks
  alone and role C's rows name items by URL, none of them a block's, role C's rows replace the blocks (role C read
  the listing in another place). The per-block request is the next batch's (plan PR2.5).
- Why: without it role C stopped supplying job locations once blocks gave rows (list precision fell 0.575 → 0.145),
  and a category-link group stood where role C had read the one real row.
- Reversible: yes

### D-1572 — One induction rule; induced values keep their source's evidence
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: `collect/induce.py` holds the rule learning's induction, the call-row path proof and the bind step's key
  induction share: the reading the most instances propose, at least a quorum, the first proposed on a tie. A value read
  at an induced key keeps its source kind, is not independent, and goes only to rows whose block lacks the field; a
  lone state value still ranks in no text precedence and has no bucket (resolution spec).
- Why: plan §3.2 asks for one module; changing state values' evidence is a resolution change left as a follow-up.
- Reversible: yes

### D-1573 — Browser item areas for listing captures only
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: The browser rung measures the rendered area of at most 2,000 blocks of a listing's item groups, by element
  path, after the page settles, and stores them in `CaptureManifest.item_areas`; the walk runs in a thread.
- Why: plan §3.2 "record bounding boxes of candidate blocks cheaply"; detail pages have no listing groups to rank.
- Reversible: yes

### D-1574 — The listing requirements move to a `listings` capability
- Date: 2026-10-18 · Change/PR: plan-phase-2 (#278) · Status: decided (owner-delegated 2026-10-17)
- Decision: The extraction spec's listing requirements (cold rows and pagination, call rows, row item URLs) move to a
  new `listings` spec with the item layer's requirements; extraction keeps collectors and content formats.
- Why: the extraction spec was past the size guidance (CLAUDE.md §6); one architecture described in one place.
- Reversible: yes
