# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pytest fixtures. Model builders live in kimbim.testing (also used by the app self-test)."""
import pytest

from kimbim.testing import build_model  # noqa: F401  (re-exported for test modules)


@pytest.fixture
def model():
    return build_model()


def pytest_configure(config):
    """`KIMBIM_TEST_SCHEMA=IFC4X3 pytest` runs the suite with every project made by `authoring.new_project` (the
    app's New project, the bridge, make_house's sample house) in that schema (D241, docs/02). Synthetic record
    fixtures (`build_model`) keep the schema they ask for: their hashes are pinned per schema, and
    test_records round-trips IFC4X3 records itself. Unset, projects are IFC4 as the app makes them."""
    import os

    schema = os.environ.get("KIMBIM_TEST_SCHEMA", "")
    if not schema:
        return
    os.environ.setdefault("KIMBIM_HOUSE_SCHEMA", schema)
    import functools

    from kimbim import authoring

    original = authoring.new_project
    forced = schema

    @functools.wraps(original)
    def new_project(name: str = "", schema: str = "") -> str:
        return original(name, schema or forced)

    authoring.new_project = new_project
