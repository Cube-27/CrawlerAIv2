# Listings Specification

## Purpose

A listing page's rows: the item layer (segment the page's repeated item groups, align each block's fields, bind
stated rows, call and state rows and blocks into one row per item), rows from captured calls, role C's values for the
blocks' rows, the row item URL and next pages. Candidates come from [extraction](../extraction/spec.md); what
publishes is [resolution](../resolution/spec.md). Rationale: master plan §3.2 (owner decision #67).

## Requirements

### Requirement: Item groups (segment)
A listing page's repeated item groups SHALL be `MIN_ITEMS` or more sibling blocks of one shape that each are or hold a
hyperlink, the blocks of one shape in sibling sections of one shape being one group in document order however few each
section holds, when two or more sections hold them and one holds several (a part each item shows once is no section's
run), outside chrome (`acquire/items.py`: `nav`, `header`, `footer`, `aside`, `search`, their landmark roles and
the WAI-ARIA `menubar` and `menu` roles), ranked once per parse (`ParsedPage.item_groups`, `content/segment.py`):
by the rendered area of their blocks when the browser capture measured it (`CaptureManifest.item_areas`, recorded for
listing captures), else by blocks showing an image or two or more text runs, then size; a block not rendered (no area,
or hidden by the HTML rendering rules, unless the element hiding it is content a script reveals, extraction spec
"Cleaned text and visibility index") is left out. `xhr` and the paging driver read this one
ranking. Refs:
owner #67, master plan §3.2.
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards' group ranks first
#### Scenario: A job board in team sections
- **WHEN** a board lists its jobs under team labels, one, two and three jobs per team, each team one `div` of one class
- **THEN** its six jobs are one group, in document order
#### Scenario: Measured areas
- **WHEN** a browser capture measured a sidebar's 20 links smaller in area than a grid's 6 cards
- **THEN** the grid ranks first, and a card with no area is not one of its blocks

### Requirement: Rows from blocks (align)
Each group whose blocks lead to one item, at least a quorum of `max(MIN_ITEMS, 60%)` of them, `MIN_ITEMS` of them
showing more than their link, SHALL give an `item_block` row per item URL (`collect/items/align.py`); a field is read at
a place shared by a quorum of the blocks whose value its normalizer accepts: the item URL (the one document the block's
links lead to, not the page in another state, an image file or an item's own nested list; for a block linking to
several, else, at group level, the one document no other block links to at the place where a quorum of the blocks
link to such a document (a link's place: its tag path, positions aside, and its parent's rank among those of the block's
links at that path, so a title, an author and a "more" link in like elements are three places, the links of one
paragraph one), a place whose link holds an image
before the first other one: documents two or more blocks
link to, a vendor's, an author's or a category's page, are the template's), the name (an item link's
one-line content holding no typed value the block aligns, each such link at its own place, and, where that line runs
one element's words into the next with no white space (a title and a location set apart by layout alone), the link's
outermost parts no such join splits, each at its own place; a link showing its own line is named by it, never by the
name its attributes state; the block's heading, or the name the item's attributes state, `aria-labelledby`/`aria-label`/`title`
or an image's `alt`, kept where the block shows it over one or several whole lines in order, WCAG label in name (leading words the
block shows as lines of their own apart from the rest, a designer line above a size line, are no part of it), a line
cut by an ellipsis standing for the rest, its unshown leading or trailing words dropped when every block states the
same, and none where its shown run holds a price or other typed value the block shows (the whole card's text); a name
read from the item link's content runs on over the block's next whole lines while an image's `alt`, hidden ones
included, goes on with them; the item's links are those leading to its URL or, for a URL without a query, to it with
one; never a URL; text every block repeats is the template's, also a child element of the name every block shows alike;
a block the chosen rule leaves unnamed reads the one line at the tag path a quorum of its names have), the image, and typed value spotting for money, dates and check-digit identifiers (text in `s`/`del`
and the options a drop-down `select` does not show, those not selected (HTML §4.10.7), excluded, also from the lines of the elements holding it; an element's line is not read where two text nodes run digits
together, a token boundary the text does not show; an element holding others is also read in each of its own text
nodes; a block showing, beside its aligned value, another value of the field in the same currency at a place too few
blocks share is `ambiguous_in_block`, as nothing says which is the field's). Values are `dom` candidates with locators; of the segment step's first eight groups, the one aligning most
fields is first, and every other group that aligns follows, for the sections bind reads. A group one of whose blocks
stands for the page itself (a link marked `aria-current="page"`, or links to this very URL only) is the site's
navigation and gives no rows; so is a group that aligns no typed value and more than half of whose blocks lead to
documents a hyperlink of the site's chrome (as "Item groups" names it) outside the group leads to, or a block of another
group apart from it does (neither inside, around nor a sibling of one of its blocks: a record may span adjacent
siblings): the site's sections repeated in the content (a category carousel, a menu's tiles, the same links in a desktop
and a mobile copy), not the page's items. The listing shell rule (acquisition spec, "Structural outcome
classification") asks the same of a group, but the typed value, with one predicate (`content/segment.py`). An item's own list is a group
lying in one block of another group at one tag path in two or more of its blocks (one template renders every item's
list alike); the different lists a page's sections hold are no item's. Refs: owner #67.
#### Scenario: Cards with title, link and price
- **WHEN** a listing shows cards of varying tags and class tokens, each with a heading link and one price
- **THEN** each card is a row with its title, URL and price
#### Scenario: A name the attributes state
- **WHEN** each card has an empty item link with `aria-label="Details of Runner 1 Blue R1"`, shows `Runner 1` and
  `Blue` on two lines, and a size picker linking to the item
- **THEN** each card's name is `Runner 1 Blue R1`
#### Scenario: A whole-card label holding the price
- **WHEN** each card's link is labelled `New Coat 1 10.00 EUR In 3 colours` and the card shows `New`, an `h3` `Coat 1`
  and `10.00 EUR`
- **THEN** each card's name is `Coat 1`
#### Scenario: A name over the link and the line below
- **WHEN** a card's link shows `Clog 1`, the next lines show `Suede Leather` and `Taupe`, and a hidden image's `alt` is
  `Clog 1 Suede Leather - main view`
- **THEN** its name is `Clog 1 Suede Leather`
#### Scenario: A designer line above a size line
- **WHEN** a card shows `Alder`, `xs` and `Wool Coat 1` on three lines and its image's `alt` is `Alder Wool Coat 1`
- **THEN** its name is `Wool Coat 1`
#### Scenario: Helper text in the name link
- **WHEN** every card's name link holds `<span>View product</span>` before the item's name
- **THEN** the names leave `View product` out
#### Scenario: A title link labelled by its price
- **WHEN** each card's image link shows only `Item 1 of 7` to screen readers, and its title link shows `Kit 1` and has
  `aria-labelledby` pointing at a hidden element reading `Kit 1 $10.00`
- **THEN** each card's name is `Kit 1`
#### Scenario: Title and location run together
- **WHEN** each card's link holds `<span>Engineer 1</span><span>Berlin</span>`, set on two lines by a class
- **THEN** each card's name is `Engineer 1`
#### Scenario: Add-on prices in a drop-down
- **WHEN** a card shows `$20.00` and a one-row `select` of add-on plans whose unselected options read `$3.00` and `$5.00`
- **THEN** its price is `$20.00`
#### Scenario: A card with a second heading
- **WHEN** one card of a grid named by its `h3` adds an `h2` `Sold out`
- **THEN** that card is named by its `h3`
#### Scenario: Was and now prices
- **WHEN** a card shows a current price and a second price not struck through
- **THEN** its price is `ambiguous_in_block` and publishes nothing unless a stated row bound to it agrees with one
#### Scenario: A second amount off the price place
- **WHEN** most tiles show their price at one place, and two show a "worth" amount there and their price in a button
- **THEN** those two tiles' price is `ambiguous_in_block`; the others publish theirs
#### Scenario: A badge next to the price
- **WHEN** a card renders `<span>EUR 10.99</span><span>20</span>` with no space between them
- **THEN** its price is `10.99` EUR from the first span, never `10.9920`
#### Scenario: Cards linking an author and a shared vendor
- **WHEN** each card links its item from its image and its title, its own author, and a vendor page every card links
- **THEN** each card's item URL is its item's
#### Scenario: Hub listing the current page
- **WHEN** a group of category tiles holds one tile marked `aria-current="page"`
- **THEN** the group gives no rows
#### Scenario: Category tiles the menu links
- **WHEN** a listing's only group is four category tiles with an image and a name, three of whose categories the `nav`
  also links, and no tile shows a price
- **THEN** the listing has no rows (`no_rows: no_blocks`); the same tiles each showing a price are its rows
#### Scenario: The same tiles twice
- **WHEN** a listing's only groups are two copies, in two containers, of four category tiles with an image and a name,
  and no tile shows a price
- **THEN** the listing has no rows
#### Scenario: Sections holding different lists
- **WHEN** a page's sections each link to more and hold one list: three job cards in one, three salary cards in another
- **THEN** the job cards are rows

### Requirement: Stated rows and blocks (bind)
The stated rows SHALL be structured data's (`resolve/listing.py`), else the active config's, else the captured calls'.
The blocks are those of the group the stated rows name most and of every other section read with it: an aligned group
of its row shape (or holding every required field it aligns and a field beyond the item URL), inner groups first (a
department's jobs before the departments holding them), a group past the first eight only where its blocks lie at the
chosen group's tag path (one template renders both), whose blocks lead, a quorum of them, to
documents of the kind its blocks lead to (host, path depth, first segment), apart from blocks already read, fewer than
half of whose blocks lead to items the chosen group lists (else it is a featured or recently viewed copy) and not
starting after the chosen group's `rel=next` link (past the listing's end); an item two sections show is one block
(D-1776). Where one structured list is the page's `mainEntity`, only its entries are stated rows
(`resolve/listing.py`); else, with stated rows in several lists, the list or lists with the most rows bound to the chosen group's blocks, give rows; with
none bound, all do. Stated rows and those blocks bind one to one by item URL (`item_key`: session parameters, one trailing
slash and added query pairs aside) or by a name the block shows (`collect/items/bind.py`); a page-scoped adapter's
row also goes by the page's links its platform routes to the same item (`PageScoped.row_links`: a Shopify product under
the collection, adapters spec). With no stated rows or
only stubs, the blocks are the rows; otherwise stated rows stay and the group's blocks no stated row names extend them.
A config's rows bind no blocks. A bound entity's values join its row where the row has none for the field or equals
them; a block's link replaces a respelled stated item URL. Of a money field, a block bound by URL takes part whatever
the row's source (structured markup or a platform adapter's answer): its one visible amount that differs from the row's
joins as a rival, which the resolution spec's visible-price rule weighs (#334: it publishes, flagged `disagree`); a
block showing several amounts joins its option equal to the row's, else every option, so that the price is a `conflict`
(C7; a stated price that is one variant's beside a card's "from" price, a theme showing a tax-inclusive amount the
catalogue price excludes). State and call array rows bind by URL, and a JSON key whose
values equal a block field on `MIN_ITEMS` bound rows is that field's key for every bound row (`collect/induce.py`).
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
([learning-configs](../learning-configs/spec.md), "Locate run"). Refs: §8.1, §8.6, Appendix A #59, D-1603, architecture
v3 a.6.
#### Scenario: Complete rows of a call
- **WHEN** the rows of a call publish every required field
- **THEN** role C is not asked

