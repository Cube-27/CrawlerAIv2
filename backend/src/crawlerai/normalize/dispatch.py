"""The normalize dispatcher (SPEC-04 §4.3): one entry point that sends each field type to its one module (C8).

Callers (the resolver, eval, the API) normalize through `normalize` and never pick a type module themselves.
"""

from crawlerai.normalize import enum, text, url
from crawlerai.normalize.base import Context, Invalid, Normalizer, NormalizeResult, Raw
from crawlerai.schemas.types import FieldSpec, FieldType

# The field-type registry. Each later SPEC-04 PR adds its type here; `list` and `object` recurse here (PR 9).
_NORMALIZERS: dict[FieldType, Normalizer] = {
    FieldType.TEXT: text.normalize,
    FieldType.LONG_TEXT: text.normalize,
    FieldType.ENUM: enum.normalize,
    FieldType.URL: url.normalize,
    FieldType.IMAGE_URL: url.normalize,
}


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize `raw` as `spec`'s type. A type with no normalizer declines (§4.7), so a schema that names one
    cannot crash a job."""
    normalizer = _NORMALIZERS.get(spec.type)
    if normalizer is None:
        return Invalid("unknown_type")
    return normalizer(raw, spec, ctx)
