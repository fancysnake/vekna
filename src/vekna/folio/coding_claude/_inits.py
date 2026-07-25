from vekna.lexicon import register_focus

from ._links import ClaudeCodingFocus

# The medium name is a literal, not an import: a folio never imports another
# folio, so this is the one place the two agree by spelling.
_MEDIUM = "coding"


def register() -> None:
    register_focus(_MEDIUM, ClaudeCodingFocus())
