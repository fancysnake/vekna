import subprocess
from pathlib import Path

import pytest

from vekna.wire import ConfigLayer, config_layers, user_layers


@pytest.fixture(name="user")
def _user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "deep").mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    return repo


def _commit(directory: Path) -> None:
    _git(
        "-c",
        "user.name=vekna",
        "-c",
        "user.email=vekna@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "root",
        cwd=directory,
    )


class TestConfigLayers:
    @staticmethod
    def test_nothing_configured_is_no_layers(tmp_path: Path, user: Path):
        assert not user.exists()
        assert config_layers(tmp_path) == ([], [])

    @staticmethod
    def test_the_user_s_project_table_comes_before_the_project_s_file(
        tmp_path: Path, user: Path
    ):
        repo = _repo(tmp_path)
        (repo / ".vekna.toml").write_text("[circle]\nprocesses = 2\n", encoding="utf-8")
        user.write_text(
            "[circle]\nprocesses = 8\n"
            f'[projects.mine]\npath = "{repo}"\n'
            "[projects.mine.circle]\nprocesses = 3\n"
            f'[projects.other]\npath = "{tmp_path}"\n'
            "[projects.other.circle]\nprocesses = 5\n",
            encoding="utf-8",
        )

        assert config_layers(repo / "deep") == (
            [
                ConfigLayer(user, {"circle": {"processes": 3}}, "mine"),
                ConfigLayer(repo / ".vekna.toml", {"circle": {"processes": 2}}),
                ConfigLayer(user, {"circle": {"processes": 8}}),
            ],
            [],
        )

    @staticmethod
    def test_a_worktree_of_the_checkout_reads_the_same_project_table(
        tmp_path: Path, user: Path
    ):
        repo = _repo(tmp_path)
        _commit(repo)
        _git("worktree", "add", "-q", str(tmp_path / "tree"), cwd=repo)
        user.write_text(f'[projects.mine]\npath = "{repo}"\n', encoding="utf-8")

        assert config_layers(tmp_path / "tree") == (
            [ConfigLayer(user, {}, "mine"), ConfigLayer(user, {})],
            [],
        )

    # A submodule: its `.git` is a file, and the directory it names has no
    # `commondir`, so the tree is a repository of its own.
    @staticmethod
    def test_a_git_file_that_leads_to_no_checkout_is_a_repository_of_its_own(
        tmp_path: Path, user: Path
    ):
        module = tmp_path / "module"
        (module / "deep").mkdir(parents=True)
        (module / ".git").write_text("gitdir: ../modules/module\n", encoding="utf-8")
        user.write_text(f'[projects.mine]\npath = "{module}"\n', encoding="utf-8")

        layers, problems = config_layers(module / "deep")

        assert layers[0] == ConfigLayer(user, {}, "mine")
        assert not problems

    @staticmethod
    def test_a_git_file_nobody_can_read_still_marks_a_repository(
        tmp_path: Path, user: Path
    ):
        module = tmp_path / "module"
        (module / "deep").mkdir(parents=True)
        (module / ".git").write_text("gitdir: ../modules/module\n", encoding="utf-8")
        (module / ".git").chmod(0)
        user.write_text(f'[projects.mine]\npath = "{module}"\n', encoding="utf-8")

        layers, problems = config_layers(module / "deep")

        assert layers[0] == ConfigLayer(user, {}, "mine")
        assert not problems

    @staticmethod
    def test_a_submodule_and_its_worktree_are_one_project(tmp_path: Path, user: Path):
        origin = tmp_path / "origin"
        origin.mkdir()
        _git("init", "-q", cwd=origin)
        _commit(origin)
        outer = _repo(tmp_path)
        _git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(origin),
            "sub",
            cwd=outer,
        )
        _commit(outer / "sub")
        _git("worktree", "add", "-q", str(tmp_path / "tree"), cwd=outer / "sub")
        user.write_text(
            f'[projects.mine]\npath = "{outer / "sub"}"\n', encoding="utf-8"
        )

        layers, problems = config_layers(tmp_path / "tree")

        assert layers == [ConfigLayer(user, {}, "mine"), ConfigLayer(user, {})]
        assert not problems

    @staticmethod
    def test_the_user_layers_read_only_what_the_user_says_for_every_project(
        tmp_path: Path, user: Path
    ):
        user.write_text(
            f'[circle]\ncoding = 2\n[projects.mine]\npath = "{tmp_path}"\n',
            encoding="utf-8",
        )

        assert user_layers() == ([ConfigLayer(user, {"circle": {"coding": 2}})], [])

    @staticmethod
    def test_a_home_relative_path_names_the_checkout(
        tmp_path: Path, user: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "work").mkdir()
        user.write_text('[projects.mine]\npath = "~/work"\n', encoding="utf-8")

        layers, problems = config_layers(tmp_path / "work")

        assert layers[0] == ConfigLayer(user, {}, "mine")
        assert not problems

    @staticmethod
    @pytest.mark.parametrize(
        ("toml", "problem"),
        [
            ("projects = 3\n", "[projects] is not a table"),
            (
                "[projects.mine]\ncircle = {}\n",
                "[projects.mine] needs a path, the project's checkout",
            ),
            ("[projects]\nmine = 3\n", "[projects.mine] needs a path"),
            (
                '[projects.mine]\npath = "work"\n',
                "[projects.mine] path = 'work' is not absolute",
            ),
        ],
    )
    def test_a_project_table_that_names_no_checkout_is_a_problem(
        tmp_path: Path, user: Path, toml: str, problem: str
    ):
        user.write_text(toml, encoding="utf-8")

        layers, problems = config_layers(tmp_path)

        assert layers == [ConfigLayer(user, {})]
        assert len(problems) == 1
        assert problems[0].startswith(f"{user}: {problem}")

    @staticmethod
    def test_a_file_that_will_not_read_is_left_out_and_named(
        tmp_path: Path, user: Path
    ):
        user.write_text("[circle\n", encoding="utf-8")
        (tmp_path / ".vekna.toml").write_text("[circle]\n", encoding="utf-8")

        layers, problems = config_layers(tmp_path)

        assert layers == [ConfigLayer(tmp_path / ".vekna.toml", {"circle": {}})]
        assert len(problems) == 1
        assert problems[0].startswith(f"{user}: ")

    @staticmethod
    def test_projects_in_a_project_s_own_file_is_a_problem(tmp_path: Path, user: Path):
        project = tmp_path / ".vekna.toml"
        project.write_text('[projects.mine]\npath = "/x"\n', encoding="utf-8")

        _, problems = config_layers(tmp_path)

        assert problems == [f"{project}: [projects] is read from {user} only"]
