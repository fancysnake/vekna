from vekna.lexicon import CODING_FOCUS, offer_prompt

from ._mills import INSTALL_HINT, MEDIUM, one_shot


# Registering handlers is the inits layer's job, not the medium's. The lexicon
# may not import a folio, so it imports this package by name and calls
# register() on it.
def register() -> None:
    CODING_FOCUS.expect(hint=INSTALL_HINT)
    offer_prompt(MEDIUM, one_shot)
