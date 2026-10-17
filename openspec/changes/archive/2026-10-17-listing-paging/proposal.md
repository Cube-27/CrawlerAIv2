# Listing paging: grown lists, call rows beside structured rows, recipe pages in jobs

## Why

Follow-ups of #241, #250 and #254 (`openspec/backlog.md`): a load-more or scroll listing whose rows come from a JSON-LD
`ItemList` kept its first batch; an integer inside a path segment (`page-2.html`) did not number pages; a virtualised
list lost the items it recycled between kept states; the paging driver stopped `no_items` on a scroll listing whose
items hold no link although its calls loaded more; structured rows could not take a field their page's call carries
per item; the worker's batch and crawl tasks served a listing recipe's first page only; and binding stored a constant
token-like query value (an API key) in a recipe.

## What Changes

- Rows of a grown document: top-level primary entities no list holds join the listed rows (microdata the grown list
  states); call rows join the structured row of their item and fill its missing fields; call rows of items the
  listing's own block group shows extend the rows; a url row path is proved by the listing blocks' links.
- An integer inside a path segment or query value numbers pages for the +1 link rule.
- The paging driver keeps a state ahead of each growing action and drops it when the next state still shows all of
  it; it counts the rows of the page's calls when the page shows no linked items.
- The worker's batch and crawl tasks serve every page of a listing recipe, up to the job's page bound.
- Binding binds a constant token-like query value from the page when the page states it, and otherwise leaves it out
  of the stored recipe; the replay shows whether the endpoint needs it.

## Impact

Capabilities: extraction (cold listing rows and pagination, listing rows from captured calls), acquisition (listing
browser actions), adapters (recipe binding, recipe politeness and pagination). Code: `resolve/listing.py`,
`resolve/call_rows.py`, `resolve/pagination.py`, `collect/xhr.py`, `collect/item_links.py`, `crawl/paging.py`,
`acquire/browser_tab.py`, `config_ir/api_recipe/{binding,model,headers,learn,execute}.py`,
`worker/handlers/{steps,scrape,crawl}.py`, `services/{scrape,scrape_steps}.py`. No API, schema or database change.
