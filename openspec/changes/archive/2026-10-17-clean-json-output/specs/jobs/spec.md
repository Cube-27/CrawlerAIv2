## MODIFIED Requirements

### Requirement: Job endpoints
`GET /v1/jobs` SHALL page all jobs newest first; `/v1/jobs/{id}` returns the summary, `/request` the validated request,
`DELETE` cancels queued tasks (a finished job is 409); `/results` serves records, page outputs, `json_values` and
exports in the pinned schema's columns, values unchanged (INV-27). A `json_values` clean record holds only published
fields, a money value flat as its amount and a `currency` (beside `price`) or `<field>_currency` code, the first key
that names no schema field, else whole (D-1210).
`csv_safe=true` prefixes `'` to cells starting with `=`, `+`, `-`, `@`, tab or CR. Refs: §12.2, §13.1, Appendix A #40,
#51, D-0577, D-0700, D-0745, D-0813, D-0816, D-1210.
