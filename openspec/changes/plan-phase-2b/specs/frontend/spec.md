## MODIFIED Requirements

### Requirement: A listing's page fields and why it has no rows
The scrape output SHALL show the answer's `page` fields (a listing that kept no record) as a Page fields table under
the records in Table and as `page` beside `data` in JSON, and the `no_rows: not_asked` reason as a sentence with the
server's reason as its tooltip (`screens/playground/output/`). (Previously: each `no_rows: <cause>` had a sentence.)
Refs: D-1475, D-1476, D-1515, D-1605.
#### Scenario: Next page of an empty listing
- **WHEN** a scrape answers `records: []`, `page.next_page_url` and reason `no_rows: not_asked`
- **THEN** Table shows `next_page_url` under Page fields, JSON holds `"page"`, and the header says the row reader was
  not asked
