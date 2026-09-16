"""DEFRA agricultural price index parsing, base-year identity and gates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.extract_defra_agricultural_price_index import (
    BASE_YEAR,
    EXPECTED_COLUMNS,
    EXPECTED_FIRST_OBSERVATION,
    MIN_EXPECTED_DATES,
    MIN_EXPECTED_SERIES,
    _build_catalog,
    make_series_id,
    parse_csv,
    parse_series_id,
    validate,
)
from scripts.metadata import validate_catalog
from scripts.time_series import Observation

HEADER = ",".join(EXPECTED_COLUMNS)
ROW = "output,wheat,2026-06-01,109.46483713645769"


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def _month(index: int) -> date:
    """Return the first of the month ``index`` months after the history start."""
    total = (EXPECTED_FIRST_OBSERVATION.month - 1) + index
    return date(EXPECTED_FIRST_OBSERVATION.year + total // 12, total % 12 + 1, 1)


def _panel(
    series: int = MIN_EXPECTED_SERIES,
    dates: int = MIN_EXPECTED_DATES,
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Build a synthetic panel that clears every validation floor."""
    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    for index in range(series):
        # Both published index families must be represented, or the panel
        # trips the type gate instead of the gate under test.
        index_type = "output" if index % 2 == 0 else "input"
        category = f"category{index}"
        series_id = make_series_id(index_type, category)
        natives[series_id] = {"type": index_type, "category": category}
        for step in range(dates):
            observations.append(
                Observation(
                    series_id=series_id,
                    reference_date=_month(step),
                    value=100.0,
                    snapshot_id="snapshot",
                )
            )
    return observations, natives


def test_parses_type_category_date_and_index() -> None:
    observations, natives = parse_csv(_csv(ROW), "test://api", "snap")
    assert len(observations) == 1
    observation = observations[0]
    assert observation.series_id == f"DEFRA_API_OUTPUT_WHEAT_B{BASE_YEAR}"
    assert observation.reference_date == date(2026, 6, 1)
    assert observation.value == pytest.approx(109.4648371, rel=1e-9)
    assert natives[observation.series_id] == {"type": "output", "category": "wheat"}


def test_a_changed_header_fails_loudly() -> None:
    with pytest.raises(ValueError, match="header is"):
        parse_csv(_csv(ROW, header="type,category,month,index"), "test://api", "snap")


def test_an_unknown_index_type_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unknown index type"):
        parse_csv(_csv("capital,wheat,2026-06-01,100.0"), "test://api", "snap")


def test_a_blank_index_is_an_unpublished_month_not_a_zero() -> None:
    observations, natives = parse_csv(_csv("output,wheat,2026-06-01,"), "test://api", "snap")
    assert observations == []
    assert natives == {}


def test_a_blank_category_is_refused() -> None:
    with pytest.raises(ValueError, match="blank category"):
        parse_csv(_csv("output,,2026-06-01,100.0"), "test://api", "snap")


def test_an_unparseable_index_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unparseable index"):
        parse_csv(_csv("output,wheat,2026-06-01,n/a"), "test://api", "snap")


def test_a_non_month_start_reference_date_fails_loudly() -> None:
    with pytest.raises(ValueError, match="not the first of a month"):
        parse_csv(_csv("output,wheat,2026-06-15,100.0"), "test://api", "snap")


def test_the_base_year_is_part_of_the_identifier() -> None:
    """A DEFRA rebasing must create new series, never redefine stored ones."""
    assert make_series_id("output", "wheat").endswith(f"_B{BASE_YEAR}")
    assert make_series_id("output", "wheat", 2015) != make_series_id("output", "wheat", 2020)


def test_output_and_input_of_the_same_name_are_distinct_series() -> None:
    assert make_series_id("output", "electricity") != make_series_id("input", "electricity")


def test_series_ids_round_trip() -> None:
    for index_type, category in [
        ("output", "wheat"),
        ("input", "all_agricultural_inputs"),
        ("output", "wheat_breadmaking"),
    ]:
        series_id = make_series_id(index_type, category)
        _source, _dataset, parsed_type, _category, base = parse_series_id(series_id)
        assert parsed_type == index_type.upper()
        assert base == BASE_YEAR


