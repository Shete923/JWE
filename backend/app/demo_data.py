import os

import psycopg
from psycopg.rows import dict_row

SEED_NAME = "retail-mvp-demo-v1"
DATABASE_URL = os.getenv("DATABASE_URL")


def seed_demo_data() -> None:
    if not DATABASE_URL:
        raise RuntimeError("Set DATABASE_URL before loading demo data.")

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        previous = connection.execute(
            "SELECT seed_name FROM jewellery.demo_seed_runs WHERE seed_name = %s",
            (SEED_NAME,),
        ).fetchone()
        if previous is not None:
            print("Clearly labelled retail demo data has already been loaded.")
            return

        settings = connection.execute(
            "SELECT business_name FROM jewellery.shop_settings WHERE branch_id = 1"
        ).fetchone()
        if settings and not settings["business_name"].startswith("[DEMO ONLY]"):
            raise RuntimeError(
                "Refusing to mix demo prices and records into a configured store. "
                "Use an empty/demo database for the demo seed."
            )

        connection.execute(
            """
            INSERT INTO jewellery.shop_settings
                (branch_id, business_name, state, fiscal_year_start_month)
            VALUES (1, '[DEMO ONLY] Jewellery Test Shop', 'Demo State', 4)
            ON CONFLICT (branch_id) DO NOTHING
            """
        )
        item = connection.execute(
            """
            INSERT INTO jewellery.item_master
                (name, branch_id, item_prefix_name, hsn_code, default_stock_product,
                 type, remove_product, apply_loyalty, default_retail_product,
                 material_type, carat, default_labour_charge, default_labour_unit,
                 default_other_charges, gst_rate)
            VALUES
                ('[DEMO ONLY] 22K Test Ring', 1, 'DEMO22', NULL, 'Yes',
                 'Gold', 'No', 'No', 'Yes', 'gold', 22, 200, 'per_gram', 0, 0)
            ON CONFLICT DO NOTHING
            RETURNING item_name_master_id
            """
        ).fetchone()
        if item is None:
            item = connection.execute(
                """
                SELECT item_name_master_id, name, material_type, carat
                FROM jewellery.item_master
                WHERE branch_id = 1 AND lower(item_prefix_name) = 'demo22'
                """
            ).fetchone()
        if item is None:
            raise RuntimeError("The demo item could not be created.")
        if (
            item.get("name") not in {None, "[DEMO ONLY] 22K Test Ring"}
            or item.get("material_type") not in {None, "gold"}
            or item.get("carat") not in {None, 22, 22.0}
        ):
            raise RuntimeError(
                "The DEMO22 prefix is already used by a non-demo item; refusing to seed."
            )

        customer = connection.execute(
            """
            INSERT INTO jewellery.ledger
                (name, branch_id, email_id, contact_no, state, party_type, description)
            VALUES
                ('[DEMO ONLY] Test Customer', 1, 'demo.customer@example.invalid',
                 '0000000000', 'Demo State', 'Retail Customer',
                 'Fictional record for testing only; not a real person.')
            ON CONFLICT DO NOTHING
            RETURNING ledger_id
            """
        ).fetchone()
        if customer is None:
            customer = connection.execute(
                """
                SELECT ledger_id, name FROM jewellery.ledger
                WHERE branch_id = 1 AND lower(email_id) = 'demo.customer@example.invalid'
                """
            ).fetchone()
        if customer is None:
            raise RuntimeError("The demo customer could not be created.")
        if customer.get("name") not in {None, "[DEMO ONLY] Test Customer"}:
            raise RuntimeError(
                "The demo email is already used by another customer; refusing to seed."
            )

        connection.execute(
            """
            INSERT INTO jewellery.metal_rates
                (branch_id, effective_date, material_type, carat, rate_per_gram)
            VALUES (1, CURRENT_DATE, 'gold', 22, 7000)
            ON CONFLICT (branch_id, effective_date, material_type, carat) DO NOTHING
            """
        )
        connection.execute(
            """
            INSERT INTO jewellery.metal_rates
                (branch_id, effective_date, material_type, carat, rate_per_gram)
            VALUES (1, CURRENT_DATE, 'silver', 0, 90)
            ON CONFLICT (branch_id, effective_date, material_type, carat) DO NOTHING
            """
        )
        connection.execute(
            """
            INSERT INTO jewellery.stock_running
                (date, item_type, item_id, item_pcs, item_weight, branch_id,
                 tag_no, labour_chrg, labour_unit, is_active,
                 net_weight, carat, sales_used, tag_active, form_name,
                 other_charges, remarks)
            VALUES
                (CURRENT_DATE, 'gold', %s, 1, 5.000, 1,
                 'DEMO-22K-RING-001', 200, 'per_gram', TRUE,
                 4.800, 22, FALSE, TRUE, 'Demo seed only',
                 0, 'DEMO ONLY: fictional test inventory')
            ON CONFLICT (tag_no) DO NOTHING
            """,
            (item["item_name_master_id"],),
        )
        connection.execute(
            "INSERT INTO jewellery.demo_seed_runs (seed_name) VALUES (%s)",
            (SEED_NAME,),
        )

    print(
        "Created clearly labelled demo store settings, a fictional customer, "
        "a demo item/tag, and example metal rates. GST is 0% on the demo item; "
        "configure actual rates before any real invoice."
    )


if __name__ == "__main__":
    seed_demo_data()
