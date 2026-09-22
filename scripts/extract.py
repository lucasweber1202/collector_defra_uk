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

import logging
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from scripts.config import MAX_STALE_MONTHS, MIN_HISTORY_YEARS
from scripts.extract_defra_agricultural_price_index import (
    collect as _collect_agricultural_price_index,
)
from scripts.extract_defra_banana_prices import collect as _collect_banana_prices
from scripts.extract_defra_fruit_veg import collect as _collect_fruit_veg
from scripts.extract_defra_milk_prices import collect as _collect_milk_prices
from scripts.govuk import SourceData, build_client

logger = logging.getLogger(__name__)


# -- series_id contract (GUIDELINES.md 4, 9.2) ---------------------------
# This repository owns four DEFRA data sets, each with its own grammar, so
# the canonical entry point dispatches to the extractor that owns the id.
# Every one of those parsers returns the raw underscore segments, so
# rejoining them is the exact inverse.
from scripts.extract_defra_agricultural_price_index import (  # noqa: F401
    describe_series_id as describe_agricultural_price_index_series_id,
)
from scripts.extract_defra_agricultural_price_index import (
    parse_series_id as _parse_api,
)
from scripts.extract_defra_banana_prices import (
    parse_series_id as _parse_banana,
)
from scripts.extract_defra_fruit_veg import (
    parse_series_id as _parse_fruit_veg,
)
from scripts.extract_defra_milk_prices import (
    parse_series_id as _parse_milk,
)

_SERIES_ID_PARSERS = (_parse_api, _parse_banana, _parse_fruit_veg, _parse_milk)


def parse_series_id(series_id: str) -> tuple[str, ...]:
    """Decode a DEFRA series_id using whichever data set owns its grammar."""
    for parser in _SERIES_ID_PARSERS:
        try:
            return tuple(parser(series_id))
        except ValueError:
            continue
    raise ValueError(f"Unknown DEFRA series_id: {series_id}")


def build_series_id(*components: str) -> str:
    """Rejoin the tuple parse_series_id returned into the original id."""
    if not components:
        raise ValueError("series_id needs at least one component")
    if any(not c or c != c.upper() for c in components):
        raise ValueError(f"invalid series_id components: {components!r}")
    return "_".join(components)


# -- 5.1 usable-series filtering ------------------------------------------


@dataclass(frozen=True)
class UsabilityReport:
    """What the filter removed, for logging and for tests to assert on."""

    kept: tuple[str, ...]
    stale: tuple[str, ...]
    short_history: tuple[str, ...]
    empty: tuple[str, ...]

    @property
    def dropped(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.stale) | set(self.short_history) | set(self.empty)))


def _months_between(earlier: date, later: date) -> int:
    """Whole months from ``earlier`` to ``later``, day-of-month aware."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def _is_valid(value: Any) -> bool:
    """A real observation: present, numeric and finite."""
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def assess_series(
    reference_dates: list[date],
    today: date,
    max_stale_months: int = MAX_STALE_MONTHS,
    min_history_years: float = MIN_HISTORY_YEARS,
) -> str:
    """Classify one series from the reference dates of its valid observations.

    Returns ``"keep"``, ``"empty"``, ``"stale"`` or ``"short_history"``.
    Recency is judged at the period end and over non-null values only: a source
    that keeps listing a discontinued series with empty recent cells must not
    look live because of those blanks.
    """
    if not reference_dates:
        return "empty"
    first, last = min(reference_dates), max(reference_dates)
    if _months_between(last, today) > max_stale_months:
        return "stale"
    if _months_between(first, last) < round(min_history_years * 12):
        return "short_history"
    return "keep"


def filter_usable_series(
    observations: list[Any],
    catalog: dict[str, dict[str, Any]],
    today: date,
    max_stale_months: int = MAX_STALE_MONTHS,
    min_history_years: float = MIN_HISTORY_YEARS,
) -> tuple[list[Any], dict[str, dict[str, Any]], UsabilityReport]:
    """Drop obsolete and history-less series before anything is persisted.

    Runs after parsing and before the time_series / metadata upsert, so the
    standardized tables never carry a dead or stub series, and prunes the
    catalog alongside the observations so metadata can never describe a series
    the database does not hold (GUIDELINES.md 5.1).
    """
    valid_dates: dict[str, list[date]] = {}
    for observation in observations:
        if _is_valid(observation.value):
            valid_dates.setdefault(observation.series_id, []).append(observation.reference_date)

    verdicts: dict[str, str] = {}
    for series_id in set(catalog) | {o.series_id for o in observations}:
        verdicts[series_id] = assess_series(
            valid_dates.get(series_id, []), today, max_stale_months, min_history_years
        )

    keep = {series_id for series_id, verdict in verdicts.items() if verdict == "keep"}
    report = UsabilityReport(
        kept=tuple(sorted(keep)),
        stale=tuple(sorted(s for s, v in verdicts.items() if v == "stale")),
        short_history=tuple(sorted(s for s, v in verdicts.items() if v == "short_history")),
        empty=tuple(sorted(s for s, v in verdicts.items() if v == "empty")),
    )

    if report.dropped:
        logger.info(
            "Usable-series filter: kept %d, dropped %d "
            "(stale=%d short_history=%d empty=%d; max_stale_months=%d min_history_years=%s)",
            len(report.kept),
            len(report.dropped),
            len(report.stale),
            len(report.short_history),
            len(report.empty),
            max_stale_months,
            min_history_years,
        )
        for series_id in report.stale:
            logger.info(
                "Dropped %s: last valid observation older than %d months",
                series_id,
                max_stale_months,
            )
        for series_id in report.short_history:
            logger.info(
                "Dropped %s: valid history shorter than %s years", series_id, min_history_years
            )
        for series_id in report.empty:
            logger.info("Dropped %s: no valid observations", series_id)
    else:
        logger.info("Usable-series filter: all %d series usable", len(report.kept))

    kept_observations = [o for o in observations if o.series_id in keep]
    kept_catalog = {sid: fields for sid, fields in catalog.items() if sid in keep}
    return kept_observations, kept_catalog, report


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
