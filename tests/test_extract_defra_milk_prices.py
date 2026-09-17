"""DEFRA milk parsing, month canonicalisation, per-series units and gates."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P

from scripts.extract_defra_milk_prices import (
    COLUMNS,
    EXPECTED_FIRST_OBSERVATION,
    MIN_EXPECTED_DATES,
    MONTHLY_SHEET,
    _build_catalog,
    _normalise_header,
    make_series_id,
    parse_ods,
    parse_series_id,
    validate,
)
from scripts.metadata import validate_catalog
from scripts.time_series import Observation

# As published: DEFRA decorates the price header with footnote markers.
HEADERS = (
    "Month",
    "Price(pence per litre)[1,2,4]",
    "Volume(million litres)",
    "Weekly average volume (million litres)",
    "Butterfat(%)",
    "Protein(%)",
)
VALUES = ("34.99", "1276.81", "288.31", "4.17", "3.38")


def _cell(text: str, *, date_value: str | None = None) -> TableCell:
    kwargs = {"valuetype": "date", "datevalue": date_value} if date_value else {}
    cell = TableCell(**kwargs)
    cell.addElement(P(text=text))
    return cell


def _ods(
    rows: list[tuple[str, tuple[str, ...]]],
    *,
    headers: tuple[str, ...] = HEADERS,
    sheet: str = MONTHLY_SHEET,
) -> bytes:
    """Render a minimal workbook shaped like the published one."""
    document = OpenDocumentSpreadsheet()
    table = Table(name=sheet)

    title = TableRow()
    title.addElement(_cell("United Kingdom Milk Prices"))
    table.addElement(title)

    header_row = TableRow()
    for header in headers:
        header_row.addElement(_cell(header))
    table.addElement(header_row)

    for stamp, values in rows:
        row = TableRow()
        row.addElement(_cell(stamp, date_value=stamp))
        for value in values:
            row.addElement(_cell(value))
        table.addElement(row)

    footer = TableRow()
    footer.addElement(_cell("© Crown copyright, 2026"))
    table.addElement(footer)

    document.spreadsheet.addElement(table)
    buffer = io.BytesIO()
    document.write(buffer)
    return buffer.getvalue()


def _month(index: int) -> date:
    total = (EXPECTED_FIRST_OBSERVATION.month - 1) + index
    return date(EXPECTED_FIRST_OBSERVATION.year + total // 12, total % 12 + 1, 1)


def _panel(dates: int = MIN_EXPECTED_DATES) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Build a synthetic panel that clears every validation floor."""
    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    midpoints = {
        "PRICE": 30.0,
        "VOLUME": 1200.0,
        "WEEKLYAVGVOLUME": 280.0,
        "BUTTERFAT": 4.0,
        "PROTEIN": 3.3,
    }
    for variable, _unit, published_unit, _text in COLUMNS.values():
        series_id = make_series_id(variable)
        natives[series_id] = {"variable": variable, "unit": published_unit}
        for step in range(dates):
            observations.append(
                Observation(
                    series_id=series_id,
                    reference_date=_month(step),
                    value=midpoints[variable],
                    snapshot_id="snapshot",
                )
            )
    return observations, natives


def test_parses_every_published_column() -> None:
    body = _ods([("1970-01-01T00:00:00", VALUES)])
    observations, natives = parse_ods(body, "test://milk", "snap")
    assert len(natives) == len(COLUMNS)
    values = {o.series_id: o.value for o in observations}
    assert values["DEFRA_MILK_PRICE"] == pytest.approx(34.99)
    assert values["DEFRA_MILK_BUTTERFAT"] == pytest.approx(4.17)
    assert all(o.reference_date == date(1970, 1, 1) for o in observations)
    assert all(o.snapshot_id == "snap" for o in observations)


def test_footnote_markers_in_a_header_are_cosmetic() -> None:
    assert _normalise_header("Price(pence per litre)[1,2,4]") == "price(pence per litre)"
    assert _normalise_header("Price(pence per litre)[3]") == "price(pence per litre)"
    # A real rename is not cosmetic and must still be visible.
    assert _normalise_header("Price(pence per pint)") != "price(pence per litre)"


def test_a_renamed_column_fails_loudly() -> None:
    headers = ("Month", "Price(pence per pint)", *HEADERS[2:])
    with pytest.raises(ValueError, match="header is"):
        parse_ods(_ods([("1970-01-01T00:00:00", VALUES)], headers=headers), "test://m", "snap")


def test_a_missing_monthly_sheet_fails_loudly() -> None:
    with pytest.raises(ValueError, match=f"no {MONTHLY_SHEET} sheet"):
        parse_ods(_ods([("1970-01-01T00:00:00", VALUES)], sheet="Prices_Annual"), "t://m", "snap")


def test_a_month_end_stamp_is_canonicalised_to_the_month_start() -> None:
    """DEFRA stamps 2017-01 to 2023-12 with month ends and the rest with starts."""
    observations, _natives = parse_ods(_ods([("2017-01-31T00:00:00", VALUES)]), "test://m", "snap")
    assert {o.reference_date for o in observations} == {date(2017, 1, 1)}


