import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.retail_ui import RetailWindow, money_text


class RetailDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = RetailWindow()

    def tearDown(self) -> None:
        self.window.close()

    def test_builds_all_retail_pages(self) -> None:
        self.assertEqual(self.window.pages.count(), 8)
        self.assertEqual(self.window.navigation.count(), 13)

    def test_navigation_opens_store_settings_page(self) -> None:
        self.window.navigation.setCurrentRow(12)

        self.assertEqual(self.window.pages.currentIndex(), 7)
        self.assertEqual(self.window.page_heading.text(), "Store settings")

    def test_navigation_opens_ledger_and_scheme_pages(self) -> None:
        self.window.navigation.setCurrentRow(3)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertEqual(self.window.page_heading.text(), "Customer & party ledger")

        self.window.navigation.setCurrentRow(4)
        self.assertEqual(self.window.pages.currentIndex(), 4)
        self.assertEqual(self.window.page_heading.text(), "Scheme / installments")

    def test_scheme_maturity_uses_tenure_contributions_and_bonus(self) -> None:
        self.window.scheme_tenure.setValue(12)
        self.window.scheme_monthly_amount.setValue(2000)
        self.window.scheme_bonus_amount.setValue(2000)

        self.assertIn("₹ 26,000.00", self.window.scheme_maturity_label.text())

    def test_quote_is_invalidated_when_checkout_inputs_change(self) -> None:
        self.window._last_quote = {"totals": {"grand_total": 100}}

        self.window.pos_cash.setValue(10)

        self.assertIsNone(self.window._last_quote)

    def test_currency_display_uses_server_amount_without_float_rounding_rules(self) -> None:
        self.assertEqual(money_text("123456.78"), "\u20b9 123,456.78")


if __name__ == "__main__":
    unittest.main()
