# Tasks

## 1. Row keys

- [x] 1.1 `session_parameters` and `without_parameters` in `normalize/url_key.py`; listing rows publish item URLs
      without them, and the extraction result names them. (#272)
- [x] 1.2 Eval row matching drops the same parameters from label URLs, then matches by (URL path, text fields), and by
      text fields alone for a label row without a URL. (#272)

## 2. Labels

- [x] 2.1 A location given in its normalized form imports by its text. (#272)
- [x] 2.2 `crawlerai eval re-key`: draft labels recomputed against the stored capture; label rows the capture does not
      show marked `stale`, reported apart and never FN. (#272)

## 3. Report

- [x] 3.1 Presence in the capture per labeled value (the coverage ceiling per field type); FN and FP split by kind. (#272)
- [x] 3.2 LLM tokens and USD per correct field. (#272)
