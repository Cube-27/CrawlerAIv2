## Decisions

### D-1290 — Identity merge in the entity graph, every agreeing pair joins
- Date: 2026-10-17 · Change/PR: resolve-followups · Status: decided (owner-delegated 2026-10-17)
- Decision: collectors state each entity's identity (`@id`/`itemid` unless blank, identifier-property scalars, a group's `productGroupID`) and its own item URLs; `resolve/identity.py` merges, before intent, entities of one most specific type that are roots, items only lists hold, or `hasVariant` members of such a group, when they share an IRI (always), an identifier value (unless their item URLs other than the page's name different items; with page URLs only, the full sets decide) or an item URL (D-1291). Each key joins every pair of its entities, so two later agreeing nodes join even when the first stays apart. Two group members never join; an entity never joins its ancestor. The head is the group member, else the first in collector order; it takes the members' URLs, identity and children, and their candidates (`EntityGraph.adopt`); lists are never merged.
- Alternatives: keep the merge in the JSON-LD collector (no cross-collector merge); anchor each key at its first node (the D-0942 defect).
- Why: one item in JSON-LD and microdata, or microdata `itemid` duplicates, left two entities and an ambiguous or split page.
- Reversible: yes

### D-1291 — One item URL joins two collectors' entities, or a group member and a standalone product
- Date: 2026-10-17 · Change/PR: resolve-followups · Status: decided (owner-delegated 2026-10-17)
- Decision: an item URL (schema.org `url`, the IRI, `mainEntityOfPage`) that is not a page URL joins entities of two collectors, or a `hasVariant` member and a standalone Product; one collector's entities sharing only a URL stay apart. This replaces `listing._one_per_item`, which dropped the second syntax's row: the merged row resolves with both syntaxes' values, and agreeing values count as `agreed`.
- Alternatives: keep dropping the second row (#196: loses its values and the agreement).
- Reversible: yes

### D-1292 — Rendition rule for image values
- Date: 2026-10-17 · Change/PR: resolve-followups · Status: decided (owner-delegated 2026-10-17)
- Decision: a list of image_url values keys as the set of its files (`resource_key`: authority and path, RFC 3986 §3.2-§3.3; JSON-LD 1.1 §4.3.1 arrays are sets), so two renditions of one file in a list count once; of renditions of one file, the first whose URLs are all `https` publishes (RFC 9110 §4.2.2); a rendition another kind states counts as agreeing with the published value (evidence).
- Alternatives: rank renditions by size parameters (no standard, C4); keep the multiset (two merged blocks decline).
- Reversible: yes

### D-1293 — A standalone variant Product relates to its ProductGroup by schema.org properties only
- Date: 2026-10-17 · Change/PR: resolve-followups · Status: decided (owner-delegated 2026-10-17)
- Decision: a root Product (not a ProductGroup) whose `inProductGroupWithID` equals the `productGroupID` of exactly one standalone ProductGroup becomes its `hasVariant` member; a standalone Product sharing an identifier value or an item URL with a group member is that member (D-1290). The group is then the target; its variants are rows and its own properties (color, gender, material) publish at top level (INV-38). `variesBy` names properties, not products, and an sku prefix is no schema.org relation (C4, C7): neither relates. `isVariantOf` stays as it is (SPEC-13 §9, follow-up).
- Alternatives: sku prefixes; a URL path match; the group's `variesBy` values.
- Reversible: yes

### D-1294 — A ListItem without `item` stands for the thing it lists on a listing's row fields
- Date: 2026-10-17 · Change/PR: resolve-followups · Status: decided (owner-delegated 2026-10-17)
- Decision: on a listing schema, a row field's paths also read a `ListItem` that states no `item` (schema.org: `item` "An entity represented by an entry in a list", range Thing; a ListItem has a Thing's `name` and `url`), whatever the path's root type. Such entries are the rows only when no listed primary entity and no top-level rows exist, and only those holding a row-field candidate, never a `BreadcrumbList`'s ("a chain of linked Web pages" to the current page).
- Alternatives: leave the entries unread (#225: 2 listings without rows); read a ListItem whose `item` is a URL text (breadcrumbs mostly).
- Reversible: yes
