# DOM description: the page's description block is a long_text candidate

## Why

On the golden set's detail pages, `long_text` (description) precision is 69%. The wrong values are an Open Graph
summary, or structured text cut short, where the full description exists only as a block of the page's main content
that no collector reads. Resolution already lets a longer candidate of which a shorter one is a prefix, and an
Open Graph description yielding to a longer one, win (`resolve/supersede.py`, #284); there is no DOM candidate to prefer.

## What Changes

- A generic DOM description collector reads, on detail pages, the main-content prose block that states a `long_text`
  field in full: the block extending a candidate other collectors proposed for the field, else the section a heading
  or ARIA label names with the field's schema words, else, for a `description` field only an Open Graph summary (or
  nothing) states, the page's main text. Reviews, related items, chrome, dialogs and link runs are left out.
- Its candidate is `dom`, independent, in the `dom` evidence bucket (`agreed` when a structured value equals it).

## Impact

`collect/dom_text.py` (new), `collect/run.py`, `collect/dom.py` (helpers made public); capability `extraction`.
