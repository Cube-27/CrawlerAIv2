---
name: snowcrawl-orchestrator
description: Run the Snowcrawl v2 build as orchestrator - start and brief builder agents in herdr tabs (max two), watch them, run the merge queue, verify and merge PRs, run the e2e phases. Use when the owner says to continue, resume or orchestrate the build, or types /snowcrawl-orchestrator.
disable-model-invocation: true
---

# Snowcrawl v2 orchestrator

1. Read `docs/agents/orchestrator.md` in full and follow it. It overrides your defaults.
2. Read the owner's current plan (outside the repo) and skim `docs/agents/builder-protocol.md` (what builders are
   told, so your briefs never contradict it).
3. Check you are inside herdr: `test "${HERDR_ENV:-}" = 1`. If not, tell the owner to start `herdr` and run
   `claude --permission-mode auto` inside it, then stop.
4. Rebuild state from GitHub and herdr ("Starting on a machine", step 2), report it to the owner in a few lines (open
   PRs, running builders, what's next), then continue the queue.
