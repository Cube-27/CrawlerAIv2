# Listings Specification

## Purpose

A listing page's rows: the item layer (segment the page's repeated item groups, align each block's fields, bind
stated rows, call and state rows and blocks into one row per item), rows from captured calls, role C's values for the
blocks' rows, the row item URL and next pages. Candidates come from [extraction](../extraction/spec.md); what
publishes is [resolution](../resolution/spec.md). Rationale: master plan §3.2 (owner decision #67).

## Requirements

### Requirement: Item groups (segment)
A listing page's repeated item groups SHALL be `MIN_ITEMS` or more sibling blocks of one shape that each are or hold a
hyperlink, outside chrome (`acquire/items.py`: `nav`, `header`, `footer`, `aside`, `search`, their landmark roles and
the WAI-ARIA `menubar` and `menu` roles), ranked once per parse (`ParsedPage.item_groups`, `content/segment.py`):
by the rendered area of their blocks when the browser capture measured it (`CaptureManifest.item_areas`, recorded for
listing captures), else by blocks showing an image or two or more text runs, then size; a block not rendered (no area,
or hidden by the HTML rendering rules) is left out. The markdown format, `xhr` and the paging driver read this one
ranking. (Previously: role C's item text read it too; a `menubar`, `menu` or `search` landmark was content.) Refs:
owner #67, master plan §3.2.
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards' group ranks first
#### Scenario: Measured areas
- **WHEN** a browser capture measured a sidebar's 20 links smaller in area than a grid's 6 cards
- **THEN** the grid ranks first, and a card with no area is not one of its blocks

### Requirement: Rows from blocks (align)
Each group whose blocks lead to one item, at least a quorum of `max(MIN_ITEMS, 60%)` of them, `MIN_ITEMS` of them
showing more than their link, SHALL give an `item_block` row per item URL (`collect/items/align.py`); a field is read at
a place shared by a quorum of the blocks whose value its normalizer accepts: the item URL (the one document the block's
links lead to, not the page in another state, an image file or an item's own nested list; for a block linking to
several, else, at group level, the one document no other block links to at the tag path where a quorum of the blocks
link to such a document, a path whose link holds an image before the first other one: documents two or more blocks link to, a vendor's, an author's or a
category's page, are the template's), the name (the accessible
name of the item link, WCAG label in name, or the block's heading; never a URL; text every block repeats is the
template's), the image, and typed value spotting for money, dates and check-digit identifiers (text in `s`/`del`
excluded, also from the lines of the elements holding it; an element's line is not read where two text nodes run digits
together, a token boundary the text does not show; an element holding others is also read in each of its own text
nodes). Values are `dom` candidates with locators; the group aligning most fields is first. A group one of whose blocks
stands for the page itself (a link marked `aria-current="page"`, or links to this very URL only) is the site's
navigation and gives no rows. (Previously: a card linking to its item and to an author or vendor page gave no item URL
unless a heading or most of its text held the item's link; a category or city hub listing the page was rows.) Refs:
owner #67.
#### Scenario: Cards with title, link and price
- **WHEN** a listing shows cards of varying tags and class tokens, each with a heading link and one price
- **THEN** each card is a row with its title, URL and price
#### Scenario: Was and now prices
- **WHEN** a card shows a current price and a second price not struck through
- **THEN** its price is `ambiguous_in_block` and publishes nothing unless a stated row bound to it agrees with one
#### Scenario: A badge next to the price
- **WHEN** a card renders `<span>EUR 10.99</span><span>20</span>` with no space between them
- **THEN** its price is `10.99` EUR from the first span, never `10.9920`
#### Scenario: Cards linking an author and a shared vendor
- **WHEN** each card links its item from its image and its title, its own author, and a vendor page every card links
- **THEN** each card's item URL is its item's
#### Scenario: Hub listing the current page
- **WHEN** a group of category tiles holds one tile marked `aria-current="page"`
- **THEN** the group gives no rows

### Requirement: Stated rows and blocks (bind)
The stated rows SHALL be structured data's (`resolve/listing.py`), else the active config's, else the captured calls'.
The blocks are those of the group the stated rows name most and of every other section read with it: an aligned group
of its row shape (or holding every required field it aligns and a field beyond the item URL) whose blocks lead, a quorum of them, to
documents of the kind its blocks lead to (host, path depth, first segment), apart from blocks already read, fewer than
half of whose blocks lead to items the chosen group lists (else it is a featured or recently viewed copy) and not
starting after the chosen group's `rel=next` link (past the listing's end); an item two sections show is one block
(D-1776). Where one structured list is the page's `mainEntity`, only its entries are stated rows
(`resolve/listing.py`); else, with stated rows in several lists, the list or lists with the most rows bound to the chosen group's blocks, give rows; with
none bound, all do. Stated rows and those blocks bind one to one by item URL (session parameters, a trailing
slash and added query parameters aside) or by a name the block shows (`collect/items/bind.py`). With no stated rows or
only stubs, the blocks are the rows; otherwise stated rows stay and the group's blocks no stated row names extend them.
A config's rows bind no blocks. A bound entity's values join its row where the row has none for the field or equals
them; a block's link replaces a respelled stated item URL. Of a money field, a block bound by URL takes part whatever
the row's source (structured markup or a platform adapter's answer): its one visible amount that differs from the row's
joins as a rival, which the resolution spec's visible-price rule weighs (#334: it publishes, flagged `disagree`); a
block showing several amounts joins its option equal to the row's, else every option, so that the price is a `conflict`
(C7; a stated price that is one variant's beside a card's "from" price, a theme showing a tax-inclusive amount the
catalogue price excludes). State and call array rows bind by URL, and a JSON key whose
values equal a block field on `MIN_ITEMS` bound rows is that field's key for every bound row (`collect/induce.py`).
(Previously: the blocks of one group only; a bound block's amount that disagreed with a row's was dropped unless only
an adapter stated the row, and a block's several amounts joined only an option equal to the row's; a featured copy or a
strip after the pager was read as a section; every structured list gave rows.)
Refs: owner #67, Appendix A #59, D-1776.
#### Scenario: Visible card price of an adapter row
- **WHEN** an adapter's answer states a row's price 19.50 EUR and the row's card, bound by URL, shows €23.40
- **THEN** the row's price publishes 23.40 EUR, flagged `disagree`
#### Scenario: Card amounts against a structured row
- **WHEN** an `ItemList` Product states 28.59 EUR, and its card shows 15.58 EUR beside 17.29 EUR
- **THEN** the row's price is a `conflict` (`disagree`); a card showing 15.58 EUR alone publishes it, flagged
#### Scenario: Two sections of one shape
- **WHEN** a listing shows items 1–3 in one section and items 3–6 in another of the same cards
- **THEN** the listing has six rows
#### Scenario: Featured strip and a strip after the pager
- **WHEN** a grid of items 1–6 is followed by a strip of the same cards showing items 1, 2, 3 and 9, or by a `rel=next`
  link and then a strip of items 7–9
- **THEN** the listing has the six rows of the grid
#### Scenario: Several item lists
- **WHEN** a page's `WebPage.mainEntity` lists items 1–3 and another `ItemList` lists items 7–9
- **THEN** the listing has the rows of items 1–3; without `mainEntity`, the same when the grid's cards show items 1–3
#### Scenario: Stub rows
- **WHEN** an `ItemList` names three items by URL only and the page's cards show their titles and prices
- **THEN** the listing has three rows with the cards' titles, prices and links
#### Scenario: A grown list
- **WHEN** the script lists items 1–3 and the list's blocks show items 1–6
- **THEN** the listing has six rows

### Requirement: Rows from captured calls
On a listing the `xhr` collector SHALL read rows from the calls of one method, origin and path, body shape and row query
(`collect/network_match.py`), the first series in which a row field's path is admitted in `MIN_ITEMS` rows or more (for
a url field also: a link of the page's item groups), each row an `array_row` entity read through the API recipe row
reader; with a learned listing recipe, its map. A call's HTML answer is no row series: a partial the page does not
show is part of the page tree ([extraction](../extraction/spec.md), "Source documents"), whose item blocks give rows as
the page's do. They are the stated rows where structured data and the config give
none; when they leave a record incomplete role C fills, through their bound blocks, the fields they lack. A locate run
on a listing without rows learns the renders' call series as the config's listing recipe, with its pagination
([learning-configs](../learning-configs/spec.md), "Locate run"). (Previously: role C's rows replaced them; a locate run
located no rows.) Refs: §8.1, §8.6, Appendix A #59, D-1603, architecture v3 a.6.
#### Scenario: Complete rows of a call
- **WHEN** the rows of a call publish every required field
- **THEN** role C is not asked

### Requirement: Rows from page state
On a listing where no structured data, config, call or block gives rows, an array of `MIN_ITEMS` or more objects in the
page's state JSON SHALL give rows (`collect/items/state_rows.py`): each row field read at the path induced across the
rows whose own member names the field (its name or schema.org property) and whose value normalizes and is shown in the
page text (an image: normalizes), the item URL also at a path whose values the rendered hyperlinks of the page's content
lead to (its main landmark, else its body, outside chrome); a row is kept only when its item URL is such a link or its
name is shown, an array with fewer such rows gives none, and an item
read once is not read again (after the choice below); of several arrays read, only the one or ones with the most rows whose item URL the page's
first item group links to give rows (all, when none does). Values are `js_state` candidates (bucket `state`). A locate run writes such rows into the
config as paths (`config_ir/json_rows.py`): a `jsonpath` row step selecting the array that holds `MIN_ITEMS` or more of
the rendered rows' item URLs in a document the HTML carries (embedded state, JSON-LD, JSON attributes, RSC rows), and
for each row field the path relative to the item that more than half of the paired items hold
([learning-configs](../learning-configs/spec.md), "Locate run"). (Previously: no rows, D-1774; the paths were induced on
every page only; any rendered link, the site's menus included, grounded an item URL; every array read gave rows.) Refs: D-1773, D-1775,
architecture v3 a.6.
#### Scenario: Items only in state
- **WHEN** a script's JSON lists three items whose names and prices the page shows without item links
- **THEN** the listing has three rows with state evidence, and none when the page shows none of them
#### Scenario: State menu tree
- **WHEN** a script's JSON holds the site's menu entries, whose links the page renders only under `role="menubar"`
- **THEN** those links ground no row

### Requirement: Row item URL
A row's item URL field SHALL read schema.org `url`, else the item's `offers.url`, else its `mainEntityOfPage` (a URL or
a page's `url`), else its own IRI (JSON-LD `@id`, microdata `itemid`) when absolute http(s), without a fragment, on the
page's site and not the page's URL, a bound block's link replacing a respelling; published row URLs drop each query parameter that two or
more of them carry once with one value and none of the page's own URLs carries (`normalize.url_key`), named in the
result. Refs: owner #67 decisions 1 and 6.
#### Scenario: Item named by its offer
- **WHEN** a listed Product states no `url` and its Offer states `url`
- **THEN** the row's item URL is the Offer's
#### Scenario: Item named by its IRI
- **WHEN** a listed Product states no `url`, Offer URL or main entity page, and its `@id` is `https://example.com/p/7`
  on a page of `example.com`
- **THEN** the row's item URL is `https://example.com/p/7`; an `@id` ending in `#product` names none
#### Scenario: Visit parameter on every row
- **WHEN** every row URL carries `sid=abc` and its own `v=<n>`, and the page URL carries neither
- **THEN** the rows publish their URLs with `v=<n>` and without `sid`

### Requirement: Role C rows
Role C SHALL be asked for the blocks whose bound rows lack a row field, each for the fields its row lacks but the item
URL, when a row field is published on no row or a row lacks a required one, and never beside a config that runs a row
field; and in a separate call over the whole cleaned text for the missing page fields when a required one is missing.
Its values fill the blocks' rows; it makes no row, so a listing without rows answers `no_rows: no_blocks`.
A block of a nested listing is read with its enclosing item's context (`collect/items/lines.py`): when the block lies
inside a block of another repeated group, and two or more blocks of that group hold rows, the enclosing block's text
before the first block of the inner group (what a building states for its units: its name, its address, column
headings) comes with the block, as the block's own text does not show it.
(Previously: role C was asked for rows when the listing had none, and its rows were placed on blocks by their links or
replaced rows read from blocks alone; a nested row was read without its enclosing item's text.) Refs: §8.6, owner #67,
D-1603, D-1604, D-1605.
#### Scenario: Only rows lacking a required field
- **WHEN** one of five bound rows lacks a required row field and every row field is published on some row
- **THEN** role C is asked for that block only, for the fields its row lacks
#### Scenario: Nested rows
- **WHEN** each of three buildings states its name and address, then lists three units that each link to a unit page
- **THEN** each unit is a row, and role C reads it with its building's name and address before its own text
#### Scenario: Listing without blocks
- **WHEN** a listing has no stated rows and no aligned item group
- **THEN** role C is not asked for rows and the answer's reason is `no_rows: no_blocks`

### Requirement: Next pages
Next pages SHALL come from `rel=next`, then the link differing from the page URL in one path segment or query value by
one integer one higher, then a config's `listing.next` (`resolve/pagination.py`); the first `rel=next` link is a
page-level `dom` candidate of `next_page_url`, and a numbered link fills no field (C7). Refs: §8.6, D-0509, D-0514.
#### Scenario: Integer inside a segment
- **WHEN** a listing at `/list/page-2.html` links to `page-3.html` and `sheet-3.html`
- **THEN** `/list/page-3.html` is its next page and `sheet-3.html` is not