@pytest.mark.parametrize(
    "series_id",
    ["DEFRA_API_OUTPUT_WHEAT", "DEFRA_API_OUTPUT_WHEAT_2020", "DEFRA_X_OUTPUT_WHEAT_B2020"],
)
def test_a_malformed_series_id_is_refused(series_id: str) -> None:
    with pytest.raises(ValueError):
        parse_series_id(series_id)


def test_validation_accepts_a_well_formed_panel() -> None:
    validate(*_panel())


def test_too_few_series_is_refused() -> None:
    observations, natives = _panel(series=MIN_EXPECTED_SERIES - 1)
    with pytest.raises(ValueError, match="below the .* floor"):
        validate(observations, natives)


def test_too_few_reference_dates_is_refused() -> None:
    observations, natives = _panel(dates=MIN_EXPECTED_DATES - 1)
    with pytest.raises(ValueError, match="reference dates, below"):
        validate(observations, natives)


def test_losing_a_whole_index_family_is_refused() -> None:
    """Dropping every input series must fail rather than halve the panel.

    The panel is built at double width so the surviving output half still
    clears the series floor, isolating the index-type gate.
    """
    observations, natives = _panel(series=MIN_EXPECTED_SERIES * 2)
    kept = {sid for sid, fields in natives.items() if fields["type"] == "output"}
    with pytest.raises(ValueError, match="returned index types"):
        validate(
            [o for o in observations if o.series_id in kept],
            {sid: fields for sid, fields in natives.items() if sid in kept},
        )


def test_a_shifted_first_observation_is_refused() -> None:
    """A rebasing usually moves the history start; that must stop collection."""
    observations, natives = _panel(dates=MIN_EXPECTED_DATES + 1)
    shifted = [o for o in observations if o.reference_date != EXPECTED_FIRST_OBSERVATION]
    with pytest.raises(ValueError, match="history starts at"):
        validate(shifted, natives)


def test_a_monthly_cadence_gap_is_refused() -> None:
    observations, natives = _panel(dates=MIN_EXPECTED_DATES + 2)
    gapped = [o for o in observations if o.reference_date not in {_month(1), _month(2)}]
    with pytest.raises(ValueError, match="cadence broken by gaps"):
        validate(gapped, natives)


def test_a_duplicate_observation_is_refused() -> None:
    observations, natives = _panel()
    with pytest.raises(ValueError, match="duplicate observations"):
        validate([*observations, observations[0]], natives)


def test_a_future_reference_date_is_refused() -> None:
    observations, natives = _panel()
    future = Observation(
        series_id=observations[0].series_id,
        reference_date=datetime.now(UTC).date().replace(day=1) + timedelta(days=400),
        value=100.0,
        snapshot_id="snapshot",
    )
    with pytest.raises(ValueError, match="future reference date"):
        validate([*observations, future], natives)


@pytest.mark.parametrize("value", [0.0, 5.0, 5000.0])
def test_an_implausible_index_is_refused(value: float) -> None:
    """An unannounced rebasing shows up as an out-of-envelope level."""
    observations, natives = _panel()
    broken = Observation(
        series_id=observations[0].series_id,
        reference_date=observations[0].reference_date,
        value=value,
        snapshot_id="snapshot",
    )
    with pytest.raises(ValueError, match="plausible"):
        validate([broken, *observations[1:]], natives)


def test_an_empty_panel_is_refused() -> None:
    with pytest.raises(ValueError, match="no observations"):
        validate([], {})


def test_the_catalog_satisfies_the_metadata_vocabularies() -> None:
    _observations, natives = parse_csv(
        _csv(ROW, "input,electricity,2026-06-01,120.0"), "test://api", "snap"
    )
    catalog = _build_catalog(natives, date(2026, 8, 27))
    validate_catalog(catalog)
    entry = catalog[f"DEFRA_API_OUTPUT_WHEAT_B{BASE_YEAR}"]
    assert entry["frequency"] == "monthly"
    assert entry["unit"] == "index"
    # The base year must be visible to a reader of the catalog, not only
    # encoded in the identifier.
    assert f"{BASE_YEAR} = 100" in entry["name"]
    assert "not chained" in entry["description"]