### Requirement: Rows from page state
On a listing where no structured data, config, call or block gives rows, an array of `MIN_ITEMS` or more objects in the
page's state JSON SHALL give rows (`collect/items/state_rows.py`): each row field read at the path induced across the
rows whose own member names the field (its name or schema.org property) and whose value normalizes and is shown in the
page text (an image: normalizes), the item URL also at a path whose values the rendered hyperlinks of the page's content
lead to (its main landmark, else its body, outside chrome); a row is kept only when its item URL is such a link or its
name is shown, an array with fewer such rows gives none, as does, with the arrays inside it, one that reads no typed
value and more than half of whose rows' items are documents the site's chrome links to (the site's menu tree, whatever
copy of the menu outside the chrome shows them too), and an item
read once is not read again (after the choice below); of several arrays read, only the one or ones with the most rows whose item URL the page's
first item group links to give rows (all, when none does). Values are `js_state` candidates (bucket `state`). A locate run writes such rows into the
config as paths (`config_ir/json_rows.py`): a `jsonpath` row step selecting the array that holds `MIN_ITEMS` or more of
the rendered rows' item URLs in a document the HTML carries (embedded state, JSON-LD, JSON attributes, RSC rows), and
for each row field the path relative to the item that more than half of the paired items hold
([learning-configs](../learning-configs/spec.md), "Locate run"). Refs: D-1773, D-1775,
architecture v3 a.6.
#### Scenario: Items only in state
- **WHEN** a script's JSON lists three items whose names and prices the page shows without item links
- **THEN** the listing has three rows with state evidence, and none when the page shows none of them
#### Scenario: State menu tree
- **WHEN** a script's JSON holds the site's menu entries, whose links the page renders only under `role="menubar"`
- **THEN** those links ground no row; nor do the entries' names when a footer outside the chrome repeats the links, and
  the entries' submenu arrays give no rows either

