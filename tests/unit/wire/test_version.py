import pytest

from vekna.wire import VERSION, compatible

_MAJOR = int(VERSION.partition(".")[0])


class TestCompatible:
    @staticmethod
    @pytest.mark.parametrize(
        "theirs", [VERSION, f"{_MAJOR}.0.0", f"{_MAJOR}.999.3", f"{_MAJOR}.4.0rc1"]
    )
    def test_the_same_major_version_is(theirs: str):
        assert compatible(theirs)

    @staticmethod
    @pytest.mark.parametrize(
        "theirs", [f"{_MAJOR + 1}.0.0", f"{_MAJOR - 1}.15.0", f"{_MAJOR}0.0.0"]
    )
    def test_another_major_version_is_not(theirs: str):
        assert not compatible(theirs)

    @staticmethod
    def test_a_daemon_that_cannot_say_its_version_is_not():
        assert not compatible(None)
