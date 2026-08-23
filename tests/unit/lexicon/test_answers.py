from vekna.lexicon import allowed_answers


class TestAllowedAnswers:
    @staticmethod
    def test_a_bare_question_allows_yes_and_no():
        assert allowed_answers(options=None, free=False) == ("yes", "no")

    @staticmethod
    def test_options_are_the_only_answers():
        assert allowed_answers(options=["fix", "stop"], free=False) == ("fix", "stop")

    # The rule the channel, the trial double and the journal all read: under
    # `free` the options are guesses at the answer, so there is nothing to check
    # against and answering past them is the point.
    @staticmethod
    def test_free_allows_anything_even_alongside_options():
        allowed = [
            allowed_answers(options=None, free=True),
            allowed_answers(options=["fix", "stop"], free=True),
        ]

        assert allowed == [None, None]
