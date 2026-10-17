# Design: caller request context and page actions

## Shape

- Request side: `services.scrape_steps.FetchOptions` (the `fetch` member every page request shares) gains `headers`,
  `cookies` (secret values, `SecretStr`), `wait_for`, `actions` and `cache`. One vocabulary of steps,
  `config_ir/page_actions.py`, validates what the caller writes: a target is a CSS selector (translated to XPath 1.0
  as an IR `css` step is), an XPath 1.0 expression or visible text.
- Fetch side: `acquire.types.FetchPolicy` carries `context: RequestContext | None` (serialized with every value
  redacted) and `steps: tuple[PageStep, ...]` (XPath targets only). `acquire/page_steps.py` runs the steps on the
  rendered page; the browser rung calls it between the settle and the read, and records `StepOutcome`s on its attempt.
- The listing paging driver (owner #52) keeps its own structural controls: it is not caller-written, and its steps are
  chosen from the page's item group, not named by the caller.

## Decisions
