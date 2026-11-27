import pytest

from vekna.wire import reaction_answers


class TestReactionAnswers:
    @staticmethod
    @pytest.mark.parametrize(
        ("options", "free", "answers"),
        [
            (None, False, ("yes", "no")),
            (["fix", "file"], False, ("fix", "file")),
            (["fix", "file"], True, ("fix", "file")),
            (None, True, None),
        ],
    )
    def test_a_question_takes_reactions_when_it_offers_answers(
        *, options: list[str] | None, free: bool, answers: tuple[str, ...] | None
    ):
        assert reaction_answers(options=options, free=free) == answers
