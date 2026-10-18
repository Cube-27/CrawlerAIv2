# Tasks

## 1. Asked fields

- [ ] 1.1 Role C on a detail page is asked for every missing field the config does not run, optional ones included;
      a listing's page fields keep the required gate.

## 2. Link and element claims

- [ ] 2.1 The cleaned text records each shown link (`a[href]`) and image (`img[src]`) with its span, path, target and
      announced name.
- [ ] 2.2 Role C's detail text carries ids for the links and images the asked fields can claim; claims take a `ref`;
      a claimed id is grounded in the element (INV-12) and its value read from the DOM; span offsets map back past the
      ids.

## 3. No apply_url derivation

- [ ] 3.1 The page-URL derivation fills only a field whose every alternative is `T.url`; `job_detail.apply_url` is
      `JobPosting.potentialAction.target`.
- [ ] 3.2 Golden-set before/after, with and without a live LLM.
