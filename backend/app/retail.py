import csv
import io
import logging
import os
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Generator

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from psycopg.rows import dict_row

from app.pricing import (
    SaleLineInput,
    SaleLineAmounts,
    SaleTotals,
    allocate_discount,
    calculate_line,
    calculate_totals,
    money,
)
from app.schemas import (
    CustomerInput,
    ItemInput,
    LedgerInput,
    MetalRateInput,
    SaleInput,
    SchemeInput,
    SchemeInstallmentInput,
    ShopSettingsInput,
    StockInput,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["retail"])


@contextmanager
def database_connection() -> Generator[psycopg.Connection, None, None]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL is not configured for the backend.",
        )
    try:
        with psycopg.connect(
            database_url, connect_timeout=4, row_factory=dict_row
        ) as connection:
            yield connection
    except psycopg.OperationalError as exc:
        logger.exception("Retail database connection failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable; check DATABASE_URL and the database service.",
        ) from exc
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn) as exc:
        logger.exception("Retail schema migration is not applied")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retail tables are missing; apply migrations 001, 002, and 003, then restart the API.",
        ) from exc
    except psycopg.errors.InvalidSchemaName as exc:
        logger.exception("Jewellery schema migration is not applied")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The jewellery schema is missing; apply migrations 001 and 002, then restart the API.",
        ) from exc


def _require_settings(connection: psycopg.Connection, branch_id: int = 1) -> dict:
    settings = connection.execute(
        """
        SELECT branch_id, business_name, state, gstin, fiscal_year_start_month, updated_at
        FROM jewellery.shop_settings
        WHERE branch_id = %s
        """,
        (branch_id,),
    ).fetchone()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Configure store settings for branch {branch_id} before using retail.",
        )
    return settings


def _get_sale_detail(
    connection: psycopg.Connection, sales_bill_info_id: int
) -> dict:
    bill = connection.execute(
        """
        SELECT s.*, l.name AS customer_name, l.contact_no AS customer_phone,
               l.state AS customer_state, l.gst_no AS customer_gstin,
               settings.business_name, settings.state AS store_state,
               settings.gstin AS store_gstin
        FROM jewellery.sales_bill_info AS s
        JOIN jewellery.shop_settings AS settings ON settings.branch_id = s.branch_id
        LEFT JOIN jewellery.ledger AS l ON l.ledger_id = s.user_id
        WHERE s.sales_bill_info_id = %s
        """,
        (sales_bill_info_id,),
    ).fetchone()
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    lines = connection.execute(
        """
        SELECT line.sales_bill_purchase_id, line.stock_id, line.bill_print_item_name,
               line.purchase_pcs, line.gross_weight, line.purchase_weight,
               line.purchase_rate, line.purchase_labour_chrg,
               line.purchase_labour_chrg_unit, line.other_chrg, line.adj_amt,
               line.purchase_rs, line.cgst_per, line.cgst_rs, line.sgst_per,
               line.sgst_rs, line.igst_per, line.igst_rs, item.hsn_code
        FROM jewellery.sales_bill_purchase AS line
        LEFT JOIN jewellery.item_master AS item
            ON item.item_name_master_id = line.category_id
        WHERE line.bill_no = %s AND line.branch_id = %s AND line.year_id = %s
        ORDER BY line.sales_bill_purchase_id
        """,
        (bill["sales_bill_no"], bill["branch_id"], bill["year_id"]),
    ).fetchall()
    return {"invoice": bill, "lines": lines}


@router.get("/settings")
def read_settings(branch_id: int = Query(default=1, ge=1)) -> dict:
    with database_connection() as connection:
        settings = _require_settings(connection, branch_id)
        rates = connection.execute(
            """
            SELECT DISTINCT ON (material_type, carat)
                   material_type, carat, rate_per_gram, effective_date, updated_at
            FROM jewellery.metal_rates
            WHERE branch_id = %s AND effective_date <= CURRENT_DATE
            ORDER BY material_type, carat, effective_date DESC, metal_rate_id DESC
            """,
            (branch_id,),
        ).fetchall()
        return {"settings": settings, "metal_rates": rates}


@router.put("/settings", status_code=status.HTTP_200_OK)
def write_settings(payload: ShopSettingsInput) -> dict:
    with database_connection() as connection:
        settings = connection.execute(
            """
            INSERT INTO jewellery.shop_settings
                (branch_id, business_name, state, gstin, fiscal_year_start_month)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (branch_id) DO UPDATE SET
                business_name = EXCLUDED.business_name,
                state = EXCLUDED.state,
                gstin = EXCLUDED.gstin,
                fiscal_year_start_month = EXCLUDED.fiscal_year_start_month,
                updated_at = now()
            RETURNING branch_id, business_name, state, gstin,
                      fiscal_year_start_month, updated_at
            """,
            (
                payload.branch_id,
                payload.business_name,
                payload.state,
                payload.gstin,
                payload.fiscal_year_start_month,
            ),
        ).fetchone()
        return settings


