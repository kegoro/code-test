"""Tests for backend.smc_analyst.symbol_config."""
from backend.smc_analyst.symbol_config import (
    SYMBOL_DIRECTIONS,
    is_direction_allowed,
)


def test_2382_long_allowed():
    assert is_direction_allowed("2382", "long") is True


def test_2382_short_blocked():
    assert is_direction_allowed("2382", "short") is False


def test_unlisted_symbol_allows_long():
    assert is_direction_allowed("2330", "long") is True


def test_unlisted_symbol_allows_short():
    assert is_direction_allowed("2330", "short") is True


def test_registered_symbols_use_frozenset():
    for symbol, dirs in SYMBOL_DIRECTIONS.items():
        assert isinstance(dirs, frozenset), (
            f"{symbol} directions must be frozenset, got {type(dirs).__name__}"
        )
