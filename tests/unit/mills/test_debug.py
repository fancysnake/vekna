from vekna.mills.debug import debug_line
from vekna.pacts.routing import Routed


class TestDebugLine:
    @staticmethod
    def test_it_leads_with_the_cast():
        line = debug_line(Routed(kind="rite_started", cast_id="c1", action="applied"))

        assert line == "c1 rite_started applied"

    @staticmethod
    def test_a_drop_says_why():
        line = debug_line(
            Routed(
                kind="rite_delta", cast_id="c1", action="dropped", reason="no such rite"
            )
        )

        assert line == "c1 rite_delta dropped (no such rite)"

    @staticmethod
    def test_what_belongs_to_no_cast_still_lines_up():
        line = debug_line(Routed(kind="surface_hello", cast_id=None, action="attached"))

        assert line == "- surface_hello attached"
