## MODIFIED Requirements

### Requirement: Greenhouse and Lever adapters
They SHALL detect only the hosts and URL forms their public Job Board / Postings API docs name and map `JobPosting`
fields as in `adapters/greenhouse.py` and `adapters/lever.py`; filtered Lever lists, apply pages and undocumented
regional hosts fall through to the page rungs. A job read for a hosted Greenhouse board page SHALL have the board's job
route on the page's host as its URL; one read for an embedded board keeps the API's `absolute_url`. Refs: D-0267,
D-0307, D-0310, D-1483.
(Previously: every Greenhouse job's URL was its `absolute_url`.)
