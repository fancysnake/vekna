import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from tests.conftest import entry
from vekna.lexicon import (
    FocusMissingError,
    MediumBoundaryError,
    NoComponents,
    RitualError,
    Transition,
    current_rite,
    done,
    emit_delta,
    expect_focus,
    medium,
    ritual,
    step,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, resolve_focus, run_cast
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@medium
async def pick(*, prompt: str, options: list[str]) -> str:
    return await current_rite().channel.decide(prompt=prompt, options=options)


class Start(BaseModel):
    pass


class Picked(BaseModel):
    choice: str


@step
async def choose(_state: Start) -> Transition:
    choice = await pick(prompt="which?", options=["a", "b"])
    return done(Picked(choice=choice))


chooser = entry(name="chooser", target=choose, payload=Start())


@medium
async def whoami() -> None:
    await asyncio.sleep(0)
    emit_delta("here")


@step
async def identify(_state: Start) -> Transition:
    await whoami()
    return done(None)


identifier = entry(name="identifier", target=identify, payload=Start())


# The ritual body itself runs at the cast root, outside any rite.
@ritual("rootless")
def rootless(_: NoComponents) -> Transition:
    emit_delta("nowhere to hang")
    return done(None)


class TestMedium:
    @staticmethod
    def test_prompts_via_channel_and_returns_choice():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO("b\n"))

        result = asyncio.run(
            run_cast(
                ritual=chooser,
                components=chooser.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        assert result == Picked(choice="b")

    @staticmethod
    def test_medium_rite_nests_under_its_step():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO("a\n"))

        asyncio.run(
            run_cast(
                ritual=chooser,
                components=chooser.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        started = [e for e in grimoire.events if isinstance(e, RiteBegan)]
        step_rite = next(e for e in started if e.name == "choose")
        medium_rite = next(e for e in started if e.name == "pick")
        assert medium_rite.category == "medium"
        assert medium_rite.parent_id == step_rite.rite_id

    @staticmethod
    def test_a_decorated_medium_introspects_as_itself():
        assert whoami.__name__ == "whoami"

    @staticmethod
    def test_current_rite_outside_cast_raises():
        with pytest.raises(RitualError):
            current_rite()


# The call arrives as a dict rather than as `**kwargs` on purpose: a wrong call
# spelled out in the test body is one the linters would refuse to let stand, and
# an author's rituals.py is a file they may never point a checker at.
def _caller(call: dict[str, object]):
    @step
    async def ask(_state: Start) -> Transition:
        await pick(**call)
        return done(None)

    return entry(name="caller", target=ask, payload=Start())


def _cast(the_ritual, grimoire):
    renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO("a\n"))
    return asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=renderer,
        )
    )


class TestMediumBoundary:
    @staticmethod
    def test_an_argument_the_medium_does_not_take_is_named():
        # A keyword that moved elsewhere is a slip in an author's rituals.py,
        # which they may never type-check; Python's own TypeError would report it
        # as a traceback out of the engine's frames.
        with pytest.raises(MediumBoundaryError, match="takes no argument 'flavour'"):
            _cast(
                _caller({"prompt": "which?", "options": ["a", "b"], "flavour": "loud"}),
                Grimoire(cast_id="c1", clock=_fixed_clock),
            )

    @staticmethod
    def test_a_call_bind_refuses_otherwise_is_quoted_as_it_came():
        # Nothing unknown was passed, so there is no keyword to name — what
        # `bind` said is more useful than anything this could reword.
        with pytest.raises(MediumBoundaryError, match="was called wrong: missing"):
            _cast(
                _caller({"prompt": "which?"}),
                Grimoire(cast_id="c1", clock=_fixed_clock),
            )

    @staticmethod
    def test_the_refusal_belongs_to_the_medium_rite():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        with pytest.raises(MediumBoundaryError):
            _cast(
                _caller({"prompt": "which?", "options": ["a"], "flavour": "loud"}),
                grimoire,
            )

        began = next(
            e for e in grimoire.events if isinstance(e, RiteBegan) and e.name == "pick"
        )
        ended = next(e for e in grimoire.events if isinstance(e, RiteEnded))
        assert (began.category, ended.rite_id, ended.status) == (
            "medium",
            began.rite_id,
            "error",
        )


class TestResolveFocus:
    @staticmethod
    def test_an_unregistered_medium_names_itself():
        with pytest.raises(FocusMissingError, match="unheard") as raised:
            resolve_focus("unheard")

        # No hint was ever expected for it, so the message is the bare one.
        assert "—" not in str(raised.value)

    @staticmethod
    def test_an_expected_medium_carries_the_hint_it_registered():
        expect_focus("unbound", hint="pip install something")

        with pytest.raises(FocusMissingError, match="pip install something"):
            resolve_focus("unbound")


class TestEmitDelta:
    @staticmethod
    def test_inside_a_medium_it_hangs_off_the_medium_rite():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())

        asyncio.run(
            run_cast(
                ritual=identifier,
                components=identifier.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        started = [e for e in grimoire.events if isinstance(e, RiteBegan)]
        medium_rite = next(e for e in started if e.name == "whoami")
        delta = next(e for e in grimoire.events if isinstance(e, RiteStreamed))
        assert (delta.rite_id, delta.delta) == (medium_rite.rite_id, "here")

    @staticmethod
    def test_at_the_cast_root_it_raises():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())

        with pytest.raises(RitualError, match="no rite is running"):
            asyncio.run(
                run_cast(
                    ritual=rootless,
                    components=rootless.components(),
                    grimoire=grimoire,
                    channel=renderer,
                )
            )
