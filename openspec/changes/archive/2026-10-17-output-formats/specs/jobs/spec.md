# Delta: jobs

## ADDED Requirements

### Requirement: Exports and llms.txt of a job
A job's records SHALL export as `jsonl`, `xlsx` and `parquet` from the columns of `csv_records`, with `csv_safe`
applying to every spreadsheet cell; `llms.txt` of a crawl, batch or map job SHALL be an H1 title, a blockquote summary
and sections of links with descriptions, and `llms-full.txt` the pages' markdown under the same opening. `map` takes
`llms_txt` to answer the file of the URLs it found. Refs: D-1426, D-1427.
#### Scenario: Job without records
- **WHEN** a job without a schema is exported as `xlsx`
- **THEN** it is refused with 409
