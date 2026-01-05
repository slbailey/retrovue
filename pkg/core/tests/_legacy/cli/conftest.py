"""
Lightweight fixtures for CLI contract tests.

These tests only assert that the CLI surface matches the documented contract
in docs/contracts/README.md (command presence, --help output shape, required flags).

They are intentionally isolated:
- They do NOT require a database.
- They do NOT require schedule_manager models.
- They do NOT spin up the API or ffmpeg.
- They do NOT mutate any state.

If a future CLI test needs a fixture like temp_db_session just to satisfy
a signature, we stub it here as a no-op so pytest doesn't fail import.
"""

import pytest


@pytest.fixture(scope="session")
def dummy_env():
    """Placeholder fixture in case a test wants 'something' to depend on."""
    return {}


# ---- Optional stubs to satisfy any imported fixture names ----
# Some of the generated tests or future tests might reference these fixtures
# (because older tests expected a DB session / engine / path). For the CLI
# surface contract tests, these are not actually used, but we define them
# so pytest doesn't die during collection.

@pytest.fixture
def temp_db_session():
    return None


@pytest.fixture
def temp_db_engine():
    return None


@pytest.fixture
def temp_db_path():
    return None
