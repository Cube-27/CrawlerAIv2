## MODIFIED Requirements

### Requirement: Context is page and request evidence only
`Context` (`normalize/base.py`) SHALL hold only evidence from the page and the request; `None` means no evidence,
never a default. Its `hreflang` holds the languages of the alternate links to the page itself (its final URL or
canonical link, HTML §4.6.7.1, RFC 6596; `content/context.py`). (Previously: every alternate link's `hreflang`.)
Refs: §9, D-0256, D-0773, D-1482.
#### Scenario: No context
- **WHEN** a context carries only `captured_at`
- **THEN** no normalizer supplies a locale, currency or country of its own
#### Scenario: Alternates in other territories
- **WHEN** a page tagged `en-US` has alternate links to other pages tagged `en-AU` and `en-CA`
- **THEN** `$10` on it normalizes to USD