@router.put("/settings/metal-rate", status_code=status.HTTP_200_OK)
def write_metal_rate(payload: MetalRateInput) -> dict:
    with database_connection() as connection:
        _require_settings(connection, payload.branch_id)
        rate = connection.execute(
            """
            INSERT INTO jewellery.metal_rates
                (branch_id, effective_date, material_type, carat, rate_per_gram)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (branch_id, effective_date, material_type, carat)
            DO UPDATE SET rate_per_gram = EXCLUDED.rate_per_gram, updated_at = now()
            RETURNING metal_rate_id, branch_id, effective_date,
                      material_type, carat, rate_per_gram, updated_at
            """,
            (
                payload.branch_id,
                payload.effective_date,
                payload.material_type,
                payload.carat,
                payload.rate_per_gram,
            ),
        ).fetchone()
        return rate


@router.get("/items")
def read_items(
    search: str = Query(default="", max_length=100),
    branch_id: int = Query(default=1, ge=1),
) -> list[dict]:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            """
            SELECT item_name_master_id AS item_id, name, item_prefix_name AS prefix,
                   material_type, carat, default_labour_charge, default_labour_unit,
                   default_other_charges, gst_rate, hsn_code, branch_id
            FROM jewellery.item_master
            WHERE branch_id = %s
              AND (name ILIKE %s OR item_prefix_name ILIKE %s)
            ORDER BY name
            LIMIT 250
            """,
            (branch_id, f"%{search}%", f"%{search}%"),
        ).fetchall()


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemInput) -> dict:
    with database_connection() as connection:
        _require_settings(connection)
        item = connection.execute(
            """
            INSERT INTO jewellery.item_master
                (name, branch_id, item_prefix_name, hsn_code, default_stock_product,
                 type, remove_product, apply_loyalty, default_retail_product,
                 material_type, carat, default_labour_charge, default_labour_unit,
                 default_other_charges, gst_rate)
            VALUES (%s, 1, %s, %s, 'Yes', %s, 'No', 'No', 'Yes',
                    %s, %s, %s, %s, %s, %s)
            RETURNING item_name_master_id AS item_id, name,
                      item_prefix_name AS prefix, material_type, carat, default_labour_charge,
                      default_labour_unit, default_other_charges, gst_rate, hsn_code
            """,
            (
                payload.name,
                payload.prefix,
                payload.hsn_code,
                payload.material_type.title(),
                payload.material_type,
                payload.carat,
                payload.default_labour_charge,
                payload.default_labour_unit,
                payload.default_other_charges,
                payload.gst_rate,
            ),
        ).fetchone()
        return item


@router.get("/customers")
def read_customers(
    search: str = Query(default="", max_length=100),
    branch_id: int = Query(default=1, ge=1),
) -> list[dict]:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            """
            SELECT ledger_id AS customer_id, name, contact_no AS phone, email_id AS email,
                   state, gst_no AS gstin
            FROM jewellery.ledger
            WHERE branch_id = %s
              AND lower(coalesce(party_type, '')) LIKE '%customer%'
              AND (name ILIKE %s OR contact_no ILIKE %s OR email_id ILIKE %s)
            ORDER BY name
            LIMIT 250
            """,
            (branch_id, f"%{search}%", f"%{search}%", f"%{search}%"),
        ).fetchall()


@router.post("/customers", status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerInput) -> dict:
    with database_connection() as connection:
        _require_settings(connection)
        customer = connection.execute(
            """
            INSERT INTO jewellery.ledger
                (name, branch_id, email_id, contact_no, state, gst_no, party_type,
                 created_date_time)
            VALUES (%s, 1, %s, %s, %s, %s, 'Retail Customer', now())
            RETURNING ledger_id AS customer_id, name, contact_no AS phone,
                      email_id AS email, state, gst_no AS gstin
            """,
            (
                payload.name,
                payload.email,
                payload.phone,
                payload.state,
                payload.gstin,
            ),
        ).fetchone()
        return customer


_LEDGER_SELECT = """
    SELECT ledger_id, name, party_type, address, city, state, pinnno AS pincode,
           contact_no AS phone, contact_no2 AS alternate_phone,
           email_id AS email, gst_no AS gstin, panno AS pan, aadhar_no AS aadhaar,
           company_name, company_website AS website, bank_name, bank_address,
           bank_ac_no AS bank_account_number, bank_ac_name AS bank_account_name,
           ifsc_code, book_no, prefix, grup AS group_name,
           coalesce(value, 0) AS opening_balance,
           opening_gold_grams, opening_silver_grams,
           coalesce(mortgage_per, 0) AS mortgage_percent,
           nom_name AS nominee_name, nom_add AS nominee_address,
           religion, description AS notes
    FROM jewellery.ledger
"""


@router.get("/ledger")
def read_ledger(
    search: str = Query(default="", max_length=100),
    party_type: str = Query(default="", max_length=30),
    branch_id: int = Query(default=1, ge=1),
) -> list[dict]:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            _LEDGER_SELECT
            + """
            WHERE branch_id = %s
              AND (%s = '' OR lower(coalesce(party_type, '')) = lower(%s))
              AND (
                  name ILIKE %s OR contact_no ILIKE %s OR email_id ILIKE %s
                  OR coalesce(prefix, '') ILIKE %s
              )
            ORDER BY name
            LIMIT 250
            """,
            (
                branch_id,
                party_type,
                party_type,
                f"%{search}%",
                f"%{search}%",
                f"%{search}%",
                f"%{search}%",
            ),
        ).fetchall()


