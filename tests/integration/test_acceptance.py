import io
import shutil
from pathlib import Path

from vekna.lexicon import main

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


class TestAcceptance:
    @staticmethod
    def test_fix_demo_runs_to_completion(tmp_path, monkeypatch, capsys):
        shutil.copy(_EXAMPLES / "rituals.py", tmp_path / "rituals.py")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.stdin", io.StringIO("fix\n"))

        exit_code = main(["fix_demo", "--bound", "3"])

        assert not exit_code
        output = capsys.readouterr().out
        assert "check" in output
        assert (tmp_path / ".fixed").is_file()
