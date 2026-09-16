# collector_defra_uk

Standalone collector for public DEFRA datasets relevant to UK inflation.

The repository owns DEFRA extraction and raw point-in-time persistence. It does
not map predictors to CPI targets or calculate modelling features; those tasks
belong to `uk_inflation_predictors`.

Schema: `collector_defra_uk`.

## Current coverage

| `source_id` | Dataset | Frequency | History | Series | Artifact |
| --- | --- | --- | --- | --- | --- |
| `defra_fruit_veg` | [Wholesale fruit and vegetable prices](https://www.gov.uk/government/statistical-data-sets/wholesale-fruit-and-vegetable-prices-weekly-average) | irregular (weekly/fortnightly) | 2015-01-09 → | 127 | ODS + CSV |
| `defra_banana_prices` | [Banana prices](https://www.gov.uk/government/statistical-data-sets/banana-prices) | weekly | 1995-01-13 → | 28 | CSV |
| `defra_milk_prices` | [UK milk prices and composition of milk](https://www.gov.uk/government/statistics/uk-milk-prices-and-composition-of-milk) | monthly | 1970-01-01 → | 5 | ODS |
| `defra_agricultural_price_index` | [Agricultural price indices](https://www.gov.uk/government/statistics/agricultural-price-indices) | monthly | 2014-01-01 → | 106 | CSV |

Verified on 2026-09-16: 266 series and 55,973 observations across the four
data sets, from five raw artifacts.

Each data set is a self-contained `scripts/extract_defra_*.py` module returning
a `SourceData`. `scripts/extract.py` only orchestrates them, and each one is
collected and committed in its own transaction, so a layout change at one DEFRA
page cannot stop the others from updating.

Stored values are the individual raw published levels only. No synthetic index,
monthly aggregation or derived transformation is built here.

### Dataset notes

- **Banana prices.** DEFRA relabelled its published aggregates at the 2018/2019
  boundary (`all_bananas_bananas` → `all_bananas`, likewise for the dollar and
  ACP aggregates), with no overlapping week. A *doubled* trailing `_bananas`
  token is therefore collapsed so each aggregate is one continuous history.
  `eu_bananas` and `eu` carry a single suffix and stay distinct, because
  nothing in the source establishes that they are the same series. DEFRA's own
  cross-origin aggregates are stored as published and flagged in their
  descriptions so the research layer does not double-count them as origins.
- **Milk prices.** Five published columns are collected: price (pence per
  litre, from 1970), delivered volume, weekly average volume, butterfat and
  protein (from the mid-1990s). DEFRA stamps months inconsistently — rows from
  2017-01 to 2023-12 carry the last day of the month and every other row the
  first — so reference dates are canonicalised to the first of the month, and
  validation asserts the result is still one row per month. The price stays in
  the published pence per litre; converting it would be a transformation. The
  `Prices_Annual` sheet is a DEFRA aggregation of the same figures and is not
  collected. There is one documented publication break: no November or
  December 1994.
- **Agricultural price indices.** Only the current 2020 = 100 file is
  collected. The archived 2015 = 100, 2010 = 100, 2005 = 100 and 2000 = 100
  workbooks on the same page are, in DEFRA's words, "not updated monthly and
  presented for archive purposes only", and DEFRA publishes no rebasing factor
  to chain them. The base year is part of every identifier (`..._B2020`), so a
  future rebasing appears as new series instead of silently redefining stored
  history. No backcast is manufactured.

## Running one data set

```bash
python main.py --source-id defra_banana_prices
```

Omit `--source-id` to collect all four.

## Run locally

```bash
python -m pip install -r requirements.txt
cp .env.example .env
python main.py
```

The default local database URL is documented in `.env.example`. Raw snapshots
are written below the gitignored snapshot directory configured there.