def test_both_stamping_conventions_for_one_month_would_be_caught() -> None:
    """Canonicalisation is only safe while it stays one row per month."""
    observations, natives = parse_ods(
        _ods([("2017-01-01T00:00:00", VALUES), ("2017-01-31T00:00:00", VALUES)]),
        "test://m",
        "snap",
    )
    with pytest.raises(ValueError, match="duplicate observations"):
        validate(observations, natives)


def test_a_blank_cell_is_an_unpublished_value_not_a_zero() -> None:
    observations, natives = parse_ods(
        _ods([("1970-01-01T00:00:00", ("4.08", "", "", "", ""))]), "test://m", "snap"
    )
    assert {o.series_id for o in observations} == {"DEFRA_MILK_PRICE"}
    assert set(natives) == {"DEFRA_MILK_PRICE"}


def test_an_unparseable_value_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unparseable"):
        parse_ods(_ods([("1970-01-01T00:00:00", ("abc", "", "", "", ""))]), "test://m", "snap")


def test_a_footer_row_is_not_data() -> None:
    observations, _natives = parse_ods(_ods([("1970-01-01T00:00:00", VALUES)]), "t://m", "snap")
    assert {o.reference_date for o in observations} == {date(1970, 1, 1)}


def test_series_ids_round_trip() -> None:
    for variable, _u, _p, _t in COLUMNS.values():
        series_id = make_series_id(variable)
        _source, _dataset, parsed = parse_series_id(series_id)
        assert make_series_id(parsed) == series_id


@pytest.mark.parametrize("series_id", ["DEFRA_MILK_FAT", "DEFRA_MILK_", "DEFRA_X_PRICE", "PRICE"])
def test_a_malformed_series_id_is_refused(series_id: str) -> None:
    with pytest.raises(ValueError):
        parse_series_id(series_id)


def test_validation_accepts_a_well_formed_panel() -> None:
    validate(*_panel())


def test_too_few_reference_months_is_refused() -> None:
    observations, natives = _panel(dates=MIN_EXPECTED_DATES - 1)
    with pytest.raises(ValueError, match="reference months, below"):
        validate(observations, natives)


def test_too_few_series_is_refused() -> None:
    observations, natives = _panel()
    kept = "DEFRA_MILK_PRICE"
    with pytest.raises(ValueError, match="below the .* floor"):
        validate([o for o in observations if o.series_id == kept], {kept: natives[kept]})


def test_a_shifted_first_observation_is_refused() -> None:
    observations, natives = _panel(dates=MIN_EXPECTED_DATES + 1)
    shifted = [o for o in observations if o.reference_date != EXPECTED_FIRST_OBSERVATION]
    with pytest.raises(ValueError, match="history starts at"):
        validate(shifted, natives)


def test_a_cadence_gap_beyond_the_documented_break_is_refused() -> None:
    observations, natives = _panel(dates=MIN_EXPECTED_DATES + 4)
    dropped = {_month(index) for index in range(1, 5)}
    gapped = [o for o in observations if o.reference_date not in dropped]
    with pytest.raises(ValueError, match="cadence broken by gaps"):
        validate(gapped, natives)


def test_a_future_reference_date_is_refused() -> None:
    observations, natives = _panel()
    future = Observation(
        series_id="DEFRA_MILK_PRICE",
        reference_date=datetime.now(UTC).date().replace(day=1) + timedelta(days=400),
        value=30.0,
        snapshot_id="snapshot",
    )
    with pytest.raises(ValueError, match="future reference date"):
        validate([*observations, future], natives)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        # A pence/pound confusion on the price series.
        ("PRICE", 0.35),
        ("PRICE", 5000.0),
        # A percentage published as a fraction.
        ("BUTTERFAT", 0.041),
        ("PROTEIN", 40.0),
        ("VOLUME", 1.2),
    ],
)
def test_an_implausible_value_is_refused_per_series(variable: str, value: float) -> None:
    """Each column has its own unit, so the envelope is checked per series."""
    observations, natives = _panel()
    series_id = make_series_id(variable)
    broken = Observation(
        series_id=series_id,
        reference_date=EXPECTED_FIRST_OBSERVATION,
        value=value,
        snapshot_id="snapshot",
    )
    kept = [
        o
        for o in observations
        if (o.series_id, o.reference_date) != (series_id, broken.reference_date)
    ]
    with pytest.raises(ValueError, match="plausible"):
        validate([broken, *kept], natives)


def test_an_empty_panel_is_refused() -> None:
    with pytest.raises(ValueError, match="no observations"):
        validate([], {})


def test_the_catalog_satisfies_the_metadata_vocabularies() -> None:
    _observations, natives = parse_ods(_ods([("1970-01-01T00:00:00", VALUES)]), "t://m", "snap")
    catalog = _build_catalog(natives, date(2026, 8, 27))
    validate_catalog(catalog)
    assert catalog["DEFRA_MILK_PRICE"]["unit"] == "currency"
    assert catalog["DEFRA_MILK_BUTTERFAT"]["unit"] == "percent"
    assert catalog["DEFRA_MILK_VOLUME"]["unit"] == "other"
    assert all(entry["frequency"] == "monthly" for entry in catalog.values())
    # The published unit must survive into the description, since the fleet
    # `unit` vocabulary cannot express "pence per litre".
    assert "pence per litre" in catalog["DEFRA_MILK_PRICE"]["description"]
