## ADDED Requirements

### Requirement: Listing rows from captured calls
On a listing the `xhr` collector SHALL read rows from the calls of one method, origin and path, body shape and row query
(`collect/network_match.py`: only query or body values vary; an array of `MIN_ITEMS` or more object items each holding a
visible string of its own; a request sent again counts once), the first such series in which a row field's path,
relative to a row, is admitted by the state admission rule in `MIN_ITEMS` rows or more; that path is read in every row
through the API recipe row reader (`collect/api.py`), each row an `array_row` entity; where the site's active config has
a listing recipe, the calls of its endpoint and row query are read with the recipe's map instead, text fields included
(`network_match.LearnedCalls`). Resolution takes these rows only where structured data and the config give none; when
they leave a record incomplete role C is asked, and its rows, if any, replace them. Refs: §8.1, §8.6, Appendix A #59,
D-1313, D-1314, D-1315, D-1367.
#### Scenario: Rows a call proves
- **WHEN** a listing with no structured rows loaded four items whose prices it shows for three
- **THEN** the call gives four rows, each with its price, and no title (text admits by equality only)
#### Scenario: Learned map
- **WHEN** a browser capture of a listing whose recipe maps `title` holds a call of the recipe's endpoint
- **THEN** its rows carry the titles, which equality alone would not admit
#### Scenario: Complete rows of a call
- **WHEN** the rows of a call publish every required field
- **THEN** role C is not asked
