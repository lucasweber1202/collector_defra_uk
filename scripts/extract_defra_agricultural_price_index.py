"""DEFRA Agricultural Price Index (API): monthly output and input price indices.

Official page:
https://www.gov.uk/government/statistics/agricultural-price-indices

DEFRA publishes the current index as a tidy machine-readable CSV covering
January 2014 onward on a 2020 = 100 base, alongside an ODS rendering of the
same figures. Only the CSV is parsed.

Base years are never spliced
----------------------------
The same page also carries archived workbooks on 2015 = 100 (from January
1988), 2010 = 100, 2005 = 100 and 2000 = 100. DEFRA states those are "not
updated monthly and presented for archive purposes only". Chaining them onto
the current series would require a rebasing factor DEFRA does not publish, so
this collector takes the current base only and encodes the base year in every
identifier (``..._B2020``). A future rebasing therefore appears as a new set of
series next to the old one instead of silently changing the meaning of a
stored history. Extending history across bases is a research-layer decision
with an explicit, documented method; it is not a collection decision, and no
backcast is manufactured here.

Published subindices are stored exactly as published. The file carries a
hierarchy (for example ``wheat`` alongside ``wheat_breadmaking``), and both the
aggregate and its components are DEFRA's own published rows, so both are kept
as published. Nothing is aggregated or re-weighted here.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Any

import httpx

from scripts.govuk import SourceData, download, fetch_page, find_attachment, release_timestamps
from scripts.snapshots import build_snapshot
from scripts.time_series import Observation

logger = logging.getLogger(__name__)

SOURCE_ID = "defra_agricultural_price_index"
PAGE_URL = "https://www.gov.uk/government/statistics/agricultural-price-indices"

# The current machine-readable attachment. Its published name carries the
# release date, so only the stable stem is matched. The archived
# `API-monthlydataset*.ods` workbooks and the older `*.xls` files on the same
# page are on other base years and are deliberately not matched.
CSV_PATTERN = r"/API_\d[^/]*\.csv"

# Verified against the live CSV header on 2026-09-16.
EXPECTED_COLUMNS = ("type", "category", "date", "index")

# The base year the current file is published on, verified against the page
# text ("The latest data are presented with a base year of 2020 = 100") and
# against the data itself, whose 2020 mean is 100.4.
BASE_YEAR = 2020

# The two index families the file publishes.
EXPECTED_TYPES = frozenset({"output", "input"})

# Observed release schedule: the reference month is published roughly twelve
# weeks later on the last Thursday of the month (June 2026 data was published
# 2026-08-27; January 2026 data on 2026-03-26). The change history begins
# 2013-04-18, before the 2014 start of this file, so in practice every
# observation is attributable to an official timestamp.
MIN_LAG_DAYS = 70
MAX_LAG_DAYS = 110
INFERRED_LAG_DAYS = 87

EXPECTED_FIRST_OBSERVATION = date(2014, 1, 1)
MIN_EXPECTED_SERIES = 90
MIN_EXPECTED_DATES = 140
# Monthly cadence: consecutive published months must never be more than one
# month plus a few days apart.
MAX_GAP_DAYS = 35

# Plausibility envelope for a price index on a 2020 = 100 base. Wide on
# purpose: a source-drift guard against a rebasing or a decimal shift arriving
# unannounced, not an economic forecast.
MIN_PLAUSIBLE_INDEX = 10.0
MAX_PLAUSIBLE_INDEX = 1000.0


def _token(raw: str) -> str:
    """Normalize one native label into an uppercase identifier token."""
    token = re.sub(r"[^A-Z0-9]+", "", raw.strip().upper())
    if not token:
        raise ValueError(f"DEFRA API label {raw!r} normalizes to an empty identifier token")
    return token


def make_series_id(index_type: str, category: str, base_year: int = BASE_YEAR) -> str:
    """Build ``DEFRA_API_{TYPE}_{CATEGORY}_B{BASE}`` from native labels.

    The base year is part of the identifier so a DEFRA rebasing produces a new
    series rather than silently redefining an existing one.
    """
    series_id = f"DEFRA_API_{_token(index_type)}_{_token(category)}_B{base_year}"
    if len(series_id) > 200:
        raise ValueError(f"series_id exceeds 200 characters: {series_id}")
    return series_id


def parse_series_id(series_id: str) -> tuple[str, str, str, str, int]:
    """Decode ``DEFRA_API_{TYPE}_{CATEGORY}_B{BASE}`` into its five parts."""
    parts = series_id.split("_")
    if len(parts) != 5 or parts[0] != "DEFRA" or parts[1] != "API":
        raise ValueError(f"Invalid DEFRA API series_id: {series_id}")
    source, dataset, index_type, category, base = parts
    if not index_type or not category:
        raise ValueError(f"Incomplete DEFRA API series_id: {series_id}")
    if not re.fullmatch(r"B\d{4}", base):
        raise ValueError(f"DEFRA API series_id carries no base year: {series_id}")
    return source, dataset, index_type, category, int(base[1:])


def _assert_schema(fieldnames: Sequence[str] | None, url: str) -> None:
    """Refuse a file whose published layout no longer matches the verified one."""
    if not fieldnames:
        raise ValueError(f"DEFRA API file {url} has no header row")
    header = tuple(name.strip().lower() for name in fieldnames)
    if header != EXPECTED_COLUMNS:
        raise ValueError(
            f"DEFRA API file {url} header is {header}, expected {EXPECTED_COLUMNS}; the "
            "published layout changed and must be re-verified against the official source"
        )


def parse_csv(
    body: bytes, url: str, snapshot_id: str
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Parse the published CSV into observations and their native labels."""
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    _assert_schema(reader.fieldnames, url)

    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    for line, row in enumerate(reader, start=2):
        index_type = str(row["type"]).strip().lower()
        if index_type not in EXPECTED_TYPES:
            raise ValueError(
                f"DEFRA API file {url} line {line} publishes unknown index type "
                f"{index_type!r}, expected one of {sorted(EXPECTED_TYPES)}; the published "
                "structure changed and must be re-verified"
            )
        category = str(row["category"]).strip().lower()
        if not category:
            raise ValueError(f"DEFRA API file {url} line {line} has a blank category")
        raw_index = str(row["index"]).strip()
        if not raw_index:
            # A blank cell is an unpublished month, not a zero.
            continue
        try:
            value = float(raw_index)
        except ValueError as exc:
            raise ValueError(
                f"DEFRA API file {url} line {line} has unparseable index {raw_index!r}"
            ) from exc
        try:
            reference_date = date.fromisoformat(str(row["date"]).strip())
        except ValueError as exc:
            raise ValueError(
                f"DEFRA API file {url} line {line} has unparseable date {row['date']!r}"
            ) from exc
        if reference_date.day != 1:
            raise ValueError(
                f"DEFRA API file {url} line {line} carries reference date {reference_date}, "
                "which is not the first of a month; the published cadence changed"
            )

        series_id = make_series_id(index_type, category)
        natives.setdefault(series_id, {"type": index_type, "category": category})
        observations.append(
            Observation(
                series_id=series_id,
                reference_date=reference_date,
                value=value,
                snapshot_id=snapshot_id,
            )
        )
    return observations, natives


