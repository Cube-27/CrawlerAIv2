## Why
Five resolution follow-ups of merged PRs (#196, #207, #209, #225) leave a class of pages without a value or a row:
one item stated by two collectors stays two entities (D-0942), a listing item in two syntaxes keeps one syntax's row,
renditions of one image across merged blocks decline (D-0944), a standalone variant Product beside its ProductGroup
gets none of the group's rows or common values (D-0966), and an `ItemList` of `ListItem`s with only `name`/`url`
gives no rows. Owner request 2026-10-17: close the backlog.

## What Changes
- Identity: the entity graph merges the entities of one item, from every collector, with one union-find
  (`resolve/identity.py`); the JSON-LD collector only states each node's identity. Every agreeing pair joins.
- Listings: an item stated in JSON-LD and microdata is one row with both syntaxes' values.
- Renditions: a list of images keys as the set of files it names; an `https` rendition publishes over its `http`
  twin; renditions another kind states count as agreeing.
- Variants: a standalone Product naming a group's `productGroupID` (`inProductGroupWithID`), or stating a group
  member's identifier or URL, is that group's variant.
- Listings: a `ListItem` without `item` stands for the thing it lists on a listing's row fields; such entries are the
  rows when nothing else gives rows, a `BreadcrumbList`'s excepted.

## Impact
`collect/{base,schema_org_map,jsonld,microdata}.py`, `resolve/{identity,ownership,intent,listing,rows,pipeline,
preference}.py`, `normalize/dispatch.py`. No API, schema or data change. Specs: resolution, extraction, variants.
