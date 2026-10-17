# Delta: frontend

## MODIFIED Requirements

### Requirement: Playground modes and command bar
The playground SHALL serve Scrape `/`, Batch `/batch`, Crawl `/crawl`, Map `/map`, Extract `/extract` and Search
`/search` behind a link-tab mode switch without visible group captions, with one centred command bar (input row, then Options, Format, Schema, Get code and the primary button) that does not move between the single-URL modes at desktop width, and at phone width puts Get code and the primary button on the row under the input; Batch's URL box shows ten lines and scrolls inside (`frontend/src/screens/playground/`). Search takes a query, shows Format and Schema only with Scrape results on, lists its results on the page and links to the batch run; Crawl's options include Strategy, Query, Include subdomains and Follow external links (the query is sent only for Best first). (Previously: five modes, no Search.) Refs: Appendix A #38, #45, #51, #61, D-0817, D-1043, D-1213, D-1216, D-1447.
#### Scenario: Back and forward
- **WHEN** a user switches from Scrape to Crawl and presses back
- **THEN** the URL returns to `/` and Scrape mode shows
