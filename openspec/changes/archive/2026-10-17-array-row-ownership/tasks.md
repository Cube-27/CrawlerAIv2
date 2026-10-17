# Tasks

## 1. Rows in state

- [x] 1.1 `collect/admission.py`: find the rows of each state document (object items of an array of two or more
      objects, nested rows under their enclosing row); a value admitted by visibility alone inside a row is owned by
      that row's `array_row` entity, which `Admitted` and `collect_page` carry, with the URLs of its scope. (#243)
- [x] 1.2 Tests: a visible price in a row of a related-item array is owned by its row; one object in an array is not a
      row; equality admission keeps its anchor's owner; a row's URLs stop at nested rows. (#243)

## 2. Row ownership

- [x] 2.1 `resolve/ownership.py`: `EntityGraph` knows the page URLs; an `array_row` owner is the target's only with
      page values and when it and every enclosing row names a page URL or the target's URL (`names_any`, shared with
      intent). (#243)
- [x] 2.2 Pipeline tests on synthetic pages: a related-item price in state does not publish as (or conflict with) the
      target's; a row naming the page is kept as the target's; JSON-LD and microdata related items, an `ItemList` on a detail page
      and another product's Offers do not leak. (#243)

## 3. Archive

- [x] 3.1 Owner decision #55; apply the deltas to `openspec/specs/` and archive this change; next current focus in
      the backlog. (#243)