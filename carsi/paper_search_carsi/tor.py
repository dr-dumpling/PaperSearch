"""Tor is intentionally not bundled. network.py imports this lazily when use_tor=True."""


def ensure_tor(*_args, **_kwargs):
    raise RuntimeError("Tor routing is not part of paper-search-carsi")


def get_tor_proxy(*_args, **_kwargs):
    return None
