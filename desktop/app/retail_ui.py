from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiWorker
from app.health import normalize_base_url

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
BRANCH_ID = 1
REFRESH_INTERVAL_MS = 30_000
GOLD = "#e5a400"
INK = "#172238"
MUTED = "#64738a"
GREEN = "#078a65"
RED = "#c23a4b"
AMBER = "#b66800"
SURFACE = "#ffffff"
CANVAS = "#eff3f8"
LINE = "#d9e1ec"


def decimal_value(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def money_text(value: object) -> str:
    amount = float(decimal_value(value))
    return f"₹ {amount:,.2f}"


def weight_text(value: object) -> str:
    return f"{decimal_value(value):,.3f} g"


def value_item(value: object, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem("" if value is None else str(value))
    if align_right:
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
    return item


def build_table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(36)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setShowGrid(False)
    return table


def make_card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    if title:
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
    return frame, layout


def make_input(label: str, placeholder: str = "") -> tuple[QVBoxLayout, QLineEdit]:
    column = QVBoxLayout()
    column.setSpacing(5)
    title = QLabel(label)
    title.setObjectName("fieldLabel")
    field = QLineEdit()
    field.setObjectName("fieldInput")
    field.setPlaceholderText(placeholder)
    column.addWidget(title)
    column.addWidget(field)
    return column, field


def make_combo(label: str, values: list[tuple[str, str]]) -> tuple[QVBoxLayout, QComboBox]:
    column = QVBoxLayout()
    column.setSpacing(5)
    title = QLabel(label)
    title.setObjectName("fieldLabel")
    field = QComboBox()
    field.setObjectName("fieldInput")
    for display, value in values:
        field.addItem(display, value)
    column.addWidget(title)
    column.addWidget(field)
    return column, field


def make_number(
    label: str,
    decimals: int = 2,
    maximum: float = 1_000_000_000,
    minimum: float = 0,
) -> tuple[QVBoxLayout, QDoubleSpinBox]:
    column = QVBoxLayout()
    column.setSpacing(5)
    title = QLabel(label)
    title.setObjectName("fieldLabel")
    field = QDoubleSpinBox()
    field.setObjectName("fieldInput")
    field.setDecimals(decimals)
    field.setRange(minimum, maximum)
    field.setKeyboardTracking(False)
    field.setGroupSeparatorShown(True)
    field.setAccelerated(True)
    column.addWidget(title)
    column.addWidget(field)
    return column, field


class RetailWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Dindorkar Saraf · Jewellery Management")
        self.setMinimumSize(1180, 760)
        self.resize(1480, 940)
        self.backend_url = DEFAULT_BACKEND_URL
        self.settings: dict[str, Any] | None = None
        self.items: list[dict[str, Any]] = []
        self.customers: list[dict[str, Any]] = []
        self.stock: list[dict[str, Any]] = []
        self.sales: list[dict[str, Any]] = []
        self.ledger_entries: list[dict[str, Any]] = []
        self.schemes: list[dict[str, Any]] = []
        self.selected_ledger_id: int | None = None
        self.installment_request_generation = 0
        self.workers: dict[str, ApiWorker] = {}
        self.success_handlers: dict[str, Callable[[Any], None]] = {}
        self.error_handlers: dict[str, Callable[[str], None]] = {}
        self.blocking_errors = {"save-settings", "save-rate", "create-item",
                                "create-stock", "create-customer", "checkout",
                                "import-customers", "create-ledger", "delete-ledger",
                                "create-scheme", "post-installment"}

        central = QWidget()
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.navigation = self._build_navigation()
        central_layout.addWidget(self.navigation)

        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 16, 22, 18)
        content_layout.setSpacing(14)
        content_layout.addLayout(self._build_topbar())
        self.page_heading = QLabel("Overview")
        self.page_heading.setObjectName("pageTitle")
        content_layout.addWidget(self.page_heading)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_dashboard())
        self.pages.addWidget(self._build_ledger())
        self.pages.addWidget(self._build_pos())
        self.pages.addWidget(self._build_inventory())
        self.pages.addWidget(self._build_scheme())
        self.pages.addWidget(self._build_customers())
        self.pages.addWidget(self._build_catalog())
        self.pages.addWidget(self._build_settings())
        content_layout.addWidget(self.pages, 1)
        central_layout.addWidget(content, 1)
        self.setCentralWidget(central)

        self.navigation.currentRowChanged.connect(self._change_page)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage("Connecting to the local jewellery workspace…")
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(REFRESH_INTERVAL_MS)
        self.health_timer.timeout.connect(self.check_connection)
        self.health_timer.start()
        QTimer.singleShot(200, self.check_connection)
        QTimer.singleShot(350, self.load_store_settings)

    def _build_navigation(self) -> QListWidget:
        nav = QListWidget()
        nav.setObjectName("navigation")
        nav.setFixedWidth(260)
        nav.setSpacing(5)
        nav.setFrameShape(QFrame.Shape.NoFrame)
        nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        entries = [
            ("◈    Overview", "WORKSPACE"),
            ("▤    Customer & party ledger", "ACCOUNTS"),
            ("▧    Scheme / installments", "ACCOUNTS"),
            ("▣    Sales / billing", "BILLING"),
            ("◇    Stock / inventory", "BILLING"),
            ("♙    Customers", "MASTERS"),
            ("▤    Item catalogue", "MASTERS"),
            ("⚙    Store settings", "CONFIGURATION"),
        ]
        previous_section = ""
        for label, section in entries:
            if section != previous_section:
                header = QListWidgetItem(section)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setData(Qt.ItemDataRole.UserRole, "section")
                nav.addItem(header)
                previous_section = section
            nav.addItem(QListWidgetItem(label))
        return nav

    def _build_topbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        brand = QLabel("DINDORKAR SARAF  /  LOCAL DESKTOP")
        brand.setObjectName("eyebrow")
        layout.addWidget(brand)
        layout.addStretch()
        self.connection_label = QLabel("●  CHECKING")
        self.connection_label.setObjectName("connectionStatus")
        layout.addWidget(self.connection_label)
        self.backend_input = QLineEdit(DEFAULT_BACKEND_URL)
        self.backend_input.setObjectName("urlInput")
        self.backend_input.setFixedWidth(230)
        self.backend_input.setToolTip("Local FastAPI server address")
        layout.addWidget(self.backend_input)
        connect_button = QPushButton("Connect")
        connect_button.setObjectName("secondaryButton")
        connect_button.clicked.connect(self.connect_backend)
        layout.addWidget(connect_button)
        return layout

    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        welcome_card = QFrame()
        welcome_card.setObjectName("welcomeCard")
        welcome_layout = QHBoxLayout(welcome_card)
        welcome_layout.setContentsMargins(23, 19, 23, 19)
        welcome_copy = QVBoxLayout()
        self.store_name_label = QLabel("Your jewellery business")
        self.store_name_label.setObjectName("welcomeTitle")
        self.store_state_label = QLabel("Set up store details and today's metal rates to get started.")
        self.store_state_label.setObjectName("welcomeSubtitle")
        welcome_copy.addWidget(self.store_name_label)
        welcome_copy.addWidget(self.store_state_label)
        welcome_layout.addLayout(welcome_copy, 1)
        open_settings = QPushButton("Configure store")
        open_settings.setObjectName("lightButton")
        open_settings.clicked.connect(lambda: self.navigation.setCurrentRow(12))
        welcome_layout.addWidget(open_settings)
        layout.addWidget(welcome_card)

        metrics = QHBoxLayout()
        metrics.setSpacing(13)
        self.metric_sales = self._metric(
            "sales", "Today's sales", "₹ 0.00", "sales and collections"
        )
        self.metric_gold = self._metric("gold", "Gold stock", "0.000 g", "net weight")
        self.metric_silver = self._metric(
            "silver", "Silver stock", "0.000 g", "net weight"
        )
        self.metric_customers = self._metric(
            "customers", "Customers", "0", "in the customer ledger"
        )
        self.metric_invoices = self._metric(
            "invoices", "Today's bills", "0", "invoices completed"
        )
        for metric in (
            self.metric_sales,
            self.metric_gold,
            self.metric_silver,
            self.metric_customers,
            self.metric_invoices,
        ):
            metrics.addWidget(metric, 1)
        layout.addLayout(metrics)

        table_card, table_layout = make_card("Recent sales")
        table_toolbar = QHBoxLayout()
        table_toolbar.addStretch()
        export = QPushButton("Export sales CSV")
        export.setObjectName("secondaryButton")
        export.clicked.connect(lambda: self.export_data("sales"))
        table_toolbar.addWidget(export)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.load_sales)
        table_toolbar.addWidget(refresh)
        table_layout.addLayout(table_toolbar)
        self.dashboard_sales_table = build_table(
            ["Invoice", "Date", "Customer", "Total", "Paid", "Due", "Status"]
        )
        self.dashboard_sales_table.setMinimumHeight(260)
        table_layout.addWidget(self.dashboard_sales_table)
        layout.addWidget(table_card, 1)
        return page

    def _metric(
        self, key: str, title_text: str, value_text: str, caption: str
    ) -> QFrame:
        card, layout = make_card()
        title = QLabel(title_text.upper())
        title.setObjectName("eyebrow")
        value = QLabel(value_text)
        value.setObjectName("metricValue")
        note = QLabel(caption)
        note.setObjectName("mutedText")
        layout.addWidget(title)
        layout.addWidget(value)
        layout.addWidget(note)
        setattr(self, f"metric_{key}_value", value)
        return card

    def _build_ledger(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        identity_card, identity_layout = make_card("Account identity & contact")
        identity_grid = QGridLayout()
        identity_grid.setHorizontalSpacing(12)
        identity_grid.setVerticalSpacing(8)
        self.ledger_inputs: dict[str, QLineEdit] = {}
        input_fields = [
            ("name", "Account / ledger name", "Required", 0, 0),
            ("prefix", "Account prefix", "Optional code", 0, 1),
            ("group_name", "Group", "Customer / Party", 0, 2),
            ("phone", "Mobile number", "Phone", 1, 0),
            ("alternate_phone", "Alternate phone", "Phone", 1, 1),
            ("email", "Email address", "Optional", 1, 2),
            ("address", "Full postal address", "Address", 2, 0),
            ("city", "City / area", "City", 2, 1),
            ("pincode", "PIN code", "Postal code", 2, 2),
            ("state", "State (GST)", "State", 3, 0),
            ("gstin", "GSTIN", "Optional", 3, 1),
            ("pan", "PAN", "Optional", 3, 2),
            ("aadhaar", "Aadhaar number", "Optional", 4, 0),
            ("company_name", "Company / firm name", "Optional", 4, 1),
            ("website", "Website", "Optional", 4, 2),
        ]
        for key, label, placeholder, row, column in input_fields:
            field_layout, field = make_input(label, placeholder)
            self.ledger_inputs[key] = field
            identity_grid.addLayout(field_layout, row, column)
        party_layout, self.ledger_party_type = make_combo(
            "Account type",
            [("Customer", "Customer"), ("Party", "Party"),
             ("Karigar", "Karigar"), ("Expense", "Expense")],
        )
        identity_grid.addLayout(party_layout, 5, 0)
        identity_layout.addLayout(identity_grid)
        layout.addWidget(identity_card)

        banking_card, banking_layout = make_card("Banking & commercial terms")
        bank_grid = QGridLayout()
        bank_fields = [
            ("bank_name", "Bank name", 0, 0),
            ("bank_address", "Bank / branch address", 0, 1),
            ("bank_account_number", "Bank A/C number", 1, 0),
            ("bank_account_name", "Bank A/C name", 1, 1),
            ("ifsc_code", "IFSC code", 2, 0),
            ("book_no", "Book number", 2, 1),
            ("mortgage_percent", "Mortgage %", 3, 0),
            ("religion", "Religion", 3, 1),
            ("nominee_name", "Nominee name", 4, 0),
            ("nominee_address", "Nominee address", 4, 1),
        ]
        for key, label, row, column in bank_fields:
            field_layout, field = make_input(label, label)
            self.ledger_inputs[key] = field
            bank_grid.addLayout(field_layout, row, column)
        banking_layout.addLayout(bank_grid)
        layout.addWidget(banking_card)

        balance_card, balance_layout = make_card("Khata detail · opening balance")
        balance_grid = QGridLayout()
        amount_layout, self.ledger_opening_amount = make_number("Amount (₹)", 2)
        gold_layout, self.ledger_opening_gold = make_number("Gold (grams)", 3)
        silver_layout, self.ledger_opening_silver = make_number("Silver (grams)", 3)
        balance_grid.addLayout(amount_layout, 0, 0)
        balance_grid.addLayout(gold_layout, 0, 1)
        balance_grid.addLayout(silver_layout, 0, 2)
        self.ledger_opening_label = QLabel("Net receivable: ₹ 0.00")
        self.ledger_opening_label.setObjectName("quoteSummary")
        self.ledger_opening_amount.valueChanged.connect(self._update_ledger_balance)
        balance_grid.addWidget(self.ledger_opening_label, 1, 0, 1, 3)
        balance_layout.addLayout(balance_grid)
        layout.addWidget(balance_card)

        actions = QHBoxLayout()
        self.ledger_form_status = QLabel("")
        self.ledger_form_status.setObjectName("mutedText")
        actions.addWidget(self.ledger_form_status, 1)
        save_ledger = QPushButton("Save account")
        save_ledger.setObjectName("primaryButton")
        save_ledger.clicked.connect(self.save_ledger_entry)
        actions.addWidget(save_ledger)
        reset_ledger = QPushButton("Reset")
        reset_ledger.setObjectName("secondaryButton")
        reset_ledger.clicked.connect(self._clear_ledger_form)
        actions.addWidget(reset_ledger)
        delete_ledger = QPushButton("Delete")
        delete_ledger.setObjectName("dangerButton")
        delete_ledger.clicked.connect(self.delete_ledger_entry)
        actions.addWidget(delete_ledger)
        layout.addLayout(actions)

        records_card, records_layout = make_card("Ledger directory")
        toolbar = QHBoxLayout()
        self.ledger_search = QLineEdit()
        self.ledger_search.setObjectName("fieldInput")
        self.ledger_search.setPlaceholderText("Search account, phone, prefix…")
        self.ledger_search.returnPressed.connect(self.load_ledger)
        toolbar.addWidget(self.ledger_search, 1)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.load_ledger)
        toolbar.addWidget(refresh)
        records_layout.addLayout(toolbar)
        self.ledger_table = build_table(
            ["Account", "Type", "Phone", "City", "Opening balance", "Gold", "Silver"]
        )
        self.ledger_table.setMinimumHeight(250)
        self.ledger_table.cellClicked.connect(self._ledger_selected)
        records_layout.addWidget(self.ledger_table)
        layout.addWidget(records_card)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _build_scheme(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        member_card, member_layout = make_card("Customer identification & membership")
        member_grid = QGridLayout()
        customer_col, self.scheme_customer_combo = make_combo(
            "Customer", [("Choose a customer", "")]
        )
        member_grid.addLayout(customer_col, 0, 0, 1, 2)
        scheme_type_col, self.scheme_type_combo = make_combo(
            "Scheme type",
            [("A (11+1 Mo.)", "A (11+1 Mo.)"),
             ("B (12 Mo.)", "B (12 Mo.)"),
             ("Custom", "Custom")],
        )
        member_grid.addLayout(scheme_type_col, 0, 2)
        member_layout.addLayout(member_grid)
        layout.addWidget(member_card)

        plan_card, plan_layout = make_card("Scheme tenure & value plan")
        plan_grid = QGridLayout()
        self.scheme_start_date = QLineEdit(date.today().isoformat())
        self.scheme_start_date.setObjectName("fieldInput")
        start_layout = QVBoxLayout()
        start_layout.addWidget(QLabel("Start date (YYYY-MM-DD)"))
        start_layout.addWidget(self.scheme_start_date)
        plan_grid.addLayout(start_layout, 0, 0)
        tenure_layout, self.scheme_tenure = make_number("Tenure (months)", 0, 120, 1)
        self.scheme_tenure.setValue(12)
        plan_grid.addLayout(tenure_layout, 0, 1)
        monthly_layout, self.scheme_monthly_amount = make_number("Monthly contribution (₹)", 2)
        plan_grid.addLayout(monthly_layout, 0, 2)
        bonus_layout, self.scheme_bonus_amount = make_number("Maturity bonus (₹)", 2)
        plan_grid.addLayout(bonus_layout, 0, 3)
        desc_layout, self.scheme_description = make_input(
            "Remarks / scheme description", "Gold savings plan"
        )
        plan_grid.addLayout(desc_layout, 1, 0, 1, 2)
        reminder_layout, self.scheme_reminder_date = make_input(
            "Follow-up reminder (YYYY-MM-DD)", date.today().isoformat()
        )
        self.scheme_reminder_date.setText(date.today().isoformat())
        plan_grid.addLayout(reminder_layout, 1, 2)
        apply_scheme = QPushButton("Apply scheme")
        apply_scheme.setObjectName("primaryButton")
        apply_scheme.clicked.connect(self.create_scheme)
        plan_grid.addWidget(apply_scheme, 1, 3, alignment=Qt.AlignmentFlag.AlignBottom)
        self.scheme_maturity_label = QLabel("Estimated maturity: ₹ 0.00")
        self.scheme_maturity_label.setObjectName("quoteSummary")
        self.scheme_monthly_amount.valueChanged.connect(self._update_scheme_maturity)
        self.scheme_bonus_amount.valueChanged.connect(self._update_scheme_maturity)
        self.scheme_tenure.valueChanged.connect(self._update_scheme_maturity)
        plan_grid.addWidget(self.scheme_maturity_label, 2, 0, 1, 4)
        plan_layout.addLayout(plan_grid)
        layout.addWidget(plan_card)

        payment_card, payment_layout = make_card("Installment payment entry")
        payment_grid = QGridLayout()
        scheme_col, self.scheme_record_combo = make_combo("Scheme account", [])
        self.scheme_record_combo.currentIndexChanged.connect(self._scheme_selected)
        payment_grid.addLayout(scheme_col, 0, 0, 1, 2)
        date_col, self.installment_date = make_input(
            "Payment date (YYYY-MM-DD)", date.today().isoformat()
        )
        self.installment_date.setText(date.today().isoformat())
        payment_grid.addLayout(date_col, 0, 2)
        installment_col, self.installment_number = make_number("Installment number", 0, 120, 1)
        payment_grid.addLayout(installment_col, 0, 3)
        amount_col, self.installment_amount = make_number("Paid amount (₹)", 2)
        payment_grid.addLayout(amount_col, 1, 0)
        rate_col, self.installment_gold_rate = make_number("Gold rate (24K / g)", 4)
        payment_grid.addLayout(rate_col, 1, 1)
        fine_col, self.installment_late_fine = make_number("Late fine (₹)", 2)
        payment_grid.addLayout(fine_col, 1, 2)
        mode_col, self.installment_mode = make_combo(
            "Payment mode",
            [("Cash", "Cash"), ("Bank", "Bank"), ("UPI", "UPI"),
             ("NEFT / RTGS", "NEFT / RTGS"), ("Cheque", "Cheque")],
        )
        payment_grid.addLayout(mode_col, 1, 3)
        reference_col, self.installment_reference = make_input("Txn / cheque reference", "Optional")
        payment_grid.addLayout(reference_col, 2, 0, 1, 2)
        bank_col, self.installment_bank = make_input("Deposit to bank", "Optional")
        payment_grid.addLayout(bank_col, 2, 2)
        post_payment = QPushButton("Post entry")
        post_payment.setObjectName("primaryButton")
        post_payment.clicked.connect(self.post_scheme_installment)
        payment_grid.addWidget(post_payment, 2, 3, alignment=Qt.AlignmentFlag.AlignBottom)
        payment_layout.addLayout(payment_grid)
        layout.addWidget(payment_card)

        records_card, records_layout = make_card("Scheme ledger records")
        self.scheme_table = build_table(
            ["Scheme", "Customer", "Type", "Start date", "Paid / tenure",
             "Contribution", "Collected", "Status"]
        )
        self.scheme_table.setMinimumHeight(190)
        self.scheme_table.cellClicked.connect(self._select_scheme_row)
        records_layout.addWidget(self.scheme_table)
        self.installment_table = build_table(
            ["No.", "Date", "Paid amount", "Gold rate", "Fine", "Mode", "Reference", "Bank"]
        )
        self.installment_table.setMinimumHeight(150)
        records_layout.addWidget(QLabel("Posted installments"))
        records_layout.addWidget(self.installment_table)
        layout.addWidget(records_card)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _build_pos(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        description = QLabel(
            "Select tagged pieces. Prices and GST are recalculated by PostgreSQL-backed "
            "server settings before the bill is saved."
        )
        description.setObjectName("mutedText")
        layout.addWidget(description)

        selector_card, selector_layout = make_card("Available tagged stock")
        toolbar = QHBoxLayout()
        self.pos_search = QLineEdit()
        self.pos_search.setObjectName("fieldInput")
        self.pos_search.setPlaceholderText("Search item or tag number")
        self.pos_search.returnPressed.connect(self.load_stock)
        toolbar.addWidget(self.pos_search, 1)
        refresh_stock = QPushButton("Refresh tags")
        refresh_stock.setObjectName("secondaryButton")
        refresh_stock.clicked.connect(self.load_stock)
        toolbar.addWidget(refresh_stock)
        toolbar.addStretch()
        self.selected_count = QLabel("0 tags selected")
        self.selected_count.setObjectName("mutedText")
        toolbar.addWidget(self.selected_count)
        selector_layout.addLayout(toolbar)
        self.pos_stock_table = build_table(
            ["Select", "Tag", "Item", "Material", "Net wt.", "Rate / g", "Metal", "Making", "GST"]
        )
        self.pos_stock_table.setMinimumHeight(230)
        self.pos_stock_table.itemChanged.connect(self._selection_changed)
        selector_layout.addWidget(self.pos_stock_table)
        layout.addWidget(selector_card, 1)

        checkout_card, checkout_layout = make_card("Invoice details")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        customer_col, self.pos_customer = make_combo("Customer", [("Walk-in customer", "")])
        grid.addLayout(customer_col, 0, 0, 1, 2)
        discount_col, self.pos_discount = make_number("Bill discount (₹)", 2)
        grid.addLayout(discount_col, 0, 2)
        cash_col, self.pos_cash = make_number("Cash received (₹)", 2)
        grid.addLayout(cash_col, 1, 0)
        bank_col, self.pos_bank = make_number("Bank / UPI received (₹)", 2)
        grid.addLayout(bank_col, 1, 1)
        self.quote_button = QPushButton("Calculate bill")
        self.quote_button.setObjectName("secondaryButton")
        self.quote_button.clicked.connect(self.calculate_quote)
        grid.addWidget(self.quote_button, 1, 2, alignment=Qt.AlignmentFlag.AlignBottom)
        self.pos_discount.valueChanged.connect(self._invalidate_quote)
        self.pos_cash.valueChanged.connect(self._invalidate_quote)
        self.pos_bank.valueChanged.connect(self._invalidate_quote)
        self.pos_customer.currentIndexChanged.connect(self._invalidate_quote)
        checkout_layout.addLayout(grid)

        self.quote_label = QLabel("Choose tagged stock, then calculate the invoice.")
        self.quote_label.setObjectName("quoteSummary")
        self.quote_label.setWordWrap(True)
        checkout_layout.addWidget(self.quote_label)
        actions = QHBoxLayout()
        self.pos_error = QLabel("")
        self.pos_error.setObjectName("inlineError")
        actions.addWidget(self.pos_error, 1)
        self.checkout_button = QPushButton("Complete sale")
        self.checkout_button.setObjectName("primaryButton")
        self.checkout_button.clicked.connect(self.complete_sale)
        actions.addWidget(self.checkout_button)
        checkout_layout.addLayout(actions)
        layout.addWidget(checkout_card)
        return page

    def _build_inventory(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        entry_card, entry_layout = make_card("Receive a tagged piece")
        fields = QGridLayout()
        fields.setHorizontalSpacing(14)
        fields.setVerticalSpacing(8)
        item_col, self.stock_item_combo = make_combo("Catalogue item", [])
        fields.addLayout(item_col, 0, 0, 1, 2)
        tag_col, self.stock_tag_input = make_input("Tag number", "e.g. GLD-0001")
        fields.addLayout(tag_col, 0, 2, 1, 2)
        gross_col, self.stock_gross = make_number("Gross weight (g)", 3)
        fields.addLayout(gross_col, 1, 0)
        net_col, self.stock_net = make_number("Net weight (g)", 3)
        fields.addLayout(net_col, 1, 1)
        pieces_col, self.stock_pieces = make_number("Pieces", 0, 10_000, 1)
        self.stock_pieces.setValue(1)
        fields.addLayout(pieces_col, 1, 2)
        self.stock_carat_col, self.stock_carat = make_combo(
            "Purity / carat",
            [("Use item default", "0"), ("18K", "18"), ("20K", "20"),
             ("22K", "22"), ("24K", "24")],
        )
        fields.addLayout(self.stock_carat_col, 1, 3)
        self.stock_item_combo.currentIndexChanged.connect(self._update_stock_carat)
        self.stock_size_layout, self.stock_size = make_input("Size", "Ring / bangle size")
        fields.addLayout(self.stock_size_layout, 2, 0)
        self.stock_huid_layout, self.stock_huid = make_input("HUID", "Hallmark ID")
        fields.addLayout(self.stock_huid_layout, 2, 1)
        self.stock_design_layout, self.stock_design = make_input("Design number", "Optional")
        fields.addLayout(self.stock_design_layout, 2, 2)
        self.stock_order_layout, self.stock_order = make_input("Order bill number", "Optional")
        fields.addLayout(self.stock_order_layout, 2, 3)
        purchase_rate_col, self.stock_purchase_rate = make_number("Purchase rate (₹ / g)", 4)
        fields.addLayout(purchase_rate_col, 3, 0)
        purchase_amount_col, self.stock_purchase_amount = make_number("Purchase cost (₹)", 2)
        fields.addLayout(purchase_amount_col, 3, 1)
        wastage_col, self.stock_wastage = make_number("Purchase wastage (%)", 4, 100)
        fields.addLayout(wastage_col, 3, 2)
        hallmark_col, self.stock_hallmark = make_number("Hallmark charge (₹)", 2)
        fields.addLayout(hallmark_col, 3, 3)
        labour_col, self.stock_labour = make_number("Making charge", 2)
        fields.addLayout(labour_col, 4, 0)
        labour_unit_col, self.stock_labour_unit = make_combo(
            "Making-charge basis",
            [("Fixed per piece", "fixed"), ("Per gram", "per_gram"), ("% of metal", "percent")],
        )
        fields.addLayout(labour_unit_col, 4, 1)
        other_col, self.stock_other = make_number("Stone / other charges (₹)", 2)
        fields.addLayout(other_col, 4, 2)
        mrp_col, self.stock_mrp = make_number("MRP / selling price (₹)", 2)
        fields.addLayout(mrp_col, 4, 3)
        stock_actions = QHBoxLayout()
        stock_actions.addStretch()
        save = QPushButton("Add tagged stock")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.create_stock)
        stock_actions.addWidget(save)
        fields.addLayout(stock_actions, 5, 0, 1, 4)
        entry_layout.addLayout(fields)
        layout.addWidget(entry_card)

        table_card, table_layout = make_card("Available stock")
        table_toolbar = QHBoxLayout()
        table_toolbar.addWidget(QLabel("Gold and silver pieces available for retail sale."))
        table_toolbar.addStretch()
        export = QPushButton("Export CSV")
        export.setObjectName("secondaryButton")
        export.clicked.connect(lambda: self.export_data("stock"))
        table_toolbar.addWidget(export)
        reload_button = QPushButton("Refresh")
        reload_button.setObjectName("secondaryButton")
        reload_button.clicked.connect(self.load_stock)
        table_toolbar.addWidget(reload_button)
        table_layout.addLayout(table_toolbar)
        self.inventory_table = build_table(
            ["Tag", "Item", "Material", "Gross wt.", "Net wt.", "Size", "HUID",
             "Purchase cost", "MRP", "Rate / g", "Retail subtotal"]
        )
        table_layout.addWidget(self.inventory_table, 1)
        layout.addWidget(table_card, 1)
        scroll.setWidget(page)
        return scroll

    def _build_customers(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card, form = make_card("Add a customer")
        grid = QGridLayout()
        fields = []
        for label, placeholder, col, row in [
            ("Full name", "Customer name", 0, 0),
            ("Phone", "Phone number", 1, 0),
            ("Email", "Email address (optional)", 2, 0),
            ("State", "State for GST", 0, 1),
            ("GSTIN", "Optional registered GSTIN", 1, 1),
        ]:
            field_layout, field = make_input(label, placeholder)
            grid.addLayout(field_layout, row, col)
            fields.append(field)
        self.customer_name, self.customer_phone, self.customer_email, self.customer_state, self.customer_gstin = fields
        card_save = QPushButton("Save customer")
        card_save.setObjectName("primaryButton")
        card_save.clicked.connect(self.create_customer)
        grid.addWidget(card_save, 1, 2, alignment=Qt.AlignmentFlag.AlignBottom)
        form.addLayout(grid)
        layout.addWidget(card)

        table_card, table_layout = make_card("Customer directory")
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Customer and contact list"))
        toolbar.addStretch()
        upload = QPushButton("Import customer CSV")
        upload.setObjectName("secondaryButton")
        upload.clicked.connect(self.import_customers)
        toolbar.addWidget(upload)
        export = QPushButton("Export CSV")
        export.setObjectName("secondaryButton")
        export.clicked.connect(lambda: self.export_data("customers"))
        toolbar.addWidget(export)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.load_customers)
        toolbar.addWidget(refresh)
        table_layout.addLayout(toolbar)
        self.customer_table = build_table(["Name", "Phone", "Email", "State", "GSTIN"])
        table_layout.addWidget(self.customer_table, 1)
        layout.addWidget(table_card, 1)
        return page

    def _build_catalog(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card, form = make_card("Create a sellable item")
        grid = QGridLayout()
        name_col, self.item_name_input = make_input("Display name", "22K gold ring")
        grid.addLayout(name_col, 0, 0)
        prefix_col, self.item_prefix_input = make_input("Short prefix", "RNG22")
        grid.addLayout(prefix_col, 0, 1)
        material_col, self.item_material_combo = make_combo(
            "Metal", [("Gold", "gold"), ("Silver", "silver"), ("Other", "other")]
        )
        self.item_material_combo.currentIndexChanged.connect(self._update_carat_enabled)
        grid.addLayout(material_col, 0, 2)
        carat_col, self.item_carat_combo = make_combo(
            "Gold carat", [("18K", "18"), ("20K", "20"), ("22K", "22"), ("24K", "24")]
        )
        grid.addLayout(carat_col, 1, 0)
        gst_col, self.item_gst = make_number("GST rate (%)", 4, 100)
        grid.addLayout(gst_col, 1, 1)
        hsn_col, self.item_hsn_input = make_input("HSN (optional)", "HSN code")
        grid.addLayout(hsn_col, 1, 2)
        labour_col, self.item_labour = make_number("Default making charge", 2)
        grid.addLayout(labour_col, 2, 0)
        unit_col, self.item_labour_unit = make_combo(
            "Making-charge basis",
            [("Fixed per piece", "fixed"), ("Per gram", "per_gram"), ("% of metal", "percent")],
        )
        grid.addLayout(unit_col, 2, 1)
        other_col, self.item_other = make_number("Default other charges (₹)", 2)
        grid.addLayout(other_col, 2, 2)
        actions = QHBoxLayout()
        actions.addStretch()
        save = QPushButton("Save catalogue item")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.create_item)
        actions.addWidget(save)
        grid.addLayout(actions, 3, 2)
        form.addLayout(grid)
        layout.addWidget(card)

        table_card, table_layout = make_card("Item catalogue")
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Tax and making defaults are editable for each new item."))
        toolbar.addStretch()
        export = QPushButton("Export CSV")
        export.setObjectName("secondaryButton")
        export.clicked.connect(lambda: self.export_data("items"))
        toolbar.addWidget(export)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.load_items)
        toolbar.addWidget(refresh)
        table_layout.addLayout(toolbar)
        self.catalog_table = build_table(
            ["Name", "Prefix", "Material", "Carat", "GST %", "Making charge", "Basis"]
        )
        table_layout.addWidget(self.catalog_table, 1)
        layout.addWidget(table_card, 1)
        return page

    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        store_card, store_layout = make_card("Store profile · branch 1")
        store_grid = QGridLayout()
        name_col, self.store_name_input = make_input("Business name", "Registered shop name")
        store_grid.addLayout(name_col, 0, 0)
        state_col, self.store_state_input = make_input("Seller state", "State as registered")
        store_grid.addLayout(state_col, 0, 1)
        gstin_col, self.store_gstin_input = make_input("Store GSTIN", "Optional GSTIN")
        store_grid.addLayout(gstin_col, 0, 2)
        financial_col, self.fiscal_start_combo = make_combo(
            "Financial-year starts",
            [(month, str(index)) for index, month in enumerate(
                ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"], 1
            )],
        )
        self.fiscal_start_combo.setCurrentIndex(3)
        store_grid.addLayout(financial_col, 1, 0)
        save_profile = QPushButton("Save store profile")
        save_profile.setObjectName("primaryButton")
        save_profile.clicked.connect(self.save_settings)
        store_grid.addWidget(save_profile, 1, 2, alignment=Qt.AlignmentFlag.AlignBottom)
        store_layout.addLayout(store_grid)
        layout.addWidget(store_card)

        rate_card, rate_layout = make_card("Daily metal rate")
        rate_grid = QGridLayout()
        material_col, self.rate_material_combo = make_combo(
            "Metal", [("Gold", "gold"), ("Silver", "silver")]
        )
        self.rate_material_combo.currentIndexChanged.connect(self._update_rate_carat_enabled)
        rate_grid.addLayout(material_col, 0, 0)
        carat_col, self.rate_carat_combo = make_combo(
            "Gold carat", [("18K", "18"), ("20K", "20"), ("22K", "22"), ("24K", "24")]
        )
        self.rate_carat_combo.setCurrentIndex(2)
        rate_grid.addLayout(carat_col, 0, 1)
        value_col, self.rate_value = make_number("Price per gram (₹)", 4)
        rate_grid.addLayout(value_col, 0, 2)
        save_rate = QPushButton("Save today's rate")
        save_rate.setObjectName("primaryButton")
        save_rate.clicked.connect(self.save_metal_rate)
        rate_grid.addWidget(save_rate, 1, 2, alignment=Qt.AlignmentFlag.AlignBottom)
        rate_layout.addLayout(rate_grid)
        rate_hint = QLabel(
            "Enter the actual selling rate per gram for each purity. GST is configured "
            "per catalogue item; verify tax settings with your accountant before invoicing."
        )
        rate_hint.setObjectName("mutedText")
        rate_hint.setWordWrap(True)
        rate_layout.addWidget(rate_hint)
        self.rates_table = build_table(["Metal", "Carat", "Rate / gram", "Effective date"])
        self.rates_table.setMaximumHeight(180)
        rate_layout.addWidget(self.rates_table)
        layout.addWidget(rate_card)

        safety = QLabel(
            "This local desktop build supports one branch. Do not expose the backend "
            "to a public or shared network; authentication and multi-user permissions "
            "must be added before production/network deployment."
        )
        safety.setObjectName("safetyNote")
        safety.setWordWrap(True)
        layout.addWidget(safety)
        layout.addStretch()
        return page

    def _update_carat_enabled(self) -> None:
        self.item_carat_combo.setEnabled(
            self.item_material_combo.currentData() == "gold"
        )

    def _update_rate_carat_enabled(self) -> None:
        self.rate_carat_combo.setEnabled(
            self.rate_material_combo.currentData() == "gold"
        )

    def _update_stock_carat(self, *_: object) -> None:
        selected_id = self.stock_item_combo.currentData()
        item = next(
            (record for record in self.items if record.get("item_id") == selected_id),
            None,
        )
        is_gold = bool(item and item.get("material_type") == "gold")
        self.stock_carat.setEnabled(False)
        if is_gold:
            carat_index = self.stock_carat.findData(
                str(int(decimal_value(item.get("carat"))))
            )
            self.stock_carat.setCurrentIndex(carat_index if carat_index >= 0 else 0)
        else:
            self.stock_carat.setCurrentIndex(0)

    def _update_ledger_balance(self, value: float) -> None:
        self.ledger_opening_label.setText(
            f"Net receivable ledger balance: {money_text(value)}"
        )

    def _update_scheme_maturity(self, *_: object) -> None:
        maturity = (
            Decimal(str(self.scheme_monthly_amount.value()))
            * int(self.scheme_tenure.value())
            + Decimal(str(self.scheme_bonus_amount.value()))
        )
        self.scheme_maturity_label.setText(
            f"Estimated maturity value: {money_text(maturity)}"
        )

    def _change_page(self, row: int) -> None:
        if row < 0:
            return
        item = self.navigation.item(row)
        if item is None or item.data(Qt.ItemDataRole.UserRole) == "section":
            return
        page_index = {
            "Overview": 0,
            "Customer & party ledger": 1,
            "Sales / billing": 2,
            "Stock / inventory": 3,
            "Scheme / installments": 4,
            "Customers": 5,
            "Item catalogue": 6,
            "Store settings": 7,
        }
        title = item.text().strip()
        for key, index in page_index.items():
            if key in title:
                self.pages.setCurrentIndex(index)
                self.page_heading.setText(key)
                self._refresh_page(index)
                return

    def _refresh_page(self, page_index: int) -> None:
        if not self.settings:
            if page_index != 7:
                self.statusBar().showMessage(
                    "Configure the store profile first in Store settings.", 7000
                )
            return
        if page_index == 0:
            self.load_sales()
            self.load_dashboard()
        elif page_index == 1:
            self.load_ledger()
            self.load_customers()
        elif page_index in {2, 3}:
            self.load_stock()
            self.load_customers()
            self.load_items()
        elif page_index == 4:
            self.load_customers()
            self.load_schemes()
        elif page_index == 5:
            self.load_customers()
        elif page_index == 6:
            self.load_items()
        elif page_index == 7:
            self.load_settings()

    def _request(
        self,
        action_id: str,
        method: str,
        path: str,
        payload: Any = None,
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        content_type: str = "application/json",
    ) -> None:
        if action_id in self.workers:
            return
        try:
            base_url = normalize_base_url(self.backend_input.text())
            worker = ApiWorker(
                action_id,
                base_url,
                method,
                path,
                payload,
                content_type,
                self,
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.workers[action_id] = worker
        self.success_handlers[action_id] = on_success or (lambda _: None)
        self.error_handlers[action_id] = on_error or self._default_error
        worker.succeeded.connect(self._request_succeeded)
        worker.failed.connect(self._request_failed)
        worker.finished.connect(lambda key=action_id: self._request_finished(key))
        worker.start()

    def _request_succeeded(self, action_id: str, result: Any) -> None:
        callback = self.success_handlers.pop(action_id, None)
        self.error_handlers.pop(action_id, None)
        if callback is not None:
            callback(result)

    def _request_failed(self, action_id: str, message: str) -> None:
        callback = self.error_handlers.pop(action_id, None)
        self.success_handlers.pop(action_id, None)
        if callback is not None:
            callback(message)

    def _request_finished(self, action_id: str) -> None:
        self.workers.pop(action_id, None)

    def _default_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 12_000)
        if message:
            self._show_error(message)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Jewellery Management", message)

    def connect_backend(self) -> None:
        try:
            self.backend_url = normalize_base_url(self.backend_input.text())
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.check_connection()
        self.load_store_settings()

    def check_connection(self) -> None:
        self._request(
            "health",
            "GET",
            "/health/db",
            on_success=self._connection_succeeded,
            on_error=self._connection_failed,
        )

    def _connection_succeeded(self, result: dict[str, Any]) -> None:
        if result.get("database") == "ok":
            self.connection_label.setText("●  API + POSTGRESQL CONNECTED")
            self.connection_label.setStyleSheet(f"color: {GREEN}; font-weight: 700;")
        else:
            self.connection_label.setText("●  CHECK BACKEND")
            self.connection_label.setStyleSheet(f"color: {AMBER}; font-weight: 700;")

    def _connection_failed(self, message: str) -> None:
        self.connection_label.setText("●  CONNECTION ISSUE")
        self.connection_label.setStyleSheet(f"color: {RED}; font-weight: 700;")
        self.statusBar().showMessage(message, 12_000)

    def load_store_settings(self) -> None:
        self._request(
            "load-settings",
            "GET",
            "/api/v1/settings?branch_id=1",
            on_success=self._settings_loaded,
            on_error=self._settings_unavailable,
        )

    def _settings_loaded(self, result: dict[str, Any]) -> None:
        self.settings = result.get("settings")
        if not self.settings:
            self._settings_unavailable("Store settings were not returned.")
            return
        self._populate_settings_form()
        self.store_name_label.setText(self.settings["business_name"])
        self.store_state_label.setText(
            f"{self.settings['state']}  ·  Branch {self.settings['branch_id']}"
        )
        self.statusBar().showMessage("Store settings connected.", 4000)
        self._refresh_page(self.pages.currentIndex())

    def _settings_unavailable(self, message: str) -> None:
        self.settings = None
        self.store_name_label.setText("Store setup required")
        self.store_state_label.setText(
            "Save your business name and seller state in Store settings before sales."
        )
        self.statusBar().showMessage(message, 10_000)

    def _populate_settings_form(self) -> None:
        if not self.settings:
            return
        self.store_name_input.setText(self.settings.get("business_name", ""))
        self.store_state_input.setText(self.settings.get("state", ""))
        self.store_gstin_input.setText(self.settings.get("gstin") or "")
        start_month = int(self.settings.get("fiscal_year_start_month", 4))
        self.fiscal_start_combo.setCurrentIndex(start_month - 1)
        rates = self._last_rate_by_material(self.settings.get("metal_rates", []))
        self.rates_table.setRowCount(0)
        for rate in self.settings.get("metal_rates", []):
            row = self.rates_table.rowCount()
            self.rates_table.insertRow(row)
            self.rates_table.setItem(row, 0, value_item(rate["material_type"].title()))
            self.rates_table.setItem(
                row, 1, value_item(f'{rate["carat"]}K' if decimal_value(rate["carat"]) else "—")
            )
            self.rates_table.setItem(row, 2, value_item(money_text(rate["rate_per_gram"])))
            self.rates_table.setItem(row, 3, value_item(rate["effective_date"]))
        self.statusBar().showMessage(
            f"{len(rates)} latest metal rates available for this branch.", 5000
        )

    @staticmethod
    def _last_rate_by_material(rates: list[dict[str, Any]]) -> dict[tuple[str, str], dict]:
        latest: dict[tuple[str, str], dict] = {}
        for rate in rates:
            key = (rate["material_type"], str(rate["carat"]))
            latest[key] = rate
        return latest

    def save_settings(self) -> None:
        if not self.store_name_input.text().strip() or not self.store_state_input.text().strip():
            self._show_error("Enter the business name and seller state.")
            return
        payload = {
            "branch_id": BRANCH_ID,
            "business_name": self.store_name_input.text().strip(),
            "state": self.store_state_input.text().strip(),
            "gstin": self.store_gstin_input.text().strip() or None,
            "fiscal_year_start_month": int(self.fiscal_start_combo.currentData()),
        }
        self._request(
            "save-settings",
            "PUT",
            "/api/v1/settings",
            payload,
            self._settings_saved,
        )

    def _settings_saved(self, result: dict[str, Any]) -> None:
        self.settings = result
        self.store_name_label.setText(result["business_name"])
        self.store_state_label.setText(f'{result["state"]}  ·  Branch 1')
        self.statusBar().showMessage("Store profile saved.", 5000)
        self.load_settings()
        self._refresh_page(0)

    def load_settings(self) -> None:
        self._request(
            "load-settings",
            "GET",
            "/api/v1/settings?branch_id=1",
            on_success=self._settings_loaded,
        )

    def save_metal_rate(self) -> None:
        material = self.rate_material_combo.currentData()
        rate = self.rate_value.value()
        if rate <= 0:
            self._show_error("Enter a metal rate greater than zero.")
            return
        payload = {
            "branch_id": BRANCH_ID,
            "material_type": material,
            "carat": self.rate_carat_combo.currentData() if material == "gold" else "0",
            "rate_per_gram": str(rate),
        }
        self._request(
            "save-rate",
            "PUT",
            "/api/v1/settings/metal-rate",
            payload,
            lambda _: self._rate_saved(),
        )

    def _rate_saved(self) -> None:
        self.statusBar().showMessage("Today's metal rate saved.", 5000)
        self.load_settings()
        self.load_stock()

    def load_items(self) -> None:
        self._request(
            "load-items",
            "GET",
            "/api/v1/items?branch_id=1",
            on_success=self._items_loaded,
        )

    def _items_loaded(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self._populate_items_table()
        self._populate_item_combo()

    def _populate_items_table(self) -> None:
        if not hasattr(self, "catalog_table"):
            return
        self.catalog_table.setRowCount(0)
        for item in self.items:
            row = self.catalog_table.rowCount()
            self.catalog_table.insertRow(row)
            values = [
                item.get("name"),
                item.get("prefix"),
                str(item.get("material_type", "")).title(),
                f'{item.get("carat", 0)}K' if item.get("material_type") == "gold" else "—",
                item.get("gst_rate"),
                money_text(item.get("default_labour_charge")),
                item.get("default_labour_unit"),
            ]
            for col, value in enumerate(values):
                self.catalog_table.setItem(row, col, value_item(value, col in {4, 5}))

    def _populate_item_combo(self) -> None:
        self.stock_item_combo.clear()
        for item in self.items:
            if item.get("material_type") in {"gold", "silver"}:
                suffix = (
                    f' · {item.get("carat")}K'
                    if item.get("material_type") == "gold"
                    else ""
                )
                self.stock_item_combo.addItem(
                    f'{item["name"]}{suffix}  ({item["prefix"]})', item["item_id"]
                )

    def create_item(self) -> None:
        name, prefix = self.item_name_input.text().strip(), self.item_prefix_input.text().strip()
        if not name or not prefix:
            self._show_error("Enter both an item name and a unique short prefix.")
            return
        material = self.item_material_combo.currentData()
        payload = {
            "name": name,
            "prefix": prefix,
            "material_type": material,
            "carat": self.item_carat_combo.currentData() if material == "gold" else "0",
            "hsn_code": self.item_hsn_input.text().strip() or None,
            "gst_rate": str(self.item_gst.value()),
            "default_labour_charge": str(self.item_labour.value()),
            "default_labour_unit": self.item_labour_unit.currentData(),
            "default_other_charges": str(self.item_other.value()),
        }
        self._request("create-item", "POST", "/api/v1/items", payload, self._item_created)

    def _item_created(self, item: dict[str, Any]) -> None:
        self.item_name_input.clear()
        self.item_prefix_input.clear()
        self.statusBar().showMessage(f'Added catalogue item: {item["name"]}.', 5000)
        self.load_items()

    def load_customers(self) -> None:
        self._request(
            "load-customers",
            "GET",
            "/api/v1/customers?branch_id=1",
            on_success=self._customers_loaded,
        )

    def _customers_loaded(self, customers: list[dict[str, Any]]) -> None:
        self.customers = customers
        self.customer_table.setRowCount(0)
        for customer in customers:
            row = self.customer_table.rowCount()
            self.customer_table.insertRow(row)
            for col, key in enumerate(("name", "phone", "email", "state", "gstin")):
                self.customer_table.setItem(row, col, value_item(customer.get(key)))
        self._populate_customer_combo()
        self.metric_customers_value.setText(str(len(customers)))

    def _populate_customer_combo(self) -> None:
        if not hasattr(self, "pos_customer"):
            return
        current_customer = self.pos_customer.currentData()
        self.pos_customer.clear()
        self.pos_customer.addItem("Walk-in customer", None)
        selected_index = 0
        for customer in self.customers:
            self.pos_customer.addItem(
                f'{customer["name"]}  ·  {customer.get("phone") or "no phone"}',
                customer["customer_id"],
            )
            if customer["customer_id"] == current_customer:
                selected_index = self.pos_customer.count() - 1
        self.pos_customer.setCurrentIndex(selected_index)
        self._populate_scheme_customers()

    def create_customer(self) -> None:
        name = self.customer_name.text().strip()
        if not name:
            self._show_error("Enter the customer's name.")
            return
        payload = {
            "name": name,
            "phone": self.customer_phone.text().strip() or None,
            "email": self.customer_email.text().strip() or None,
            "state": self.customer_state.text().strip() or None,
            "gstin": self.customer_gstin.text().strip() or None,
        }
        self._request(
            "create-customer", "POST", "/api/v1/customers", payload, self._customer_created
        )

    def _customer_created(self, customer: dict[str, Any]) -> None:
        for field in (
            self.customer_name,
            self.customer_phone,
            self.customer_email,
            self.customer_state,
            self.customer_gstin,
        ):
            field.clear()
        self.statusBar().showMessage(f'Customer saved: {customer["name"]}.', 5000)
        self.load_customers()

    def load_ledger(self) -> None:
        from urllib.parse import quote

        search = quote(self.ledger_search.text().strip())
        self._request(
            "load-ledger",
            "GET",
            f"/api/v1/ledger?branch_id=1&search={search}",
            on_success=self._ledger_loaded,
        )

    def _ledger_loaded(self, entries: list[dict[str, Any]]) -> None:
        self.ledger_entries = entries
        self.ledger_table.setRowCount(0)
        for entry in entries:
            row = self.ledger_table.rowCount()
            self.ledger_table.insertRow(row)
            values = [
                entry.get("name"),
                entry.get("party_type"),
                entry.get("phone"),
                entry.get("city"),
                money_text(entry.get("opening_balance")),
                weight_text(entry.get("opening_gold_grams")),
                weight_text(entry.get("opening_silver_grams")),
            ]
            for column, value in enumerate(values):
                cell = value_item(value, column >= 4)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, entry)
                self.ledger_table.setItem(row, column, cell)

    def _ledger_selected(self, row: int, _column: int) -> None:
        cell = self.ledger_table.item(row, 0)
        if cell is None:
            return
        entry = cell.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return
        self.selected_ledger_id = int(entry["ledger_id"])
        for key, field in self.ledger_inputs.items():
            field.setText(str(entry.get(key) or ""))
        party_index = self.ledger_party_type.findData(entry.get("party_type"))
        self.ledger_party_type.setCurrentIndex(max(party_index, 0))
        self.ledger_opening_amount.setValue(float(decimal_value(entry.get("opening_balance"))))
        self.ledger_opening_gold.setValue(float(decimal_value(entry.get("opening_gold_grams"))))
        self.ledger_opening_silver.setValue(float(decimal_value(entry.get("opening_silver_grams"))))
        self.ledger_form_status.setText(f'Editing {entry.get("name", "ledger account")}')

    def save_ledger_entry(self) -> None:
        name = self.ledger_inputs["name"].text().strip()
        if not name:
            self._show_error("Enter the account or ledger name.")
            return
        payload: dict[str, Any] = {
            key: field.text().strip() or None for key, field in self.ledger_inputs.items()
        }
        payload.update(
            {
                "name": name,
                "party_type": self.ledger_party_type.currentData(),
                "opening_balance": str(self.ledger_opening_amount.value()),
                "opening_gold_grams": str(self.ledger_opening_gold.value()),
                "opening_silver_grams": str(self.ledger_opening_silver.value()),
                "mortgage_percent": payload.pop("mortgage_percent", None) or "0",
            }
        )
        if self.selected_ledger_id is None:
            self._request(
                "create-ledger", "POST", "/api/v1/ledger", payload, self._ledger_saved
            )
        else:
            self._request(
                "update-ledger",
                "PUT",
                f"/api/v1/ledger/{self.selected_ledger_id}",
                payload,
                self._ledger_saved,
            )

    def _ledger_saved(self, entry: dict[str, Any]) -> None:
        self.statusBar().showMessage(f'Ledger account saved: {entry["name"]}.', 5000)
        self._clear_ledger_form()
        self.load_ledger()
        self.load_customers()

    def _clear_ledger_form(self) -> None:
        self.selected_ledger_id = None
        for field in self.ledger_inputs.values():
            field.clear()
        self.ledger_party_type.setCurrentIndex(0)
        self.ledger_opening_amount.setValue(0)
        self.ledger_opening_gold.setValue(0)
        self.ledger_opening_silver.setValue(0)
        self.ledger_form_status.clear()
        self.ledger_table.clearSelection()

    def delete_ledger_entry(self) -> None:
        if self.selected_ledger_id is None:
            self._show_error("Select a ledger account before deleting.")
            return
        name = self.ledger_inputs["name"].text().strip()
        reply = QMessageBox.question(
            self,
            "Delete ledger account",
            f"Delete {name}? Accounts referenced by bills or schemes cannot be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._request(
            "delete-ledger",
            "DELETE",
            f"/api/v1/ledger/{self.selected_ledger_id}",
            on_success=lambda _: self._ledger_deleted(name),
        )

    def _ledger_deleted(self, name: str) -> None:
        self._clear_ledger_form()
        self.load_ledger()
        self.load_customers()
        self.statusBar().showMessage(f"Ledger account deleted: {name}.", 5000)

    def _populate_scheme_customers(self) -> None:
        if not hasattr(self, "scheme_customer_combo"):
            return
        previous = self.scheme_customer_combo.currentData()
        self.scheme_customer_combo.blockSignals(True)
        self.scheme_customer_combo.clear()
        self.scheme_customer_combo.addItem("Choose a customer", None)
        selected_index = 0
        for customer in self.customers:
            self.scheme_customer_combo.addItem(
                f'{customer["name"]} · {customer.get("phone") or "no phone"}',
                customer["customer_id"],
            )
            if customer["customer_id"] == previous:
                selected_index = self.scheme_customer_combo.count() - 1
        self.scheme_customer_combo.setCurrentIndex(selected_index)
        self.scheme_customer_combo.blockSignals(False)

    def load_schemes(self) -> None:
        self._request(
            "load-schemes",
            "GET",
            "/api/v1/schemes?branch_id=1",
            on_success=self._schemes_loaded,
        )

    def _schemes_loaded(self, schemes: list[dict[str, Any]]) -> None:
        self.schemes = schemes
        self.scheme_table.setRowCount(0)
        current_id = getattr(
            self, "preferred_scheme_id", self.scheme_record_combo.currentData()
        )
        self.preferred_scheme_id = None
        self.scheme_record_combo.blockSignals(True)
        self.scheme_record_combo.clear()
        for scheme in schemes:
            row = self.scheme_table.rowCount()
            self.scheme_table.insertRow(row)
            values = [
                scheme.get("scheme_no"),
                scheme.get("customer_name"),
                scheme.get("scheme_type"),
                scheme.get("start_date"),
                f'{scheme.get("installment_count", 0)} / {scheme.get("tenure_months")}',
                money_text(scheme.get("monthly_contribution")),
                money_text(scheme.get("paid_total")),
                scheme.get("status"),
            ]
            for column, value in enumerate(values):
                cell = value_item(value, column >= 5)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, scheme["scheme_id"])
                self.scheme_table.setItem(row, column, cell)
            self.scheme_record_combo.addItem(
                f'{scheme["scheme_no"]} · {scheme["customer_name"]}',
                scheme["scheme_id"],
            )
        selected_index = self.scheme_record_combo.findData(current_id)
        if selected_index < 0 and self.scheme_record_combo.count():
            selected_index = 0
        self.scheme_record_combo.setCurrentIndex(selected_index)
        self.scheme_record_combo.blockSignals(False)
        if selected_index >= 0:
            self._scheme_selected(selected_index)

    def _select_scheme_row(self, row: int, _column: int) -> None:
        cell = self.scheme_table.item(row, 0)
        if cell is None:
            return
        scheme_id = cell.data(Qt.ItemDataRole.UserRole)
        index = self.scheme_record_combo.findData(scheme_id)
        if index >= 0:
            self.scheme_record_combo.setCurrentIndex(index)

    def _scheme_selected(self, index: int) -> None:
        scheme_id = self.scheme_record_combo.itemData(index)
        if scheme_id is None:
            self.installment_table.setRowCount(0)
            return
        scheme = next(
            (entry for entry in self.schemes if entry["scheme_id"] == scheme_id), None
        )
        if scheme:
            next_number = int(scheme.get("installment_count", 0)) + 1
            self.installment_number.setValue(
                min(next_number, int(scheme["tenure_months"]))
            )
            self.installment_number.setEnabled(scheme.get("status") == "Running")
            self.installment_amount.setValue(
                float(decimal_value(scheme.get("monthly_contribution")))
            )
        self.load_scheme_installments(int(scheme_id))

    def load_scheme_installments(self, scheme_id: int) -> None:
        self.installment_request_generation += 1
        generation = self.installment_request_generation
        self._request(
            f"load-installments-{generation}",
            "GET",
            f"/api/v1/schemes/{scheme_id}/installments",
            on_success=lambda installments: self._installments_loaded(
                scheme_id, generation, installments
            ),
            on_error=lambda message: self._installment_load_failed(
                generation, message
            ),
        )

    def _installment_load_failed(self, generation: int, message: str) -> None:
        if generation == self.installment_request_generation:
            self._default_error(message)

    def _installments_loaded(
        self, scheme_id: int, generation: int, installments: list[dict[str, Any]]
    ) -> None:
        if (
            self.scheme_record_combo.currentData() != scheme_id
            or generation != self.installment_request_generation
        ):
            return
        self.installment_table.setRowCount(0)
        for installment in installments:
            row = self.installment_table.rowCount()
            self.installment_table.insertRow(row)
            values = [
                installment.get("installment_no"),
                installment.get("payment_date"),
                money_text(installment.get("paid_amount")),
                money_text(installment.get("gold_rate")),
                money_text(installment.get("late_fine")),
                installment.get("payment_mode"),
                installment.get("transaction_reference"),
                installment.get("deposit_bank"),
            ]
            for column, value in enumerate(values):
                self.installment_table.setItem(
                    row, column, value_item(value, column in {2, 3, 4})
                )

    def create_scheme(self) -> None:
        customer_id = self.scheme_customer_combo.currentData()
        if customer_id is None:
            self._show_error("Choose a customer before enrolling in a scheme.")
            return
        description = self.scheme_description.text().strip()
        if not description:
            self._show_error("Enter a description for this scheme.")
            return
        payload = {
            "customer_id": customer_id,
            "scheme_type": self.scheme_type_combo.currentData(),
            "start_date": self.scheme_start_date.text().strip(),
            "tenure_months": int(self.scheme_tenure.value()),
            "monthly_contribution": str(self.scheme_monthly_amount.value()),
            "bonus_amount": str(self.scheme_bonus_amount.value()),
            "description": description,
            "reminder_date": self.scheme_reminder_date.text().strip() or None,
        }
        self._request(
            "create-scheme", "POST", "/api/v1/schemes", payload, self._scheme_created
        )

    def _scheme_created(self, scheme: dict[str, Any]) -> None:
        self.statusBar().showMessage(
            f'Scheme account created: {scheme["scheme_no"]}.', 5000
        )
        self.preferred_scheme_id = scheme["scheme_id"]
        self.scheme_description.clear()
        self.load_schemes()

    def post_scheme_installment(self) -> None:
        scheme_id = self.scheme_record_combo.currentData()
        if scheme_id is None:
            self._show_error("Choose a scheme account before posting a payment.")
            return
        payload = {
            "installment_no": int(self.installment_number.value()),
            "payment_date": self.installment_date.text().strip(),
            "paid_amount": str(self.installment_amount.value()),
            "gold_rate": str(self.installment_gold_rate.value()),
            "late_fine": str(self.installment_late_fine.value()),
            "payment_mode": self.installment_mode.currentData(),
            "transaction_reference": self.installment_reference.text().strip() or None,
            "deposit_bank": self.installment_bank.text().strip() or None,
        }
        self._request(
            "post-installment",
            "POST",
            f"/api/v1/schemes/{scheme_id}/installments",
            payload,
            self._installment_posted,
        )

    def _installment_posted(self, scheme: dict[str, Any]) -> None:
        self.statusBar().showMessage(
            f'Installment posted to {scheme["scheme_no"]}.', 5000
        )
        self.installment_reference.clear()
        self.installment_bank.clear()
        self.load_schemes()

    def load_stock(self) -> None:
        if not self.settings:
            return
        search = self.pos_search.text().strip() if hasattr(self, "pos_search") else ""
        from urllib.parse import quote
        self._request(
            "load-stock",
            "GET",
            f"/api/v1/stock?branch_id=1&search={quote(search)}",
            on_success=self._stock_loaded,
        )

    def _stock_loaded(self, stock: list[dict[str, Any]]) -> None:
        self.stock = stock
        self._populate_inventory_table()
        self._populate_pos_stock_table()

    def _populate_inventory_table(self) -> None:
        if not hasattr(self, "inventory_table"):
            return
        self.inventory_table.setRowCount(0)
        for record in self.stock:
            row = self.inventory_table.rowCount()
            self.inventory_table.insertRow(row)
            values = [
                record.get("tag_no"),
                record.get("item_name"),
                str(record.get("material_type", "")).title(),
                weight_text(record.get("gross_weight")),
                weight_text(record.get("net_weight")),
                record.get("size") or "—",
                record.get("huid") or "—",
                money_text(record.get("purchase_amount")),
                money_text(record.get("mrp")),
                money_text(record.get("rate_per_gram")),
                money_text(
                    decimal_value(record.get("metal_amount"))
                    + decimal_value(record.get("labour_amount"))
                    + decimal_value(record.get("other_charges"))
                ),
            ]
            for col, value in enumerate(values):
                self.inventory_table.setItem(row, col, value_item(value, col >= 3))

    def _populate_pos_stock_table(self) -> None:
        if not hasattr(self, "pos_stock_table"):
            return
        self.pos_stock_table.blockSignals(True)
        self.pos_stock_table.setRowCount(0)
        for record in self.stock:
            row = self.pos_stock_table.rowCount()
            self.pos_stock_table.insertRow(row)
            select = QTableWidgetItem()
            select.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            select.setCheckState(Qt.CheckState.Unchecked)
            select.setData(Qt.ItemDataRole.UserRole, record)
            self.pos_stock_table.setItem(row, 0, select)
            values = [
                record.get("tag_no"),
                record.get("item_name"),
                str(record.get("material_type", "")).title(),
                weight_text(record.get("net_weight")),
                money_text(record.get("rate_per_gram")),
                money_text(record.get("metal_amount")),
                money_text(record.get("labour_amount")),
                f'{record.get("gst_rate", 0)}%',
            ]
            for col, value in enumerate(values, start=1):
                self.pos_stock_table.setItem(row, col, value_item(value, col >= 4))
        self.pos_stock_table.blockSignals(False)
        self._selection_changed()

    def _selected_stock_ids(self) -> list[int]:
        selected = []
        for row in range(self.pos_stock_table.rowCount()):
            check = self.pos_stock_table.item(row, 0)
            if check and check.checkState() == Qt.CheckState.Checked:
                stock = check.data(Qt.ItemDataRole.UserRole)
                selected.append(int(stock["stock_id"]))
        return selected

    def _invalidate_quote(self, *_: object) -> None:
        self._last_quote = None
        self._selection_changed()

    def _selection_changed(self, _: QTableWidgetItem | None = None) -> None:
        self._last_quote = None
        if hasattr(self, "selected_count"):
            count = len(self._selected_stock_ids())
            self.selected_count.setText(f"{count} tag{'s' if count != 1 else ''} selected")
            self.quote_label.setText(
                "Selection changed. Calculate the quote before completing the sale."
                if count
                else "Choose tagged stock, then calculate the invoice."
            )

    def _sale_payload(self) -> dict[str, Any] | None:
        stock_ids = self._selected_stock_ids()
        if not stock_ids:
            self.pos_error.setText("Select at least one available tag.")
            return None
        self.pos_error.setText("")
        return {
            "stock_ids": stock_ids,
            "customer_id": self.pos_customer.currentData(),
            "discount": str(self.pos_discount.value()),
            "cash_amount": str(self.pos_cash.value()),
            "bank_amount": str(self.pos_bank.value()),
        }

    def calculate_quote(self) -> None:
        payload = self._sale_payload()
        if payload is not None:
            self._request(
                "quote",
                "POST",
                "/api/v1/sales/quote",
                payload,
                self._quote_loaded,
                self._quote_failed,
            )

    def _quote_loaded(self, quote: dict[str, Any]) -> None:
        totals = quote["totals"]
        tax_type = "IGST" if quote["tax_type"] == "IGST" else "CGST + SGST"
        tax_amount = (
            decimal_value(totals["igst_amount"])
            + decimal_value(totals["cgst_amount"])
            + decimal_value(totals["sgst_amount"])
        )
        self.quote_label.setText(
            f'Subtotal {money_text(totals["subtotal"])}    ·    '
            f'Discount {money_text(totals["discount"])}    ·    '
            f'Taxable {money_text(totals["taxable_amount"])}    ·    '
            f'{tax_type} {money_text(tax_amount)}    ·    '
            f'TOTAL {money_text(totals["grand_total"])}    ·    '
            f'Due after payment {money_text(totals["payment_due"])}'
        )
        self.pos_error.setText("")
        self._last_quote = quote

    def _quote_failed(self, message: str) -> None:
        self._last_quote = None
        self.pos_error.setText(message)

    def complete_sale(self) -> None:
        payload = self._sale_payload()
        if payload is None:
            return
        if not getattr(self, "_last_quote", None):
            self.pos_error.setText("Calculate the bill total before completing the sale.")
            return
        total = money_text(self._last_quote["totals"]["grand_total"])
        reply = QMessageBox.question(
            self,
            "Complete sale",
            f"Save this invoice for {total} and mark the selected stock tags as sold?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._request(
            "checkout", "POST", "/api/v1/sales", payload, self._sale_completed
        )

    def _sale_completed(self, result: dict[str, Any]) -> None:
        self._last_quote = None
        invoice = result["invoice"]
        lines = result.get("lines", [])
        line_text = "\n".join(
            f'• {line["bill_print_item_name"]} · {line["gross_weight"]} g · '
            f'{money_text(line["purchase_rs"])}'
            for line in lines
        )
        QMessageBox.information(
            self,
            "Sale saved",
            f'Invoice {invoice["sales_bill_no"]}\n'
            f'Customer: {invoice.get("customer_name") or "Walk-in"}\n\n'
            f"{line_text}\n\n"
            f'Total: {money_text(invoice["grand_total"])}\n'
            f'Paid: {money_text(invoice["total_payment"])}\n'
            f'Due: {money_text(invoice["payment_due"])}',
        )
        self.pos_discount.setValue(0)
        self.pos_cash.setValue(0)
        self.pos_bank.setValue(0)
        self.load_stock()
        self.load_sales()
        self.statusBar().showMessage("Sale and inventory update committed.", 6000)

    def _show_sales(self, table: QTableWidget) -> None:
        table.setRowCount(0)
        for sale in self.sales:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                sale.get("sales_bill_no"),
                sale.get("purchase_date"),
                sale.get("customer_name") or "Walk-in",
                money_text(sale.get("grand_total")),
                money_text(sale.get("total_payment")),
                money_text(sale.get("payment_due")),
                sale.get("status", ""),
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, value_item(value, col >= 3))

    def load_sales(self) -> None:
        if not self.settings:
            return
        self._request(
            "load-sales",
            "GET",
            "/api/v1/sales?branch_id=1&limit=50",
            on_success=self._sales_loaded,
        )

    def _sales_loaded(self, sales: list[dict[str, Any]]) -> None:
        self.sales = sales
        self._show_sales(self.dashboard_sales_table)

    def load_dashboard(self) -> None:
        self._request(
            "load-dashboard",
            "GET",
            "/api/v1/dashboard?branch_id=1",
            on_success=self._dashboard_loaded,
        )

    def _dashboard_loaded(self, result: dict[str, Any]) -> None:
        self.metric_sales_value.setText(money_text(result.get("today_sales")))
        self.metric_gold_value.setText(weight_text(result.get("gold_stock_weight")))
        self.metric_silver_value.setText(weight_text(result.get("silver_stock_weight")))
        self.metric_customers_value.setText(str(result.get("customer_count", 0)))
        self.metric_invoices_value.setText(str(result.get("today_invoice_count", 0)))

    def create_stock(self) -> None:
        if self.stock_item_combo.count() == 0:
            self._show_error("Create a gold or silver item in Item catalogue first.")
            return
        tag = self.stock_tag_input.text().strip()
        if not tag:
            self._show_error("Enter a unique tag number.")
            return
        if self.stock_net.value() > self.stock_gross.value():
            self._show_error("Net weight cannot exceed gross weight.")
            return
        payload = {
            "item_id": int(self.stock_item_combo.currentData()),
            "tag_no": tag,
            "gross_weight": str(self.stock_gross.value()),
            "net_weight": str(self.stock_net.value()),
            "pieces": int(self.stock_pieces.value()),
            "carat": self.stock_carat.currentData(),
            "labour_charge": str(self.stock_labour.value()),
            "labour_unit": self.stock_labour_unit.currentData(),
            "other_charges": str(self.stock_other.value()),
            "size": self.stock_size.text().strip() or None,
            "huid": self.stock_huid.text().strip() or None,
            "design_no": self.stock_design.text().strip() or None,
            "order_bill_no": self.stock_order.text().strip() or None,
            "purchase_rate": str(self.stock_purchase_rate.value()),
            "purchase_amount": str(self.stock_purchase_amount.value()),
            "wastage_percent": str(self.stock_wastage.value()),
            "hallmark_charge": str(self.stock_hallmark.value()),
            "mrp": str(self.stock_mrp.value()),
        }
        self._request(
            "create-stock", "POST", "/api/v1/stock", payload, self._stock_created
        )

    def _stock_created(self, stock: dict[str, Any]) -> None:
        self.stock_tag_input.clear()
        self.stock_gross.setValue(0)
        self.stock_net.setValue(0)
        self.stock_pieces.setValue(1)
        self.stock_size.clear()
        self.stock_huid.clear()
        self.stock_design.clear()
        self.stock_order.clear()
        self.stock_purchase_rate.setValue(0)
        self.stock_purchase_amount.setValue(0)
        self.stock_wastage.setValue(0)
        self.stock_hallmark.setValue(0)
        self.stock_other.setValue(0)
        self.stock_mrp.setValue(0)
        self.statusBar().showMessage(f'Tag added to stock: {stock["tag_no"]}.', 5000)
        self.load_stock()

    def import_customers(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import customer CSV", "", "CSV files (*.csv);;All files (*.*)"
        )
        if not path:
            return
        try:
            csv_text = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            self._show_error(f"Could not read that CSV file: {exc}")
            return
        self._request(
            "import-customers",
            "POST",
            "/api/v1/import/customers",
            csv_text,
            self._customers_imported,
            content_type="text/csv",
        )

    def _customers_imported(self, result: dict[str, Any]) -> None:
        self.statusBar().showMessage(
            f'Imported {result.get("imported", 0)} customers.', 7000
        )
        self.load_customers()

    def export_data(self, resource: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {resource}",
            f"{resource}.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return
        self._request(
            f"export-{resource}",
            "GET",
            f"/api/v1/export/{resource}",
            on_success=lambda text: self._save_export(path, text),
        )

    def _save_export(self, path: str, csv_text: str) -> None:
        try:
            Path(path).write_text(csv_text, encoding="utf-8-sig", newline="")
        except OSError as exc:
            self._show_error(f"Could not save the CSV export: {exc}")
            return
        self.statusBar().showMessage(f"CSV export saved to {path}.", 7000)

    def open_api_docs(self) -> None:
        try:
            base_url = normalize_base_url(self.backend_input.text())
        except ValueError as exc:
            self._show_error(str(exc))
            return
        QDesktopServices.openUrl(QUrl(f"{base_url}/docs"))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.health_timer.stop()
        for worker in self.workers.values():
            if worker.isRunning():
                worker.requestInterruption()
        for worker in self.workers.values():
            if worker.isRunning():
                worker.wait(13_000)
        super().closeEvent(event)


def stylesheet() -> str:
    return f"""
        QWidget {{ font-family: "Segoe UI"; font-size: 12px; color: {INK}; }}
        QMainWindow, QWidget#content {{ background: {CANVAS}; }}
        QListWidget#navigation {{
            background: #101827; color: #d9e1ed; border: none;
            padding: 16px 10px; outline: none;
        }}
        QListWidget#navigation::item {{
            border-radius: 7px; padding: 11px 10px; margin: 2px 2px;
        }}
        QListWidget#navigation::item:selected {{
            background: #d99a10; color: #111827; border-left: 3px solid #ffc445;
        }}
        QListWidget#navigation::item:hover:!selected {{ background: #202c40; }}
        QListWidget#navigation::item:disabled {{
            color: #8492a7; padding: 15px 10px 6px 10px; font-size: 9px;
            font-weight: 700;
        }}
        QLabel#eyebrow {{ color: {MUTED}; font-size: 9px; font-weight: 700; letter-spacing: 1px; }}
        QLabel#pageTitle {{ font-size: 25px; font-weight: 650; color: {INK}; }}
        QLabel#connectionStatus {{ font-size: 9px; font-weight: 700; }}
        QLabel#mutedText {{ color: {MUTED}; font-size: 11px; }}
        QLabel#fieldLabel {{ color: #676a62; font-size: 10px; font-weight: 650; }}
        QLabel#cardTitle {{ color: #30322c; font-size: 14px; font-weight: 650; }}
        QLabel#metricValue {{ color: {INK}; font-size: 23px; font-weight: 700; }}
        QLabel#quoteSummary {{
            background: #fff8e8; color: #694313; border: 1px solid #f1d183;
            border-radius: 8px; padding: 12px; font-size: 11px; font-weight: 600;
        }}
        QLabel#inlineError {{ color: {RED}; font-size: 10px; }}
        QLabel#safetyNote {{
            color: #7c622f; background: #faf3e4; border: 1px solid #eee0c4;
            border-radius: 8px; padding: 11px; font-size: 10px;
        }}
        QLabel#welcomeTitle {{ color: #f9f5ed; font-size: 18px; font-weight: 650; }}
        QLabel#welcomeSubtitle {{ color: #b9c7d9; font-size: 11px; }}
        QFrame#card {{
            background: {SURFACE}; border: 1px solid {LINE}; border-radius: 9px;
        }}
        QFrame#welcomeCard {{
            background: #111c30; border: 1px solid #26364e; border-radius: 9px;
        }}
        QLineEdit#fieldInput, QComboBox#fieldInput, QDoubleSpinBox#fieldInput,
        QLineEdit#urlInput {{
            background: #fff; border: 1px solid #cbd6e4; border-radius: 6px;
            padding: 8px 10px; min-height: 19px; selection-background-color: #eac66c;
        }}
        QLineEdit#fieldInput:focus, QComboBox#fieldInput:focus,
        QDoubleSpinBox#fieldInput:focus, QLineEdit#urlInput:focus {{
            border: 1px solid {GOLD};
        }}
        QPushButton#primaryButton, QPushButton#secondaryButton, QPushButton#lightButton {{
            border-radius: 6px; padding: 9px 13px; font-size: 11px; font-weight: 650;
        }}
        QPushButton#primaryButton {{ background: #d98208; color: #fff; border: none; }}
        QPushButton#primaryButton:hover {{ background: #bd6f05; }}
        QPushButton#dangerButton {{
            background: #fff; color: #b52d43; border: 1px solid #efabb5;
            border-radius: 6px; padding: 9px 13px; font-size: 11px; font-weight: 650;
        }}
        QPushButton#dangerButton:hover {{ background: #fff1f3; }}
        QPushButton#secondaryButton {{
            background: #fff; color: #25344b; border: 1px solid #cbd6e4;
        }}
        QPushButton#secondaryButton:hover {{ background: #f2f6fb; border-color: #a8b8cc; }}
        QPushButton#lightButton {{ background: #f2c14b; color: #142035; border: none; }}
        QPushButton#lightButton:hover {{ background: #ffcf53; }}
        QTableWidget {{
            background: #fff; alternate-background-color: #f7f9fc;
            border: 1px solid #e1e7ef; border-radius: 7px;
            gridline-color: transparent; outline: none;
        }}
        QTableWidget::item {{ padding: 5px; border-bottom: 1px solid #f0efeb; }}
        QTableWidget::item:selected {{ background: #fff0c2; color: #172238; }}
        QHeaderView::section {{
            background: #f3f6fa; color: #53647d; padding: 8px 5px;
            border: none; border-bottom: 1px solid #dfe6ef;
            font-size: 9px; font-weight: 700;
        }}
        QStatusBar {{ background: transparent; color: {MUTED}; font-size: 10px; }}
    """


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Dindorkar Saraf Jewellery Management")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(stylesheet())
    window = RetailWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
