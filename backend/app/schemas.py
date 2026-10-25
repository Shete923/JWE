from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

MaterialType = Literal["gold", "silver", "other"]
LabourUnit = Literal["fixed", "per_gram", "percent"]


class ShopSettingsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    branch_id: Literal[1] = 1
    business_name: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=100)
    gstin: str | None = Field(default=None, max_length=20)
    fiscal_year_start_month: int = Field(default=4, ge=1, le=12)

    @field_validator("gstin")
    @classmethod
    def normalize_gstin(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class MetalRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: Literal[1] = 1
    effective_date: date = Field(default_factory=date.today)
    material_type: Literal["gold", "silver"]
    carat: Decimal = Field(default=Decimal("0"), ge=0, le=24, max_digits=5, decimal_places=2)
    rate_per_gram: Decimal = Field(gt=0, max_digits=14, decimal_places=4)

    @field_validator("carat")
    @classmethod
    def validate_carat_for_material(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        material_type = info.data.get("material_type")
        if material_type == "gold" and value <= 0:
            raise ValueError("Enter the carat for a gold rate.")
        if material_type == "silver" and value != 0:
            raise ValueError("Silver rates use carat 0.")
        return value


class ItemInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    prefix: str = Field(min_length=1, max_length=30)
    material_type: MaterialType
    carat: Decimal = Field(default=Decimal("0"), ge=0, le=24, max_digits=5, decimal_places=2)
    hsn_code: str | None = Field(default=None, max_length=20)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4)
    default_labour_charge: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2
    )
    default_labour_unit: LabourUnit = "fixed"
    default_other_charges: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2
    )

    @field_validator("carat")
    @classmethod
    def validate_carat_for_material(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        if info.data.get("material_type") == "gold" and value <= 0:
            raise ValueError("Enter the carat for a gold item.")
        if info.data.get("material_type") != "gold" and value != 0:
            raise ValueError("Only gold items use carat in this retail release.")
        return value


class CustomerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    state: str | None = Field(default=None, max_length=100)
    gstin: str | None = Field(default=None, max_length=20)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.casefold() if value else None

    @field_validator("gstin")
    @classmethod
    def normalize_gstin(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class LedgerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    party_type: Literal["Customer", "Party", "Karigar", "Expense"] = "Customer"
    address: str | None = Field(default=None, max_length=1000)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    pincode: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    alternate_phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    gstin: str | None = Field(default=None, max_length=20)
    pan: str | None = Field(default=None, max_length=20)
    aadhaar: str | None = Field(default=None, max_length=20)
    company_name: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=254)
    bank_name: str | None = Field(default=None, max_length=200)
    bank_address: str | None = Field(default=None, max_length=500)
    bank_account_number: str | None = Field(default=None, max_length=50)
    bank_account_name: str | None = Field(default=None, max_length=200)
    ifsc_code: str | None = Field(default=None, max_length=20)
    book_no: str | None = Field(default=None, max_length=50)
    prefix: str | None = Field(default=None, max_length=30)
    group_name: str | None = Field(default=None, max_length=100)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    opening_gold_grams: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=3)
    opening_silver_grams: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=3)
    mortgage_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4)
    nominee_name: str | None = Field(default=None, max_length=200)
    nominee_address: str | None = Field(default=None, max_length=1000)
    religion: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.casefold() if value else None

    @field_validator("gstin", "pan", "aadhaar", "ifsc_code")
    @classmethod
    def normalize_identifiers(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class SchemeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    customer_id: int = Field(ge=1)
    scheme_type: Literal["A (11+1 Mo.)", "B (12 Mo.)", "Custom"] = "A (11+1 Mo.)"
    start_date: date
    tenure_months: int = Field(ge=1, le=120)
    monthly_contribution: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bonus_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    description: str = Field(min_length=1, max_length=500)
    reminder_date: date | None = None


class SchemeInstallmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    installment_no: int = Field(ge=1, le=120)
    payment_date: date
    paid_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    gold_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=4)
    late_fine: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    payment_mode: Literal["Cash", "Bank", "UPI", "NEFT / RTGS", "Cheque"] = "Cash"
    transaction_reference: str | None = Field(default=None, max_length=100)
    deposit_bank: str | None = Field(default=None, max_length=200)


class StockInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    item_id: int = Field(ge=1)
    tag_no: str = Field(min_length=1, max_length=80)
    gross_weight: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    net_weight: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    pieces: int = Field(default=1, ge=1)
    carat: Decimal = Field(default=Decimal("0"), ge=0, le=24, max_digits=5, decimal_places=2)
    labour_charge: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    labour_unit: LabourUnit | None = None
    other_charges: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    size: str | None = Field(default=None, max_length=50)
    huid: str | None = Field(default=None, max_length=80)
    design_no: str | None = Field(default=None, max_length=80)
    order_bill_no: str | None = Field(default=None, max_length=80)
    purchase_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=4)
    purchase_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    wastage_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4)
    hallmark_charge: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    mrp: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)

    @field_validator("tag_no")
    @classmethod
    def normalize_tag(cls, value: str) -> str:
        return value.upper()


class SaleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_ids: list[int] = Field(min_length=1, max_length=100)
    customer_id: int | None = Field(default=None, ge=1)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    cash_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    bank_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("stock_ids")
    @classmethod
    def require_unique_stock_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("A stock tag can only appear once in a bill.")
        return value
