# User requirements and evidence base (Appendices B, C)

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## Appendix B. User requirements

- **Config users** set up crawls in an existing crawler platform written in PHP. They need:
  - XPath 1.0 strings, regex and named parameters per field;
  - listing row and next-page selectors;
  - for API-backed sites, a request recipe plus a code hint.

  Configs must be validated by execution before handover.
- **Data users** need final records as CSV/JSON for common commerce and job sites, without configuring anything.
- **Acceptance.** Precision and coverage are reported separately, never as one "accuracy" number counting filled
  fields. Each phase has one zero-touch target, measured on fresh sites (OPEN_QUESTIONS #3).
- **Known hard cases:** behavioural bot challenges, CDN edge blocking, IP rate limits. No authenticated crawls.

---

## Appendix C. Evidence base

Condensed from the 2026-10-08 research notes, which are not in the repo.

**Resolution and confidence:**
- **Pinterest 2025** (arxiv.org/html/2508.01096v1), 1,015 unseen domains **[verified]**:
  - schema.org precision: sale price 0.90, title 0.95, image 0.66;
  - an XGBoost ranker over render features reached 0.97 price precision.

  Structured data is strong but imperfect; a learned ranker is the known upgrade (§22).
- **Klarna** (arxiv.org/html/2111.02168v4): an LLM chooser added +16.8 pp over a weak ranker. Pinterest saw no gain
  over a strong one **[verified]**.
- **Wrapper induction across sibling pages:** Dalvi et al. VLDB 2011 (arxiv 1103.2406); Ceres (arxiv 1804.04635)
  **[verified]**.
- **Calibration:** Platt below ~1k labels, isotonic above (Guo et al. ICML 2017; scikit-learn docs) **[verified]**.
  Split-conformal extraction at α=0.02 gave 98.3% coverage with 70% singleton sets (Rombach & Mehdiyev, IJDAR 2026)
  **[verified]**.
- **Static benchmarks overstate live accuracy** by ~8 points (LiveWeb-IE, arxiv.org/html/2603.13773)
  **[verified]**.
- **WDC 2024-12:** Product markup on 3.3M hosts; JobPosting on 63k hosts **[verified]**.
- **v1's tie-breaking audit:** none of 16 defects was a tie between valid candidates. All were validity, scope,
  intent or absence failures. This is why the structural stages come first.

**LLM role:**
- **ScrapingBee** (2026-09-07): validated selector maps reached 96/96 fields at 2 ms/page vs 87/96 for a per-page
  LLM **[verified]**.
- **Brosch et al. DATA 2025** (arxiv.org/html/2506.21585v1): generated extractors came within −1.6 pts of per-page
  extraction with 95.8% fewer calls; per-page extraction hallucinated attributes **[verified]**.
- **OmbuLabs:** 30–40% first-attempt selector failure, hence validation and repair **[verified, anecdotal]**.
- **Structured Output Benchmark** (arxiv 2604.25359): 83% best value accuracy **[verified abstract]**.
- **Thinking Machines:** temperature 0 is not reproducible **[verified]**.
- **NEXT-EVAL** (arxiv 2505.17125): flat inputs hallucinate least **[verified abstract]**.
- **LangExtract** (github.com/google/langextract): char-offset grounding, Apache-2.0 **[verified]**.
- **Prices, 2026-10-08, per 1M tokens** **[verified]**: Gemini 2.5 Flash-Lite $0.10/$0.40; Claude Haiku 5.5
  $0.10/$0.50; Claude Sonnet 5.5 $2/$10. Per-page Flash-Lite-class at 10k pages/day ≈ $186/month.

**Browser:**
- **Patchright:** Apache-2.0, PyPI 1.63.0 (2026-09-20) **[verified]**.
- **Runtime.enable detection:** the classic probe reportedly stopped working in Chrome after V8 changes in May 2025
  (blog.crawlex.net) **[self-reported]**. Other sources dispute this **[self-reported]**.
- **nodriver / zendriver:** AGPL-3.0 **[verified]**.
- **v1 50-site audit:** 11 of 22 listing failures were WAF 403s; 5 were JS shells.
