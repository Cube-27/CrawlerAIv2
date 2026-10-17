# Design: listing-paging

## Data shape

- `crawl.paging._View.ids`: the linked items' identities, else the digests of the rows of the first call series of
  `Tab.calls()` (the page's latest data responses); `_Held` restores the run's kept-state record when a state kept
  ahead of an action is dropped (`Tab.discard`).
- `resolve.call_rows.with_call_rows(graph, schema, rows, call_rows, candidates, page, base_url)`: the listing's rows
  with the call rows that extend them, and the candidates joined call rows give the structured rows. Identity keys:
  `("url", canonical item URL)` and `(identifier field, value)`.
- `config_ir.api_recipe.binding.withhold_tokens(samples) -> (samples, withheld names)`; `model.token_like`.
- `worker.handlers.steps.FetchedPage.further`: a listing recipe's pages after the first; `scrape_steps.Further`,
  `extract_further`, `store_further` shared by the scrape service and the worker.
