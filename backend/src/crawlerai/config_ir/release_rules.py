"""What the release executor is told of a schema (SPEC-08 §4.12, D-0527): one `FieldRule` per field, built from the
schema and SPEC-04's normalizers, so a valid value is defined in one place (C8) while the release executor itself
imports nothing of the engine (INV-20)."""

from pydantic import ValidationError

from crawlerai.config_ir.release_executor import FieldRule, Value
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef


def release_rules(schema: SchemaDef, ctx: Context) -> dict[str, FieldRule]:
    """A rule per schema field: a list field takes every match; a value is accepted when the field's normalizer, or the
    normalizer a post op names, returns `Ok` for it, as the engine executor checks it."""
    return {name: _rule(spec, ctx) for name, spec in schema.fields.items()}


def _rule(spec: FieldSpec, ctx: Context) -> FieldRule:
    own = spec.item or spec

    def accepts(value: Value, type_: str | None) -> bool:
        try:
            target = spec if type_ is None else own if own.type == type_ else FieldSpec(type=FieldType(type_))
        except ValidationError:  # an enum or identifier type needs the field's own vocabulary or scheme
            return False
        return isinstance(normalize(value, target, ctx), Ok)

    return FieldRule(many=spec.item is not None, accepts=accepts)
