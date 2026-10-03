import pytest

from vekna.folio.coding_claude import ClaudeOptions, ClaudeOptionsError


class TestClaudeOptions:
    @staticmethod
    def test_misspelled_field_is_refused():
        with pytest.raises(
            ClaudeOptionsError, match="disalowed_tools: Extra inputs are not permitted"
        ):
            ClaudeOptions(disalowed_tools=["Bash"])
