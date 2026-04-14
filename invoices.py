"""
Invoice routes — read-only lookup endpoints mirroring Acumatica's
Receivables → Invoices and Memos screen.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

import database as db
from models import Invoice, InvoiceListResponse, InvoiceStatus, ErrorResponse

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get(
    "",
    response_model=InvoiceListResponse,
    summary="List / search invoices",
    description=(
        "Search Acumatica invoices. Mirrors the **Invoices and Memos** screen in the "
        "Receivables module. Use `customer_id` and/or `status` to filter results. "
        "Returns all open invoices by default."
    ),
    responses={200: {"description": "List of matching invoices"}}
)
def list_invoices(
    customer_id: Optional[str] = Query(None, description="Filter by Acumatica Customer ID (e.g. OXBLUE001)"),
    status: Optional[InvoiceStatus] = Query(None, description="Filter by invoice status. Defaults to all statuses."),
):
    invoices = db.list_invoices(customer_id=customer_id, status=status)
    return InvoiceListResponse(invoices=invoices, total=len(invoices))


@router.get(
    "/{reference_nbr}",
    response_model=Invoice,
    summary="Get invoice by reference number",
    description=(
        "Retrieve a single invoice by its reference number. "
        "Returns invoice details including current balance due and status. "
        "Use this before creating a payment to verify the invoice exists and is Open."
    ),
    responses={
        200: {"description": "Invoice found"},
        404: {"model": ErrorResponse, "description": "Invoice not found"}
    }
)
def get_invoice(
    reference_nbr: str,
):
    invoice = db.get_invoice(reference_nbr)
    if not invoice:
        raise HTTPException(
            status_code=404,
            detail=f"Invoice '{reference_nbr}' not found. It may have been paid, credited, or belong to a different customer."
        )
    return invoice
