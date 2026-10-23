"""Absent fields: the required fields of a detail schema a site's pages do not state, which a
learned config lists so that role C is not asked for them on every page.

A learning run reads `LEARN_AFTER_PAGES` stored pages. A field is absent when, on every one of them, nothing
published it, no source gave a valid value for it (structured data, embedded state, the DOM, role C), and role C was
asked (an extraction outside config mode called the LLM: on a detail page, role C is asked for every missing
required field at once; in config mode only for the fields the config does not cover).
Only required fields and the members of a required group count: an optional field never makes role C run, it only rides
along in a call a required one makes. An `object` field, or a list of objects, is never asked,
so it is never absent either.

In config mode an absent field is not asked of role C and stays `missing` with reason `absent` (`resolve.pipeline`);
any source that states it still publishes it, and a config page that publishes it re-tests it: the field leaves the
list and the site re-learns (`config_ir.drift.record_run`).
"""

from collections.abc import Sequence

from crawlerai.config_ir.held_out import StoredPage
from crawlerai.config_ir.progressive import LEARN_AFTER_PAGES
from crawlerai.resolve.evidence import required_fields
from crawlerai.resolve.pipeline import ABSENT as ABSENT  # the reason an absent field's `missing` outcome carries
from crawlerai.schemas.types import FieldType, SchemaDef


def absent_fields(schema: SchemaDef, pages: Sequence[StoredPage]) -> list[str]:
    """The fields of `schema` absent from `pages`, in schema order; none for a listing, or with fewer pages than a run
    reads (too few to say a site never states a field)."""
    if schema.page_kind != "detail" or len(pages) < LEARN_AFTER_PAGES:
        return []
    required = required_fields(schema)
    return [
        name
        for name, spec in schema.fields.items()
        if name in required
        and spec.type is not FieldType.OBJECT
        and not (spec.item is not None and spec.item.type is FieldType.OBJECT)
        and all(_unstated(page, name) for page in pages)
    ]


def _unstated(page: StoredPage, name: str) -> bool:
    return page.asked_llm and name not in page.held_out.facts.published and name not in page.stated
