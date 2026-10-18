# Change: accuracy round 1 from the draft dev baseline

## Why

The draft dev baseline (#264, backlog "Draft dev baseline") shows structural failure classes that are not site bugs:
listing precision counts rows of pages no label holds, a hosted job board's rows carry a URL form the board's pages do
not use, structured text written as escaped HTML is published as markup, and scoring calls renditions of one image
file, or a place a label states only as text, different values. Each is fixed in the layer whose rule failed, for the
whole class; the classes the contract keeps declined are investigated and logged.

## What Changes

- Eval: `eval run` scores the engine rows of the labeled page (as many as the label has rows) and writes the report
  over every row beside it; image_url scores renditions of one file as one image; a place labeled by text only
  scores an output whose text agrees, whatever parts it parsed.
- Greenhouse: a hosted board page names each job by the board's job route on its own host; an integer member can be
  a prefixed property's value.
- Structured-data text whose markup is written escaped reads as the fragment's rendered text.
- Investigated and kept declined (decisions): listing prices of shops with several presentment currencies (D-1114),
  money without a stated currency or with a sign several currencies share (D-0301, D-0302), stated apply links outside
  `JobPosting.url`.

## Impact

- Capabilities: [evaluation](../../specs/evaluation/spec.md), [extraction](../../specs/extraction/spec.md),
  [adapters](../../specs/adapters/spec.md).
- Code: `backend/src/crawlerai/eval/` (`metrics.py`, new `scoring.py`), `backend/src/crawlerai/cli.py`,
  `backend/src/crawlerai/adapters/` (`base.py`, `greenhouse.py`), `backend/src/crawlerai/collect/` (`adapter.py`,
  `schema_org_map.py`).
- No labels or captures change; the dev set stays outside the repo.
