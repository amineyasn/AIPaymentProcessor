"""
Pydantic models for the Acumatica Payment Simulation API.
All models include field-level descriptions for OpenAPI / Copilot Studio discovery.
"""

from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class PaymentMethod(str, Enum):
    ACH_PNC    = "ACH/Wire (PNC)"
    ACH_TRUIST = "ACH/Wire (Truist)"
    CHECK      = "Check"


class PaymentStatus(str, Enum):
    PENDING   = "Pending"
    OPEN      = "Open"
    RELEASED  = "Released"
    VOIDED    = "Voided"


class InvoiceStatus(str, Enum):
    OPEN      = "Open"
    CLOSED    = "Closed"
    VOIDED    = "Voided"
    ON_HOLD   = "On Hold"


class DocumentType(str, Enum):
    INVOICE      = "INV"
    CREDIT_MEMO  = "CRM"
    DEBIT_MEMO   = "DRM"


# ─────────────────────────────────────────────
# Customer
# ─────────────────────────────────────────────

class Customer(BaseModel):
    customer_id:           str           = Field(..., description="Acumatica Customer ID (e.g. OXBLUE001)", example="OXBLUE001")
    customer_name:         str           = Field(..., description="Full legal name of the customer", example="OxBlue Corporation")
    email:                 str           = Field(..., description="Primary billing email", example="ar@oxblue.com")
    billing_contact_name:  Optional[str] = Field(None, description="Primary billing contact name", example="Jamie Lee")
    billing_phone:         Optional[str] = Field(None, description="Primary billing contact phone number", example="555-0100")
    billing_address_line1: Optional[str] = Field(None, description="Billing street address line 1", example="123 Main St")
    billing_address_line2: Optional[str] = Field(None, description="Billing street address line 2", example="Suite 400")
    billing_city:          Optional[str] = Field(None, description="Billing city", example="Atlanta")
    billing_state:         Optional[str] = Field(None, description="Billing state or province", example="GA")
    billing_postal_code:   Optional[str] = Field(None, description="Billing postal code", example="30303")

    model_config = {"json_schema_extra": {"example": {
        "customer_id": "OXBLUE001",
        "customer_name": "OxBlue Corporation",
        "email": "ar@oxblue.com",
        "billing_contact_name": "Jamie Lee",
        "billing_phone": "555-0100",
        "billing_address_line1": "123 Main St",
        "billing_address_line2": "Suite 400",
        "billing_city": "Atlanta",
        "billing_state": "GA",
        "billing_postal_code": "30303"
    }}}


class UpdateCustomerBillingRequest(BaseModel):
    email:                 Optional[str] = Field(None, description="Updated primary billing email", example="billing@oxblue.com")
    billing_contact_name:  Optional[str] = Field(None, description="Updated primary billing contact name", example="Jamie Lee")
    billing_phone:         Optional[str] = Field(None, description="Updated primary billing contact phone number", example="555-0100")
    billing_address_line1: Optional[str] = Field(None, description="Updated billing street address line 1", example="123 Main St")
    billing_address_line2: Optional[str] = Field(None, description="Updated billing street address line 2", example="Suite 400")
    billing_city:          Optional[str] = Field(None, description="Updated billing city", example="Atlanta")
    billing_state:         Optional[str] = Field(None, description="Updated billing state or province", example="GA")
    billing_postal_code:   Optional[str] = Field(None, description="Updated billing postal code", example="30303")

    model_config = {"json_schema_extra": {"example": {
        "email": "billing@oxblue.com",
        "billing_contact_name": "Jamie Lee",
        "billing_phone": "555-0100",
        "billing_address_line1": "123 Main St",
        "billing_address_line2": "Suite 400",
        "billing_city": "Atlanta",
        "billing_state": "GA",
        "billing_postal_code": "30303"
    }}}


# ─────────────────────────────────────────────
# Invoice
# ─────────────────────────────────────────────

class Invoice(BaseModel):
    reference_nbr:    str            = Field(..., description="Unique invoice reference number", example="607535")
    customer_id:      str            = Field(..., description="Customer ID linked to this invoice", example="OXBLUE001")
    customer_name:    str            = Field(..., description="Customer display name", example="OxBlue Corporation")
    document_type:    DocumentType   = Field(DocumentType.INVOICE, description="Document type code")
    status:           InvoiceStatus  = Field(..., description="Current invoice status")
    doc_date:         date           = Field(..., description="Invoice date", example="2026-03-01")
    due_date:         date           = Field(..., description="Payment due date", example="2026-04-01")
    amount_due:       float          = Field(..., description="Original invoice amount (USD)", example=649.00)
    balance_due:      float          = Field(..., description="Remaining unpaid balance (USD)", example=649.00)
    description:      Optional[str]  = Field(None, description="Invoice description or project name")


