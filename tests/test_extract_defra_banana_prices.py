"""DEFRA banana parsing, label normalisation, identifier round-trip and gates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.extract_defra_banana_prices import (
    EXPECTED_FIRST_OBSERVATION,
    EXPECTED_UNIT,
    MAX_GAP_DAYS,
    MIN_EXPECTED_DATES,
    MIN_EXPECTED_SERIES,
    _build_catalog,
    make_series_id,
    normalise_origin,
    parse_csv,
    parse_series_id,
    validate,
)
from scripts.metadata import validate_catalog
from scripts.time_series import Observation

HEADER = '"Origin","Date","Price","Units"'
ROW = '"costa_rica","2026-09-14",0.94,"£/kg"'


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return ("﻿" + "\n".join([header, *rows]) + "\n").encode("utf-8")


def _panel(
    series: int = MIN_EXPECTED_SERIES,
    dates: int = MIN_EXPECTED_DATES,
) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    """Build a synthetic panel that clears every validation floor."""
    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    for index in range(series):
        origin = f"origin{index}"
        series_id = make_series_id(origin)
        natives[series_id] = {"origin": origin, "unit": EXPECTED_UNIT}
        for step in range(dates):
            observations.append(
                Observation(
                    series_id=series_id,
                    reference_date=EXPECTED_FIRST_OBSERVATION + timedelta(days=7 * step),
                    value=1.0,
                    snapshot_id="snapshot",
                )
            )
    return observations, natives


def test_parses_origin_price_and_reference_date() -> None:
    observations, natives = parse_csv(_csv(ROW), "test://banana", "snap")
    assert len(observations) == 1
    observation = observations[0]
    assert observation.series_id == "DEFRA_BANANA_COSTARICA"
    assert observation.reference_date == date(2026, 9, 14)
    assert observation.value == pytest.approx(0.94)
    assert observation.snapshot_id == "snap"
    assert natives[observation.series_id] == {"origin": "costa_rica", "unit": EXPECTED_UNIT}


def test_a_changed_header_fails_loudly() -> None:
    with pytest.raises(ValueError, match="header is"):
        parse_csv(_csv(ROW, header='"Origin","Week","Price","Units"'), "test://b", "snap")


def test_an_unverified_unit_fails_loudly() -> None:
    row = '"costa_rica","2026-09-14",0.94,"p/kg"'
    with pytest.raises(ValueError, match="publishes unit"):
        parse_csv(_csv(row), "test://b", "snap")


def test_a_blank_price_is_an_unpublished_week_not_a_zero() -> None:
    row = '"costa_rica","2026-09-14",,"£/kg"'
    observations, natives = parse_csv(_csv(row), "test://b", "snap")
    assert observations == []
    assert natives == {}


def test_an_unparseable_price_fails_loudly() -> None:
    row = '"costa_rica","2026-09-14","n/a","£/kg"'
    with pytest.raises(ValueError, match="unparseable price"):
        parse_csv(_csv(row), "test://b", "snap")


def test_an_unparseable_date_fails_loudly() -> None:
    row = '"costa_rica","14/09/2026",0.94,"£/kg"'
    with pytest.raises(ValueError, match="unparseable date"):
        parse_csv(_csv(row), "test://b", "snap")


# The 2018/2019 relabelling: DEFRA published the aggregates as
# `all_bananas_bananas` up to 2018-12-21 and as `all_bananas` from 2019-01-11.
@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("all_bananas_bananas", "all_bananas"),
        ("dollar_bananas_bananas", "dollar_bananas"),
        ("acp_bananas_bananas", "acp_bananas"),
        ("all_bananas", "all_bananas"),
        ("costa_rica", "costa_rica"),
    ],
)
def test_a_doubled_bananas_suffix_is_collapsed(published: str, expected: str) -> None:
    assert normalise_origin(published) == expected


def test_a_single_bananas_suffix_is_left_alone() -> None:
    """`eu_bananas` and `eu` are distinct published rows, not one renamed series."""
    assert normalise_origin("eu_bananas") == "eu_bananas"
    assert normalise_origin("eu") == "eu"
    assert make_series_id("eu_bananas") != make_series_id("eu")


def test_the_relabelled_aggregate_forms_one_continuous_series() -> None:
    observations, natives = parse_csv(
        _csv(
            '"all_bananas_bananas","2018-12-21",0.80,"£/kg"',
            '"all_bananas","2019-01-11",0.82,"£/kg"',
        ),
        "test://b",
        "snap",
    )
    assert len(natives) == 1
    assert {observation.series_id for observation in observations} == {"DEFRA_BANANA_ALLBANANAS"}


def test_a_blank_origin_is_refused() -> None:
    with pytest.raises(ValueError, match="blank origin"):
        normalise_origin("   ")


def test_series_ids_round_trip() -> None:
    for origin in ("costa_rica", "all_bananas", "eu_bananas", "windward_isles"):
        series_id = make_series_id(origin)
        _source, _dataset, token = parse_series_id(series_id)
        assert make_series_id(token.lower()) == series_id


@pytest.mark.parametrize("series_id", ["DEFRA_BANANA_", "DEFRA_X_ORIGIN", "BANANA_DEFRA_X", "X"])
def test_a_malformed_series_id_is_refused(series_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid DEFRA banana series_id"):
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


def test_a_shifted_first_observation_is_refused() -> None:
    observations, natives = _panel()
    shifted = [
        Observation(
            series_id=observation.series_id,
            reference_date=observation.reference_date + timedelta(days=1),
            value=observation.value,
            snapshot_id=observation.snapshot_id,
        )
        for observation in observations
    ]
    with pytest.raises(ValueError, match="history starts at"):
        validate(shifted, natives)


def test_a_history_gap_is_refused() -> None:
    # Enough slack that removing the gap block still clears the date floor, so
    # this asserts the cadence gate rather than the truncation gate.
    removed = MAX_GAP_DAYS // 7 + 1
    observations, natives = _panel(dates=MIN_EXPECTED_DATES + removed)
    gapped = [
        observation
        for observation in observations
        if observation.reference_date
        not in {
            EXPECTED_FIRST_OBSERVATION + timedelta(days=7 * step)
            for step in range(1, removed + 1)
        }
    ]
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
        reference_date=datetime.now(UTC).date() + timedelta(days=30),
        value=1.0,
        snapshot_id="snapshot",
    )
    with pytest.raises(ValueError, match="future reference date"):
        validate([*observations, future], natives)


@pytest.mark.parametrize("value", [0.0, -1.0, 250.0])
def test_an_implausible_price_is_refused(value: float) -> None:
    """A decimal shift or a pence/pound unit change must stop collection."""
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
        _csv(ROW, '"all_bananas","2026-09-14",0.99,"£/kg"'), "test://b", "snap"
    )
    catalog = _build_catalog(natives, date(2026, 9, 15))
    validate_catalog(catalog)
    assert catalog["DEFRA_BANANA_ALLBANANAS"]["frequency"] == "weekly"
    assert catalog["DEFRA_BANANA_ALLBANANAS"]["unit"] == "currency"
    # DEFRA's own aggregate must be described as such so the research layer
    # never treats it as one more origin.
    assert "aggregate" in catalog["DEFRA_BANANA_ALLBANANAS"]["description"]
    assert "aggregate" not in catalog["DEFRA_BANANA_COSTARICA"]["description"]
