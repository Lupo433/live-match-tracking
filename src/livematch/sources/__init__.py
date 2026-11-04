"""Data sources. Everything downstream depends only on :class:`DataSource`."""

from livematch.sources.base import DataSource
from livematch.sources.synthetic import SyntheticSource

__all__ = ["DataSource", "SyntheticSource"]
