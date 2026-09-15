"""DEFRA Wholesale fruit and vegetable prices: average home-grown produce prices.

Official page:
https://www.gov.uk/government/statistical-data-sets/wholesale-fruit-and-vegetable-prices-weekly-average

DEFRA publishes a tidy machine-readable CSV from November 2017 onward and an
official ODS workbook whose weekly history begins in January 2015. Both are
parsed. The CSV wins deterministic overlap deduplication after a value check;
the ODS supplies the earlier history and observations absent from the CSV.

The dataset also carries ``cut_flowers`` and ``pot_plants`` categories. Those
are out of scope for a consumer price predictor layer and are filtered out
explicitly rather than silently, so a new category appearing upstream is
reported instead of being swept in.

Prices are stored exactly as published, per product and per published unit. No
aggregate fruit, vegetable or food index is constructed here: building one would
be a modelling decision, not a collection one.
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
from odf import teletype
from odf.opendocument import load
from odf.table import CoveredTableCell, Table, TableCell, TableRow

from scripts.govuk import SourceData, download, fetch_page, find_attachment, release_timestamps
from scripts.snapshots import build_snapshot
from scripts.time_series import Observation

logger = logging.getLogger(__name__)

SOURCE_ID = "defra_fruit_veg"
PAGE_URL = (
    "https://www.gov.uk/government/statistical-data-sets/"
    "wholesale-fruit-and-vegetable-prices-weekly-average"
)

# The machine-readable attachment. Its published name carries the latest
# reference week, so only the stable stem is matched.
CSV_PATTERN = r"fruitvegprices[^/]*\.csv"
ODS_PATTERN = r"fruitveg-weeklyhort[^/]*\.ods"

# Verified against the live CSV header on 2026-09-15.
EXPECTED_COLUMNS = ("category", "item", "variety", "date", "price", "unit")

# Categories this predictor layer collects. Anything else on the page is a
# horticultural product that does not enter consumer food prices.
COLLECTED_CATEGORIES = frozenset({"fruit", "vegetable"})
KNOWN_IGNORED_CATEGORIES = frozenset({"cut_flowers", "pot_plants"})

# Published price units. All are a GBP amount per the stated physical unit, so
# the fleet `unit` is currency and the physical unit is preserved in the name
# and description of each series.
KNOWN_UNITS = frozenset({"kg", "head", "twin", "unit", "stem", "bunch", "cob"})

# Observed release schedule: a release can carry its own reference day, and the
# modal lag is three days. The page's change history begins 2017-01-05, before
# the first observation, so in practice every observation is attributable to an
# official timestamp and the inferred rule is a fallback only.
MIN_LAG_DAYS = 0
MAX_LAG_DAYS = 31
INFERRED_LAG_DAYS = 3

EXPECTED_FIRST_OBSERVATION = date(2015, 1, 9)
# Measured cadence over the full history: mostly weekly, with fortnightly runs
# and occasional seasonal gaps. The source describes itself as a fortnightly
# series, so the stored frequency is `irregular` rather than a false `weekly`.
MAX_GAP_DAYS = 45
MIN_EXPECTED_SERIES = 100
MIN_EXPECTED_DATES = 500

# The ODS displays prices to two decimal places while some formula cells retain
# longer binary values. The two official artifacts can consequently differ by
# one penny at a handful of overlap cells. Anything larger is material and
# blocks collection rather than silently choosing one source.
OVERLAP_TOLERANCE = 0.011
MAX_ODS_COLUMNS = 180
REQUIRED_ODS_SHEETS = frozenset({"2016-2015", "2017-2016"})
ODS_MISSING_VALUES = frozenset({"", "*", "-", "..", "n/a", "na"})
_ODS_CELL_QNAMES = frozenset({TableCell().qname, CoveredTableCell().qname})


def _token(raw: str) -> str:
    """Normalize one native label into an uppercase identifier token."""
    token = re.sub(r"[^A-Z0-9]+", "", raw.strip().upper())
    if not token:
        raise ValueError(f"DEFRA label {raw!r} normalizes to an empty identifier token")
    return token


def make_series_id(category: str, item: str, variety: str) -> str:
    """Build ``DEFRA_FRUITVEG_{CATEGORY}_{ITEM}_{VARIETY}`` from native labels.

    The native labels stay in metadata. Normalization is verified to be
    collision-free across all 71 published fruit and vegetable series, and
    ``validate`` re-checks that on every run rather than trusting it.
    """
    series_id = f"DEFRA_FRUITVEG_{_token(category)}_{_token(item)}_{_token(variety)}"
    if len(series_id) > 200:
        raise ValueError(f"series_id exceeds 200 characters: {series_id}")
    return series_id


def parse_series_id(series_id: str) -> tuple[str, str, str, str, str]:
    """Decode ``DEFRA_FRUITVEG_{CATEGORY}_{ITEM}_{VARIETY}`` into its five parts."""
    parts = series_id.split("_")
    if len(parts) != 5 or parts[0] != "DEFRA" or parts[1] != "FRUITVEG":
        raise ValueError(f"Invalid DEFRA fruit and vegetable series_id: {series_id}")
    source, dataset, category, item, variety = parts
    if not category or not item or not variety:
        raise ValueError(f"Incomplete DEFRA fruit and vegetable series_id: {series_id}")
    return source, dataset, category, item, variety


def _assert_schema(fieldnames: Sequence[str] | None, url: str) -> None:
    """Refuse a file whose published layout no longer matches the verified one."""
    if not fieldnames:
        raise ValueError(f"DEFRA file {url} has no header row")
    header = tuple(name.strip().lower() for name in fieldnames)
    if header != EXPECTED_COLUMNS:
        raise ValueError(
            f"DEFRA file {url} header is {header}, expected {EXPECTED_COLUMNS}; the published "
            "layout changed and must be re-verified against the official source"
        )


def _parse_csv(
    body: bytes, url: str, snapshot_id: str
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Parse the DEFRA CSV into observations plus the native labels per series."""
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    _assert_schema(reader.fieldnames, url)
    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    ignored: set[str] = set()
    skipped = 0
    for row in reader:
        category = (row.get("category") or "").strip().lower()
        if category not in COLLECTED_CATEGORIES:
            ignored.add(category)
            continue
        item = (row.get("item") or "").strip().lower()
        variety = (row.get("variety") or "").strip().lower()
        unit = (row.get("unit") or "").strip().lower()
        raw_date = (row.get("date") or "").strip()
        raw_price = (row.get("price") or "").strip()
        try:
            reference_date = date.fromisoformat(raw_date)
            price = float(raw_price)
            series_id = make_series_id(category, item, variety)
        except ValueError:
            # One malformed record is a soft failure: warn and skip it.
            logger.warning("DEFRA %s: unreadable row %r; skipping", url, row)
            skipped += 1
            continue
        if unit not in KNOWN_UNITS:
            raise ValueError(
                f"DEFRA published unverified price unit {unit!r} for {series_id}; "
                "the unit vocabulary must be re-verified against the official source"
            )
        existing = natives.get(series_id)
        if existing is not None and existing["unit"] != unit:
            raise ValueError(
                f"DEFRA published {series_id} in two units, {existing['unit']!r} and {unit!r}; "
                "one series must carry one unit"
            )
        natives[series_id] = {
            "category": category,
            "item": item,
            "variety": variety,
            "unit": unit,
        }
        observations.append(
            Observation(
                series_id=series_id,
                reference_date=reference_date,
                value=price,
                snapshot_id=snapshot_id,
            )
        )
    unexpected = ignored - KNOWN_IGNORED_CATEGORIES - {""}
    if unexpected:
        # Not a hard failure: a new horticultural category does not corrupt the
        # collected ones, but it must never pass unreported.
        logger.warning(
            "DEFRA published unrecognised categories %s, which were not collected; "
            "review whether they belong in this predictor layer",
            sorted(unexpected),
        )
    if skipped:
        logger.warning("DEFRA %s: skipped %d unreadable rows", url, skipped)
    logger.info(
        "DEFRA %s: parsed %d observations across %d series", url, len(observations), len(natives)
    )
    return observations, natives


