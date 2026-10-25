import unittest
from decimal import Decimal

from pydantic import ValidationError

from app.schemas import (
    ItemInput,
    LedgerInput,
    MetalRateInput,
    SaleInput,
    SchemeInput,
    SchemeInstallmentInput,
    StockInput,
)


class RetailSchemaTests(unittest.TestCase):
    def test_requires_gold_item_carat(self) -> None:
        with self.assertRaises(ValidationError):
            ItemInput(
                name="Ring",
                prefix="RING",
                material_type="gold",
                carat=Decimal("0"),
            )

    def test_rejects_carat_on_silver_rate(self) -> None:
        with self.assertRaises(ValidationError):
            MetalRateInput(
                material_type="silver",
                carat=Decimal("22"),
                rate_per_gram=Decimal("90"),
            )

    def test_rejects_duplicate_stock_tags_in_one_sale(self) -> None:
        with self.assertRaises(ValidationError):
            SaleInput(stock_ids=[12, 12])

    def test_rejects_negative_gst(self) -> None:
        with self.assertRaises(ValidationError):
            ItemInput(
                name="Silver bowl",
                prefix="SLB",
                material_type="silver",
                gst_rate=Decimal("-1"),
            )

    def test_normalizes_ledger_identifiers_and_email(self) -> None:
        entry = LedgerInput(
            name="  M. Jewellers ",
            email=" SHOP@EXAMPLE.COM ",
            gstin="27aabcu9603r1zm",
            ifsc_code="sbin0000437",
        )

        self.assertEqual(entry.name, "M. Jewellers")
        self.assertEqual(entry.email, "shop@example.com")
        self.assertEqual(entry.gstin, "27AABCU9603R1ZM")
        self.assertEqual(entry.ifsc_code, "SBIN0000437")

    def test_rejects_negative_opening_metal_balance(self) -> None:
        with self.assertRaises(ValidationError):
            LedgerInput(name="Customer", opening_gold_grams=Decimal("-0.001"))

    def test_rejects_zero_scheme_contribution(self) -> None:
        with self.assertRaises(ValidationError):
            SchemeInput(
                customer_id=1,
                start_date="2026-10-22",
                tenure_months=12,
                monthly_contribution=Decimal("0"),
                description="Gold savings plan",
            )

    def test_rejects_invalid_scheme_payment_mode(self) -> None:
        with self.assertRaises(ValidationError):
            SchemeInstallmentInput(
                installment_no=1,
                payment_date="2026-10-22",
                paid_amount=Decimal("1000"),
                payment_mode="Crypto",
            )

    def test_accepts_stock_tag_details_from_inventory_screen(self) -> None:
        stock = StockInput(
            item_id=1,
            tag_no="BG-001",
            gross_weight=Decimal("22.450"),
            net_weight=Decimal("21.980"),
            size="2.4",
            huid="ABC1234567",
            purchase_rate=Decimal("6452"),
            purchase_amount=Decimal("145345"),
            wastage_percent=Decimal("2.5"),
            hallmark_charge=Decimal("45"),
            mrp=Decimal("172000"),
        )

        self.assertEqual(stock.tag_no, "BG-001")
        self.assertEqual(stock.wastage_percent, Decimal("2.5"))
        self.assertEqual(stock.purchase_amount, Decimal("145345"))


if __name__ == "__main__":
    unittest.main()
