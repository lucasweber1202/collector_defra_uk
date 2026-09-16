# Point-in-time contract

This collector stores predictor data for forecasting. A historical backtest must never see information that was unavailable at the simulated forecast instant.

## Stored dates

- `reference_date`: period the observation describes.
- `vintage_date`: UTC date on which this collector stored that version.
- `release_date`: source publication date when explicitly supported.
- `available_at`: earliest defensible instant at which this stored vintage could have been known.
- `collected_at`: timestamp of this pipeline run.

`availability_basis` is one of `official_timestamp`, `official_date`, `archived_release`, `first_seen`, `inferred`, `unknown`.

By default `get_series_as_of()` accepts only `official_timestamp`, `official_date`, `archived_release`, and `first_seen`. `inferred` and `unknown` require explicit opt-in.

## Historical revisions

A revised value for an already stored `(series_id, reference_date)` must not reuse the original publication timestamp. Unless the source exposes explicit evidence for the revision release, the revised vintage is stamped:

- `available_at = collected_at`
- `availability_basis = first_seen`
- `release_date = NULL`

This prevents a 2026 revision of a 2024 observation from appearing in a 2024 backtest.

## Same-day revisions

The fleet schema uses `vintage_date DATE`. Two different intraday revisions therefore cannot be represented without overwriting one information set. Predictor collectors fail closed when an already stored vintage changes again on the same UTC date. Retry after the UTC date changes rather than rewriting history.

## As-of guarantee

`get_series_as_of(series_id, as_of)` filters on `available_at <= as_of` before ranking vintages. A later revision therefore cannot mask the vintage that was actually current at the historical instant.

## Per-dataset release attribution

Every data set attributes an observation to the earliest GOV.UK change-history
entry falling inside its own release window. The windows below were measured
against the live change history rather than assumed.

| `source_id` | Reference period | Measured lag | Window used | Inferred fallback | Change history begins |
| --- | --- | --- | --- | --- | --- |
| `defra_fruit_veg` | week ending | 0–31 days, mode 3 | 0–31 days | 3 days | 2017-01-05 |
| `defra_banana_prices` | week ending Friday | Monday after (mode 3 days, 207/320 weeks) | 0–21 days | 3 days | 2019-07-21 |
| `defra_milk_prices` | month | ~8 weeks, last Thursday | 40–80 days | 57 days | 2013-04-30 |
| `defra_agricultural_price_index` | month | ~12 weeks, last Thursday | 70–110 days | 87 days | 2013-04-18 |

Where the change history begins after the first observation — bananas from
1995 against a history starting in 2019, milk from 1970 against a history
starting in 2013 — the uncovered tail is recorded as `availability_basis =
inferred` and is excluded from `get_series_as_of()` by default. It is a
reconstruction from the observed release rule, not evidence, and must never be
treated as a point-in-time guarantee.

On the verified 2026-09-16 build this yields 38,771 observations carrying
`official_timestamp`, 17,202 carrying `inferred`, and none `unknown`.
