from pathlib import Path

import pytest

from vekna.links.debug_log import DebugLog


class TestWriting:
    @staticmethod
    def test_a_line_is_stamped_and_appended(tmp_path: Path):
        log = DebugLog(tmp_path / "debug.log")

        log.write("first")
        log.write("second")

        written = (tmp_path / "debug.log").read_text(encoding="utf-8").splitlines()
        assert [line.split(" ", maxsplit=1)[1] for line in written] == [
            "first",
            "second",
        ]

    # A log that cannot be written must not end the cast being logged, but an
    # operator watching a file that stopped growing has no way to tell that from
    # a daemon with nothing to say. Once, then never again.
    @staticmethod
    def test_a_log_that_cannot_be_written_says_so_once(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        path = tmp_path / "debug.log"
        log = DebugLog(path)
        path.mkdir()

        log.write("into a directory")
        log.write("and again")

        assert path.is_dir()
        said = capsys.readouterr().err.splitlines()
        assert len(said) == 1
        assert str(path) in said[0]