def _label(raw: str) -> str:
    """Render a native snake_case label as readable English."""
    return raw.replace("_", " ").strip()


def _build_catalog(
    natives: dict[str, dict[str, str]], last_publish_date: date | None
) -> dict[str, dict[str, Any]]:
    """Describe every collected series from its verified native labels."""
    catalog: dict[str, dict[str, Any]] = {}
    for series_id, fields in natives.items():
        index_type, category = fields["type"], _label(fields["category"])
        side = "output" if index_type == "output" else "input"
        catalog[series_id] = {
            "source_id": SOURCE_ID,
            "name": (
                f"UK agricultural price index, {side}: {category} ({BASE_YEAR} = 100)"
            ),
            "description": (
                f"Monthly UK agricultural {side} price index for {category}, on a "
                f"{BASE_YEAR} = 100 base, as published by the Department for Environment, "
                "Food & Rural Affairs. Stored exactly as published. Archived DEFRA series on "
                "other base years are not chained onto this one; rebasing is a research-layer "
                "decision, not a collection one."
            ),
            "frequency": "monthly",
            "unit": "index",
            "eco_group": "producer_prices",
            "source_url": PAGE_URL,
            "last_publish_date": last_publish_date,
        }
    return catalog


def validate(observations: list[Observation], natives: dict[str, dict[str, str]]) -> None:
    """Gate the parsed panel before anything reaches the database."""
    if not observations:
        raise ValueError("DEFRA API collection produced no observations")
    if len(natives) < MIN_EXPECTED_SERIES:
        raise ValueError(
            f"DEFRA API returned only {len(natives)} series, below the {MIN_EXPECTED_SERIES} "
            "floor; the download was probably truncated"
        )

    # Normalization must stay injective, or two published categories would
    # share one stored history.
    by_series: dict[str, set[tuple[str, str]]] = {}
    for series_id, fields in natives.items():
        by_series.setdefault(series_id, set()).add((fields["type"], fields["category"]))
    clashing = {sid: keys for sid, keys in by_series.items() if len(keys) > 1}
    if clashing:
        raise ValueError(f"DEFRA API identifier normalization collided: {clashing}")

    keys = [(observation.series_id, observation.reference_date) for observation in observations]
    if len(keys) != len(set(keys)):
        counts: dict[tuple[str, date], int] = {}
        for observation_key in keys:
            counts[observation_key] = counts.get(observation_key, 0) + 1
        duplicates = sorted(key for key, count in counts.items() if count > 1)[:5]
        raise ValueError(f"DEFRA API published duplicate observations, for example {duplicates}")

    # Both published index families must be present: losing one silently would
    # halve the panel without failing anything else.
    present_types = {fields["type"] for fields in natives.values()}
    if present_types != EXPECTED_TYPES:
        raise ValueError(
            f"DEFRA API returned index types {sorted(present_types)}, expected "
            f"{sorted(EXPECTED_TYPES)}"
        )

    dates = sorted({observation.reference_date for observation in observations})
    if dates[0] != EXPECTED_FIRST_OBSERVATION:
        raise ValueError(
            f"DEFRA API history starts at {dates[0]}, expected {EXPECTED_FIRST_OBSERVATION}; "
            "the published file changed — check for a rebasing — and must be re-verified"
        )
    if len(dates) < MIN_EXPECTED_DATES:
        raise ValueError(
            f"DEFRA API returned only {len(dates)} reference dates, below the "
            f"{MIN_EXPECTED_DATES} floor; the download was probably truncated"
        )
    if dates[-1] > datetime.now(UTC).date():
        raise ValueError(f"DEFRA API published a future reference date {dates[-1]}")

    long_gaps = [
        (earlier, later)
        for earlier, later in pairwise(dates)
        if (later - earlier).days > MAX_GAP_DAYS
    ]
    if long_gaps:
        raise ValueError(
            f"DEFRA API monthly cadence broken by gaps longer than {MAX_GAP_DAYS} days at "
            f"{long_gaps[:5]}"
        )

    implausible = [
        (observation.series_id, observation.reference_date, observation.value)
        for observation in observations
        if not MIN_PLAUSIBLE_INDEX <= observation.value <= MAX_PLAUSIBLE_INDEX
    ]
    if implausible:
        raise ValueError(
            f"DEFRA API published index values outside the plausible "
            f"[{MIN_PLAUSIBLE_INDEX}, {MAX_PLAUSIBLE_INDEX}] envelope, for example "
            f"{implausible[:5]}; check for an unannounced rebasing at source"
        )

    logger.info(
        "DEFRA API validation passed: %d series, %d reference dates, %s to %s (base %d = 100)",
        len(natives),
        len(dates),
        dates[0],
        dates[-1],
        BASE_YEAR,
    )


