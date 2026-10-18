"""How an output value scores against its label's value (SPEC-03 §4.6): the type's equality (SPEC-04 §4.5), with the
dev scoring rules where that equality is stricter than what a label states (D-1462, D-1484, D-1487)."""

from pydantic import JsonValue

from crawlerai.normalize.dispatch import equal, resource_key, similarity
from crawlerai.schemas.types import FieldSpec, FieldType

# D-1462: a long_text output matches its label when their word multisets overlap by at least this Dice coefficient
# (`normalize.dispatch.similarity`): a description is one value, but where it ends and how it is broken into lines
# differ between a page's sources, so exact equality would score most correct descriptions wrong.
LONG_TEXT_MIN_SIMILARITY = 0.9
# A location value's parsed parts (SPEC-04 §4.4 `location`), beside its `text` and `remote_flag`.
_PLACE_PARTS = ("locality", "region", "country")


def same(output: JsonValue, label: JsonValue, spec: FieldSpec) -> bool:
    """Whether an output value scores as its label's value: equal by the type's equality (SPEC-04 §4.5); for long_text,
    similar enough (`LONG_TEXT_MIN_SIMILARITY`, D-1462); for image_url, naming the same stored file in another
    rendition (D-1484); for location, agreeing on the text when the label states only its text (D-1487)."""
    if equal(output, label, spec):
        return True
    match spec.type:
        case FieldType.LONG_TEXT:
            score = similarity(output, label, spec)
            return score is not None and score >= LONG_TEXT_MIN_SIMILARITY
        case FieldType.IMAGE_URL:
            return _same_file(output, label, spec)
        case FieldType.LOCATION:
            return _same_place(output, label, spec)
        case FieldType.LIST if spec.item is not None and spec.item.type is FieldType.IMAGE_URL:
            return _same_file(output, label, spec)
        case FieldType.LIST if spec.item is not None and spec.item.type is FieldType.LOCATION:
            return _same_places(output, label, spec.item)
        case _:
            return False


def _same_file(output: JsonValue, label: JsonValue, spec: FieldSpec) -> bool:
    """D-1484: two image URLs that name one stored file (`resource_key`: authority and path, the scheme and the query
    aside, RFC 3986 §3) are renditions of one image, as the resolver reads them (SPEC-05 §4.7); a list of images, the
    same set of files."""
    key = resource_key(label, spec)
    return key is not None and key == resource_key(output, spec)


def _same_place(output: JsonValue, label: JsonValue, spec: FieldSpec) -> bool:
    """D-1487: a label that states only a place's text (no locality, region or country) says nothing of its parts, so
    an output whose text and remote flag equal it scores as it, whatever parts the output parsed (SPEC-04 §4.5 compares
    a part only where both values state it, and the parts are where the label is silent)."""
    if not (isinstance(output, dict) and isinstance(label, dict) and label.get("text") is not None):
        return False
    if any(label.get(part) is not None for part in _PLACE_PARTS):
        return False
    return equal({**output, **dict.fromkeys(_PLACE_PARTS)}, label, spec)


def _same_places(output: JsonValue, label: JsonValue, item: FieldSpec) -> bool:
    """Lists of places as multisets (SPEC-04 §4.5 list equality), each label place paired with one output place it
    scores as (`same`), by augmenting paths (a maximum bipartite matching)."""
    if not (isinstance(output, list) and isinstance(label, list) and len(output) == len(label)):
        return False
    pairs = [[j for j, out in enumerate(output) if same(out, lab, item)] for lab in label]
    return _all_paired(pairs)


def _all_paired(pairs: list[list[int]]) -> bool:
    """Whether every left item `i` pairs with a distinct right item among `pairs[i]` (Kuhn's augmenting paths)."""
    taken: dict[int, int] = {}  # right item -> left item

    def place(i: int, seen: set[int]) -> bool:
        for j in pairs[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in taken or place(taken[j], seen):
                taken[j] = i
                return True
        return False

    return all(place(i, set()) for i in range(len(pairs)))
