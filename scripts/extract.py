"""DEFRA extractor entrypoint: orchestrates this repository's datasets.

This module stays deliberately small. It owns no parsing and no HTTP beyond the
one shared client: each DEFRA data set is a self-contained ``extract_defra_*``
module returning its own ``SourceData``, and adding a data set means adding a
module and one entry to ``DATASETS``.

Datasets are collected one at a time so that a layout change at one DEFRA page
fails that data set alone. ``main.py`` persists each one in its own transaction
and reports the failures at the end of the run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx

from scripts.extract_defra_agricultural_price_index import (
    collect as _collect_agricultural_price_index,
)
from scripts.extract_defra_banana_prices import collect as _collect_banana_prices
from scripts.extract_defra_fruit_veg import collect as _collect_fruit_veg
from scripts.extract_defra_milk_prices import collect as _collect_milk_prices
from scripts.govuk import SourceData, build_client

# source_id -> collector. Ordered oldest-established first, so a full run's log
# reads in the order this repository grew.
DATASETS: dict[str, Callable[[httpx.Client], SourceData]] = {
    "defra_fruit_veg": _collect_fruit_veg,
    "defra_banana_prices": _collect_banana_prices,
    "defra_milk_prices": _collect_milk_prices,
    "defra_agricultural_price_index": _collect_agricultural_price_index,
}


def resolve(source_ids: list[str] | None) -> list[str]:
    """Return the data sets to run, rejecting an unknown name loudly."""
    selected = list(DATASETS) if source_ids is None else list(source_ids)
    unknown = [source_id for source_id in selected if source_id not in DATASETS]
    if unknown:
        raise ValueError(f"Unknown DEFRA data set(s) {unknown}; known: {sorted(DATASETS)}")
    return selected


@contextmanager
def open_client() -> Iterator[httpx.Client]:
    """Yield the single managed HTTP client shared by one run."""
    with build_client() as client:
        yield client


def collect_one(client: httpx.Client, source_id: str) -> SourceData:
    """Collect exactly one data set with an already-open client."""
    return DATASETS[resolve([source_id])[0]](client)


def collect(source_ids: list[str] | None = None) -> list[SourceData]:
    """Collect the named data sets, or all of them, failing on the first error."""
    with open_client() as client:
        return [collect_one(client, source_id) for source_id in resolve(source_ids)]
