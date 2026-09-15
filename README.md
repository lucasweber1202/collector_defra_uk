# collector_defra_uk

Standalone collector for public DEFRA datasets relevant to UK inflation. The
initial dataset is [Wholesale fruit and vegetable prices](https://www.gov.uk/government/statistical-data-sets/wholesale-fruit-and-vegetable-prices-weekly-average).

The repository owns DEFRA extraction and raw point-in-time persistence. It does
not map predictors to CPI targets or calculate modelling features; those tasks
belong to `uk_inflation_predictors`.

## Current coverage

- Publisher: Department for Environment, Food & Rural Affairs (DEFRA)
- Dataset: fortnightly average wholesale prices of selected home-grown produce
- Official history: 9 January 2015 to the latest publication
- Artifacts: historical ODS (2015-present) plus machine-readable CSV
  (3 November 2017-present)
- Stored values: individual raw published prices only; no synthetic fruit,
  vegetable or food index
- Schema: `collector_defra_uk`

## Run locally

```bash
python -m pip install -r requirements.txt
cp .env.example .env
python main.py
```

The default local database URL is documented in `.env.example`. Raw snapshots
are written below the gitignored snapshot directory configured there.