def _ledger_values(payload: LedgerInput) -> tuple:
    return (
        payload.name,
        payload.party_type,
        payload.address,
        payload.city,
        payload.state,
        payload.pincode,
        payload.phone,
        payload.alternate_phone,
        payload.email,
        payload.gstin,
        payload.pan,
        payload.aadhaar,
        payload.company_name,
        payload.website,
        payload.bank_name,
        payload.bank_address,
        payload.bank_account_number,
        payload.bank_account_name,
        payload.ifsc_code,
        payload.book_no,
        payload.prefix,
        payload.group_name,
        payload.opening_balance,
        payload.opening_gold_grams,
        payload.opening_silver_grams,
        payload.mortgage_percent,
        payload.nominee_name,
        payload.nominee_address,
        payload.religion,
        payload.notes,
    )


@router.post("/ledger", status_code=status.HTTP_201_CREATED)
def create_ledger_entry(payload: LedgerInput) -> dict:
    with database_connection() as connection:
        _require_settings(connection)
        result = connection.execute(
            """
            INSERT INTO jewellery.ledger
                (name, party_type, address, city, state, pinnno, contact_no,
                 contact_no2, email_id, gst_no, panno, aadhar_no, company_name,
                 company_website, bank_name, bank_address, bank_ac_no, bank_ac_name,
                 ifsc_code, book_no, prefix, grup, value, opening_gold_grams,
                 opening_silver_grams, mortgage_per, nom_name, nom_add, religion,
                 description, branch_id, created_date_time)
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, now()
            )
            RETURNING ledger_id
            """,
            _ledger_values(payload),
        ).fetchone()
        return connection.execute(
            _LEDGER_SELECT + " WHERE ledger_id = %s", (result["ledger_id"],)
        ).fetchone()


@router.put("/ledger/{ledger_id}")
def update_ledger_entry(ledger_id: int, payload: LedgerInput) -> dict:
    fields = (
        "name = %s, party_type = %s, address = %s, city = %s, state = %s, "
        "pinnno = %s, contact_no = %s, contact_no2 = %s, email_id = %s, "
        "gst_no = %s, panno = %s, aadhar_no = %s, company_name = %s, "
        "company_website = %s, bank_name = %s, bank_address = %s, "
        "bank_ac_no = %s, bank_ac_name = %s, ifsc_code = %s, book_no = %s, "
        "prefix = %s, grup = %s, value = %s, opening_gold_grams = %s, "
        "opening_silver_grams = %s, mortgage_per = %s, nom_name = %s, "
        "nom_add = %s, religion = %s, description = %s"
    )
    with database_connection() as connection:
        _require_settings(connection)
        result = connection.execute(
            f"UPDATE jewellery.ledger SET {fields} "
            "WHERE ledger_id = %s AND branch_id = 1 RETURNING ledger_id",
            (*_ledger_values(payload), ledger_id),
        ).fetchone()
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ledger account not found.")
        return connection.execute(
            _LEDGER_SELECT + " WHERE ledger_id = %s", (ledger_id,)
        ).fetchone()


