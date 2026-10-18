# Tasks

## 1. Evaluation scope and scoring

- [x] 1.1 `eval run` bounds a listing's unmatched engine rows to the label's row count and writes the all-rows report
      beside it. (#267)
- [x] 1.2 image_url (and lists of images) score by the stored file (`resource_key`). (#267)
- [x] 1.3 A place labeled by text only scores an output whose text and remote flag agree; lists pair places one to
      one. (#267)

## 2. Extraction

- [x] 2.1 Greenhouse hosted board pages publish each job's board route on the page's host; integer prefixed values. (#267)
- [x] 2.2 Structured-data text with escaped markup reads as the fragment's rendered text. (#267)
- [x] 2.3 Investigate listing price declines (platform rows, money `invalid`/`ambiguous`) and apply links; log what
      stays declined and why. (#267)
- [x] 2.4 Dev eval before and after; apply the deltas and archive this change. (#267)
