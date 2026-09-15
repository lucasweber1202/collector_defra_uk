"""DEFRA extractor entrypoint for the standalone collector."""
from __future__ import annotations

from scripts.extract_defra_fruit_veg import collect as _collect
from scripts.govuk import SourceData, build_client


def collect() -> SourceData:
    with build_client() as client:
        return _collect(client)
