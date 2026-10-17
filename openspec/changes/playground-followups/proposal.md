# Playground follow-ups

## Why
Four playground follow-ups from `openspec/backlog.md` (#206, #214, #218): Extract's toolbar Schema and its "Schema
source" option overlap, and a missing schema opens Options to say so; a map's URLs are lost on back navigation; at phone
width the primary button moves between modes because the toolbar wraps differently; and records of listing pages are
still refused in the UI although the API serves them since #206.

## What Changes
- Extract: one toolbar Schema holds the source: a stored schema, Inline JSON, From a prompt or From field names; the
  Options panel keeps only the source's JSON, prompt or names. A missing schema is reported at the toolbar's Schema,
  without opening Options (D-1214).
- Map: a map's request and URLs are kept in its browser history entry, so back, forward and reload show them again; the
  server stays unpersisted (jobs spec "Map, scope and sitemaps") (D-1215).
- Command bar: at phone width the action row (Get code, primary button) comes first under the input, so it sits at the
  same place in every single-URL mode (D-1216).
- Records of listing pages are asked for like detail ones in every mode; the "not available yet" refusal is removed
  (D-1217).

## Impact
- Capability: frontend (`frontend/src/screens/playground/`). No API, database or backend change.