def _normalise_label(raw: str) -> str:
    """Normalize an ODS label to the snake-case vocabulary used by the CSV."""
    without_footnote = re.sub(r"\s*\([a-z]\)\s*$", "", raw.strip(), flags=re.IGNORECASE)
    expanded = without_footnote.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "_", expanded).strip("_")


def _normalise_ods_unit(raw: str) -> str:
    """Return the physical unit encoded by an ODS ``£/<unit>`` label."""
    unit = raw.strip().lower().removeprefix("£/")
    if unit == "each":
        unit = "unit"
    if unit not in KNOWN_UNITS:
        raise ValueError(f"DEFRA ODS published unverified price unit {raw!r}")
    return unit


def _expand_ods_row(row: Any) -> list[tuple[str, date | None]]:
    """Expand repeated and covered ODS cells up to the source's useful width."""
    expanded: list[tuple[str, date | None]] = []
    for cell in row.childNodes:
        if getattr(cell, "qname", None) not in _ODS_CELL_QNAMES:
            continue
        repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
        raw_date = cell.getAttribute("datevalue")
        cell_date = date.fromisoformat(raw_date[:10]) if raw_date else None
        value = (teletype.extractText(cell) or "").strip()
        remaining = MAX_ODS_COLUMNS - len(expanded)
        expanded.extend([(value, cell_date)] * min(repeat, remaining))
        if len(expanded) == MAX_ODS_COLUMNS:
            break
    return expanded


