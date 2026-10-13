# schema.org enumerations

Member names of schema.org enumerations, one file per enumeration, named after it. The enum normalizer matches a
`schema:<Enumeration>` field against these names (SPEC-04 §4.4).

| File | Source | Content |
|---|---|---|
| `ItemAvailability.json` | schema.org `ItemAvailability` (https://schema.org/ItemAvailability), the members listed by the standard | Exactly the enumeration's members; nothing added. |

The member names are facts of the standard, typed from it (SPEC-04 §9, open issue on the schema.org file license).
Once the pinned schema.org vocabulary file is in `backend/data/manifest.json` (SPEC-04 PR 7), these lists can be read
from it instead. A file here changes only when the standard changes.
