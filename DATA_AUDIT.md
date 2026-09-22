# Data audit — collector_defra_uk

- Audit seed: `20260918`
- Source version: live capture on 2026-09-18
- Test result: **125 passed**
- Execution: **PASS**
- Overall: **PARTIAL** — Quatro datasets validados; disponibilidade histórica do arquivo mutável é conservadora. Edições históricas não capturadas continuam não verificáveis.
- Output: 55,973 observations, 266 series, 1970-01-01 to 2026-09-14.
- Sample: 60; values matched: 60; failures: 0; not verifiable: 0.

## Observation evidence

| # | Series | Period | Collector | Official source | Unit/frequency evidence | Result |
|---:|---|---|---:|---:|---|---|
| 1 | `DEFRA_FRUITVEG_VEGETABLE_TURNIP_ALLVARIETIES` | 2015-01-09 | 0.91 | 0.90625 | £/kg; irregular; 2016-2015!row 136 col 7 | **PASS** |
| 2 | `DEFRA_FRUITVEG_VEGETABLE_CABBAGE_SUMMERAUTUMNPOINTED` | 2026-09-14 | 0.87 | 0.87 | kg; irregular; CSV row 22 | **PASS** |
| 3 | `DEFRA_FRUITVEG_VEGETABLE_CABBAGE_RED` | 2015-08-28 | 0.39 | 0.3864457142857143 | £/kg; irregular; 2016-2015!row 77 col 40 | **PASS** |
| 4 | `DEFRA_FRUITVEG_FRUIT_COOKINGAPPLES_BRAMLEYSSEEDLING` | 2017-07-07 | 0.72 | 0.7246594558016924 | £/kg; irregular; 2017-2016!row 20 col 85 | **PASS** |
| 5 | `DEFRA_FRUITVEG_VEGETABLE_BULBONIONS_YELLOW` | 2015-04-10 | 0.29 | 0.285515625 | £/kg; irregular; 2016-2015!row 75 col 20 | **PASS** |
| 6 | `DEFRA_FRUITVEG_VEGETABLE_SWEDE_ALLVARIETIES` | 2017-06-16 | 0.36 | 0.35759503836535206 | £/kg; irregular; 2017-2016!row 122 col 82 | **PASS** |
| 7 | `DEFRA_FRUITVEG_FRUIT_PEARS_CONFERENCE` | 2022-02-25 | 1.11 | 1.11 | kg; irregular; CSV row 8075 | **PASS** |
| 8 | `DEFRA_FRUITVEG_VEGETABLE_CALABRESE_CALABRESE` | 2020-06-05 | 1.77 | 1.77 | kg; irregular; CSV row 11951 | **PASS** |
| 9 | `DEFRA_FRUITVEG_FRUIT_APPLES_GALA` | 2020-01-17 | 0.95 | 0.95 | kg; irregular; CSV row 12588 | **PASS** |
| 10 | `DEFRA_FRUITVEG_FRUIT_APPLES_OTHEREARLYSEASON` | 2021-10-01 | 0.96 | 0.96 | kg; irregular; CSV row 8814 | **PASS** |
| 11 | `DEFRA_FRUITVEG_VEGETABLE_LEEKS_TRIMMED` | 2026-05-25 | 1.29 | 1.29 | kg; irregular; CSV row 457 | **PASS** |
| 12 | `DEFRA_FRUITVEG_VEGETABLE_CARROTS_TOPPEDWASHED` | 2025-12-22 | 0.48 | 0.48 | kg; irregular; CSV row 790 | **PASS** |
| 13 | `DEFRA_FRUITVEG_VEGETABLE_SPRINGGREENS_PREPACKED` | 2026-06-08 | 1.6 | 1.6 | kg; irregular; CSV row 399 | **PASS** |
| 14 | `DEFRA_FRUITVEG_FRUIT_APPLES_OTHERLATESEASON` | 2025-11-24 | 0.97 | 0.97 | kg; irregular; CSV row 848 | **PASS** |
| 15 | `DEFRA_FRUITVEG_VEGETABLE_PARSNIPS_ALLVARIETIES` | 2020-09-25 | 1.13 | 1.13 | kg; irregular; CSV row 11092 | **PASS** |
| 16 | `DEFRA_BANANA_SURINAM` | 1995-01-13 | 0.61 | 0.61 | £/kg; weekly; CSV row 14263 | **PASS** |
| 17 | `DEFRA_BANANA_BELIZE` | 2026-09-14 | 1.06 | 1.06 | £/kg; weekly; CSV row 2 | **PASS** |
| 18 | `DEFRA_BANANA_COLOMBIA` | 2001-12-07 | 0.68 | 0.68 | £/kg; weekly; CSV row 11731 | **PASS** |
| 19 | `DEFRA_BANANA_WINDWARDISLES` | 1996-08-23 | 0.54 | 0.54 | £/kg; weekly; CSV row 14060 | **PASS** |
| 20 | `DEFRA_BANANA_DOMINICANREPUBLIC` | 2001-11-09 | 0.42 | 0.42 | £/kg; weekly; CSV row 11783 | **PASS** |
| 21 | `DEFRA_BANANA_COSTARICA` | 2000-11-10 | 0.48 | 0.48 | £/kg; weekly; CSV row 12494 | **PASS** |
| 22 | `DEFRA_BANANA_ECUADOR` | 2011-03-11 | 0.77 | 0.77 | £/kg; weekly; CSV row 6633 | **PASS** |
| 23 | `DEFRA_BANANA_COLOMBIA` | 2010-09-24 | 0.67 | 0.67 | £/kg; weekly; CSV row 6844 | **PASS** |
| 24 | `DEFRA_BANANA_ECUADOR` | 2007-12-07 | 0.6 | 0.6 | £/kg; weekly; CSV row 8234 | **PASS** |
| 25 | `DEFRA_BANANA_IVORYCOAST` | 2011-04-15 | 0.74 | 0.74 | £/kg; weekly; CSV row 6584 | **PASS** |
| 26 | `DEFRA_BANANA_NICARAGUA` | 2026-09-14 | 0.99 | 0.99 | £/kg; weekly; CSV row 8 | **PASS** |
| 27 | `DEFRA_BANANA_NICARAGUA` | 2025-11-10 | 0.7 | 0.7 | £/kg; weekly; CSV row 169 | **PASS** |
| 28 | `DEFRA_BANANA_BELIZE` | 2026-07-06 | 0.99 | 0.99 | £/kg; weekly; CSV row 47 | **PASS** |
| 29 | `DEFRA_BANANA_COSTARICA` | 2026-07-20 | 0.93 | 0.93 | £/kg; weekly; CSV row 41 | **PASS** |
| 30 | `DEFRA_BANANA_GHANA` | 2012-09-07 | 0.66 | 0.66 | £/kg; weekly; CSV row 5864 | **PASS** |
| 31 | `DEFRA_MILK_PRICE` | 1970-01-01 | 4.08 | 4.08 | pence/litre; monthly; Prices_Monthly!row 3 col 2 | **PASS** |
| 32 | `DEFRA_MILK_PRICE` | 2026-07-01 | 34.99991781549453 | 34.99991781549453 | pence/litre; monthly; Prices_Monthly!row 681 col 2 | **PASS** |
| 33 | `DEFRA_MILK_PRICE` | 1974-04-01 | 5.5 | 5.5 | pence/litre; monthly; Prices_Monthly!row 54 col 2 | **PASS** |
| 34 | `DEFRA_MILK_PRICE` | 1997-04-01 | 20.503037711491874 | 20.503037711491874 | pence/litre; monthly; Prices_Monthly!row 330 col 2 | **PASS** |
| 35 | `DEFRA_MILK_BUTTERFAT` | 1995-12-01 | 4.15 | 4.15 | percent; monthly; Prices_Monthly!row 314 col 5 | **PASS** |
| 36 | `DEFRA_MILK_VOLUME` | 1995-06-01 | 1195.1526799999997 | 1195.1526799999997 | million litres; monthly; Prices_Monthly!row 308 col 3 | **PASS** |
| 37 | `DEFRA_MILK_VOLUME` | 2013-05-01 | 1234.1 | 1234.1 | million litres; monthly; Prices_Monthly!row 523 col 3 | **PASS** |
| 38 | `DEFRA_MILK_VOLUME` | 2004-10-01 | 1074.153696 | 1074.153696 | million litres; monthly; Prices_Monthly!row 420 col 3 | **PASS** |
| 39 | `DEFRA_MILK_WEEKLYAVGVOLUME` | 2008-03-01 | 256.7193548387097 | 256.7193548387097 | million litres; monthly; Prices_Monthly!row 461 col 4 | **PASS** |
| 40 | `DEFRA_MILK_BUTTERFAT` | 2004-01-01 | 4.02 | 4.02 | percent; monthly; Prices_Monthly!row 411 col 5 | **PASS** |
| 41 | `DEFRA_MILK_BUTTERFAT` | 2026-05-01 | 4.270389447761346 | 4.270389447761346 | percent; monthly; Prices_Monthly!row 679 col 5 | **PASS** |
| 42 | `DEFRA_MILK_PROTEIN` | 2026-05-01 | 3.459199013085755 | 3.459199013085755 | percent; monthly; Prices_Monthly!row 679 col 6 | **PASS** |
| 43 | `DEFRA_MILK_VOLUME` | 2026-02-01 | 1218.0717833323656 | 1218.0717833323656 | million litres; monthly; Prices_Monthly!row 676 col 3 | **PASS** |
| 44 | `DEFRA_MILK_PROTEIN` | 2025-11-01 | 3.5851219261324676 | 3.5851219261324676 | percent; monthly; Prices_Monthly!row 673 col 6 | **PASS** |
| 45 | `DEFRA_MILK_PROTEIN` | 2012-11-01 | 3.3417769202203065 | 3.3417769202203065 | percent; monthly; Prices_Monthly!row 517 col 6 | **PASS** |
| 46 | `DEFRA_API_INPUT_SOYABEANS_B2020` | 2014-01-01 | 94.505608911962 | 94.505608911962 | index 2020=100; monthly; CSV row 15691 | **PASS** |
| 47 | `DEFRA_API_INPUT_GOODSANDSERVICESCONTRIBUTINGTOINVESTMENT_B2020` | 2026-06-01 | 133.56988353892925 | 133.56988353892925 | index 2020=100; monthly; CSV row 98 | **PASS** |
| 48 | `DEFRA_API_INPUT_FIELDPEAS_B2020` | 2016-01-01 | 56.296745590339725 | 56.296745590339725 | index 2020=100; monthly; CSV row 13175 | **PASS** |
| 49 | `DEFRA_API_INPUT_ANIMALFEEDINGSTUFFS_B2020` | 2014-03-01 | 100.38770093687502 | 100.38770093687502 | index 2020=100; monthly; CSV row 15476 | **PASS** |
| 50 | `DEFRA_API_OUTPUT_FORAGEPLANTS_B2020` | 2015-12-01 | 57.1410120393007 | 57.1410120393007 | index 2020=100; monthly; CSV row 13211 | **PASS** |
| 51 | `DEFRA_API_OUTPUT_OATSMILLING_B2020` | 2016-12-01 | 96.54784683306215 | 96.54784683306215 | index 2020=100; monthly; CSV row 11949 | **PASS** |
| 52 | `DEFRA_API_OUTPUT_FLOWERSANDPLANTS_B2020` | 2020-12-01 | 99.99999999999999 | 99.99999999999999 | index 2020=100; monthly; CSV row 6935 | **PASS** |
| 53 | `DEFRA_API_OUTPUT_CARROTS_B2020` | 2020-06-01 | 121.25337372949909 | 121.25337372949909 | index 2020=100; monthly; CSV row 7566 | **PASS** |
| 54 | `DEFRA_API_INPUT_GOODSANDSERVICESCONTRIBUTINGTOINVESTMENT_B2020` | 2022-04-01 | 122.74669791652497 | 122.74669791652497 | index 2020=100; monthly; CSV row 5336 | **PASS** |
| 55 | `DEFRA_API_OUTPUT_ALLPOULTRY_B2020` | 2020-04-01 | 101.12020548335354 | 101.12020548335354 | index 2020=100; monthly; CSV row 7801 | **PASS** |
| 56 | `DEFRA_API_OUTPUT_ANIMALSANDANIMALPRODUCTS_B2020` | 2026-04-01 | 141.49107859067453 | 141.49107859067453 | index 2020=100; monthly; CSV row 247 | **PASS** |
| 57 | `DEFRA_API_OUTPUT_BARLEYFEEDING_B2020` | 2025-11-01 | 112.59365627690643 | 112.59365627690643 | index 2020=100; monthly; CSV row 736 | **PASS** |
| 58 | `DEFRA_API_OUTPUT_ANIMALPRODUCTS_B2020` | 2026-01-01 | 136.9996162684086 | 136.9996162684086 | index 2020=100; monthly; CSV row 570 | **PASS** |
| 59 | `DEFRA_API_INPUT_FERTILISERSANDSOILIMPROVERS_B2020` | 2026-06-01 | 217.2889803657019 | 217.2889803657019 | index 2020=100; monthly; CSV row 65 | **PASS** |
| 60 | `DEFRA_API_INPUT_CEREALANDMILLINGBYPRODUCTS_B2020` | 2023-04-01 | 122.72634281518187 | 122.72634281518187 | index 2020=100; monthly; CSV row 4061 | **PASS** |

