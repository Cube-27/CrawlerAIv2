## MODIFIED Requirements

### Requirement: Embedded JSON state and XHR admission
The system SHALL admit a scalar from `<script>` JSON, JS assignments or captured XHR bodies only when it equals another
kind's candidate (`independent=false`, owned by that candidate's entity), or when the field has none, the value is
visible and its type is checkable (`collect/admission.py`); text-like types admit by equality only. A value admitted by
visibility inside an array row (an object item of an array holding two or more objects, or an array's only object when
its own scope writes a URL that names a document, not a media file) is owned by that row's `array_row` entity, whose
`urls` are the URLs in its scope up to nested rows; elsewhere it is owned by `page`. Each field, normalized value and
owner is one candidate, the one with the shortest locator. (Previously: a lone object was never a row, and every repeat
was a candidate.) Refs: §8.1, Appendix A #34, #55, D-0418, D-0943, D-1250–D-1252, D-1254, D-1343, D-1345.
#### Scenario: Visible text in state
- **WHEN** a visible state string is the only candidate for a `text` field
- **THEN** it is not admitted
#### Scenario: Price in a row of state
- **WHEN** a visible state price is the only candidate for a `money` field and sits in the second object of an array
  of two objects
- **THEN** it is owned by that object's `array_row` entity, not by `page`
#### Scenario: Related item alone in its array
- **WHEN** an array's only object writes another page's URL and a visible price
- **THEN** the price is owned by that object's `array_row` entity and is not the detail target's
