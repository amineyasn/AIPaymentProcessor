"""
Customer routes — lookup endpoints for finding Acumatica customers.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

import database as db
from models import Customer, ErrorResponse, UpdateCustomerBillingRequest

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get(
    "",
    response_model=List[Customer],
    summary="Search customers",
    description="Search Acumatica customers by name fragment. Case-insensitive partial match."
)
def search_customers(
    name: Optional[str] = Query(None, description="Customer name fragment to search (e.g. 'LeChase')")
):
    if name:
        return db.search_customers(name)
    return list(db.CUSTOMERS.values())


@router.get(
    "/{customer_id}",
    response_model=Customer,
    summary="Get customer by ID",
    description="Retrieve a single customer record by their Acumatica Customer ID.",
    responses={404: {"model": ErrorResponse, "description": "Customer not found"}}
)
def get_customer(customer_id: str):
    customer = db.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found.")
    return customer


@router.patch(
    "/{customer_id}",
    response_model=Customer,
    summary="Update customer billing information",
    description="Update writable billing fields for an existing Acumatica customer record.",
    responses={404: {"model": ErrorResponse, "description": "Customer not found"}}
)
def update_customer_billing_info(customer_id: str, body: UpdateCustomerBillingRequest):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one billing field to update."
        )

    customer = db.update_customer_billing_info(customer_id, updates)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found.")
    return customer
