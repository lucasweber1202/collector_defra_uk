# Predictor collector methodology

This repository belongs to the UK inflation predictor fleet. It collects raw explanatory variables (X) only. Official forecast targets (Y), CPI weights and bottom-up reconciliation remain owned by `collector_ons_cpi` / `collector_ons_ex_cpi`.

## Collector contract

Each repository owns one publisher/source family and writes five tables in a schema whose name equals the repository name:

1. `metadata`
2. `time_series`
3. `availability`
4. `source_snapshots`
5. `logs`

Only raw published levels are stored. MoM, YoY, MTD, rolling averages, monthly aggregation, diffusion and model features are downstream research transformations.

## Source isolation

Source-specific download, parsing and validation live in `scripts/extract.py` or source-forced helper modules. There are no imports from other collector repositories, no shared Python package, no `BaseCollector`, ORM layer or migration framework. Template code is copied into each repository so every collector remains independently deployable and auditable.

## Validation

Before persistence the source module should validate at least source schema, duplicate keys, units, frequency/cadence, plausible values, expected history boundaries where defensible and non-empty output. Source changes that undermine an invariant fail loudly.

## Idempotency and revisions

An unchanged rerun writes no `time_series`, `availability`, `source_snapshots` or `metadata` rows. A later-day historical change creates a new vintage and keeps the old vintage. Point-in-time revision handling follows `POINT_IN_TIME.md`.

## Raw snapshots

Every parsed artifact is hashed with SHA-256. A changed upstream file becomes a new `source_snapshots` row rather than replacing the previous snapshot. Raw bytes stay outside Git in a gitignored location.

## DEFRA wholesale fruit and vegetable history

The official page currently publishes two complementary time-series artifacts:

- `fruitveg-weeklyhort-*.ods`: weekly history beginning 9 January 2015;
- `fruitvegprices-*.csv`: tidy machine-readable history beginning 3 November 2017.

The collector parses both. Historical ODS rows retain only the published
average (`Ave`) or ungraded (`-`) price, because first- and second-quality rows
are different measures from the modern average-price panel. No missing value is
interpolated. Where annual ODS worksheets overlap, the newer worksheet is the
official revised representation and wins deterministically; the event is
logged. If a product changes quotation unit, the incompatible historical unit
receives a unit-qualified series identifier instead of being spliced into one
level.

The ODS and CSV overlap is checked cell by cell. Differences of at most one
penny are accepted as published spreadsheet/CSV rounding and the CSV wins.
Anything larger than `0.011` GBP is material and stops the run. On the source
artifact verified on 15 September 2026, the combined panel contained 127 series
and 23,801 observations from 9 January 2015 through 14 September 2026.

## DEFRA banana prices

One tidy CSV carries the whole weekly history from 13 January 1995 in GBP per
kilogram. The two ODS workbooks on the same page restate the same figures, so
parsing them would add a reconciliation failure mode without adding an
observation; only the CSV is collected.

DEFRA renamed its published aggregate rows at the 2018/2019 boundary. The
`_bananas_bananas` spelling runs to 21 December 2018 and the plain spelling
from 11 January 2019, with zero overlapping weeks, so this is a cosmetic
relabelling of one economic series rather than two series. A *doubled* trailing
`_bananas` token is collapsed; a single one is not, which keeps `eu_bananas`
and `eu` distinct. Validation re-checks after normalisation that no two
published origins collapsed onto one identifier.

## DEFRA milk prices

The `Prices_Monthly` sheet of the official ODS carries five published columns.
Each is stored only where it is actually published, so the price series starts
in January 1970 while composition and volume start in the mid-1990s.

Reference months are canonicalised to the first of the month because DEFRA is
not internally consistent: rows from January 2017 to December 2023 carry the
month end and every other row the month start. Both denote the same monthly
period. The canonicalisation is only safe while it stays one row per month, so
validation asserts exactly that and fails on a duplicate.

The price is stored in the published pence per litre. Converting it to pounds
would be a transformation, so the published unit is recorded in the series name
and description instead. The `Prices_Annual` sheet is DEFRA's own calendar-year
aggregation of the same monthly figures and is not collected.

## DEFRA agricultural price indices

Only the current 2020 = 100 CSV (January 2014 onward) is collected. The page
also carries archived workbooks on 2015 = 100 (from January 1988), 2010 = 100,
2005 = 100 and 2000 = 100, which DEFRA states are "not updated monthly and
presented for archive purposes only".

Those bases are never spliced onto the current series. Chaining them requires a
rebasing factor DEFRA does not publish, and a silent concatenation would make
the stored level mean two different things either side of a join. The base year
is therefore part of every identifier, so a future DEFRA rebasing appears as a
new set of series beside the old one rather than redefining a stored history.
Extending history across bases is a research-layer decision with an explicit
documented method; no backcast is manufactured here.

Both published index families (`output` and `input`) must be present, and
validation fails if one disappears rather than silently halving the panel.
