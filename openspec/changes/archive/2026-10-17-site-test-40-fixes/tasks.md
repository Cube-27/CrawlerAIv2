# Tasks: site-test-40-fixes

## 1. Triage
- [x] 1.1 Triage every failure class of the site test in `design.md`: generic fix, by design (with its basis), or
  `needs-owner`. (#240)

## 2. Money
- [x] 2.1 A structured `price` written as display text is read under its `priceCurrency`; a sign that denotes
  another currency declines (property tests). (#240)

## 3. Listing row URLs
- [x] 3.1 Block text as the cleaned text shows it: ellipsis cuts completed by `title`, non-rendered elements dropped. (#240)
- [x] 3.2 Rows matched with all their grounded values; a whole element text picks one block among several. (#240)
- [x] 3.3 A block linking to several documents gives the one its row-labelled hyperlinks lead to, else none. (#240)
- [x] 3.4 Rows are looked for in every repeated item group; the group holding most rows wins. (#240)
- [x] 3.5 Replay the site test's listing captures (outside the repo) and record the row URL counts. (#240)

## 4. Escalation
- [x] 4.1 Log the `needs-owner` decision for class A (no browser retry for a listing without rows at HTTP). (#240)
