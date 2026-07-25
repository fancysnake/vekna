"""The ritual author's door.

Everything here is what a rituals.py — or a folio implementing a medium —
reaches for. CLI and cast-runtime plumbing lives in `vekna.lexicon.entry`.
"""

from ._dispatch import medium, ritual, step
from ._mills import (
    RiteContext,
    current_rite,
    emit_delta,
    expect_focus,
    offer_prompt,
    record_result,
    register_focus,
    reset_foci,
    resolve_focus,
)
from ._pacts import (
    AskFn,
    Channel,
    CodingCall,
    CodingFocusProtocol,
    Done,
    FocusMissingError,
    FocusReply,
    GateFn,
    Goto,
    RitualDefinitionError,
    RitualError,
    StandalonePromptError,
    StepBoundaryError,
    StepBudgetExceededError,
    Transition,
    done,
    goto,
)

__all__ = [
    "AskFn",
    "Channel",
    "CodingCall",
    "CodingFocusProtocol",
    "Done",
    "FocusMissingError",
    "FocusReply",
    "GateFn",
    "Goto",
    "RiteContext",
    "RitualDefinitionError",
    "RitualError",
    "StandalonePromptError",
    "StepBoundaryError",
    "StepBudgetExceededError",
    "Transition",
    "current_rite",
    "done",
    "emit_delta",
    "expect_focus",
    "goto",
    "medium",
    "offer_prompt",
    "record_result",
    "register_focus",
    "reset_foci",
    "resolve_focus",
    "ritual",
    "step",
]
