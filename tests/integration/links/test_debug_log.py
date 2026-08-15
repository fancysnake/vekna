from pathlib import Path

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

    @staticmethod
    def test_a_log_that_cannot_be_written_is_not_an_error(tmp_path: Path):
        path = tmp_path / "debug.log"
        log = DebugLog(path)
        path.mkdir()

        log.write("into a directory")

        assert path.is_dir()