@router.delete("/ledger/{ledger_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ledger_entry(ledger_id: int) -> Response:
    with database_connection() as connection:
        _require_settings(connection)
        result = connection.execute(
            "DELETE FROM jewellery.ledger WHERE ledger_id = %s AND branch_id = 1",
            (ledger_id,),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ledger account not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_SCHEME_SUMMARY = """
    SELECT scheme.scheme_id, scheme.scheme_no, scheme.branch_id,
           scheme.customer_id, customer.name AS customer_name,
           customer.contact_no AS customer_phone, scheme.scheme_type,
           scheme.start_date, scheme.tenure_months, scheme.monthly_contribution,
           scheme.bonus_amount, scheme.description, scheme.reminder_date,
           scheme.status, coalesce(sum(payment.paid_amount), 0) AS paid_total,
           count(payment.installment_id) AS installment_count
    FROM jewellery.savings_scheme AS scheme
    JOIN jewellery.ledger AS customer ON customer.ledger_id = scheme.customer_id
    LEFT JOIN jewellery.scheme_installment AS payment
        ON payment.scheme_id = scheme.scheme_id
"""


@router.get("/schemes")
def read_schemes(
    search: str = Query(default="", max_length=100),
    branch_id: int = Query(default=1, ge=1),
) -> list[dict]:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            _SCHEME_SUMMARY
            + """
            WHERE scheme.branch_id = %s
              AND (scheme.scheme_no ILIKE %s OR customer.name ILIKE %s)
            GROUP BY scheme.scheme_id, customer.ledger_id
            ORDER BY scheme.scheme_id DESC
            LIMIT 250
            """,
            (branch_id, f"%{search}%", f"%{search}%"),
        ).fetchall()


def _get_scheme(connection: psycopg.Connection, scheme_id: int) -> dict:
    scheme = connection.execute(
        _SCHEME_SUMMARY
        + """
        WHERE scheme.scheme_id = %s
        GROUP BY scheme.scheme_id, customer.ledger_id
        """,
        (scheme_id,),
    ).fetchone()
    if scheme is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheme not found.")
    return scheme


@router.post("/schemes", status_code=status.HTTP_201_CREATED)
def create_scheme(payload: SchemeInput) -> dict:
    with database_connection() as connection:
        _require_settings(connection)
        customer = connection.execute(
            """
            SELECT ledger_id FROM jewellery.ledger
            WHERE ledger_id = %s AND branch_id = 1
              AND lower(coalesce(party_type, '')) LIKE '%customer%'
            """,
            (payload.customer_id,),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer account not found.")
        created = connection.execute(
            """
            INSERT INTO jewellery.savings_scheme
                (scheme_no, branch_id, customer_id, scheme_type, start_date,
                 tenure_months, monthly_contribution, bonus_amount, description,
                 reminder_date)
            VALUES (
                'SCH-' || lpad(nextval('jewellery.scheme_no_seq')::text, 6, '0'),
                1, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING scheme_id
            """,
            (
                payload.customer_id,
                payload.scheme_type,
                payload.start_date,
                payload.tenure_months,
                payload.monthly_contribution,
                payload.bonus_amount,
                payload.description,
                payload.reminder_date,
            ),
        ).fetchone()
        return _get_scheme(connection, created["scheme_id"])


@router.get("/schemes/{scheme_id}/installments")
def read_scheme_installments(scheme_id: int) -> list[dict]:
    with database_connection() as connection:
        _get_scheme(connection, scheme_id)
        return connection.execute(
            """
            SELECT installment_no, payment_date, paid_amount, gold_rate, late_fine,
                   payment_mode, transaction_reference, deposit_bank
            FROM jewellery.scheme_installment
            WHERE scheme_id = %s
            ORDER BY installment_no
            """,
            (scheme_id,),
        ).fetchall()


@router.post("/schemes/{scheme_id}/installments", status_code=status.HTTP_201_CREATED)
def post_scheme_installment(
    scheme_id: int, payload: SchemeInstallmentInput
) -> dict:
    with database_connection() as connection:
        scheme = connection.execute(
            """
            SELECT scheme.tenure_months, scheme.status,
                   (
                       SELECT count(*)
                       FROM jewellery.scheme_installment AS payment
                       WHERE payment.scheme_id = scheme.scheme_id
                   ) AS installment_count
            FROM jewellery.savings_scheme AS scheme
            WHERE scheme.scheme_id = %s AND scheme.branch_id = 1
            FOR UPDATE
            """,
            (scheme_id,),
        ).fetchone()
        if scheme is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheme not found.")
        if scheme["status"] != "Running":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only running schemes accept installments.")
        expected_number = scheme["installment_count"] + 1
        if payload.installment_no > scheme["tenure_months"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Installment number exceeds this scheme's tenure.",
            )
        if payload.installment_no != expected_number:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Post installment {expected_number} next.",
            )
        connection.execute(
            """
            INSERT INTO jewellery.scheme_installment
                (scheme_id, installment_no, payment_date, paid_amount, gold_rate,
                 late_fine, payment_mode, transaction_reference, deposit_bank)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                scheme_id,
                payload.installment_no,
                payload.payment_date,
                payload.paid_amount,
                payload.gold_rate,
                payload.late_fine,
                payload.payment_mode,
                payload.transaction_reference,
                payload.deposit_bank,
            ),
        )
        count = connection.execute(
            "SELECT count(*) AS paid_count FROM jewellery.scheme_installment WHERE scheme_id = %s",
            (scheme_id,),
        ).fetchone()["paid_count"]
        if count == scheme["tenure_months"]:
            connection.execute(
                "UPDATE jewellery.savings_scheme SET status = 'Completed' WHERE scheme_id = %s",
                (scheme_id,),
            )
        return _get_scheme(connection, scheme_id)


_STOCK_SELECT = """
    SELECT stock.stock_id, stock.tag_no, stock.item_id, item.name AS item_name,
           item.item_prefix_name AS item_prefix, item.material_type,
           stock.carat, stock.item_pcs AS pieces, stock.item_weight AS gross_weight,
           stock.net_weight, stock.labour_chrg AS labour_charge,
           stock.labour_unit, stock.other_charges, stock.size, stock.huid,
           stock.design_no, stock.order_bill_no,
           stock.actual_rate AS purchase_rate, stock.purchase_amount,
           stock.wastage AS wastage_percent, stock.hallmark_chrg AS hallmark_charge,
           stock.mrp, item.gst_rate, item.hsn_code,
           rate.rate_per_gram,
           (stock.net_weight * rate.rate_per_gram)::numeric(14, 2) AS metal_amount,
           CASE
               WHEN stock.labour_unit = 'per_gram'
                  THEN (stock.net_weight * coalesce(stock.labour_chrg, 0))::numeric(14, 2)
               WHEN stock.labour_unit = 'percent'
                   THEN (
                      stock.net_weight * rate.rate_per_gram
                      * coalesce(stock.labour_chrg, 0) / 100
                  )::numeric(14, 2)
              ELSE coalesce(stock.labour_chrg, 0)::numeric(14, 2)
           END AS labour_amount
    FROM jewellery.stock_running AS stock
    JOIN jewellery.item_master AS item
        ON item.item_name_master_id = stock.item_id
    LEFT JOIN LATERAL (
        SELECT r.rate_per_gram
        FROM jewellery.metal_rates AS r
        WHERE r.branch_id = stock.branch_id
          AND r.material_type = item.material_type
          AND r.effective_date <= CURRENT_DATE
          AND (r.material_type = 'silver' OR r.carat = stock.carat)
        ORDER BY r.effective_date DESC, r.metal_rate_id DESC
        LIMIT 1
    ) AS rate ON true
"""


@router.get("/stock")
def read_stock(
    search: str = Query(default="", max_length=100),
    branch_id: int = Query(default=1, ge=1),
) -> list[dict]:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            _STOCK_SELECT
            + """
            WHERE stock.branch_id = %s
              AND stock.is_active IS TRUE
              AND stock.tag_active IS TRUE
              AND stock.sales_used IS FALSE
              AND item.material_type IN ('gold', 'silver')
              AND (stock.tag_no ILIKE %s OR item.name ILIKE %s)
            ORDER BY stock.tag_no
            LIMIT 250
            """,
            (branch_id, f"%{search}%", f"%{search}%"),
        ).fetchall()


@router.post("/stock", status_code=status.HTTP_201_CREATED)
def create_stock(payload: StockInput) -> dict:
    if payload.net_weight > payload.gross_weight:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Net weight cannot exceed gross weight.",
        )
    with database_connection() as connection:
        _require_settings(connection)
        item = connection.execute(
            """
            SELECT item_name_master_id, name, material_type, carat,
                   default_labour_charge, default_labour_unit, default_other_charges
            FROM jewellery.item_master
            WHERE item_name_master_id = %s AND branch_id = 1
            """,
            (payload.item_id,),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="Item was not found.")
        if item["material_type"] not in {"gold", "silver"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tagged sales in this release support gold and silver items.",
            )
        carat = item["carat"] if item["material_type"] == "gold" else Decimal("0")
        if payload.carat not in {Decimal("0"), carat}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Stock carat must match the gold item master.",
            )
        stock = connection.execute(
            """
            INSERT INTO jewellery.stock_running
                (date, item_type, item_id, item_pcs, item_weight, branch_id,
                 tag_no, labour_chrg, labour_unit, is_active, net_weight, carat,
                 sales_used, tag_active, form_name, other_charges, size, huid,
                 design_no, order_bill_no, actual_rate, purchase_amount, wastage,
                 hallmark_chrg, mrp)
            VALUES
                (CURRENT_DATE, %s, %s, %s, %s, 1, %s, %s, %s, TRUE, %s, %s,
                 FALSE, TRUE, 'Desktop POS stock entry', %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s)
            RETURNING stock_id, tag_no, item_id, item_pcs AS pieces,
                      item_weight AS gross_weight, net_weight, carat,
                      labour_chrg AS labour_charge, labour_unit, other_charges,
                      size, huid, design_no, order_bill_no,
                      actual_rate AS purchase_rate, purchase_amount,
                      wastage AS wastage_percent, hallmark_chrg AS hallmark_charge,
                      mrp
            """,
            (
                item["material_type"],
                payload.item_id,
                payload.pieces,
                payload.gross_weight,
                payload.tag_no,
                payload.labour_charge
                if payload.labour_charge is not None
                else item["default_labour_charge"],
                payload.labour_unit or item["default_labour_unit"],
                payload.net_weight,
                carat,
                payload.other_charges
                if payload.other_charges is not None
                else item["default_other_charges"],
                payload.size,
                payload.huid,
                payload.design_no,
                payload.order_bill_no,
                payload.purchase_rate,
                payload.purchase_amount,
                payload.wastage_percent,
                payload.hallmark_charge,
                payload.mrp,
            ),
        ).fetchone()
        return stock


@router.get("/sales")
def read_sales(
    branch_id: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            """
            SELECT sale.sales_bill_info_id, sale.sales_bill_no, sale.purchase_date,
                   sale.grand_total, sale.total_payment, sale.payment_due,
                   sale.user_id AS customer_id, ledger.name AS customer_name
            FROM jewellery.sales_bill_info AS sale
            LEFT JOIN jewellery.ledger AS ledger ON ledger.ledger_id = sale.user_id
            WHERE sale.branch_id = %s AND sale.form_type = 'sale'
            ORDER BY sale.sales_bill_info_id DESC
            LIMIT %s
            """,
            (branch_id, limit),
        ).fetchall()


@router.get("/dashboard")
def read_dashboard(branch_id: int = Query(default=1, ge=1)) -> dict:
    with database_connection() as connection:
        _require_settings(connection, branch_id)
        return connection.execute(
            """
            SELECT
                coalesce(
                    sum(grand_total) FILTER (WHERE purchase_date = CURRENT_DATE),
                    0
                ) AS today_sales,
                count(*) FILTER (WHERE purchase_date = CURRENT_DATE) AS today_invoice_count,
                (
                    SELECT count(*)
                    FROM jewellery.stock_running
                    WHERE branch_id = %s
                      AND is_active IS TRUE
                      AND tag_active IS TRUE
                      AND sales_used IS FALSE
                ) AS available_tags,
                (
                    SELECT count(*)
                    FROM jewellery.ledger
                    WHERE branch_id = %s
                      AND lower(coalesce(party_type, '')) LIKE '%customer%'
                ) AS customer_count,
                (
                    SELECT coalesce(sum(stock.net_weight), 0)
                    FROM jewellery.stock_running AS stock
                    JOIN jewellery.item_master AS item
                        ON item.item_name_master_id = stock.item_id
                    WHERE stock.branch_id = %s
                      AND stock.is_active IS TRUE
                      AND stock.tag_active IS TRUE
                      AND stock.sales_used IS FALSE
                      AND item.material_type = 'gold'
                ) AS gold_stock_weight,
                (
                    SELECT coalesce(sum(stock.net_weight), 0)
                    FROM jewellery.stock_running AS stock
                    JOIN jewellery.item_master AS item
                        ON item.item_name_master_id = stock.item_id
                    WHERE stock.branch_id = %s
                      AND stock.is_active IS TRUE
                      AND stock.tag_active IS TRUE
                      AND stock.sales_used IS FALSE
                      AND item.material_type = 'silver'
                ) AS silver_stock_weight
            FROM jewellery.sales_bill_info
            WHERE branch_id = %s AND form_type = 'sale'
            """,
            (branch_id, branch_id, branch_id, branch_id, branch_id),
        ).fetchone()


@router.get("/sales/{sales_bill_info_id}")
def read_sale(sales_bill_info_id: int) -> dict:
    with database_connection() as connection:
        return _get_sale_detail(connection, sales_bill_info_id)


def _csv_response(
    filename: str, columns: list[str], records: list[dict]
) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for record in records:
        values = []
        for column in columns:
            value = record.get(column)
            if value is None:
                values.append("")
            elif isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                values.append("'" + value)
            else:
                values.append(value)
        writer.writerow(values)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/{resource}")
def export_data(resource: str) -> Response:
    exports = {
        "customers": (
            "customers.csv",
            ["name", "phone", "email", "state", "gstin"],
            """
            SELECT name, contact_no AS phone, email_id AS email,
                   state, gst_no AS gstin
            FROM jewellery.ledger
            WHERE branch_id = 1
              AND lower(coalesce(party_type, '')) LIKE '%customer%'
            ORDER BY name
            LIMIT 10000
            """,
        ),
        "items": (
            "items.csv",
            [
                "name",
                "prefix",
                "material_type",
                "carat",
                "hsn_code",
                "gst_rate",
                "default_labour_charge",
                "default_labour_unit",
                "default_other_charges",
            ],
            """
            SELECT name, item_prefix_name AS prefix, material_type, carat,
                   hsn_code, gst_rate, default_labour_charge,
                   default_labour_unit, default_other_charges
            FROM jewellery.item_master
            WHERE branch_id = 1
            ORDER BY name
            LIMIT 10000
            """,
        ),
        "stock": (
            "stock.csv",
            [
                "tag_no",
                "item_id",
                "gross_weight",
                "net_weight",
                "pieces",
                "carat",
                "labour_charge",
                "labour_unit",
                "other_charges",
                "is_active",
                "sales_used",
            ],
            """
            SELECT tag_no, item_id, item_weight AS gross_weight,
                   net_weight, item_pcs AS pieces, carat, labour_chrg AS labour_charge,
                   labour_unit, other_charges, is_active, sales_used
            FROM jewellery.stock_running
            WHERE branch_id = 1
            ORDER BY stock_id
            LIMIT 10000
            """,
        ),
        "sales": (
            "sales.csv",
            [
                "sales_bill_no",
                "purchase_date",
                "customer_name",
                "grand_total",
                "total_payment",
                "payment_due",
                "status",
            ],
            """
            SELECT sale.sales_bill_no, sale.purchase_date, ledger.name AS customer_name,
                   sale.grand_total, sale.total_payment, sale.payment_due, sale.status
            FROM jewellery.sales_bill_info AS sale
            LEFT JOIN jewellery.ledger AS ledger ON ledger.ledger_id = sale.user_id
            WHERE sale.branch_id = 1 AND sale.form_type = 'sale'
            ORDER BY sale.sales_bill_info_id
            LIMIT 10000
            """,
        ),
    }
    export = exports.get(resource)
    if export is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Choose one of these export types: customers, items, stock, sales.",
        )
    filename, columns, query = export
    with database_connection() as connection:
        _require_settings(connection)
        records = connection.execute(query.replace("LIMIT 10000", "LIMIT 10001")).fetchall()
        if len(records) > 10_000:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="This export exceeds 10,000 records; export a smaller subset.",
            )
        return _csv_response(filename, columns, records)


@router.post("/import/customers", status_code=status.HTTP_201_CREATED)
async def import_customers(request: Request) -> dict[str, int]:
    csv_bytes = await request.body()
    if len(csv_bytes) > 2_000_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Customer CSV must be smaller than 2 MB.",
        )
    try:
        text = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = [header.strip().casefold() for header in (reader.fieldnames or [])]
        allowed_headers = {"name", "phone", "email", "state", "gstin"}
        if (
            not headers
            or len(headers) != len(set(headers))
            or "name" not in headers
            or not set(headers) <= allowed_headers
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="CSV needs a name column. Optional columns: phone, email, state, gstin.",
            )
        reader.fieldnames = headers
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not a valid UTF-8 CSV.",
        ) from exc

    if len(rows) > 5000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Import at most 5,000 customers at a time.",
        )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The customer CSV has a header but no data rows.",
        )

    with database_connection() as connection:
        _require_settings(connection)
        for row_number, row in enumerate(rows, start=2):
            if None in row or any(isinstance(value, list) for value in row.values()):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Customer CSV row {row_number} has a different number of columns than its header.",
                )
            try:
                customer = CustomerInput.model_validate(
                    {key: value or None for key, value in row.items()}
                )
            except ValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Customer CSV row {row_number} contains invalid values.",
                ) from exc
            connection.execute(
                """
                INSERT INTO jewellery.ledger
                    (name, branch_id, email_id, contact_no, state, gst_no, party_type,
                     created_date_time)
                VALUES (%s, 1, %s, %s, %s, %s, 'Retail Customer', now())
                """,
                (
                    customer.name,
                    customer.email,
                    customer.phone,
                    customer.state,
                    customer.gstin,
                ),
            )
    return {"imported": len(rows)}


def _prepare_sale(
    connection: psycopg.Connection, payload: SaleInput, lock_stock: bool
) -> tuple[
    dict,
    list[dict],
    dict | None,
    list[SaleLineAmounts],
    list[Decimal],
    SaleTotals,
    bool,
]:
    settings = _require_settings(connection)
    lock_clause = "FOR UPDATE OF stock" if lock_stock else ""
    rows = connection.execute(
        _STOCK_SELECT
        + f"""
        WHERE stock.branch_id = %s
          AND stock.stock_id = ANY(%s)
          AND stock.is_active IS TRUE
          AND stock.tag_active IS TRUE
          AND stock.sales_used IS FALSE
        ORDER BY stock.stock_id
        {lock_clause}
        """,
        (1, payload.stock_ids),
    ).fetchall()
    if len(rows) != len(payload.stock_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more selected tags are no longer available. Refresh the stock list.",
        )

    customer = None
    if payload.customer_id is not None:
        customer = connection.execute(
            """
            SELECT ledger_id, name, state
            FROM jewellery.ledger
            WHERE ledger_id = %s AND branch_id = 1
              AND lower(coalesce(party_type, '')) LIKE '%customer%'
            """,
            (payload.customer_id,),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer was not found.")

    line_amounts: list[SaleLineAmounts] = []
    for row in rows:
        if row["rate_per_gram"] is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No current {row['material_type']} rate is configured for tag {row['tag_no']}.",
            )
        try:
            line_amounts.append(
                calculate_line(
                    SaleLineInput(
                        net_weight=row["net_weight"],
                        rate_per_gram=row["rate_per_gram"],
                        labour_charge=row["labour_charge"] or Decimal("0"),
                        labour_unit=row["labour_unit"] or "fixed",
                        other_charges=row["other_charges"] or Decimal("0"),
                        gst_rate=row["gst_rate"],
                    )
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid pricing data for tag {row['tag_no']}: {exc}",
            ) from exc

    taxable_before_gst = sum((line.subtotal for line in line_amounts), Decimal("0"))
    if payload.discount > taxable_before_gst:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Discount cannot exceed the pre-tax sale subtotal.",
        )
    customer_state = settings["state"] if customer is None else customer["state"]
    has_taxable_lines = any(line.gst_rate > 0 for line in line_amounts)
    if has_taxable_lines and not customer_state:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Set the customer's state before calculating GST.",
        )
    is_interstate = (
        (customer_state or "").strip().casefold()
        != settings["state"].strip().casefold()
    )
    try:
        totals = calculate_totals(
            line_amounts,
            payload.discount,
            payload.cash_amount,
            payload.bank_amount,
            is_interstate,
        )
        allocations = allocate_discount(line_amounts, totals.discount)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return settings, rows, customer, line_amounts, allocations, totals, is_interstate


@router.post("/sales/quote")
def quote_sale(payload: SaleInput) -> dict:
    with database_connection() as connection:
        _, rows, _, line_amounts, discounts, totals, is_interstate = _prepare_sale(
            connection, payload, lock_stock=False
        )
        lines = []
        for row, amounts, discount_share in zip(
            rows, line_amounts, discounts, strict=True
        ):
            taxable_line = money(amounts.subtotal - discount_share)
            tax = money(taxable_line * amounts.gst_rate / Decimal("100"))
            lines.append(
                {
                    "stock_id": row["stock_id"],
                    "tag_no": row["tag_no"],
                    "item_name": row["item_name"],
                    "net_weight": row["net_weight"],
                    "rate_per_gram": row["rate_per_gram"],
                    "metal_amount": amounts.metal_amount,
                    "labour_amount": amounts.labour_amount,
                    "other_charges": amounts.other_charges,
                    "subtotal": amounts.subtotal,
                    "discount": discount_share,
                    "taxable_amount": taxable_line,
                    "gst_rate": amounts.gst_rate,
                    "igst_amount": tax if is_interstate else Decimal("0"),
                    "cgst_amount": (
                        Decimal("0")
                        if is_interstate
                        else money(
                            taxable_line
                            * amounts.gst_rate
                            / Decimal("2")
                            / Decimal("100")
                        )
                    ),
                    "sgst_amount": (
                        Decimal("0")
                        if is_interstate
                        else money(
                            taxable_line
                            * amounts.gst_rate
                            / Decimal("2")
                            / Decimal("100")
                        )
                    ),
                }
            )
        return {
            "lines": lines,
            "totals": totals,
            "tax_type": "IGST" if is_interstate else "CGST_SGST",
        }


@router.post("/sales", status_code=status.HTTP_201_CREATED)
def create_sale(payload: SaleInput) -> dict:
    with database_connection() as connection:
        (
            settings,
            rows,
            _,
            line_amounts,
            allocations,
            totals,
            is_interstate,
        ) = _prepare_sale(connection, payload, lock_stock=True)

        today = date.today()
        fiscal_year_start_month = settings["fiscal_year_start_month"]
        year_id = today.year if today.month >= fiscal_year_start_month else today.year - 1
        sequence = connection.execute(
            "SELECT nextval('jewellery.sales_invoice_number_seq') AS number"
        ).fetchone()["number"]
        invoice_number = f"SALE-{1}-{year_id}-{sequence:06d}"
        paid_amount = totals.cash_amount + totals.bank_amount
        payment_status = (
            "PAID" if totals.payment_due == 0 else "PARTIALLY_PAID" if paid_amount else "UNPAID"
        )
        header = connection.execute(
            """
            INSERT INTO jewellery.sales_bill_info
                (user_id, purchase_date, sales_bill_no, branch_id, total_purchase_rs,
                 discount, grand_total, total_payment, payment_due, cgst_per, cgst_rs,
                 sgst_per, sgst_rs, igst_per, igst_rs, account_mode, description,
                 form_type, year_id, status, khata_user_id, cash_amount, bank_amount,
                 before_tax, gst, bill_type, created_date_time)
            VALUES
                (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                 %s, %s, 'sale', %s, %s, %s, %s, %s, %s, %s, 'Retail Sales', now())
            RETURNING sales_bill_info_id, sales_bill_no, purchase_date, branch_id,
                      total_purchase_rs, discount, grand_total, total_payment,
                      payment_due, cgst_per, cgst_rs, sgst_per, sgst_rs,
                      igst_per, igst_rs, account_mode, description, form_type,
                      year_id, status, user_id, cash_amount, bank_amount, before_tax, gst
            """,
            (
                payload.customer_id,
                today,
                invoice_number,
                totals.subtotal,
                totals.discount,
                totals.grand_total,
                paid_amount,
                totals.payment_due,
                totals.cgst_rate,
                totals.cgst_amount,
                totals.sgst_rate,
                totals.sgst_amount,
                totals.igst_rate,
                totals.igst_amount,
                "Cash and Bank" if totals.cash_amount and totals.bank_amount
                else "Cash" if totals.cash_amount
                else "Bank" if totals.bank_amount
                else "Due",
                payload.description,
                year_id,
                payment_status,
                payload.customer_id,
                totals.cash_amount,
                totals.bank_amount,
                totals.taxable_amount,
                totals.cgst_amount + totals.sgst_amount + totals.igst_amount,
            ),
        ).fetchone()

        for row, amounts, discount_share in zip(rows, line_amounts, allocations, strict=True):
            taxable_line = money(amounts.subtotal - discount_share)
            line_tax = money(taxable_line * amounts.gst_rate / Decimal("100"))
            if is_interstate:
                cgst_rate = cgst_amount = sgst_rate = sgst_amount = Decimal("0")
                igst_rate, igst_amount = amounts.gst_rate, line_tax
            else:
                cgst_rate = sgst_rate = amounts.gst_rate / Decimal("2")
                cgst_amount = money(taxable_line * cgst_rate / Decimal("100"))
                sgst_amount = money(taxable_line * sgst_rate / Decimal("100"))
                igst_rate = igst_amount = Decimal("0")
            connection.execute(
                """
                INSERT INTO jewellery.sales_bill_purchase
                    (bill_no, purchase_type, purchase_item_id, purchase_pcs,
                     purchase_weight, purchase_labour_chrg, purchase_rate, purchase_rs,
                     branch_id, purchase_labour_chrg_unit, purchase_carat, account_mode,
                     gross_weight, cgst_per, cgst_rs, sgst_per, sgst_rs, igst_per,
                     igst_rs, with_gst, adj_amt, form_type, year_id, other_chrg,
                     bill_print_item_name, stock_id, purity, fine, category_id, user_id,
                     discount)
                VALUES
                    (%s, 'Sale', %s, %s, %s, %s, %s, %s, 1, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, 'sale', %s, %s,
                     %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    invoice_number,
                    row["item_id"],
                    row["pieces"],
                    row["net_weight"],
                    row["labour_charge"] or Decimal("0"),
                    row["rate_per_gram"],
                    taxable_line,
                    row["labour_unit"],
                    row["carat"],
                    "Taxable" if amounts.gst_rate else "No GST",
                    row["gross_weight"],
                    cgst_rate,
                    cgst_amount,
                    sgst_rate,
                    sgst_amount,
                    igst_rate,
                    igst_amount,
                    "Yes" if amounts.gst_rate else "No",
                    discount_share,
                    year_id,
                    amounts.other_charges,
                    row["item_name"],
                    row["stock_id"],
                    row["carat"] / Decimal("24")
                    if row["material_type"] == "gold"
                    else Decimal("0"),
                    row["net_weight"] * row["carat"] / Decimal("24")
                    if row["material_type"] == "gold"
                    else Decimal("0"),
                    row["item_id"],
                    payload.customer_id,
                    discount_share,
                ),
            )
            connection.execute(
                """
                UPDATE jewellery.stock_running
                SET sales_used = TRUE, tag_active = FALSE, is_active = FALSE
                WHERE stock_id = %s AND branch_id = 1
                  AND is_active IS TRUE AND tag_active IS TRUE AND sales_used IS FALSE
                """,
                (row["stock_id"],),
            )

        return _get_sale_detail(connection, header["sales_bill_info_id"])
