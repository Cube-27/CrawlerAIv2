"""Every validation error the engine reports reads the same way: a dotted path with list indexes in brackets, and
our own validators' message without pydantic's "Value error, " prefix."""

from pydantic import BaseModel, ValidationError, field_validator

from crawlerai.core.validation import error_path, field_error


class _Row(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the name is blank")
        return value


class _Table(BaseModel):
    rows: list[_Row]


def _errors(raw: object) -> list[tuple[str, str]]:
    try:
        _Table.model_validate(raw)
    except ValidationError as e:
        return [field_error(error) for error in e.errors()]
    raise AssertionError("the document validated")


def test_an_own_validator_reports_its_message_alone_at_an_indexed_path() -> None:
    assert _errors({"rows": [{"name": "a"}, {"name": " "}]}) == [("rows[1].name", "the name is blank")]


def test_a_pydantic_error_keeps_its_message() -> None:
    assert _errors({"rows": [{"name": 3}]}) == [("rows[0].name", "Input should be a valid string")]


def test_the_whole_document_has_the_empty_path() -> None:
    assert error_path(()) == ""
