"""DEFRA parsing, scope filtering, identifier round-trip, and validation gates."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P

from scripts.extract_defra_fruit_veg import (
    EXPECTED_COLUMNS,
    EXPECTED_FIRST_OBSERVATION,
    _build_catalog,
    _combine_artifacts,
    _parse_csv,
    _parse_ods,
    make_series_id,
    parse_series_id,
    validate,
)
from scripts.metadata import validate_catalog
from scripts.time_series import Observation

HEADER = ",".join(EXPECTED_COLUMNS)
FRUIT = "fruit,apples,gala,2026-09-14,1.43,kg"
VEG = "vegetable,cabbage,savoy,2026-09-14,0.85,head"
FLOWERS = "cut_flowers,lillies,oriental,2026-09-14,0.7,stem"


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return ("﻿" + "\n".join([header, *rows]) + "\n").encode("utf-8")


def _cell(text: str, *, date_value: date | None = None) -> TableCell:
    kwargs = {"valuetype": "date", "datevalue": date_value.isoformat()} if date_value else {}
    cell = TableCell(**kwargs)
    cell.addElement(P(text=text))
    return cell


def _mini_ods() -> bytes:
    document = OpenDocumentSpreadsheet()
    layouts = (
        ("2017", date(2017, 11, 3), True, "-"),
        ("2017-2016", date(2016, 1, 8), False, "Ave"),
        ("2016-2015", date(2015, 1, 9), False, "Ave"),
    )
    for name, reference_date, modern, quality in layouts:
        table = Table(name=name)
        date_row = TableRow()
        for value in ("", "", "", "", "Week ending"):
            date_row.addElement(_cell(value))
        date_row.addElement(_cell(reference_date.strftime("%-d/%-m/%y"), date_value=reference_date))
        table.addElement(date_row)
        table.addElement(TableRow())
        if not modern:
            first_quality_row = TableRow()
            for value in ("Fruit", "Apples", "Gala", "1st", "£/kg", "1.50"):
                first_quality_row.addElement(_cell(value))
            table.addElement(first_quality_row)
        data_row = TableRow()
        values = (
            ("1", "Fruit", "Apples", "Gala", "kg", "1.43")
            if modern
            else ("Fruit", "", "Gala", quality, "£/kg", "1.43")
        )
        for value in values:
            data_row.addElement(_cell(value))
        table.addElement(data_row)
        document.spreadsheet.addElement(table)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_parses_product_price_unit_and_reference_date() -> None:
    """All four fields the source publishes per record are preserved."""
    observations, natives = _parse_csv(_csv(FRUIT, VEG), "t.csv", "snap")
    assert len(observations) == 2
    by_series = {row.series_id: row for row in observations}
    apples = by_series["DEFRA_FRUITVEG_FRUIT_APPLES_GALA"]
    assert apples.value == 1.43
    assert apples.reference_date == date(2026, 9, 14)
    assert natives["DEFRA_FRUITVEG_FRUIT_APPLES_GALA"]["unit"] == "kg"
    assert natives["DEFRA_FRUITVEG_VEGETABLE_CABBAGE_SAVOY"]["unit"] == "head"


def test_non_food_categories_are_excluded() -> None:
    """Cut flowers and pot plants are not consumer food prices."""
    observations, natives = _parse_csv(_csv(FRUIT, FLOWERS), "t.csv", "snap")
    assert [row.series_id for row in observations] == ["DEFRA_FRUITVEG_FRUIT_APPLES_GALA"]
    assert "CUTFLOWERS" not in " ".join(natives)


def test_an_unrecognised_category_is_reported_not_silently_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new upstream category must surface in the run log."""
    with caplog.at_level("WARNING"):
        _parse_csv(_csv(FRUIT, "nuts,walnuts,shelled,2026-09-14,4.2,kg"), "t.csv", "snap")
    assert "unrecognised categories" in caplog.text
    assert "nuts" in caplog.text


def test_a_changed_header_fails_loudly() -> None:
    """The tidy layout is the contract; a change must stop the run."""
    with pytest.raises(ValueError, match="header is"):
        _parse_csv(_csv(FRUIT, header="category,item,variety,week,price,unit"), "t.csv", "s")


def test_an_unverified_price_unit_fails_loudly() -> None:
    """An unknown unit means the price means something this layer has not verified."""
    with pytest.raises(ValueError, match="unverified price unit"):
        _parse_csv(_csv("fruit,apples,gala,2026-09-14,1.43,punnet"), "t.csv", "snap")


def test_one_series_published_in_two_units_fails_loudly() -> None:
    """A unit switch inside one series would make its history incomparable."""
    rows = ("fruit,apples,gala,2026-09-07,1.40,kg", "fruit,apples,gala,2026-09-14,1.43,head")
    with pytest.raises(ValueError, match="two units"):
        _parse_csv(_csv(*rows), "t.csv", "snap")


def test_an_unreadable_row_is_a_soft_failure() -> None:
    """One malformed record is skipped; the rest of the file still loads."""
    observations, _ = _parse_csv(_csv("fruit,apples,gala,not-a-date,1.43,kg", VEG), "t.csv", "s")
    assert len(observations) == 1


