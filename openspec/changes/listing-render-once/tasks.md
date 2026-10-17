# Tasks

## 1. Owner decision

- [ ] 1.1 Append owner decision #54 to `design/owner-decisions.md`; fill D-1245's owner answer, remove it from
      "Open owner items" and mark `OPEN_QUESTIONS.md` row 33 answered.

## 2. Render check for listings

- [ ] 2.1 Generalize the owner #49 check: a listing schema's HTTP `ok` capture whose extraction gives no rows is
      rendered once in `auto`, and the render is kept only when its extraction gives rows; the check keeps each
      extraction so the kept capture is not extracted (or role C asked) again; scrape, batch and crawl use it.
- [ ] 2.2 Tests on synthetic listings: a client-template listing whose HTTP body holds other repeated links is
      rendered and keeps the render's rows; a listing with rows at HTTP is not rendered; method `http` never renders;
      a render with no more rows than HTTP is not kept.

## 3. Archive

- [ ] 3.1 Apply the delta to `openspec/specs/` and archive this change.
