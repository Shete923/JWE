# Dindorkar Saraf Jewellery Management desktop

A native Python desktop app built with **PySide6** (not Tkinter), connected to
the FastAPI backend and PostgreSQL database. The desktop app includes:

- Store profile, financial-year start, and daily gold/silver prices by carat.
- A jewellery item catalogue with configurable per-item GST and making charges.
- Customer and party ledger profiles with bank, contact, and opening metal balances.
- Gold savings schemes with sequential installment posting and payment history.
- Searchable tagged gold/silver stock and inventory intake.
- Server-calculated POS quotes and atomic invoice/payment/stock updates.
- Customer CSV import; customer, item, stock, and sales CSV exports.

## Apply the backend migration first

The first schema migration creates the original workbook tables. Apply
migrations 002 and 003 once to add retail settings, metal rates, ledger opening
metal balances, and savings schemes before restarting the API. From the
`backend` folder in PowerShell:

```powershell
$pgBin = "C:\Program Files\PostgreSQL\16\bin"
& "$pgBin\psql.exe" -h localhost -p 5432 -U postgres -d jewellery_management -v ON_ERROR_STOP=1 -f ".\migrations\002_retail_mvp.sql"
& "$pgBin\psql.exe" -h localhost -p 5432 -U postgres -d jewellery_management -v ON_ERROR_STOP=1 -f ".\migrations\003_ledger_schemes.sql"
```

Back up the database first. The migration is additive but normalizes existing
stock labour-unit text values; review it before applying to valuable data. Do
not rerun a migration after it succeeds. For an existing database, run only
migrations that have not yet succeeded, in order.

The updated backend requires a restart to load the retail endpoints. From the
`backend` folder, in the PowerShell window where `DATABASE_URL` is configured:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Keep the API bound to `127.0.0.1` for local desktop use. Authentication and
multi-user permissions are not implemented; do not expose this backend to a
shared or public network. Ledger entries can contain PAN, Aadhaar, and banking
details; restrict database and backup access accordingly.

## Run on Windows

Open a second PowerShell window in this `desktop` folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
python -m app.main
```

If `py` selects a Python release without a compatible PySide6 wheel, create the
environment using another installed Python version, for example:

```powershell
py -3.14 -m venv .venv
```

Start the FastAPI backend separately. The dashboard defaults to
`http://127.0.0.1:8000`; enter another HTTP(S) backend URL in the window if
needed. Set up your store and today's metal prices under **Store settings**,
add the item, customer, and tagged stock, then use **Customer & party ledger**,
**Scheme / installments**, **Sales / billing**, and **Stock / inventory** for
the corresponding workflows. The dashboard summarizes today's sales,
gold/silver stock weights, customer count, and invoices. The app checks
database connectivity periodically.

To create clearly labelled, fictional demo records in an empty demo database,
run this only when you explicitly want demo data:

```powershell
cd ..\backend
.\.venv\Scripts\Activate.ps1
python -m app.demo_data
```

The demo seed refuses to run if branch 1 already has non-demo store settings.
Its item has a 0% GST setting for demonstration only. Replace sample rates and
tax settings with verified business values before any real transaction.

## Calculation notes

The server calculates each line as **net metal weight × configured rate for
that metal/carat + making charge + other/stone charges**, allocates the bill
discount proportionally, and calculates tax using the item's configured GST
rate. It uses CGST + SGST when seller and customer states match, and IGST when
they differ. The calculations use decimal arithmetic and database transactions.
Rates, HSN/GST treatment, rounding policy, and invoice format must be checked
with your accountant and local requirements before using this for real billing.

## Run tests

From `desktop`:

```powershell
python -m unittest discover -s tests -v
```

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
