"""Shared fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Tests never touch the developer's real cache: use a throw-away directory.
os.environ.setdefault("LIVEMATCH_CACHE_DIR", tempfile.mkdtemp(prefix="livematch-test-cache-"))

from livematch.sources.synthetic import SyntheticSource  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "sample"


@pytest.fixture(scope="session")
def synthetic() -> SyntheticSource:
    return SyntheticSource(duration_s=120.0, seed=1)