def _sheet_priority(name: str) -> int:
    """Prefer the newest official worksheet when annual tabs overlap."""
    if name.isdigit():
        return 10_000 + int(name)
    if name == "2017-2016":
        return 2017
    if name == "2016-2015":
        return 2016
    return 0


def _parse_ods(
    body: bytes, url: str, snapshot_id: str
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Parse the official 2015-present ODS workbook at displayed precision."""
    document = load(io.BytesIO(body))
    tables = document.spreadsheet.getElementsByType(Table)
    table_names = {str(table.getAttribute("name")) for table in tables}
    missing_sheets = REQUIRED_ODS_SHEETS - table_names
    if missing_sheets:
        raise ValueError(f"DEFRA ODS {url} is missing historical sheets {sorted(missing_sheets)}")

    by_key: dict[tuple[str, date], Observation] = {}
    natives: dict[str, dict[str, str]] = {}
    internal_revisions = 0
    parsed_sheets = 0
    for table in sorted(
        tables, key=lambda item: _sheet_priority(str(item.getAttribute("name"))), reverse=True
    ):
        sheet_name = str(table.getAttribute("name"))
        if _sheet_priority(sheet_name) == 0:
            continue
        rows = [_expand_ods_row(row) for row in table.getElementsByType(TableRow)]
        date_row_index = next(
            (
                index
                for index, row in enumerate(rows)
                if any(value == "Week ending" for value, _ in row)
            ),
            None,
        )
        if date_row_index is None:
            raise ValueError(f"DEFRA ODS sheet {sheet_name!r} has no 'Week ending' row")
        date_row = rows[date_row_index]
        date_start = next(
            index for index, (value, _) in enumerate(date_row) if value == "Week ending"
        ) + 1
        reference_dates = [cell_date for _, cell_date in date_row[date_start:]]
        if not any(reference_dates):
            raise ValueError(f"DEFRA ODS sheet {sheet_name!r} has no machine-readable dates")

        modern_layout = sheet_name.isdigit()
        previous_item = ""
        sheet_observations = 0
        for row in rows[date_row_index + 2 :]:
            if modern_layout:
                if len(row) < 5:
                    continue
                category = _normalise_label(row[1][0])
                item = _normalise_label(row[2][0])
                variety = _normalise_label(row[3][0]) or item
                raw_unit = row[4][0]
            else:
                if len(row) < 5:
                    continue
                category = _normalise_label(row[0][0])
                item = _normalise_label(row[1][0])
                variety = _normalise_label(row[2][0])
                quality = row[3][0].strip().lower()
                raw_unit = row[4][0]
                # The modern file is an average-price panel. Historical first-
                # and second-quality rows are separate measures, so only the
                # published average (or ungraded single price) is stitched.
                if quality not in {"-", "ave"}:
                    continue
            if category not in COLLECTED_CATEGORIES:
                continue
            if item:
                previous_item = item
            else:
                item = previous_item
            variety = variety or item
            if not item or not variety:
                raise ValueError(
                    f"DEFRA ODS sheet {sheet_name!r} has an incomplete product label"
                )
            unit = _normalise_ods_unit(raw_unit)
            series_id = make_series_id(category, item, variety)
            descriptor = {
                "category": category,
                "item": item,
                "variety": variety,
                "unit": unit,
            }
            existing_descriptor = natives.get(series_id)
            if existing_descriptor is not None and existing_descriptor["unit"] != unit:
                # A few historical products changed quotation unit. They are
                # not one comparable level and must not be spliced together.
                variety = f"{variety}_per_{unit}"
                series_id = make_series_id(category, item, variety)
                descriptor["variety"] = variety
                existing_descriptor = natives.get(series_id)
                if existing_descriptor is not None and existing_descriptor["unit"] != unit:
                    raise ValueError(
                        f"DEFRA ODS unit-qualified identifier still collides for {series_id}"
                    )
            for offset, reference_date in enumerate(reference_dates):
                column = date_start + offset
                if reference_date is None or column >= len(row):
                    continue
                raw_value = row[column][0].replace(",", "").strip()
                if raw_value.lower() in ODS_MISSING_VALUES:
                    continue
                try:
                    value = float(raw_value)
                except ValueError as exc:
                    raise ValueError(
                        f"DEFRA ODS sheet {sheet_name!r} has non-numeric price "
                        f"{raw_value!r} for {series_id} on {reference_date}"
                    ) from exc
                natives.setdefault(series_id, descriptor)
                observation = Observation(series_id, reference_date, value, snapshot_id)
                key = (series_id, reference_date)
                existing = by_key.get(key)
                if existing is not None:
                    if abs(existing.value - value) > OVERLAP_TOLERANCE:
                        internal_revisions += 1
                    continue
                by_key[key] = observation
                sheet_observations += 1
        if sheet_observations:
            parsed_sheets += 1

    if parsed_sheets < len(REQUIRED_ODS_SHEETS) + 1:
        raise ValueError(f"DEFRA ODS {url} yielded only {parsed_sheets} populated sheets")
    if internal_revisions:
        logger.warning(
            "DEFRA ODS contains %d materially revised cells across overlapping annual tabs; "
            "the newer official worksheet wins deterministically",
            internal_revisions,
        )
    observations = sorted(by_key.values(), key=lambda row: (row.reference_date, row.series_id))
    logger.info(
        "DEFRA %s: parsed %d ODS observations across %d series and %d sheets",
        url,
        len(observations),
        len(natives),
        parsed_sheets,
    )
    return observations, natives


def _combine_artifacts(
    ods_observations: list[Observation],
    ods_natives: dict[str, dict[str, str]],
    csv_observations: list[Observation],
    csv_natives: dict[str, dict[str, str]],
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Validate ODS/CSV overlap and let the modern CSV win deduplication."""
    ods_by_key = {(row.series_id, row.reference_date): row for row in ods_observations}
    csv_by_key = {(row.series_id, row.reference_date): row for row in csv_observations}
    overlap = sorted(ods_by_key.keys() & csv_by_key.keys())
    if not overlap:
        raise ValueError("DEFRA ODS and CSV have no comparable overlap")
    material = [
        (key, ods_by_key[key].value, csv_by_key[key].value)
        for key in overlap
        if abs(ods_by_key[key].value - csv_by_key[key].value) > OVERLAP_TOLERANCE
    ]
    if material:
        raise ValueError(
            "DEFRA ODS and CSV materially disagree in overlap; examples: "
            f"{material[:5]}"
        )
    penny_rounding = sum(
        ods_by_key[key].value != csv_by_key[key].value for key in overlap
    )
    logger.info(
        "DEFRA overlap passed: %d identical/comparable cells, %d one-penny rounding differences",
        len(overlap),
        penny_rounding,
    )

    for series_id in ods_natives.keys() & csv_natives.keys():
        if ods_natives[series_id]["unit"] != csv_natives[series_id]["unit"]:
            raise ValueError(
                f"DEFRA ODS/CSV unit mismatch for {series_id}: "
                f"{ods_natives[series_id]['unit']!r} vs {csv_natives[series_id]['unit']!r}"
            )
    combined = dict(ods_by_key)
    combined.update(csv_by_key)
    natives = dict(ods_natives)
    natives.update(csv_natives)
    return (
        sorted(combined.values(), key=lambda row: (row.reference_date, row.series_id)),
        natives,
    )


def _label(raw: str) -> str:
    """Render a native snake_case label as readable English."""
    return raw.replace("_", " ").strip()


def _build_catalog(
    natives: dict[str, dict[str, str]], last_publish_date: date | None
) -> dict[str, dict[str, Any]]:
    """Describe every collected series from its verified native labels."""
    catalog: dict[str, dict[str, Any]] = {}
    for series_id, fields in natives.items():
        item, variety = _label(fields["item"]), _label(fields["variety"])
        product = item if variety == item else f"{item}, {variety}"
        catalog[series_id] = {
            "source_id": SOURCE_ID,
            "name": (
                f"England and Wales wholesale {fields['category']} price: "
                f"{product} (GBP per {fields['unit']})"
            ),
            "description": (
                f"Average wholesale market price of home grown {product} in England and "
                f"Wales, in GBP per {fields['unit']}, as published by the Department for "
                "Environment, Food & Rural Affairs. Stored at the published reference dates "
                "with no derived transformation and no aggregate index."
            ),
            # The published cadence is weekly for most of the history and
            # fortnightly latterly; `irregular` is the honest fleet label.
            "frequency": "irregular",
            "unit": "currency",
            "eco_group": "producer_prices",
            "source_url": PAGE_URL,
            "last_publish_date": last_publish_date,
        }
    return catalog


def validate(observations: list[Observation], natives: dict[str, dict[str, str]]) -> None:
    """Gate the parsed panel before anything reaches the database."""
    if not observations:
        raise ValueError("DEFRA collection produced no observations")
    if len(natives) < MIN_EXPECTED_SERIES:
        raise ValueError(
            f"DEFRA returned only {len(natives)} series, below the {MIN_EXPECTED_SERIES} floor; "
            "the download was probably truncated"
        )

    # Normalization must stay injective, or two published products would share
    # one stored history.
    collisions: dict[str, set[tuple[str, str, str]]] = {}
    for series_id, fields in natives.items():
        native_key = (fields["category"], fields["item"], fields["variety"])
        collisions.setdefault(series_id, set()).add(native_key)
    clashing = {sid: keys for sid, keys in collisions.items() if len(keys) > 1}
    if clashing:
        raise ValueError(f"DEFRA identifier normalization collided: {clashing}")

    keys = [(observation.series_id, observation.reference_date) for observation in observations]
    if len(keys) != len(set(keys)):
        counts: dict[tuple[str, date], int] = {}
        for observation_key in keys:
            counts[observation_key] = counts.get(observation_key, 0) + 1
        duplicates = sorted(key for key, count in counts.items() if count > 1)[:5]
        raise ValueError(f"DEFRA published duplicate observations, for example {duplicates}")

    dates = sorted({observation.reference_date for observation in observations})
    if dates[0] != EXPECTED_FIRST_OBSERVATION:
        raise ValueError(
            f"DEFRA history starts at {dates[0]}, expected {EXPECTED_FIRST_OBSERVATION}; "
            "the published file changed and must be re-verified"
        )
    if len(dates) < MIN_EXPECTED_DATES:
        raise ValueError(
            f"DEFRA returned only {len(dates)} reference dates, below the "
            f"{MIN_EXPECTED_DATES} floor; the download was probably truncated"
        )
    if dates[-1] > datetime.now(UTC).date():
        raise ValueError(f"DEFRA published a future reference date {dates[-1]}")

    long_gaps = [
        (earlier, later)
        for earlier, later in pairwise(dates)
        if (later - earlier).days > MAX_GAP_DAYS
    ]
    if long_gaps:
        raise ValueError(
            f"DEFRA cadence broken by gaps longer than {MAX_GAP_DAYS} days at {long_gaps[:5]}"
        )

    non_positive = [
        (observation.series_id, observation.reference_date, observation.value)
        for observation in observations
        if observation.value <= 0.0
    ]
    if non_positive:
        raise ValueError(f"DEFRA published non-positive prices, for example {non_positive[:5]}")

    logger.info(
        "DEFRA validation passed: %d series, %d reference dates, %s to %s",
        len(natives),
        len(dates),
        dates[0],
        dates[-1],
    )


def collect(client: httpx.Client) -> SourceData:
    """Download, parse and validate the full DEFRA fruit and vegetable history."""
    page = fetch_page(client, PAGE_URL)
    releases = release_timestamps(page)
    if not releases:
        raise ValueError(f"No publication history found on {PAGE_URL}; the page layout changed")
    last_publish_date = releases[-1].astimezone(UTC).date()
    logger.info(
        "DEFRA page carries %d official release timestamps, %s to %s",
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
    csv_observations, csv_natives = _parse_csv(csv_body, csv_url, csv_digest)
    ods_observations, ods_natives = _parse_ods(ods_body, ods_url, ods_digest)
    observations, natives = _combine_artifacts(
        ods_observations,
        ods_natives,
        csv_observations,
        csv_natives,
    )
    validate(observations, natives)
    return SourceData(
        source_id=SOURCE_ID,
        source_url=PAGE_URL,
        catalog=_build_catalog(natives, last_publish_date),
        observations=observations,
        releases=releases,
        snapshots=[ods_snapshot, csv_snapshot],
        min_lag_days=MIN_LAG_DAYS,
        max_lag_days=MAX_LAG_DAYS,
        inferred_lag_days=INFERRED_LAG_DAYS,
        last_publish_date=last_publish_date,
    )
