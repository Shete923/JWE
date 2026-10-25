# Jewellery Management API foundation

This directory contains the FastAPI backend for the Python PySide6 desktop
application. PostgreSQL migration files define the workbook tables, retail
billing, customer ledger, and savings schemes.

## What is included

- `migrations/001_initial_schema.sql`: initial schema under the PostgreSQL
  namespace `jewellery`.
- `migrations/002_retail_mvp.sql`: store settings, per-day metal rates,
  catalogue pricing fields, and sales indexes.
- `migrations/003_ledger_schemes.sql`: opening metal balances and persistent
  scheme enrollment/installment tables.
- `app/main.py`: API routes, liveness, and PostgreSQL connectivity checks.
- `app/pricing.py`: exact-decimal sale line, tax, and discount calculations.
- `app/demo_data.py`: explicitly invoked, labelled fictional demo seed.
- `requirements.txt`: backend dependencies.

The migration retains the spreadsheet's source attributes while using
lowercase `snake_case` table and column names. Table mappings:

| Spreadsheet table | PostgreSQL table |
| --- | --- |
| `RAW_tbl_Ledger` | `jewellery.ledger` |
| `RAW_tbl_ItemMaster` | `jewellery.item_master` |
| `RAW_tbl_StockRunning` | `jewellery.stock_running` |
| `RAW_tbl_SalesBillInfo` | `jewellery.sales_bill_info` |
| `RAW_tbl_SalesBillPurchase` | `jewellery.sales_bill_purchase` |
| `RAW_tbl_ReturnBillInfo` | `jewellery.return_bill_info` |
| `RAW_tbl_ReturnItem` | `jewellery.return_item` |
| `RAW_PNL_TagWiseValuation` | `jewellery.pnl_tag_wise_valuation` |

IDs use identity columns; weights, rates, tax, and money use exact `NUMERIC`
types rather than floating-point types. Branches, years, and lookup entities
that do not have their own tables in the spreadsheet are not invented here.
`Ledger.Password` maps to `password_hash`; store only a securely generated
password hash there, never a plaintext password.

The `Data_Dictionary` tab reports 70 attributes for `RAW_tbl_SalesBillInfo`,
while that table's actual header row contains 69. This migration follows the
69 columns in the table sheet.

## Apply the migrations (PowerShell)

The database must already exist. Apply migration 001 once to a new database,
then migrations 002 and 003 once to enable all desktop modules. Do not rerun a
successful migration:

```powershell
$pgBin = "C:\Program Files\PostgreSQL\16\bin"
& "$pgBin\psql.exe" -h localhost -p 5432 -U postgres -d jewellery_management -v ON_ERROR_STOP=1 -f ".\migrations\001_initial_schema.sql"
& "$pgBin\psql.exe" -h localhost -p 5432 -U postgres -d jewellery_management -v ON_ERROR_STOP=1 -f ".\migrations\002_retail_mvp.sql"
& "$pgBin\psql.exe" -h localhost -p 5432 -U postgres -d jewellery_management -v ON_ERROR_STOP=1 -f ".\migrations\003_ledger_schemes.sql"
```

For an existing database, apply only migrations that have not already
succeeded, in order. If migration 002 previously stopped because one or more
retail columns already existed, the updated 002 can be rerun; it preserves
existing non-null values and fills null retail defaults. `ON_ERROR_STOP` makes
`psql` stop on the first SQL error; each migration is transactional. Back up
valuable data first and review the labour unit normalization in 002.

## Run the API

From this directory, create and activate a virtual environment, then install
dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r .\requirements.txt
$env:DATABASE_URL = "postgresql://postgres:your_password@localhost:5432/jewellery_management"
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API reference. `GET
/health` checks that the service is running; `GET /health/db` checks the
PostgreSQL connection and returns HTTP 503 with a logged error if it is not
available. Do not commit a real database URL or password.

## Retail API and desktop app

The API provides store/tax configuration, daily metal rates, items, tagged
stock, POS quote and checkout, recent sales, a searchable party/customer ledger,
opening amount and metal balances, savings scheme enrollment, and
installment-payment recording. Checkout locks the chosen inventory tags and
saves the invoice, lines, payment, and sold-stock flags in one PostgreSQL
transaction. Scheme payments are sequential and each installment number is
unique within its scheme.

Start at branch 1. Configure the seller state, metal prices by gold carat or
silver, item GST rate, and making-charge unit before using the POS. The
calculation is net weight × configured metal rate + making charge + other
charges; the invoice discount is allocated across lines and GST is calculated
from each item's configured rate. CGST/SGST or IGST is selected by comparing
the configured seller state with the customer's state. Verify tax treatment,
HSN, weights, rate units, and invoice rules with your accountant before real
invoicing; defaults are not tax advice.

Apply `002_retail_mvp.sql` and `003_ledger_schemes.sql` once, restart FastAPI, and follow
`..\desktop\README.md` to start the PySide6 app. Demo data can be loaded
explicitly with `python -m app.demo_data` only in a demo database. The backend
must remain local: authentication and multi-user permissions are not
implemented. Ledger entries can contain PAN, Aadhaar, and banking details;
restrict database and backup access accordingly. Do not expose the API to
other computers or the internet.
