from datetime import timedelta
from pathlib import Path

import pytest

from vekna.links.window_config import HISTORY_AFTER, history_after


@pytest.fixture(name="config")
def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


def _project(tmp_path: Path, toml: str) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".vekna.toml").write_text(toml, encoding="utf-8")
    return project


class TestHistoryAfter:
    @staticmethod
    def test_nothing_configured_is_the_default(tmp_path: Path, config: Path):
        assert not config.exists()
        assert history_after(tmp_path) == (HISTORY_AFTER, "")

    @staticmethod
    def test_the_project_s_duration_wins_over_the_user_s(tmp_path: Path, config: Path):
        config.write_text('[window]\nhistory_after = "P2D"\n', encoding="utf-8")
        project = _project(tmp_path, '[window]\nhistory_after = "PT30M"\n')

        assert history_after(project) == (timedelta(minutes=30), "")

    @staticmethod
    def test_a_project_that_does_not_say_leaves_it_to_the_user(
        tmp_path: Path, config: Path
    ):
        config.write_text('[window]\nhistory_after = "PT0S"\n', encoding="utf-8")
        project = _project(tmp_path, "[circle]\nprocesses = 2\n")

        assert history_after(project) == (timedelta(0), "")

    @staticmethod
    @pytest.mark.parametrize("value", ['"soon"', '"-P1D"'])
    def test_a_duration_that_will_not_read_is_named_and_passed_over(
        tmp_path: Path, config: Path, value: str
    ):
        config.write_text('[window]\nhistory_after = "P2D"\n', encoding="utf-8")
        project = _project(tmp_path, f"[window]\nhistory_after = {value}\n")

        after, ignored = history_after(project)

        assert after == timedelta(days=2)
        assert ignored.startswith(f"{project / '.vekna.toml'}: ")
        assert "history_after" in ignored
        assert ignored.endswith(" — [window] ignored")