class InvoiceListResponse(BaseModel):
    invoices: List[Invoice]
    total:    int = Field(..., description="Total number of matching invoices")


# ─────────────────────────────────────────────
# Payment — request bodies
# ─────────────────────────────────────────────

class InvoiceApplication(BaseModel):
    """A single invoice to apply against a payment."""
    reference_nbr:    str   = Field(..., description="Invoice reference number to apply", example="607535")
    amount_to_apply:  float = Field(..., description="Dollar amount to apply from this payment to this invoice", example=649.00)


class CreatePaymentRequest(BaseModel):
    """
    Request body to create a new payment record in Acumatica.
    Mirrors the fields filled on the Payment screen (Method 1 or Method 2).
    """
    customer_id:      str                    = Field(..., description="Acumatica Customer ID", example="OXBLUE001")
    payment_amount:   float                  = Field(..., description="Total payment amount in USD. For multiple invoices enter the combined total.", example=649.00)
    payment_method:   PaymentMethod          = Field(..., description="Payment method — must match the Cash Account selected", example="ACH/Wire (PNC)")
    cash_account:     str                    = Field(..., description="Acumatica Cash Account code (e.g. 10200PNC, 10200TRU, 10200CHK)", example="10200PNC")
    application_date: date                   = Field(..., description="Date the payment was received. If not on remittance, use the email date.", example="2026-04-02")
    payment_ref:      str                    = Field(..., description="Payment reference from client remittance. Use invoice number if client reference cannot be copy-pasted.", example="607535")
    invoices_to_apply: List[InvoiceApplication] = Field(..., description="One or more invoices this payment should be applied to")
    notes:            Optional[str]          = Field(None, description="Optional internal notes about this payment")

    model_config = {"json_schema_extra": {"example": {
        "customer_id": "OXBLUE001",
        "payment_amount": 649.00,
        "payment_method": "ACH/Wire (PNC)",
        "cash_account": "10200PNC",
        "application_date": "2026-04-02",
        "payment_ref": "607535",
        "invoices_to_apply": [
            {"reference_nbr": "607535", "amount_to_apply": 649.00}
        ],
        "notes": "Single invoice payment from emailed PDF"
    }}}


# ─────────────────────────────────────────────
# Payment — response
# ─────────────────────────────────────────────

class AppliedInvoice(BaseModel):
    reference_nbr:   str   = Field(..., description="Invoice reference number")
    amount_applied:  float = Field(..., description="Amount applied from this payment")
    remaining_balance: float = Field(..., description="Invoice balance remaining after this payment")


class Payment(BaseModel):
    payment_id:       str            = Field(..., description="Internal payment UUID", example="PMT-2026-00042")
    reference_nbr:    str            = Field(..., description="Acumatica payment reference number", example="AR007823")
    customer_id:      str            = Field(..., description="Customer ID", example="OXBLUE001")
    customer_name:    str            = Field(..., description="Customer display name", example="OxBlue Corporation")
    payment_amount:   float          = Field(..., description="Total payment amount in USD")
    payment_method:   PaymentMethod  = Field(..., description="Payment method used")
    cash_account:     str            = Field(..., description="Cash account code")
    application_date: date           = Field(..., description="Date of payment application")
    payment_ref:      str            = Field(..., description="Client-provided payment reference")
    status:           PaymentStatus  = Field(..., description="Current payment status")
    applied_invoices: List[AppliedInvoice] = Field(..., description="Invoices this payment has been applied to")
    created_at:       datetime       = Field(..., description="Timestamp when payment record was created")
    released_at:      Optional[datetime] = Field(None, description="Timestamp when payment was released (None if not yet released)")
    notes:            Optional[str]  = Field(None, description="Internal notes")


class PaymentListResponse(BaseModel):
    payments: List[Payment]
    total:    int


# ─────────────────────────────────────────────
# AI Extraction — PDF / email parsing
# ─────────────────────────────────────────────