def test_ods_supplies_2015_history() -> None:
    """The historical artifact extends coverage before the modern CSV."""
    observations, _ = _parse_ods(_mini_ods(), "history.ods", "ods-snapshot")
    assert [row.reference_date for row in observations] == [
        date(2015, 1, 9),
        date(2016, 1, 8),
        date(2017, 11, 3),
    ]
    assert all(row.snapshot_id == "ods-snapshot" for row in observations)


def test_csv_wins_a_one_penny_overlap_after_validation() -> None:
    """Published rounding noise is accepted, but the modern artifact is canonical."""
    series_id = make_series_id("fruit", "apples", "gala")
    ods = [Observation(series_id, date(2026, 9, 14), 1.44, "ods")]
    csv_rows = [Observation(series_id, date(2026, 9, 14), 1.43, "csv")]
    native = {series_id: {"category": "fruit", "item": "apples", "variety": "gala", "unit": "kg"}}
    combined, _ = _combine_artifacts(ods, native, csv_rows, native)
    assert combined == csv_rows


def test_material_ods_csv_overlap_difference_fails() -> None:
    """A substantive disagreement cannot be hidden by deterministic deduplication."""
    series_id = make_series_id("fruit", "apples", "gala")
    native = {series_id: {"category": "fruit", "item": "apples", "variety": "gala", "unit": "kg"}}
    ods = [Observation(series_id, date(2026, 9, 14), 1.50, "ods")]
    csv_rows = [Observation(series_id, date(2026, 9, 14), 1.43, "csv")]
    with pytest.raises(ValueError, match="materially disagree"):
        _combine_artifacts(ods, native, csv_rows, native)


def test_series_ids_round_trip() -> None:
    """Identifiers must decode back to the parts that built them."""
    series_id = make_series_id("vegetable", "brussels_sprouts", "brussels_sprouts")
    assert series_id == "DEFRA_FRUITVEG_VEGETABLE_BRUSSELSSPROUTS_BRUSSELSSPROUTS"
    assert parse_series_id(series_id) == (
        "DEFRA",
        "FRUITVEG",
        "VEGETABLE",
        "BRUSSELSSPROUTS",
        "BRUSSELSSPROUTS",
    )


def test_an_empty_label_cannot_produce_an_identifier() -> None:
    """A blank native label must not collapse into a shared identifier."""
    with pytest.raises(ValueError, match="empty identifier token"):
        make_series_id("fruit", "", "gala")


def _panel(count: int, series: int = 105) -> list[Observation]:
    dates = [EXPECTED_FIRST_OBSERVATION + timedelta(days=7 * index) for index in range(count)]
    return [
        Observation(f"DEFRA_FRUITVEG_FRUIT_ITEM{index}_ALL", day, 1.5, "snap")
        for day in dates
        for index in range(series)
    ]


def _natives(series: int = 105) -> dict[str, dict[str, str]]:
    return {
        f"DEFRA_FRUITVEG_FRUIT_ITEM{index}_ALL": {
            "category": "fruit",
            "item": f"item{index}",
            "variety": "all",
            "unit": "kg",
        }
        for index in range(series)
    }


def test_validation_accepts_a_well_formed_panel() -> None:
    """The gate must pass the shape the source actually publishes."""
    validate(_panel(520), _natives())


def test_too_few_series_is_refused() -> None:
    """A partial download must not replace the full product list."""
    with pytest.raises(ValueError, match="below the 100"):
        validate(_panel(520, series=10), _natives(10))


def test_too_few_reference_dates_is_refused() -> None:
    """A truncated history must not overwrite a complete one."""
    with pytest.raises(ValueError, match="reference dates, below"):
        validate(_panel(100), _natives())


def test_a_shifted_first_observation_is_refused() -> None:
    """A shifted 2015 start means the official historical workbook was truncated."""
    panel = [
        Observation(row.series_id, row.reference_date + timedelta(days=7), row.value, "snap")
        for row in _panel(520)
    ]
    with pytest.raises(ValueError, match="history starts at"):
        validate(panel, _natives())


def test_a_non_positive_price_is_refused() -> None:
    """A zero or negative wholesale price is not a price."""
    panel = _panel(520)
    panel[5] = Observation(panel[5].series_id, panel[5].reference_date, 0.0, "snap")
    with pytest.raises(ValueError, match="non-positive prices"):
        validate(panel, _natives())


def test_a_duplicate_observation_is_refused() -> None:
    """One product may publish one price per reference date."""
    panel = _panel(520)
    with pytest.raises(ValueError, match="duplicate observations"):
        validate([*panel, panel[0]], _natives())


def test_the_catalog_satisfies_the_metadata_vocabularies() -> None:
    """Descriptors must pass the same gate the pipeline applies before writing."""
    _, natives = _parse_csv(_csv(FRUIT, VEG), "t.csv", "snap")
    catalog = _build_catalog(natives, date(2026, 9, 14))
    validate_catalog(catalog)
    name = catalog["DEFRA_FRUITVEG_VEGETABLE_CABBAGE_SAVOY"]["name"]
    # The published physical unit must survive into the descriptive fields,
    # because the fleet `unit` column can only say "currency".
    assert "GBP per head" in name
