"""Tests for shelfr.console __all__ exports alignment."""

from __future__ import annotations


def test_console_all_has_attributes() -> None:
    """Verify all names in shelfr.console.__all__ are actually present on the module."""
    import shelfr.console

    missing = []
    for name in shelfr.console.__all__:
        if not hasattr(shelfr.console, name):
            missing.append(name)

    assert not missing, f"Names in __all__ missing from module: {missing}"


def test_console_all_matches_ui() -> None:
    """Verify shelfr.console.__all__ is a subset of shelfr.ui exports."""
    import shelfr.console
    import shelfr.ui

    console_all = set(shelfr.console.__all__)
    ui_exports = set(dir(shelfr.ui))

    missing_from_ui = console_all - ui_exports
    assert (
        not missing_from_ui
    ), f"Names in console.__all__ not found in shelfr.ui: {missing_from_ui}"