def collect(client: httpx.Client) -> SourceData:
    """Download, parse and validate the current-base DEFRA agricultural price index."""
    page = fetch_page(client, PAGE_URL)
    releases = release_timestamps(page)
    if not releases:
        raise ValueError(f"No publication history found on {PAGE_URL}; the page layout changed")
    last_publish_date = releases[-1].astimezone(UTC).date()
    logger.info(
        "DEFRA API page carries %d official release timestamps, %s to %s",
        len(releases),
        releases[0].astimezone(UTC).date(),
        last_publish_date,
    )

    csv_url = find_attachment(page, PAGE_URL, CSV_PATTERN)
    csv_body, csv_digest, csv_etag, csv_last_modified = download(client, csv_url)
    csv_snapshot = build_snapshot(
        source_id=SOURCE_ID,
        source_url=csv_url,
        filename=csv_url.rsplit("/", 1)[-1],
        body=csv_body,
        digest=csv_digest,
        etag=csv_etag,
        last_modified=csv_last_modified,
        fetched_at=datetime.now(UTC),
        source_published_date=last_publish_date,
    )
    observations, natives = parse_csv(csv_body, csv_url, csv_digest)
    validate(observations, natives)
    return SourceData(
        source_id=SOURCE_ID,
        source_url=PAGE_URL,
        catalog=_build_catalog(natives, last_publish_date),
        observations=observations,
        releases=releases,
        snapshots=[csv_snapshot],
        min_lag_days=MIN_LAG_DAYS,
        max_lag_days=MAX_LAG_DAYS,
        inferred_lag_days=INFERRED_LAG_DAYS,
        last_publish_date=last_publish_date,
    )
