"""DEFRA UK milk prices and composition of milk: monthly farm-gate milk series.

Official page:
https://www.gov.uk/government/statistics/uk-milk-prices-and-composition-of-milk

DEFRA publishes this data set as a single ODS workbook. There is no CSV
rendering, so the workbook's ``Prices_Monthly`` sheet is the authoritative
artifact and the only one parsed. Its ``Prices_Annual`` sheet restates the same
monthly figures as calendar-year averages; that is an aggregation DEFRA
performed, and the research layer builds its own from the monthly series, so it
is not collected.

Five variables are published per month:

===========================  ======================  =============
Published column             Series                  Fleet unit
===========================  ======================  =============
Price (pence per litre)      ``PRICE``               currency
Volume (million litres)      ``VOLUME``              other
Weekly average volume        ``WEEKLYAVGVOLUME``     other
Butterfat (%)                ``BUTTERFAT``           percent
Protein (%)                  ``PROTEIN``             percent
===========================  ======================  =============

The price series reaches back to January 1970; the composition and volume
series begin in the mid-1990s. Each column is stored only where it is actually
published, so a series starts at its own first published month rather than
being back-filled with nulls.

The price is stored in pence per litre exactly as DEFRA publishes it. It is not
converted to pounds: a unit conversion is a transformation, and the published
unit is recorded in the series name and description instead.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Any

import httpx
from odf import teletype
from odf.opendocument import load
from odf.table import CoveredTableCell, Table, TableCell, TableRow

from scripts.govuk import SourceData, download, fetch_page, find_attachment, release_timestamps
from scripts.snapshots import build_snapshot
from scripts.time_series import Observation

logger = logging.getLogger(__name__)

SOURCE_ID = "defra_milk_prices"
PAGE_URL = (
    "https://www.gov.uk/government/statistics/uk-milk-prices-and-composition-of-milk"
)

# The machine-readable attachment. Its published name carries the release date,
# so only the stable stem is matched. The methodology PDF and ODT on the same
# page are documentation, not data, and are not matched.
ODS_PATTERN = r"milkprice_dataset[^/]*\.ods"

MONTHLY_SHEET = "Prices_Monthly"

# Verified against the live workbook on 2026-09-16. DEFRA appends footnote
# markers such as "[1,2,4]" to header labels and moves them between releases,
# so headers are compared with the markers stripped: a footnote change is
# cosmetic, while a column rename is not.
EXPECTED_HEADERS = (
    "month",
    "price(pence per litre)",
    "volume(million litres)",
    "weekly average volume (million litres)",
    "butterfat(%)",
    "protein(%)",
)

# Column index -> (identifier token, fleet unit, published unit, description).
COLUMNS: dict[int, tuple[str, str, str, str]] = {
    1: (
        "PRICE",
        "currency",
        "pence per litre",
        "Average farm-gate price paid to UK producers for milk",
    ),
    2: (
        "VOLUME",
        "other",
        "million litres",
        "Volume of milk delivered to dairies in the United Kingdom",
    ),
    3: (
        "WEEKLYAVGVOLUME",
        "other",
        "million litres",
        "Weekly average volume of milk delivered to dairies in the United Kingdom",
    ),
    4: ("BUTTERFAT", "percent", "%", "Average butterfat content of UK milk deliveries"),
    5: ("PROTEIN", "percent", "%", "Average protein content of UK milk deliveries"),
}

# Observed release schedule: the reference month is published roughly eight
# weeks later on the last Thursday of the month (July 2026 data was published
# 2026-08-27, June 2026 data on 2026-07-30, May 2026 data on 2026-06-25). The
# change history begins 2013-04-30, far later than the 1970 start of the price
# series, so most of the history falls back to the inferred rule.
MIN_LAG_DAYS = 40
MAX_LAG_DAYS = 80
INFERRED_LAG_DAYS = 57

EXPECTED_FIRST_OBSERVATION = date(1970, 1, 1)
MIN_EXPECTED_SERIES = 5
MIN_EXPECTED_DATES = 650
# Monthly cadence, with one documented break: DEFRA publishes no November or
# December 1994, so consecutive published months are up to three months apart.
MAX_GAP_DAYS = 95

# Per-series plausibility envelopes in the published unit. Wide on purpose:
# these are source-drift guards against a unit change or a decimal shift, not
# economic forecasts. The price floor accommodates the 1970 start at ~4p/litre.
PLAUSIBLE_RANGE: dict[str, tuple[float, float]] = {
    "PRICE": (1.0, 200.0),
    "VOLUME": (100.0, 3000.0),
    "WEEKLYAVGVOLUME": (20.0, 700.0),
    "BUTTERFAT": (2.0, 6.0),
    "PROTEIN": (2.0, 5.0),
}

MISSING_VALUES = frozenset({"", "*", "-", "..", "n/a", "na", ":"})
# A generous ceiling on a repeated-cell run, so a malformed workbook cannot
# expand into an unbounded row.
MAX_COLUMNS = 40
_CELL_QNAMES = frozenset({TableCell().qname, CoveredTableCell().qname})
_FOOTNOTE_MARKER = re.compile(r"\[[\d,\s]+\]")


def make_series_id(variable: str) -> str:
    """Build ``DEFRA_MILK_{VARIABLE}`` for one published column."""
    series_id = f"DEFRA_MILK_{variable}"
    if len(series_id) > 200:
        raise ValueError(f"series_id exceeds 200 characters: {series_id}")
    return series_id


def parse_series_id(series_id: str) -> tuple[str, str, str]:
    """Decode ``DEFRA_MILK_{VARIABLE}`` into its three parts."""
    parts = series_id.split("_", 2)
    if len(parts) != 3 or parts[0] != "DEFRA" or parts[1] != "MILK" or not parts[2]:
        raise ValueError(f"Invalid DEFRA milk series_id: {series_id}")
    source, dataset, variable = parts
    if variable not in {token for token, _, _, _ in COLUMNS.values()}:
        raise ValueError(f"Unknown DEFRA milk variable in series_id: {series_id}")
    return source, dataset, variable


def _normalise_header(raw: str) -> str:
    """Strip DEFRA's footnote markers and collapse whitespace in a header."""
    return re.sub(r"\s+", " ", _FOOTNOTE_MARKER.sub("", raw)).strip().lower()


