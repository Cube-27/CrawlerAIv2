# Plan phase 3c: fragments of a text value do not outrank the whole, and image renditions share a key

## Why

On the golden set's detail pages, a description is often published from a fragment: an Open Graph summary or a
JSON-LD text cut at a length limit ranks before the full text another kind states, and a decorated title
("Title | Brand") ranks before the clean one. Image URLs that differ only in a stated size are counted as different
files.

## What Changes

- **Fragments**: before source precedence ranks kinds, a `long_text` candidate that is a prefix (or an ellipsis-cut
  prefix) of a longer candidate, or an Open Graph description with a longer description of another kind, ranks
  nowhere; a `text` candidate that is another kind's value plus ` - ` or ` | ` and more text ranks nowhere.
  Superseded candidates stay kept and may agree.
- **Image resource key**: the key also ignores a stated size in the path, a format-conversion extension and a
  trailing `=<options>`.

## Impact

`resolve/supersede.py` (new), `resolve/preference.py`, `normalize/url.py`; capability `resolution`.
