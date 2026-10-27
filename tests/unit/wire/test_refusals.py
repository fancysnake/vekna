import pytest
from pydantic import BaseModel, ValidationError

from vekna.wire import Refusal, explained, refusals


class _Inner(BaseModel):
    count: int


class _Outer(BaseModel):
    name: str
    inner: _Inner


def _refused(data: object) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        _Outer.model_validate(data)
    return caught.value


class TestRefusals:
    @staticmethod
    def test_each_error_keeps_its_place_kind_and_message():
        error = _refused({"inner": {"count": "many"}})

        assert refusals(error) == [
            Refusal(loc=("name",), kind="missing", msg="Field required"),
            Refusal(
                loc=("inner", "count"),
                kind="int_parsing",
                msg="Input should be a valid integer, unable to parse string as an"
                " integer",
            ),
        ]


class TestExplained:
    @staticmethod
    def test_names_each_field_by_its_dotted_path():
        error = _refused({"name": "x", "inner": {"count": "many"}})

        assert explained(error) == (
            "inner.count: Input should be a valid integer, unable to parse string as"
            " an integer"
        )

    @staticmethod
    def test_joins_several_errors_and_drops_the_model_name_and_url():
        error = _refused({"inner": {}})

        said = explained(error)

        assert said == "name: Field required; inner.count: Field required"
        assert "errors.pydantic.dev" not in said

    @staticmethod
    def test_an_error_with_no_place_is_its_message_alone():
        with pytest.raises(ValidationError) as caught:
            _Outer.model_validate_json("{")

        assert explained(caught.value).startswith("Invalid JSON: EOF while parsing")
