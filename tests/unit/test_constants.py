from pathlib import Path

from vekna.specs.constants import (
    STEM_DIGEST_LENGTH,
    paths_for,
    stem_for_cwd,
    stem_from_tmux_env,
)


class TestStemForCwd:
    @staticmethod
    def test_uses_directory_basename_and_hash(tmp_path: Path) -> None:
        project = tmp_path / "my-project"
        project.mkdir()

        stem = stem_for_cwd(project)

        assert stem.startswith("vekna-my-project-")
        assert len(stem.removeprefix("vekna-my-project-")) == STEM_DIGEST_LENGTH

    @staticmethod
    def test_is_deterministic_for_same_path(tmp_path: Path) -> None:
        project = tmp_path / "foo"
        project.mkdir()

        assert stem_for_cwd(project) == stem_for_cwd(project)

    @staticmethod
    def test_differs_for_same_name_different_paths(tmp_path: Path) -> None:
        left = tmp_path / "a" / "backend"
        right = tmp_path / "b" / "backend"
        left.mkdir(parents=True)
        right.mkdir(parents=True)

        assert stem_for_cwd(left) != stem_for_cwd(right)

    @staticmethod
    def test_slugs_spaces_and_unicode(tmp_path: Path) -> None:
        project = tmp_path / "My Project ünicode"
        project.mkdir()

        stem = stem_for_cwd(project)

        body = stem.removeprefix("vekna-").rsplit("-", 1)[0]
        assert body == "my-project-nicode"

    @staticmethod
    def test_falls_back_to_root_when_name_empty() -> None:
        # Path("/") has name "", which would slug to empty.
        stem = stem_for_cwd(Path("/"))

        assert stem.startswith("vekna-root-")


class TestStemFromTmuxEnv:
    @staticmethod
    def test_extracts_basename_of_socket_path() -> None:
        env = "/tmp/tmux-1000/vekna-foo-a3f1c2,12345,$0"

        assert stem_from_tmux_env(env) == "vekna-foo-a3f1c2"

    @staticmethod
    def test_handles_default_tmux_socket() -> None:
        env = "/tmp/tmux-1000/default,99,$1"

        assert stem_from_tmux_env(env) == "default"


class TestPathsFor:
    @staticmethod
    def test_returns_stem_stem_and_socket_path() -> None:
        tmux_socket, tmux_session, unix_socket_path = paths_for("vekna-foo-a3f1c2")

        assert tmux_socket == "vekna-foo-a3f1c2"
        assert tmux_session == "vekna-foo-a3f1c2"
        assert unix_socket_path.endswith("/vekna-foo-a3f1c2.sock")
