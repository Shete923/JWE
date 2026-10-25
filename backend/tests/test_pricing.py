import unittest
from decimal import Decimal

from app.pricing import (
    SaleLineInput,
    allocate_discount,
    calculate_line,
    calculate_totals,
)


class JewelleryPricingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.line = calculate_line(
            SaleLineInput(
                net_weight=Decimal("10.000"),
                rate_per_gram=Decimal("7000"),
                labour_charge=Decimal("250"),
                labour_unit="per_gram",
                other_charges=Decimal("500"),
                gst_rate=Decimal("3"),
            )
        )

    def test_calculates_net_weight_metal_labour_and_other_charges(self) -> None:
        self.assertEqual(self.line.metal_amount, Decimal("70000.00"))
        self.assertEqual(self.line.labour_amount, Decimal("2500.00"))
        self.assertEqual(self.line.other_charges, Decimal("500.00"))
        self.assertEqual(self.line.subtotal, Decimal("73000.00"))

    def test_calculates_intra_state_cgst_and_sgst(self) -> None:
        totals = calculate_totals(
            [self.line],
            discount=Decimal("0"),
            cash_amount=Decimal("10000"),
            bank_amount=Decimal("0"),
            is_interstate=False,
        )
        self.assertEqual(totals.cgst_amount, Decimal("1095.00"))
        self.assertEqual(totals.sgst_amount, Decimal("1095.00"))
        self.assertEqual(totals.igst_amount, Decimal("0"))
        self.assertEqual(totals.grand_total, Decimal("75190.00"))
        self.assertEqual(totals.payment_due, Decimal("65190.00"))

    def test_calculates_interstate_igst_and_discount(self) -> None:
        totals = calculate_totals(
            [self.line],
            discount=Decimal("1000"),
            cash_amount=Decimal("0"),
            bank_amount=Decimal("0"),
            is_interstate=True,
        )
        self.assertEqual(totals.taxable_amount, Decimal("72000.00"))
        self.assertEqual(totals.igst_amount, Decimal("2160.00"))
        self.assertEqual(totals.cgst_amount, Decimal("0"))
        self.assertEqual(totals.grand_total, Decimal("74160.00"))

    def test_allocates_rounding_residual_to_last_line(self) -> None:
        lines = [
            calculate_line(
                SaleLineInput(
                    net_weight=Decimal("1"),
                    rate_per_gram=Decimal("1"),
                    labour_charge=Decimal("0"),
                    labour_unit="fixed",
                    other_charges=Decimal("0"),
                    gst_rate=Decimal("0"),
                )
            )
            for _ in range(3)
        ]
        self.assertEqual(
            allocate_discount(lines, Decimal("0.01")),
            [Decimal("0.00"), Decimal("0.00"), Decimal("0.01")],
        )

    def test_rejects_overpayment(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot exceed the invoice total"):
            calculate_totals(
                [self.line],
                discount=Decimal("0"),
                cash_amount=Decimal("99999"),
                bank_amount=Decimal("0"),
                is_interstate=False,
            )


if __name__ == "__main__":
    unittest.main()
