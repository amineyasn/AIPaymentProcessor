"""
Payment routes — full CRUD for Acumatica payment simulation.
Mirrors both Method 1 (Pay from Invoice) and Method 2 (New Payment from Receivables menu).
"""

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

import database as db
from models import (
    CreatePaymentRequest, Payment, PaymentListResponse,
    PaymentStatus, ReleasePaymentResponse, ErrorResponse
)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get(
    "",
    response_model=PaymentListResponse,
    summary="List payments",
    description=(
        "List all payment records. Filter by customer or status. "
        "Results are sorted newest-first."
    )
)
def list_payments(
    customer_id: Optional[str] = Query(None, description="Filter by Customer ID"),
    status: Optional[PaymentStatus] = Query(None, description="Filter by payment status")
):
    payments = db.list_payments(customer_id=customer_id, status=status)
    return PaymentListResponse(payments=payments, total=len(payments))


@router.post(
    "",
    response_model=Payment,
    status_code=201,
    summary="Create a payment",
    description=(
        "Create a new payment record and apply it to one or more invoices. "
        "This simulates both **Method 1** (Pay From an Invoice) and "
        "**Method 2** (New Payment from Receivables menu) from the Acumatica SOP. "
        "\n\n"
        "**Validation rules applied:**\n"
        "- Customer must exist\n"
        "- All invoices must exist, belong to the customer, and be Open\n"
        "- Payment amount must match the sum of amounts_to_apply\n"
        "- Duplicate payment_ref check prevents double-entry\n"
        "\n"
        "Payment is created in **Open** status. Call `POST /payments/{id}/release` to finalize."
    ),
    responses={
        201: {"description": "Payment created successfully"},
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Customer or invoice not found"},
        409: {"model": ErrorResponse, "description": "Duplicate payment reference detected"}
    }
)
def create_payment(body: CreatePaymentRequest):
    # 1. Duplicate reference guard
    existing = db.check_duplicate_payment_ref(body.payment_ref)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Payment reference '{body.payment_ref}' already exists as {existing.reference_nbr} "
                   f"(status: {existing.status}). To avoid double-entry, this request was blocked."
        )

    # 2. Customer validation
    customer = db.get_customer(body.customer_id)
    if not customer:
        raise HTTPException(
            status_code=404,
            detail=f"Customer '{body.customer_id}' not found in Acumatica."
        )

    # 3. Invoice validation
    for item in body.invoices_to_apply:
        invoice = db.get_invoice(item.reference_nbr)
        if not invoice:
            raise HTTPException(
                status_code=404,
                detail=f"Invoice '{item.reference_nbr}' not found. It may be incorrect, "
                       "previously paid, or belong to a different customer."
            )
        if invoice.customer_id != body.customer_id:
            raise HTTPException(
                status_code=400,
                detail=f"Invoice '{item.reference_nbr}' belongs to customer '{invoice.customer_id}', "
                       f"not '{body.customer_id}'."
            )
        if invoice.status != "Open":
            raise HTTPException(
                status_code=400,
                detail=f"Invoice '{item.reference_nbr}' is in status '{invoice.status}' and cannot accept payments. "
                       "Only Open invoices can be paid."
            )
        if item.amount_to_apply > invoice.balance_due:
            raise HTTPException(
                status_code=400,
                detail=f"Amount to apply (${item.amount_to_apply:,.2f}) exceeds the balance due "
                       f"(${invoice.balance_due:,.2f}) on invoice '{item.reference_nbr}'. "
                       "Select a different date to allow the difference, or adjust the amount."
            )

    # 4. Amount reconciliation
    total_applied = round(sum(i.amount_to_apply for i in body.invoices_to_apply), 2)
    if round(body.payment_amount, 2) != total_applied:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount (${body.payment_amount:,.2f}) does not match the sum of "
                   f"amounts to apply (${total_applied:,.2f}). "
                   "For multiple invoices, enter the combined payment amount and ensure the per-invoice amounts add up."
        )

    # 5. Create the payment
    payment = db.create_payment(
        customer_id=body.customer_id,
        payment_amount=body.payment_amount,
        payment_method=body.payment_method,
        cash_account=body.cash_account,
        application_date=body.application_date,
        payment_ref=body.payment_ref,
        invoices_to_apply=body.invoices_to_apply,
        notes=body.notes,
    )
    return payment


@router.get(
    "/{payment_id}",
    response_model=Payment,
    summary="Get payment by ID",
    description="Retrieve a single payment record by its internal payment ID.",
    responses={404: {"model": ErrorResponse, "description": "Payment not found"}}
)
def get_payment(payment_id: str):
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail=f"Payment '{payment_id}' not found.")
    return payment


@router.post(
    "/{payment_id}/release",
    response_model=ReleasePaymentResponse,
    summary="Release a payment",
    description=(
        "Release a payment record. This is the equivalent of clicking the green **RELEASE** "
        "button in Acumatica. Once released:\n"
        "- Status changes from **Open** → **Released**\n"
        "- The transaction is posted to the general ledger\n"
        "- The applied invoices are marked Closed if fully paid\n\n"
        "Only payments in **Open** status can be released."
    ),
    responses={
        200: {"description": "Payment released successfully"},
        400: {"model": ErrorResponse, "description": "Payment is not in a releasable state"},
        404: {"model": ErrorResponse, "description": "Payment not found"}
    }
)
def release_payment(payment_id: str):
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail=f"Payment '{payment_id}' not found.")
    if payment.status != PaymentStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"Payment '{payment_id}' is in status '{payment.status}' and cannot be released. "
                   "Only Open payments can be released."
        )

    released = db.release_payment(payment_id)
    return ReleasePaymentResponse(
        payment_id=released.payment_id,
        reference_nbr=released.reference_nbr,
        status=released.status,
        released_at=released.released_at,
        message=(
            f"Payment {released.reference_nbr} for ${released.payment_amount:,.2f} "
            f"has been released successfully. "
            f"Applied to {len(released.applied_invoices)} invoice(s)."
        )
    )
