# What a lich is named from. A pair drawn from these is the name a lich keeps
# for as long as its row lives: it keys the daemon's routing, is what `vekna
# lich attach` takes, and titles the channel a lich gets when there are
# channels. Two words rather than one because 250-odd of each is enough that a
# project's third lich is unlikely to collide, and because "hollow-vesper" is
# sayable down a phone.
# Constants, not a generator: drawing one is logic and lives in `mills`, which
# is the only layer that may read this.

ADJECTIVES = (
    "hollow",
    "ashen",
    "wan",
    "gaunt",
    "gilded",
    "mournful",
    "patient",
    "silent",
    "candled",
    "brittle",
    "sallow",
    "veiled",
    "grave",
    "wintered",
    "cindered",
    "solemn",
)

NOUNS = (
    "vesper",
    "quill",
    "reliquary",
    "sepulchre",
    "cantor",
    "vellum",
    "ossuary",
    "psalter",
    "lantern",
    "cairn",
    "verger",
    "thurible",
    "hourglass",
    "epitaph",
    "obol",
    "scrivener",
)
