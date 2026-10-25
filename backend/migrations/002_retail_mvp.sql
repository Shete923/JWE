BEGIN;

ALTER TABLE jewellery.item_master
    ADD COLUMN IF NOT EXISTS material_type TEXT,
    ADD COLUMN IF NOT EXISTS carat NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS default_labour_charge NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS default_labour_unit TEXT,
    ADD COLUMN IF NOT EXISTS default_other_charges NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS gst_rate NUMERIC(7, 4);

UPDATE jewellery.item_master
SET material_type = COALESCE(material_type, 'other'),
    carat = COALESCE(carat, 0),
    default_labour_charge = COALESCE(default_labour_charge, 0),
    default_labour_unit = COALESCE(default_labour_unit, 'fixed'),
    default_other_charges = COALESCE(default_other_charges, 0),
    gst_rate = COALESCE(gst_rate, 0);

ALTER TABLE jewellery.item_master
    ALTER COLUMN material_type SET DEFAULT 'other',
    ALTER COLUMN material_type SET NOT NULL,
    ALTER COLUMN carat SET DEFAULT 0,
    ALTER COLUMN carat SET NOT NULL,
    ALTER COLUMN default_labour_charge SET DEFAULT 0,
    ALTER COLUMN default_labour_charge SET NOT NULL,
    ALTER COLUMN default_labour_unit SET DEFAULT 'fixed',
    ALTER COLUMN default_labour_unit SET NOT NULL,
    ALTER COLUMN default_other_charges SET DEFAULT 0,
    ALTER COLUMN default_other_charges SET NOT NULL,
    ALTER COLUMN gst_rate SET DEFAULT 0,
    ALTER COLUMN gst_rate SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.item_master'::regclass
          AND conname = 'ck_item_master_material_type'
    ) THEN
        ALTER TABLE jewellery.item_master
            ADD CONSTRAINT ck_item_master_material_type
            CHECK (material_type IN ('gold', 'silver', 'other'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.item_master'::regclass
          AND conname = 'ck_item_master_carat'
    ) THEN
        ALTER TABLE jewellery.item_master
            ADD CONSTRAINT ck_item_master_carat
            CHECK (carat >= 0 AND carat <= 24);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.item_master'::regclass
          AND conname = 'ck_item_master_default_labour_charge'
    ) THEN
        ALTER TABLE jewellery.item_master
            ADD CONSTRAINT ck_item_master_default_labour_charge
            CHECK (default_labour_charge >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.item_master'::regclass
          AND conname = 'ck_item_master_default_labour_unit'
    ) THEN
        ALTER TABLE jewellery.item_master
            ADD CONSTRAINT ck_item_master_default_labour_unit
            CHECK (default_labour_unit IN ('fixed', 'per_gram', 'percent'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.item_master'::regclass
          AND conname = 'ck_item_master_default_other_charges'
    ) THEN
        ALTER TABLE jewellery.item_master
            ADD CONSTRAINT ck_item_master_default_other_charges
            CHECK (default_other_charges >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.item_master'::regclass
          AND conname = 'ck_item_master_gst_rate'
    ) THEN
        ALTER TABLE jewellery.item_master
            ADD CONSTRAINT ck_item_master_gst_rate
            CHECK (gst_rate >= 0 AND gst_rate <= 100);
    END IF;
END
$$;

ALTER TABLE jewellery.stock_running
    ADD COLUMN IF NOT EXISTS other_charges NUMERIC(14, 2);

UPDATE jewellery.stock_running
SET other_charges = 0
WHERE other_charges IS NULL;

ALTER TABLE jewellery.stock_running
    ALTER COLUMN other_charges SET DEFAULT 0,
    ALTER COLUMN other_charges SET NOT NULL;

UPDATE jewellery.stock_running
SET labour_unit = CASE
    WHEN lower(trim(labour_unit)) IN ('per gram', 'per_gram', 'gram') THEN 'per_gram'
    WHEN lower(trim(labour_unit)) IN ('percent', 'percentage', '%') THEN 'percent'
    ELSE 'fixed'
END
WHERE labour_unit IS NOT NULL;

ALTER TABLE jewellery.stock_running
    ALTER COLUMN labour_unit SET DEFAULT 'fixed';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.stock_running'::regclass
          AND conname = 'ck_stock_running_other_charges'
    ) THEN
        ALTER TABLE jewellery.stock_running
            ADD CONSTRAINT ck_stock_running_other_charges
            CHECK (other_charges >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.stock_running'::regclass
          AND conname = 'ck_stock_running_labour_unit'
    ) THEN
        ALTER TABLE jewellery.stock_running
            ADD CONSTRAINT ck_stock_running_labour_unit
            CHECK (labour_unit IS NULL OR labour_unit IN ('fixed', 'per_gram', 'percent'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'jewellery.stock_running'::regclass
          AND conname = 'ck_stock_running_nonnegative_weights'
    ) THEN
        ALTER TABLE jewellery.stock_running
            ADD CONSTRAINT ck_stock_running_nonnegative_weights
            CHECK (
                (item_weight IS NULL OR item_weight >= 0)
                AND (net_weight IS NULL OR net_weight >= 0)
                AND (item_pcs IS NULL OR item_pcs >= 0)
            );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS jewellery.shop_settings (
    branch_id BIGINT PRIMARY KEY CHECK (branch_id = 1),
    business_name TEXT NOT NULL CHECK (length(trim(business_name)) > 0),
    state TEXT NOT NULL CHECK (length(trim(state)) > 0),
    gstin TEXT,
    fiscal_year_start_month SMALLINT NOT NULL DEFAULT 4
        CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jewellery.metal_rates (
    metal_rate_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    branch_id BIGINT NOT NULL REFERENCES jewellery.shop_settings (branch_id),
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    material_type TEXT NOT NULL CHECK (material_type IN ('gold', 'silver')),
    carat NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (carat >= 0 AND carat <= 24),
    rate_per_gram NUMERIC(14, 4) NOT NULL CHECK (rate_per_gram > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_metal_rate_day_material_carat
        UNIQUE (branch_id, effective_date, material_type, carat),
    CONSTRAINT ck_metal_rate_carat
        CHECK (
            (material_type = 'gold' AND carat > 0)
            OR (material_type = 'silver' AND carat = 0)
        )
);

CREATE SEQUENCE IF NOT EXISTS jewellery.sales_invoice_number_seq AS BIGINT START WITH 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_branch_email
    ON jewellery.ledger (branch_id, lower(email_id))
    WHERE email_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_item_master_branch_prefix
    ON jewellery.item_master (branch_id, lower(item_prefix_name))
    WHERE item_prefix_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_metal_rates_lookup
    ON jewellery.metal_rates (branch_id, material_type, carat, effective_date DESC);
CREATE INDEX IF NOT EXISTS ix_sales_bill_purchase_stock_id
    ON jewellery.sales_bill_purchase (stock_id);
CREATE INDEX IF NOT EXISTS ix_sales_bill_info_number
    ON jewellery.sales_bill_info (sales_bill_no);

CREATE TABLE IF NOT EXISTS jewellery.demo_seed_runs (
    seed_name TEXT PRIMARY KEY,
    seeded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
