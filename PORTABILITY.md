# Standalone portability

Verified 2026-09-16. No fleet sibling is required. Each dataset can be checked
separately with `--source-id`.

```powershell
git clone https://github.com/lucasweber1202/collector_defra_uk.git
Set-Location collector_defra_uk
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m pytest -q
ruff check .
mypy .
python main.py --source-id defra_banana_prices
```

Python 3.11/3.12. `COLLECTOR_DB_URL` is required locally; Databricks is optional.
Snapshots use `COLLECTOR_RAW_DIR`. Network: HTTPS to `www.gov.uk` and official
GOV.UK attachment hosts. TLS remains verified; corporate CAs use
`SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`.

Certification: standalone code PASS; sibling required NO; database and internet
required for collection; Databricks not required.
