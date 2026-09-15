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
