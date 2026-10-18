# Evaluation delta

## ADDED Requirements

### Requirement: Row matching
Listing label rows SHALL match engine rows one to one by canonical URL after dropping the page's session parameters
the engine reports (the extraction spec's function), then by URL path with equal text fields, then, for a label row
without a URL, by equal text fields alone.
#### Scenario: Label URL without the visit's query
- **WHEN** the engine dropped `sid` from its rows and a label row's URL still carries it
- **THEN** that label row matches the engine row of the same item

### Requirement: Label re-keying
`crawlerai eval re-key <file> --split dev` SHALL recompute each draft-labeled golden page's labels from the label file
against its stored capture and mark a label row `stale` when the capture shows neither its text fields nor its URL
path; checked and labeled pages are left as they are. A stale label row that no engine row matches is counted in
`label_stale`, never as FN.

### Requirement: Presence, disagreement kinds and cost
The report SHALL count per field type the labeled values the capture shows (`presence`, the coverage ceiling), split
FN into `declined:<reason>`, `absent`, `unread` and FP into `wrong_value`, `on_absent`, `extra_row:on_page`,
`extra_row:not_on_page`, and report LLM tokens and USD per correct field (`cost`).
