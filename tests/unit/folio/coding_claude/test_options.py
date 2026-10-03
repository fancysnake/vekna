import pytest

from vekna.folio.coding_claude import ClaudeOptions, ClaudeOptionsError


class TestClaudeOptions:
    @staticmethod
    def test_denylist_stands_alone():
        options = ClaudeOptions(disallowed_tools=["WebFetch"])

        assert options.disallowed_tools == ["WebFetch"]
        assert options.allowed_tools is None

    @staticmethod
    def test_allowlist_and_denylist_are_refused_together():
        with pytest.raises(ClaudeOptionsError, match="not both"):
            ClaudeOptions(allowed_tools=["Read"], disallowed_tools=["Bash"])
