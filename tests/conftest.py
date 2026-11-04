"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from livematch.sources.synthetic import SyntheticSource

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "sample"


@pytest.fixture(scope="session")
def synthetic() -> SyntheticSource:
    return SyntheticSource(duration_s=120.0, seed=1)
