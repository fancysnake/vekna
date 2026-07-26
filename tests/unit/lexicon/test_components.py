import hashlib
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from vekna.lexicon import Directory, File, GitRef, Text, TextSpec, Url, sha256_of


class TestFile:
    @staticmethod
    def test_accepts_existing_file(tmp_path):
        path = tmp_path / "x.txt"
        path.write_text("hi")

        assert TypeAdapter(File).validate_python(path) == path

    @staticmethod
    def test_rejects_missing_path(tmp_path):
        with pytest.raises(ValidationError):
            TypeAdapter(File).validate_python(tmp_path / "missing.txt")


class TestDirectory:
    @staticmethod
    def test_accepts_existing_directory(tmp_path):
        assert TypeAdapter(Directory).validate_python(tmp_path) == tmp_path

    @staticmethod
    def test_rejects_file(tmp_path):
        path = tmp_path / "x.txt"
        path.write_text("hi")

        with pytest.raises(ValidationError):
            TypeAdapter(Directory).validate_python(path)


class TestText:
    @staticmethod
    def test_default_is_single_line():
        spec = get_args(Text)[1]

        assert isinstance(spec, TextSpec)
        assert spec.multiline is False


class TestUrl:
    @staticmethod
    def test_accepts_valid_url():
        result = TypeAdapter(Url).validate_python("https://example.com")

        assert str(result).startswith("https://")

    @staticmethod
    def test_rejects_invalid_url():
        with pytest.raises(ValidationError):
            TypeAdapter(Url).validate_python("not a url")


class TestGitRef:
    @staticmethod
    def test_accepts_ref():
        assert TypeAdapter(GitRef).validate_python("main") == "main"

    @staticmethod
    def test_rejects_blank():
        with pytest.raises(ValidationError):
            TypeAdapter(GitRef).validate_python("   ")


class TestSha256:
    @staticmethod
    def test_matches_hashlib(tmp_path):
        path = tmp_path / "x.bin"
        path.write_bytes(b"hello")

        assert sha256_of(path) == hashlib.sha256(b"hello").hexdigest()
