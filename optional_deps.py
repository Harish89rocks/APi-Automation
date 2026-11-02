"""Distinguish "optional dependency absent" (skip) from "required but missing" (fail).

Developers without the optional packages get a skip. CI sets
REQUIRE_OPTIONAL_DEPS=1, so a broken install there fails loudly instead of
silently skipping whole suites.
"""

import importlib

import pytest

from services.config import env_flag


def require_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if env_flag("REQUIRE_OPTIONAL_DEPS"):
            pytest.fail(
                f"Python package {name!r} is required (REQUIRE_OPTIONAL_DEPS=1) "
                f"but cannot be imported: {error}. "
                "Install it with: pip install -r requirements-cloud.txt",
                pytrace=False,
            )
        pytest.skip(
            f"optional package {name!r} not installed "
            "(pip install -r requirements-cloud.txt)"
        )
