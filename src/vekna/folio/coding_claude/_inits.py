from vekna.lexicon import CODING_FOCUS

from ._links import ClaudeCodingFocus


# The slot comes from the lexicon, not from the coding folio: a folio never
# imports another folio, and the lexicon is where the two agree on both the
# medium's name and the protocol a Focus for it must satisfy.
def register() -> None:
    CODING_FOCUS.register(ClaudeCodingFocus())