class ExtractedPaymentData(BaseModel):
    """
    Structured payment data extracted from a remittance PDF or email by the AI agent.
    Confidence scores help the caller decide whether to auto-apply or request human review.
    """
    customer_name:     Optional[str]        = Field(None, description="Customer name found in the document", example="LeChase Construction Services, LLC")
    customer_id:       Optional[str]        = Field(None, description="Matched Acumatica Customer ID (if found)", example="LECHASE001")
    invoice_numbers:   List[str]            = Field(default_factory=list, description="All invoice numbers detected", example=["607535"])
    payment_amounts:   List[float]          = Field(default_factory=list, description="Per-invoice amounts (same order as invoice_numbers)", example=[649.00])
    total_amount:      Optional[float]      = Field(None, description="Total payment amount", example=649.00)
    payment_date:      Optional[str]        = Field(None, description="Payment date as found in document (ISO 8601 preferred)", example="2026-04-02")
    payment_method:    Optional[str]        = Field(None, description="Payment method detected (ACH, Wire, Check, etc.)", example="ACH")
    payment_reference: Optional[str]        = Field(None, description="Client payment reference or check number", example="607535")
    confidence:        float                = Field(..., description="AI confidence score 0.0–1.0. Below 0.75 triggers human review.", example=0.95)
    needs_review:      bool                 = Field(..., description="True when confidence < 0.75 or required fields are missing")
    raw_text_excerpt:  Optional[str]        = Field(None, description="Short excerpt from the document used for extraction")
    extraction_notes:  Optional[str]        = Field(None, description="Any caveats or ambiguities the AI flagged during extraction")


class ExtractionResponse(BaseModel):
    extraction_id:  str                  = Field(..., description="Unique ID for this extraction job")
    extracted_data: ExtractedPaymentData = Field(..., description="The structured data extracted from the document")
    suggested_payload: Optional[CreatePaymentRequest] = Field(None, description="A pre-filled CreatePaymentRequest ready to POST to /payments if needs_review is False")


# ─────────────────────────────────────────────
# Agent — conversational endpoint
# ─────────────────────────────────────────────

class AgentMessage(BaseModel):
    role:    str = Field(..., description="'user' or 'assistant'", example="user")
    content: str = Field(..., description="Message text", example="Process the attached remittance for invoice 607535")


class AgentRequest(BaseModel):
    """
    Conversational agent request. Accepts a message and an optional base64-encoded PDF.
    The agent will extract payment data, validate against Acumatica, and execute if approved.
    """
    message:         str              = Field(..., description="Natural language instruction from the user", example="Process this remittance and enter the payment in Acumatica")
    pdf_base64:      Optional[str]    = Field(None, description="Base64-encoded PDF attachment (remittance advice)")
    conversation_id: Optional[str]    = Field(None, description="Session ID to maintain multi-turn context")
    auto_release:    bool             = Field(False, description="If True, release the payment immediately after creation. Default False requires explicit release.")
    history:         List[AgentMessage] = Field(default_factory=list, description="Prior conversation turns for multi-turn context")


class AgentResponse(BaseModel):
    conversation_id:   str                        = Field(..., description="Session ID for follow-up turns")
    message:           str                        = Field(..., description="Agent's natural language response")
    extracted_data:    Optional[ExtractedPaymentData] = Field(None, description="Payment data extracted from the PDF (if any)")
    payment_created:   Optional[Payment]          = Field(None, description="Payment record created in Acumatica (if action was taken)")
    payment_released:  bool                       = Field(False, description="True if the payment was also released")
    action_taken:      str                        = Field(..., description="Summary of what the agent did: 'extracted_only' | 'created_payment' | 'created_and_released' | 'needs_review' | 'error'")
    next_steps:        List[str]                  = Field(default_factory=list, description="Suggested follow-up actions for the user")


# ─────────────────────────────────────────────
# Generic responses
# ─────────────────────────────────────────────

class ReleasePaymentResponse(BaseModel):
    payment_id:   str            = Field(..., description="Payment ID that was released")
    reference_nbr: str           = Field(..., description="Acumatica payment reference number")
    status:        PaymentStatus = Field(..., description="New status after release — should be 'Released'")
    released_at:   datetime      = Field(..., description="Timestamp of release")
    message:       str           = Field(..., description="Human-readable confirmation message")


class ErrorResponse(BaseModel):
    error:   str = Field(..., description="Error type / code")
    detail:  str = Field(..., description="Human-readable error message")
    field:   Optional[str] = Field(None, description="Specific field that caused the error, if applicable")