def _cell_values(row: TableRow) -> list[str]:
    """Expand one ODS row into a flat list of cell strings, honouring repeats."""
    expanded: list[str] = []
    for cell in row.childNodes:
        if cell.qname not in _CELL_QNAMES:
            continue
        repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
        date_value = cell.getAttribute("datevalue")
        value = cell.getAttribute("value")
        text = date_value or (value if value is not None else teletype.extractText(cell).strip())
        # A trailing run of empty cells is padding the writer emitted, not data.
        if repeat > MAX_COLUMNS:
            repeat = 1
        remaining = MAX_COLUMNS - len(expanded)
        if remaining <= 0:
            break
        expanded.extend([text] * min(repeat, remaining))
    return expanded


def _assert_schema(header: list[str], url: str) -> None:
    """Refuse a workbook whose published layout no longer matches the verified one."""
    found = tuple(_normalise_header(cell) for cell in header[: len(EXPECTED_HEADERS)])
    if found != EXPECTED_HEADERS:
        raise ValueError(
            f"DEFRA milk workbook {url} sheet {MONTHLY_SHEET} header is {found}, expected "
            f"{EXPECTED_HEADERS}; the published layout changed and must be re-verified "
            "against the official source"
        )


def parse_ods(
    body: bytes, url: str, snapshot_id: str
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Parse the monthly sheet into observations and their native labels."""
    document = load(io.BytesIO(body))
    sheets = {
        str(table.getAttribute("name")): table for table in document.getElementsByType(Table)
    }
    if MONTHLY_SHEET not in sheets:
        raise ValueError(
            f"DEFRA milk workbook {url} has no {MONTHLY_SHEET} sheet; found "
            f"{sorted(sheets)}. The published layout changed and must be re-verified."
        )

    rows = [_cell_values(row) for row in sheets[MONTHLY_SHEET].getElementsByType(TableRow)]
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and _normalise_header(row[0]) == EXPECTED_HEADERS[0]
        ),
        None,
    )
    if header_index is None:
        raise ValueError(
            f"DEFRA milk workbook {url} sheet {MONTHLY_SHEET} has no '{EXPECTED_HEADERS[0]}' "
            "header row; the published layout changed"
        )
    _assert_schema(rows[header_index], url)

    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    for row in rows[header_index + 1 :]:
        if not row or not row[0].strip():
            continue
        raw_month = row[0].strip()
        if not re.match(r"^(19|20)\d\d-\d\d-\d\d", raw_month):
            # Footer rows (copyright, notes) trail the data block.
            continue
        published_date = date.fromisoformat(raw_month[:10])
        # DEFRA is not internally consistent about how it stamps a month: rows
        # from 2017-01 to 2023-12 carry the last day of the month while every
        # other row carries the first. Both denote the same monthly reference
        # period, so the reference date is canonicalised to the first of the
        # month. `validate` then asserts the result is still one row per month,
        # which is what makes this a safe normalisation rather than a guess.
        reference_date = published_date.replace(day=1)
        for column, (variable, _unit, published_unit, _text) in COLUMNS.items():
            if column >= len(row):
                continue
            raw = row[column].strip()
            if raw.lower() in MISSING_VALUES:
                continue
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(
                    f"DEFRA milk workbook {url} has unparseable {variable} value {raw!r} at "
                    f"{reference_date}"
                ) from exc
            series_id = make_series_id(variable)
            natives.setdefault(series_id, {"variable": variable, "unit": published_unit})
            observations.append(
                Observation(
                    series_id=series_id,
                    reference_date=reference_date,
                    value=value,
                    snapshot_id=snapshot_id,
                )
            )
    return observations, natives


def _build_catalog(
    natives: dict[str, dict[str, str]], last_publish_date: date | None
) -> dict[str, dict[str, Any]]:
    """Describe every collected series from its verified native labels."""
    catalog: dict[str, dict[str, Any]] = {}
    by_token = {token: (unit, published, text) for token, unit, published, text in COLUMNS.values()}
    for series_id, fields in natives.items():
        variable = fields["variable"]
        fleet_unit, published_unit, text = by_token[variable]
        catalog[series_id] = {
            "source_id": SOURCE_ID,
            "name": f"UK milk: {text.split(' in the United Kingdom')[0]} ({published_unit})",
            "description": (
                f"{text}, in {published_unit}, monthly, as published by the Department for "
                "Environment, Food & Rural Affairs. Stored exactly as published, in the "
                "published unit, with no derived transformation and no annual aggregation."
            ),
            "frequency": "monthly",
            "unit": fleet_unit,
            "eco_group": "producer_prices",
            "source_url": PAGE_URL,
            "last_publish_date": last_publish_date,
        }
    return catalog


def validate(observations: list[Observation], natives: dict[str, dict[str, str]]) -> None:
    """Gate the parsed panel before anything reaches the database."""
    if not observations:
        raise ValueError("DEFRA milk collection produced no observations")
    if len(natives) < MIN_EXPECTED_SERIES:
        raise ValueError(
            f"DEFRA milk returned only {len(natives)} series, below the "
            f"{MIN_EXPECTED_SERIES} floor; the published layout probably changed"
        )

    keys = [(observation.series_id, observation.reference_date) for observation in observations]
    if len(keys) != len(set(keys)):
        counts: dict[tuple[str, date], int] = {}
        for observation_key in keys:
            counts[observation_key] = counts.get(observation_key, 0) + 1
        duplicates = sorted(key for key, count in counts.items() if count > 1)[:5]
        raise ValueError(f"DEFRA milk published duplicate observations, for example {duplicates}")

    dates = sorted({observation.reference_date for observation in observations})
    if dates[0] != EXPECTED_FIRST_OBSERVATION:
        raise ValueError(
            f"DEFRA milk history starts at {dates[0]}, expected {EXPECTED_FIRST_OBSERVATION}; "
            "the published file changed and must be re-verified"
        )
    if len(dates) < MIN_EXPECTED_DATES:
        raise ValueError(
            f"DEFRA milk returned only {len(dates)} reference months, below the "
            f"{MIN_EXPECTED_DATES} floor; the download was probably truncated"
        )
    if dates[-1] > datetime.now(UTC).date():
        raise ValueError(f"DEFRA milk published a future reference date {dates[-1]}")

    long_gaps = [
        (earlier, later)
        for earlier, later in pairwise(dates)
        if (later - earlier).days > MAX_GAP_DAYS
    ]
    if long_gaps:
        raise ValueError(
            f"DEFRA milk monthly cadence broken by gaps longer than {MAX_GAP_DAYS} days at "
            f"{long_gaps[:5]}"
        )

    # Each published column carries its own unit, so plausibility is checked
    # per series rather than against one global envelope.
    for observation in observations:
        variable = observation.series_id.rsplit("_", 1)[-1]
        low, high = PLAUSIBLE_RANGE[variable]
        if not low <= observation.value <= high:
            raise ValueError(
                f"DEFRA milk published {observation.series_id} = {observation.value} at "
                f"{observation.reference_date}, outside the plausible [{low}, {high}] "
                "envelope; check for a unit or decimal change at source"
            )

    logger.info(
        "DEFRA milk validation passed: %d series, %d reference months, %s to %s",
        len(natives),
        len(dates),
        dates[0],
        dates[-1],
    )


def collect(client: httpx.Client) -> SourceData:
    """Download, parse and validate the full DEFRA milk price history."""
    page = fetch_page(client, PAGE_URL)
    releases = release_timestamps(page)
    if not releases:
        raise ValueError(f"No publication history found on {PAGE_URL}; the page layout changed")
    last_publish_date = releases[-1].astimezone(UTC).date()
    logger.info(
        "DEFRA milk page carries %d official release timestamps, %s to %s",
        len(releases),
        releases[0].astimezone(UTC).date(),
        last_publish_date,
    )

    ods_url = find_attachment(page, PAGE_URL, ODS_PATTERN)
    ods_body, ods_digest, ods_etag, ods_last_modified = download(client, ods_url)
    ods_snapshot = build_snapshot(
        source_id=SOURCE_ID,
        source_url=ods_url,
        filename=ods_url.rsplit("/", 1)[-1],
        body=ods_body,
        digest=ods_digest,
        etag=ods_etag,
        last_modified=ods_last_modified,
        fetched_at=datetime.now(UTC),
        source_published_date=last_publish_date,
    )
    observations, natives = parse_ods(ods_body, ods_url, ods_digest)
    validate(observations, natives)
    return SourceData(
        source_id=SOURCE_ID,
        source_url=PAGE_URL,
        catalog=_build_catalog(natives, last_publish_date),
        observations=observations,
        releases=releases,
        snapshots=[ods_snapshot],
        min_lag_days=MIN_LAG_DAYS,
        max_lag_days=MAX_LAG_DAYS,
        inferred_lag_days=INFERRED_LAG_DAYS,
        last_publish_date=last_publish_date,
    )