### Requirement: Row item URL
A row's item URL field SHALL read schema.org `url`, else the item's `offers.url`, else its `mainEntityOfPage` (a URL or
a page's `url`), else its own IRI (JSON-LD `@id`, microdata `itemid`) when absolute http(s), without a fragment, on the
page's site and not the page's URL, a bound block's link replacing a respelling; row keys drop each query parameter that two or
more row URLs carry once with one value and none of the page's own URLs carries (`normalize.url_key`), named in the
result, while each row URL publishes as the page writes it (normalization spec). A row url field is the item URL field
(`collect/schema_org_map.py` `is_item_url`) when any
alternative of its path is the row type's own `url` (`Product.url|Offer.url` is one): one predicate for alignment,
binding, the row key of a listing's records (the first item URL a row publishes, else its position on the page) and
the recurring listing diff. Two URLs name one document by `normalize/url_key.py` `document_key` (the canonical form's
scheme, authority and path, one trailing slash of the path aside: RFC 3986 §6.2.4, `/a//` is another path) and one
item by `item_key` (that and the query's decoded pairs as a multiset, in any order); the keys compare URLs and are never
published.
Refs: owner #67 decisions 1 and 6, D-1785.
#### Scenario: Item named by its offer
- **WHEN** a listed Product states no `url` and its Offer states `url`
- **THEN** the row's item URL is the Offer's
#### Scenario: Item named by its IRI
- **WHEN** a listed Product states no `url`, Offer URL or main entity page, and its `@id` is `https://example.com/p/7`
  on a page of `example.com`
- **THEN** the row's item URL is `https://example.com/p/7`; an `@id` ending in `#product` names none
#### Scenario: Visit parameter on every row
- **WHEN** every row URL carries `sid=abc` and its own `v=<n>`, and the page URL carries neither
- **THEN** the rows are keyed by their URLs with `v=<n>` and without `sid`, and publish them as written
#### Scenario: Item URL among alternatives
- **WHEN** a listing schema's row field `url` maps `Product.url|Offer.url` and the rows publish it
- **THEN** each record is keyed by its row's URL, not its position, in the run and in the recurring listing diff
#### Scenario: One trailing slash
- **WHEN** a stated row names `https://example.com/p/7/?b=2&a=1` and a block links to `https://example.com/p/7?a=1&b=2`
- **THEN** they name one item and bind, and the row publishes the URL as written; `https://example.com/p/7//` names
  another

### Requirement: Role C rows
Role C SHALL be asked for the blocks whose bound rows lack a row field, each for the fields its row lacks but the item
URL, when a row field is published on no row or a row lacks a required one, and never beside a config that runs a row
field; and in a separate call over the whole cleaned text for the missing page fields when a required one is missing.
Its values fill the blocks' rows; it makes no row, so a listing without rows answers `no_rows: no_blocks`.
A block of a nested listing is read with its enclosing item's context (`collect/items/lines.py`): when the block lies
inside a block of another repeated group, and two or more blocks of that group hold rows, the enclosing block's text
before the first block of the inner group (what a building states for its units: its name, its address, column
headings) comes with the block, as the block's own text does not show it.
Refs: §8.6, owner #67,
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
