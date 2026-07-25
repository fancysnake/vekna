from importlib import import_module


def dispatch_cast(argv: list[str]) -> int:
    return import_module("vekna.lexicon").main(argv)


def dispatch_rituals(argv: list[str]) -> int:
    return import_module("vekna.lexicon").rituals_main(argv)
