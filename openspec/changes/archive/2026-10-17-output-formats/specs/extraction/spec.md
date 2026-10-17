# Delta: extraction

## ADDED Requirements

### Requirement: Fit markdown and chunks
`markdown_fit` SHALL be the page's markdown pruned by deterministic block scores (link density, text density, and
repetition of a block across the page), keeping at most `fit.max_blocks`; with `fit.query` it keeps the blocks that
rank by BM25 (Robertson and Zaragoza, 2009) over the blocks. `chunks` SHALL split the markdown (or `markdown_fit`)
by `heading`, `sentence` or `token` strategy with a `size` and `overlap` in words, each chunk carrying its heading
path. Neither uses an LLM. Refs: D-1422, D-1423.
#### Scenario: Query keeps relevant blocks
- **WHEN** `fit.query` names a topic of one block
- **THEN** that block is kept and unrelated blocks are not
