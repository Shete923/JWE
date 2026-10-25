from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SaleLineInput:
    net_weight: Decimal
    rate_per_gram: Decimal
    labour_charge: Decimal
    labour_unit: str
    other_charges: Decimal
    gst_rate: Decimal


@dataclass(frozen=True)
class SaleLineAmounts:
    metal_amount: Decimal
    labour_amount: Decimal
    other_charges: Decimal
    subtotal: Decimal
    gst_rate: Decimal


@dataclass(frozen=True)
class SaleTotals:
    subtotal: Decimal
    discount: Decimal
    taxable_amount: Decimal
    cgst_rate: Decimal
    cgst_amount: Decimal
    sgst_rate: Decimal
    sgst_amount: Decimal
    igst_rate: Decimal
    igst_amount: Decimal
    grand_total: Decimal
    cash_amount: Decimal
    bank_amount: Decimal
    payment_due: Decimal


def calculate_line(line: SaleLineInput) -> SaleLineAmounts:
    if line.net_weight <= ZERO:
        raise ValueError("Net weight must be greater than zero.")
    if line.rate_per_gram <= ZERO:
        raise ValueError("Metal rate must be greater than zero.")
    if line.labour_charge < ZERO or line.other_charges < ZERO:
        raise ValueError("Labour and other charges cannot be negative.")
    if not ZERO <= line.gst_rate <= Decimal("100"):
        raise ValueError("GST rate must be between 0 and 100 percent.")

    metal_amount = money(line.net_weight * line.rate_per_gram)
    normalized_unit = line.labour_unit.casefold().replace(" ", "_")
    if normalized_unit == "fixed":
        labour_amount = money(line.labour_charge)
    elif normalized_unit == "per_gram":
        labour_amount = money(line.net_weight * line.labour_charge)
    elif normalized_unit == "percent":
        labour_amount = money(metal_amount * line.labour_charge / Decimal("100"))
    else:
        raise ValueError("Labour unit must be fixed, per_gram, or percent.")

    other_charges = money(line.other_charges)
    return SaleLineAmounts(
        metal_amount=metal_amount,
        labour_amount=labour_amount,
        other_charges=other_charges,
        subtotal=money(metal_amount + labour_amount + other_charges),
        gst_rate=line.gst_rate.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP),
    )


def allocate_discount(
    lines: list[SaleLineAmounts], discount: Decimal
) -> list[Decimal]:
    subtotal = sum((line.subtotal for line in lines), ZERO)
    if discount < ZERO or discount > subtotal:
        raise ValueError("Discount must be between zero and the sale subtotal.")
    if not lines:
        raise ValueError("At least one sale line is required.")
    if subtotal == ZERO:
        return [ZERO for _ in lines]

    allocations: list[Decimal] = []
    allocated = ZERO
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            share = money(discount - allocated)
        else:
            share = money(discount * line.subtotal / subtotal)
        allocations.append(share)
        allocated += share

    if sum(allocations, ZERO) != discount:
        raise ValueError("Discount could not be allocated exactly across sale lines.")
    return allocations


def calculate_totals(
    lines: list[SaleLineAmounts],
    discount: Decimal,
    cash_amount: Decimal,
    bank_amount: Decimal,
    is_interstate: bool,
) -> SaleTotals:
    if not lines:
        raise ValueError("At least one sale line is required.")
    if cash_amount < ZERO or bank_amount < ZERO:
        raise ValueError("Payment amounts cannot be negative.")

    subtotal = money(sum((line.subtotal for line in lines), ZERO))
    discount = money(discount)
    allocations = allocate_discount(lines, discount)
    taxable_amount = ZERO
    tax_amount = ZERO

    for line, line_discount in zip(lines, allocations, strict=True):
        taxable_line = money(line.subtotal - line_discount)
        taxable_amount += taxable_line
        tax_amount += money(taxable_line * line.gst_rate / Decimal("100"))

    taxable_amount = money(taxable_amount)
    tax_amount = money(tax_amount)
    if is_interstate:
        cgst_rate = sgst_rate = ZERO
        cgst_amount = sgst_amount = ZERO
        igst_rate = max((line.gst_rate for line in lines), default=ZERO)
        igst_amount = tax_amount
    else:
        cgst_rate = sgst_rate = (
            max((line.gst_rate for line in lines), default=ZERO) / Decimal("2")
        )
        cgst_amount = ZERO
        sgst_amount = ZERO
        for line, line_discount in zip(lines, allocations, strict=True):
            taxable_line = money(line.subtotal - line_discount)
            half_rate = line.gst_rate / Decimal("2")
            cgst_amount += money(taxable_line * half_rate / Decimal("100"))
            sgst_amount += money(taxable_line * half_rate / Decimal("100"))
        cgst_amount = money(cgst_amount)
        sgst_amount = money(sgst_amount)
        igst_rate = igst_amount = ZERO

    grand_total = money(taxable_amount + cgst_amount + sgst_amount + igst_amount)
    cash_amount = money(cash_amount)
    bank_amount = money(bank_amount)
    if cash_amount + bank_amount > grand_total:
        raise ValueError("Cash and bank payments cannot exceed the invoice total.")
    return SaleTotals(
        subtotal=subtotal,
        discount=discount,
        taxable_amount=taxable_amount,
        cgst_rate=cgst_rate,
        cgst_amount=cgst_amount,
        sgst_rate=sgst_rate,
        sgst_amount=sgst_amount,
        igst_rate=igst_rate,
        igst_amount=igst_amount,
        grand_total=grand_total,
        cash_amount=cash_amount,
        bank_amount=bank_amount,
        payment_due=money(grand_total - cash_amount - bank_amount),
    )
