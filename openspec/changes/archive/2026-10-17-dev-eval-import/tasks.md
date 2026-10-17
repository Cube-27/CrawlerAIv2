# Tasks

## 1. Import

- [x] 1.1 `crawlerai eval import-labels`: generic label file, dev only, drafts only, fetched through the worker's
      acquisition path, values normalized in the captured page's context, declines reported, re-runs skip pages
      already in dev. (#264)

## 2. Dev report on drafts

- [x] 2.1 `crawlerai eval run`: replay and score dev; store checked-only runs; `--labels all` scores drafts too. (#264)
- [x] 2.2 Metrics: long_text by word overlap, per page kind cells, disagreement counts, engine reasons, LLM calls
      without a reply; `--llm unanswered|live` and `--llm-max-calls`. (#264)
- [x] 2.3 Apply the delta to `openspec/specs/evaluation/spec.md` and archive this change. (#264)
