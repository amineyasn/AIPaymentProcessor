"""
In-memory simulated Acumatica database.
Seeded with realistic customers and invoices matching the training document examples.
Replace with real Acumatica REST calls in production.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
import uuid

from models import (
    Customer, Invoice, Payment, InvoiceStatus,
    PaymentMethod, PaymentStatus, DocumentType, AppliedInvoice
)


# ─────────────────────────────────────────────
# Seed data — Customers
# ─────────────────────────────────────────────

CUSTOMERS: Dict[str, Customer] = {
    "OXBLUE001": Customer(
        customer_id="OXBLUE001",
        customer_name="OxBlue Corporation",
        email="ar@oxblue.com",
        billing_contact_name="OxBlue Accounts Receivable",
        billing_phone="555-1001",
        billing_address_line1="123 Peachtree St NE",
        billing_address_line2="Suite 500",
        billing_city="Atlanta",
        billing_state="GA",
        billing_postal_code="30303"
    ),
    "LECHASE001": Customer(
        customer_id="LECHASE001",
        customer_name="LeChase Construction Services, LLC",
        email="ap@lechase.com",
        billing_contact_name="LeChase Payables",
        billing_phone="555-1002",
        billing_address_line1="205 St Paul St",
        billing_city="Rochester",
        billing_state="NY",
        billing_postal_code="14604"
    ),
    "CWLTH001": Customer(
        customer_id="CWLTH001",
        customer_name="Commonwealth Fusion Systems",
        email="accounts@cfs.energy",
        billing_contact_name="CFS Accounts Payable",
        billing_phone="555-1003",
        billing_address_line1="117 Hospital Rd",
        billing_city="Devens",
        billing_state="MA",
        billing_postal_code="01434"
    ),
    "DRISCOLL001": Customer(
        customer_id="DRISCOLL001",
        customer_name="L.F. Driscoll Company",
        email="ap@lfdriscoll.com",
        billing_contact_name="Driscoll Billing",
        billing_phone="555-1004",
        billing_address_line1="1000 N West St",
        billing_city="Wilmington",
        billing_state="DE",
        billing_postal_code="19801"
    ),
    "DPR001": Customer(
        customer_id="DPR001",
        customer_name="DPR Construction",
        email="payables@dprinc.com",
        billing_contact_name="DPR Payables",
        billing_phone="555-1005",
        billing_address_line1="1450 Veterans Blvd",
        billing_city="Redwood City",
        billing_state="CA",
        billing_postal_code="94063"
    ),
    "SLAYDEN001": Customer(
        customer_id="SLAYDEN001",
        customer_name="Slayden Constructors",
        email="ap@slayden.com",
        billing_contact_name="Slayden Billing",
        billing_phone="555-1006",
        billing_address_line1="1519 Nashville Pike",
        billing_city="Gallatin",
        billing_state="TN",
        billing_postal_code="37066"
    ),
    "KNUTSON001": Customer(
        customer_id="KNUTSON001",
        customer_name="Knutson Construction",
        email="accounting@knutsonconstruction.com",
        billing_contact_name="Knutson Accounting",
        billing_phone="555-1007",
        billing_address_line1="7515 Wayzata Blvd",
        billing_city="Minneapolis",
        billing_state="MN",
        billing_postal_code="55426"
    ),
}


# ─────────────────────────────────────────────
# Seed data — Invoices
# ─────────────────────────────────────────────

INVOICES: Dict[str, Invoice] = {
    # LeChase — Example 1 from training doc
    "607535": Invoice(
        reference_nbr="607535",
        customer_id="LECHASE001",
        customer_name="LeChase Construction Services, LLC",
        document_type=DocumentType.INVOICE,
        status=InvoiceStatus.OPEN,
        doc_date=date(2026, 3, 1),
        due_date=date(2026, 4, 1),
        amount_due=649.00,
        balance_due=649.00,
        description="OxBlue Camera Service — Site A"
    ),
    # Commonwealth Fusion — Example 2 from training doc (two invoices)
    "604541": Invoice(
        reference_nbr="604541",
        customer_id="CWLTH001",
        customer_name="Commonwealth Fusion Systems",
        document_type=DocumentType.INVOICE,
        status=InvoiceStatus.OPEN,
        doc_date=date(2026, 2, 15),
        due_date=date(2026, 3, 15),
        amount_due=10936.00,
        balance_due=10936.00,
        description="Camera monitoring — Q1 2026"
    ),
    "607228": Invoice(
        reference_nbr="607228",
        customer_id="CWLTH001",
        customer_name="Commonwealth Fusion Systems",
        document_type=DocumentType.INVOICE,
        status=InvoiceStatus.OPEN,
        doc_date=date(2026, 2, 28),
        due_date=date(2026, 3, 28),
        amount_due=4780.00,
        balance_due=4780.00,
        description="Camera monitoring — February supplement"
    ),
    # OxBlue invoices
    "608001": Invoice(
        reference_nbr="608001",
        customer_id="OXBLUE001",
        customer_name="OxBlue Corporation",
        document_type=DocumentType.INVOICE,
        status=InvoiceStatus.OPEN,
        doc_date=date(2026, 3, 10),
        due_date=date(2026, 4, 10),
        amount_due=2150.00,
        balance_due=2150.00,
        description="Monthly camera service — March 2026"
    ),
    "605900": Invoice(
        reference_nbr="605900",
        customer_id="DRISCOLL001",
        customer_name="L.F. Driscoll Company",
        document_type=DocumentType.INVOICE,
        status=InvoiceStatus.OPEN,
        doc_date=date(2026, 2, 1),
        due_date=date(2026, 3, 1),
        amount_due=3200.00,
        balance_due=3200.00,
        description="Site installation — Project 44"
    ),
    # Already-paid invoice for troubleshooting demo
    "600100": Invoice(
        reference_nbr="600100",
        customer_id="DPR001",
        customer_name="DPR Construction",
        document_type=DocumentType.INVOICE,
        status=InvoiceStatus.CLOSED,
        doc_date=date(2026, 1, 5),
        due_date=date(2026, 2, 5),
        amount_due=1875.00,
        balance_due=0.00,
        description="Q4 2025 camera service — paid"
    ),
}


# ─────────────────────────────────────────────
# In-memory payment store
# ─────────────────────────────────────────────

PAYMENTS: Dict[str, Payment] = {}

# Counter for human-readable reference numbers
_payment_counter = 7800


def _next_ref() -> str:
    global _payment_counter
    _payment_counter += 1
    return f"AR{_payment_counter:06d}"


# ─────────────────────────────────────────────
# Database helper functions
# ─────────────────────────────────────────────

def get_customer(customer_id: str) -> Optional[Customer]:
    return CUSTOMERS.get(customer_id)


def update_customer_billing_info(customer_id: str, updates: dict) -> Optional[Customer]:
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return None

    updated_customer = customer.model_copy(update=updates)
    CUSTOMERS[customer_id] = updated_customer
    return updated_customer


def search_customers(name_fragment: str) -> List[Customer]:
    fragment = name_fragment.lower()
    return [c for c in CUSTOMERS.values() if fragment in c.customer_name.lower()]


def get_invoice(reference_nbr: str) -> Optional[Invoice]:
    return INVOICES.get(reference_nbr)


def list_invoices(
    customer_id: Optional[str] = None,
    status: Optional[InvoiceStatus] = None
) -> List[Invoice]:
    results = list(INVOICES.values())
    if customer_id:
        results = [i for i in results if i.customer_id == customer_id]
    if status:
        results = [i for i in results if i.status == status]
    return results


def create_payment(
    customer_id: str,
    payment_amount: float,
    payment_method: PaymentMethod,
    cash_account: str,
    application_date: date,
    payment_ref: str,
    invoices_to_apply: list,
    notes: Optional[str] = None,
) -> Payment:
    """
    Simulate creating a payment record and applying it to invoices.
    Reduces each invoice's balance_due accordingly.
    """
    applied = []
    for item in invoices_to_apply:
        inv = INVOICES.get(item.reference_nbr)
        if inv:
            new_balance = max(0.0, round(inv.balance_due - item.amount_to_apply, 2))
            applied.append(AppliedInvoice(
                reference_nbr=item.reference_nbr,
                amount_applied=item.amount_to_apply,
                remaining_balance=new_balance
            ))
            # Mutate balance
            INVOICES[item.reference_nbr] = inv.model_copy(
                update={"balance_due": new_balance,
                        "status": InvoiceStatus.CLOSED if new_balance == 0 else InvoiceStatus.OPEN}
            )

    customer = CUSTOMERS.get(customer_id)
    payment_id = f"PMT-{datetime.utcnow().year}-{str(uuid.uuid4())[:8].upper()}"

    payment = Payment(
        payment_id=payment_id,
        reference_nbr=_next_ref(),
        customer_id=customer_id,
        customer_name=customer.customer_name if customer else customer_id,
        payment_amount=payment_amount,
        payment_method=payment_method,
        cash_account=cash_account,
        application_date=application_date,
        payment_ref=payment_ref,
        status=PaymentStatus.OPEN,
        applied_invoices=applied,
        created_at=datetime.utcnow(),
        released_at=None,
        notes=notes,
    )
    PAYMENTS[payment_id] = payment
    return payment


def release_payment(payment_id: str) -> Optional[Payment]:
    """Simulate the RELEASE action — moves status from Open → Released."""
    payment = PAYMENTS.get(payment_id)
    if not payment:
        return None
    released = payment.model_copy(update={
        "status": PaymentStatus.RELEASED,
        "released_at": datetime.utcnow()
    })
    PAYMENTS[payment_id] = released
    return released


def get_payment(payment_id: str) -> Optional[Payment]:
    return PAYMENTS.get(payment_id)


def list_payments(
    customer_id: Optional[str] = None,
    status: Optional[PaymentStatus] = None
) -> List[Payment]:
    results = list(PAYMENTS.values())
    if customer_id:
        results = [p for p in results if p.customer_id == customer_id]
    if status:
        results = [p for p in results if p.status == status]
    return sorted(results, key=lambda p: p.created_at, reverse=True)


def check_duplicate_payment_ref(payment_ref: str) -> Optional[Payment]:
    """Guard against duplicate payment entries by reference number."""
    for p in PAYMENTS.values():
        if p.payment_ref == payment_ref and p.status != PaymentStatus.VOIDED:
            return p
    return None