## Filtering and metadata

- `{"file":"https://assets.publishing.service.gov.uk/media/6aa3acc592e72b8ac437f13e/fruitvegprices-260914.csv","raw_rows":17649,"columns":["category","item","variety","date","price","unit"]}`
- `{"file":"https://assets.publishing.service.gov.uk/media/6aa3ad284e17456e2cdf537b/bananas-260914.csv","raw_rows":14264,"columns":["Origin","Date","Price","Units"]}`
- `{"file":"https://assets.publishing.service.gov.uk/media/6a82dcdc03b4fe14b1e7def6/API_20260827.csv","raw_rows":15708,"columns":["type","category","date","index"]}`

The audit read the captured official artifact independently of the collector parser. It checked identifier linkage, published labels, units, frequency and first/latest boundaries. Source artifacts are identified by SHA-256 in the audit evidence.

## Point-in-time and revisions

Predictor as-of queries filter availability before ranking vintages. `inferred` and `unknown` remain excluded by default. Current mutable-file backfills are recorded at `first_seen`; later observed revisions create later vintages and do not inherit an original release timestamp. Actual pre-collection historical editions remain `NOT_VERIFIABLE` unless an archived source file exists.

## Corrections

- Mesma correção PIT para os quatro datasets GOV.UK.

## Result

**PARTIAL** — Quatro datasets validados; disponibilidade histórica do arquivo mutável é conservadora. Edições históricas não capturadas continuam não verificáveis.
