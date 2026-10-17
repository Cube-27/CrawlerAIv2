## MODIFIED Requirements

### Requirement: identifier, text and url
`normalize/identifier.py` SHALL check GTIN and ISBN check digits and publish the identifier as a string, the scheme being
the field's (D-1209); `text.py` cleans text and declines templates; `url.py` parses per WHATWG, absolutizes,
canonicalizes and declines non-http(s) or hostless URLs, never repairing. Refs: §9, D-0287–D-0290, D-0257–D-0263, D-1022, D-1209.
