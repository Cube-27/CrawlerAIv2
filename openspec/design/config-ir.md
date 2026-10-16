# Config IR and exporters

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 12. Config IR and exporters

### 12.1 IR

Everything learned about a site is one portable, versioned, executable IR. The engine runs it, and exporters
translate it, so what we export is what we run.

```jsonc
{
  "ir_version": "1",
  "site": "example.com", "schema": {"name": "commerce_detail"}, "page_kind": "detail",
  "fetch": { "method": "http" },
  "fields": {
    "title": { "steps": [ {"jsonld": "$.name", "when_type": "Product"},
                          {"xpath": "normalize-space(//h1[@data-testid='pdp-title'])"} ],
               "status": "corroborated" },
    "price": { "steps": [ {"xpath": "normalize-space(//*[@class='price-current'])", "post": [{"money": {}}]} ],
               "status": "uncorroborated" }
  },
  "listing": { "row": {"xpath": "//ul[@class='grid']/li"}, "fields": {}, "next": {"xpath": "//a[@rel='next']/@href"} },
  "api_recipe": { "method": "GET", "url": "https://example.com/api/products/{slug}",
                  "params_from_url": {"slug": "regex:/p/([^/]+)"}, "map": {"title": "$.data.name"} },
  "provenance": { "origin": "llm_synth", "validated_on": ["<capture ids>"] }
}
```

- **Steps:** `xpath` (XPath 1.0 only, so PHP `DOMXPath` and `lxml` agree), `css` (compiled to XPath), `jsonld`,
  `jsonpath`, `regex`, `attr`.
- **Post-processing:** type normalizers, `trim`, `regex_replace`, `absolutize_url`.
- In config-only execution, the first valid step wins.
- Site-specific strings are allowed here because the IR is per-site data (C3).

### 12.2 Exporters

- `json`: the IR itself.
- `platform_draft`: XPath 1.0 + regex + named params per field, listing row/next, and `api_recipe` as a PHP code
  hint. This is a draft for an external crawler platform, revised once a sample of its config format exists
  (OPEN_QUESTIONS #1).
- `json_records`, `csv_records`, `markdown`. A `csv_safe` request prefixes `'` to CSV cells a spreadsheet would read
  as a formula (OWASP CSV Injection); the UI's downloads ask for it, and the default export is unchanged (D-0879).
- `json_values`: one item per task, `{url, outcome, records, metadata?}`, where each record holds the schema's
  published fields only (null when not published), with page `metadata` on request; no status columns; jobs with and
  without a schema (SPEC-14).

### 12.3 Release check

A separate minimal executor (lxml XPath 1.0 + regex + JSONPath, no engine logic) runs the exported config on the
held-out pages. A field passes when it reproduces the engine's published values on every held-out page while there
are fewer than 10, and on ≥ 95% from 10 on. Otherwise it is marked `manual` in the export. This proves the export
matches the engine. Correctness is measured in §16, per field status.
