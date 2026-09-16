"""DEFRA Banana prices: weekly wholesale banana prices by origin.

Official page:
https://www.gov.uk/government/statistical-data-sets/banana-prices

DEFRA publishes this data set as a tidy machine-readable CSV whose weekly
history begins in January 1995, alongside two ODS workbooks that restate the
same figures for presentation. Only the CSV is parsed: it is the single
authoritative machine-readable artifact and carries the full history, so
reconciling a second rendering of the same numbers would add a failure mode
without adding an observation.

Prices are stored exactly as published, per origin, in GBP per kilogram. The
file already carries DEFRA's own published aggregates (``all_bananas``,
``dollar_bananas``, ``acp_bananas``); those are collected as published series
because DEFRA computed them, but no aggregate is constructed here.

Label normalisation
-------------------
DEFRA renamed its aggregate rows at the 2018/2019 boundary: ``all_bananas``
was published as ``all_bananas_bananas`` up to 2018-12-21 and as
``all_bananas`` from 2019-01-11, with no overlapping week. The same doubled
suffix affects the dollar and ACP aggregates. That is a cosmetic relabelling of
one economic series, so a repeated trailing ``_bananas`` token is collapsed and
the two segments form one continuous history. The rule collapses a *doubled*
token only; ``eu_bananas`` and ``eu`` are left as the distinct published rows
they are, because nothing in the source establishes that they are one series.
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

SOURCE_ID = "defra_banana_prices"
PAGE_URL = "https://www.gov.uk/government/statistical-data-sets/banana-prices"

# The machine-readable attachment. Its published name carries the latest
# reference week, so only the stable stem is matched. The two ODS workbooks on
# the same page (`bananas-weekly-*.ods`, `bananas-current-*.ods`) restate the
# CSV and are deliberately not matched.
CSV_PATTERN = r"bananas-\d[^/]*\.csv"

# Verified against the live CSV header on 2026-09-16.
EXPECTED_COLUMNS = ("origin", "date", "price", "units")

# The only unit the file has ever published. A change here is a unit change, not
# a formatting change, and must stop collection.
EXPECTED_UNIT = "£/kg"

# Observed release schedule, measured over the 320 reference weeks the change
# history covers: the Friday reference week is published the following Monday
# in 207 cases and the Tuesday after in 61, with a handful of later catch-ups.
# The change history begins 2019-07-21, long after the 1995 history starts, so
# the great majority of observations fall back to the inferred rule.
MIN_LAG_DAYS = 0
MAX_LAG_DAYS = 21
INFERRED_LAG_DAYS = 3

EXPECTED_FIRST_OBSERVATION = date(1995, 1, 13)
# The published cadence is weekly, but the file carries seasonal breaks and a
# few multi-week gaps across thirty years of history.
MAX_GAP_DAYS = 90
MIN_EXPECTED_SERIES = 25
MIN_EXPECTED_DATES = 1400

# Plausibility envelope for a wholesale banana price in GBP per kilogram,
# deliberately wide: it is a source-drift guard against a unit change or a
# decimal shift, not an economic forecast.
MIN_PLAUSIBLE_PRICE = 0.05
MAX_PLAUSIBLE_PRICE = 10.0

# DEFRA's own published aggregate rows, kept as published and flagged in
# metadata so the research layer never double-counts them as origins.
AGGREGATE_ORIGINS = frozenset({"all_bananas", "dollar_bananas", "acp_bananas"})

_DOUBLED_SUFFIX = re.compile(r"_bananas_bananas$", re.IGNORECASE)


def normalise_origin(raw: str) -> str:
    """Collapse DEFRA's doubled ``_bananas_bananas`` suffix to one token.

    Only a *repeated* trailing token is collapsed, so ``all_bananas_bananas``
    becomes ``all_bananas`` while ``eu_bananas`` is left untouched.
    """
    origin = raw.strip().lower()
    if not origin:
        raise ValueError("DEFRA banana file carries a blank origin")
    return _DOUBLED_SUFFIX.sub("_bananas", origin)


def _token(raw: str) -> str:
    """Normalize one native label into an uppercase identifier token."""
    token = re.sub(r"[^A-Z0-9]+", "", raw.strip().upper())
    if not token:
        raise ValueError(f"DEFRA banana label {raw!r} normalizes to an empty identifier token")
    return token


def make_series_id(origin: str) -> str:
    """Build ``DEFRA_BANANA_{ORIGIN}`` from a normalised native origin."""
    series_id = f"DEFRA_BANANA_{_token(origin)}"
    if len(series_id) > 200:
        raise ValueError(f"series_id exceeds 200 characters: {series_id}")
    return series_id


def parse_series_id(series_id: str) -> tuple[str, str, str]:
    """Decode ``DEFRA_BANANA_{ORIGIN}`` into its three parts."""
    parts = series_id.split("_", 2)
    if len(parts) != 3 or parts[0] != "DEFRA" or parts[1] != "BANANA" or not parts[2]:
        raise ValueError(f"Invalid DEFRA banana series_id: {series_id}")
    source, dataset, origin = parts
    return source, dataset, origin


def _assert_schema(fieldnames: Sequence[str] | None, url: str) -> None:
    """Refuse a file whose published layout no longer matches the verified one."""
    if not fieldnames:
        raise ValueError(f"DEFRA banana file {url} has no header row")
    header = tuple(name.strip().lower() for name in fieldnames)
    if header != EXPECTED_COLUMNS:
        raise ValueError(
            f"DEFRA banana file {url} header is {header}, expected {EXPECTED_COLUMNS}; the "
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
        origin = normalise_origin(str(row["Origin"]))
        unit = str(row["Units"]).strip()
        if unit != EXPECTED_UNIT:
            raise ValueError(
                f"DEFRA banana file {url} line {line} publishes unit {unit!r}, expected "
                f"{EXPECTED_UNIT!r}; a unit change must be re-verified before collection"
            )
        raw_price = str(row["Price"]).strip()
        if not raw_price:
            # A blank price is an unpublished week, not a zero.
            continue
        try:
            value = float(raw_price)
        except ValueError as exc:
            raise ValueError(
                f"DEFRA banana file {url} line {line} has unparseable price {raw_price!r}"
            ) from exc
        try:
            reference_date = date.fromisoformat(str(row["Date"]).strip())
        except ValueError as exc:
            raise ValueError(
                f"DEFRA banana file {url} line {line} has unparseable date {row['Date']!r}"
            ) from exc

        series_id = make_series_id(origin)
        natives.setdefault(series_id, {"origin": origin, "unit": unit})
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
        origin = fields["origin"]
        readable = _label(origin)
        if origin in AGGREGATE_ORIGINS:
            name = f"UK wholesale banana price: {readable} (GBP per kg)"
            description = (
                f"Weekly average wholesale price of {readable} in the United Kingdom, in GBP "
                "per kilogram, as published by the Department for Environment, Food & Rural "
                "Affairs. This is DEFRA's own published aggregate across origins, stored as "
                "published; it is not computed here and overlaps the individual origin series."
            )
        else:
            name = f"UK wholesale banana price, origin {readable} (GBP per kg)"
            description = (
                f"Weekly average wholesale price of bananas of {readable} origin in the "
                "United Kingdom, in GBP per kilogram, as published by the Department for "
                "Environment, Food & Rural Affairs. Stored at the published reference dates "
                "with no derived transformation."
            )
        catalog[series_id] = {
            "source_id": SOURCE_ID,
            "name": name,
            "description": description,
            "frequency": "weekly",
            "unit": "currency",
            "eco_group": "producer_prices",
            "source_url": PAGE_URL,
            "last_publish_date": last_publish_date,
        }
    return catalog


def validate(observations: list[Observation], natives: dict[str, dict[str, str]]) -> None:
    """Gate the parsed panel before anything reaches the database."""
    if not observations:
        raise ValueError("DEFRA banana collection produced no observations")
    if len(natives) < MIN_EXPECTED_SERIES:
        raise ValueError(
            f"DEFRA banana returned only {len(natives)} series, below the "
            f"{MIN_EXPECTED_SERIES} floor; the download was probably truncated"
        )

    # Normalization must stay injective, or two published origins would share
    # one stored history.
    by_series: dict[str, set[str]] = {}
    for series_id, fields in natives.items():
        by_series.setdefault(series_id, set()).add(fields["origin"])
    clashing = {sid: origins for sid, origins in by_series.items() if len(origins) > 1}
    if clashing:
        raise ValueError(f"DEFRA banana identifier normalization collided: {clashing}")

    keys = [(observation.series_id, observation.reference_date) for observation in observations]
    if len(keys) != len(set(keys)):
        counts: dict[tuple[str, date], int] = {}
        for observation_key in keys:
            counts[observation_key] = counts.get(observation_key, 0) + 1
        duplicates = sorted(key for key, count in counts.items() if count > 1)[:5]
        raise ValueError(
            f"DEFRA banana published duplicate observations, for example {duplicates}. The "
            "doubled-suffix normalisation may have merged two genuinely distinct origins."
        )

    dates = sorted({observation.reference_date for observation in observations})
    if dates[0] != EXPECTED_FIRST_OBSERVATION:
        raise ValueError(
            f"DEFRA banana history starts at {dates[0]}, expected {EXPECTED_FIRST_OBSERVATION}; "
            "the published file changed and must be re-verified"
        )
    if len(dates) < MIN_EXPECTED_DATES:
        raise ValueError(
            f"DEFRA banana returned only {len(dates)} reference dates, below the "
            f"{MIN_EXPECTED_DATES} floor; the download was probably truncated"
        )
    if dates[-1] > datetime.now(UTC).date():
        raise ValueError(f"DEFRA banana published a future reference date {dates[-1]}")

    long_gaps = [
        (earlier, later)
        for earlier, later in pairwise(dates)
        if (later - earlier).days > MAX_GAP_DAYS
    ]
    if long_gaps:
        raise ValueError(
            f"DEFRA banana cadence broken by gaps longer than {MAX_GAP_DAYS} days at "
            f"{long_gaps[:5]}"
        )

    implausible = [
        (observation.series_id, observation.reference_date, observation.value)
        for observation in observations
        if not MIN_PLAUSIBLE_PRICE <= observation.value <= MAX_PLAUSIBLE_PRICE
    ]
    if implausible:
        raise ValueError(
            f"DEFRA banana published prices outside the plausible "
            f"[{MIN_PLAUSIBLE_PRICE}, {MAX_PLAUSIBLE_PRICE}] GBP/kg envelope, for example "
            f"{implausible[:5]}; check for a unit or decimal change at source"
        )

    logger.info(
        "DEFRA banana validation passed: %d series, %d reference dates, %s to %s",
        len(natives),
        len(dates),
        dates[0],
        dates[-1],
    )


def collect(client: httpx.Client) -> SourceData:
    """Download, parse and validate the full DEFRA banana price history."""
    page = fetch_page(client, PAGE_URL)
    releases = release_timestamps(page)
    if not releases:
        raise ValueError(f"No publication history found on {PAGE_URL}; the page layout changed")
    last_publish_date = releases[-1].astimezone(UTC).date()
    logger.info(
        "DEFRA banana page carries %d official release timestamps, %s to %s",
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
