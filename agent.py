"""
AI Agent routes — PDF extraction and conversational payment processing.

POST /extract    — Upload a PDF remittance, get back structured payment data
POST /agent      — Conversational agent: understands natural language, extracts PDF,
                   validates invoices, creates and optionally releases the payment.
"""

import base64
import json
import uuid
from datetime import datetime, date
from typing import Optional

import anthropic
from fastapi import APIRouter, HTTPException, File, Form, UploadFile

import database as db
from config import settings
from models import (
    ExtractedPaymentData, ExtractionResponse,
    CreatePaymentRequest, InvoiceApplication, PaymentMethod,
    AgentRequest, AgentResponse
)

router = APIRouter(tags=["AI Agent"])

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

EXTRACTION_SYSTEM_PROMPT = """
You are a remittance parsing specialist for an accounts receivable team.
Your job is to extract structured payment data from PDF remittance advice documents and emails.

You MUST return ONLY valid JSON — no markdown fences, no explanation, no preamble.
Return exactly this structure:

{
  "customer_name": "<string or null>",
  "invoice_numbers": ["<string>", ...],
  "payment_amounts": [<float>, ...],
  "total_amount": <float or null>,
  "payment_date": "<YYYY-MM-DD or null>",
  "payment_method": "<ACH|Wire|Check|null>",
  "payment_reference": "<string or null>",
  "confidence": <float 0.0-1.0>,
  "needs_review": <true|false>,
  "raw_text_excerpt": "<first 200 chars of extracted text>",
  "extraction_notes": "<any caveats or ambiguities, or null>"
}

Rules:
- invoice_numbers and payment_amounts arrays must be the same length and in the same order
- payment_date must be ISO 8601 (YYYY-MM-DD)
- confidence < 0.75 → set needs_review to true
- needs_review = true if any required field (customer_name, invoice_numbers, total_amount, payment_date) is null
- payment_method: map ACH/EFT/Wire → "ACH" or "Wire", paper check → "Check"
- payment_reference: prefer the client's unique reference number; use invoice number if that's clearest
""".strip()

AGENT_SYSTEM_PROMPT = """
You are an AI assistant for an accounts receivable team using Acumatica.
You help staff process remittance payments by:
1. Extracting payment data from PDF attachments
2. Validating invoices exist and are open
3. Creating payment records
4. Confirming actions taken

When responding:
- Be concise and professional
- Always confirm what you found and what action you took
- If something needs review, clearly explain what's missing or ambiguous
- Use dollar amounts formatted as $X,XXX.XX
- Reference invoice numbers explicitly

You have access to these capabilities:
- PDF/document parsing (when pdf_base64 is provided)
- Invoice validation against the Acumatica database
- Payment creation and release

Respond in plain conversational English. Do not use JSON in your response — the API wraps structured data separately.
""".strip()


def _parse_extraction(raw: str) -> dict:
    """Parse AI JSON response, stripping markdown fences if present."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return json.loads(cleaned)


def _map_payment_method(method_str: Optional[str]) -> PaymentMethod:
    if not method_str:
        return PaymentMethod.ACH_PNC
    s = method_str.lower()
    if "check" in s:
        return PaymentMethod.CHECK
    if "truist" in s:
        return PaymentMethod.ACH_TRUIST
    return PaymentMethod.ACH_PNC


def _map_cash_account(method: PaymentMethod) -> str:
    return {
        PaymentMethod.ACH_PNC:    "10200PNC",
        PaymentMethod.ACH_TRUIST: "10200TRU",
        PaymentMethod.CHECK:      "10200CHK",
    }[method]


# ─────────────────────────────────────────────
# Extraction endpoint
# ─────────────────────────────────────────────

@router.post(
    "/extract",
    response_model=ExtractionResponse,
    summary="Extract payment data from a PDF remittance",
    description=(
        "Upload a PDF remittance advice document. The AI (Claude claude-sonnet-4-20250514) will parse it and "
        "return structured payment fields including invoice numbers, amounts, date, customer name, "
        "and payment reference.\n\n"
        "If `needs_review` is **False** and confidence ≥ 0.75, the response also includes a "
        "`suggested_payload` ready to POST directly to `POST /payments`.\n\n"
        "Supports remittances with single or multiple invoices."
    ),
    tags=["AI Agent"]
)
async def extract_pdf(
    file: UploadFile = File(..., description="PDF remittance document"),
    email_subject: Optional[str] = Form(None, description="Email subject line (helps with date and customer detection)"),
    email_body: Optional[str] = Form(None, description="Email body text (used as fallback if PDF is sparse)")
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    pdf_bytes = await file.read()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    user_content = []

    if email_subject or email_body:
        context_text = ""
        if email_subject:
            context_text += f"Email subject: {email_subject}\n"
        if email_body:
            context_text += f"Email body:\n{email_body}\n\n"
        context_text += "Extract payment data from the attached PDF remittance:"
        user_content.append({"type": "text", "text": context_text})
    else:
        user_content.append({"type": "text", "text": "Extract payment data from this remittance PDF:"})

    user_content.append({
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": pdf_b64
        }
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}]
    )

    raw = response.content[0].text
    try:
        data = _parse_extraction(raw)
    except (json.JSONDecodeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=f"AI returned unparseable response: {str(e)}")

    extracted = ExtractedPaymentData(**data)

    # Try to match customer
    customer_id = None
    if extracted.customer_name:
        matches = db.search_customers(extracted.customer_name.split()[0])
        if matches:
            customer_id = matches[0].customer_id
            extracted.customer_id = customer_id

    # Build suggested payload if high confidence
    suggested = None
    if not extracted.needs_review and customer_id and extracted.invoice_numbers and extracted.total_amount:
        try:
            inv_apps = [
                InvoiceApplication(
                    reference_nbr=inv_num,
                    amount_to_apply=amt
                )
                for inv_num, amt in zip(extracted.invoice_numbers, extracted.payment_amounts)
            ]
            method = _map_payment_method(extracted.payment_method)
            suggested = CreatePaymentRequest(
                customer_id=customer_id,
                payment_amount=extracted.total_amount,
                payment_method=method,
                cash_account=_map_cash_account(method),
                application_date=date.fromisoformat(extracted.payment_date) if extracted.payment_date else date.today(),
                payment_ref=extracted.payment_reference or extracted.invoice_numbers[0],
                invoices_to_apply=inv_apps,
            )
        except Exception:
            pass  # Don't fail extraction if suggestion build fails

    return ExtractionResponse(
        extraction_id=f"EXT-{str(uuid.uuid4())[:8].upper()}",
        extracted_data=extracted,
        suggested_payload=suggested
    )


# ─────────────────────────────────────────────
# Conversational agent endpoint
# ─────────────────────────────────────────────

@router.post(
    "/agent",
    response_model=AgentResponse,
    summary="Conversational AI payment agent",
    description=(
        "A full conversational AI agent for processing remittance payments. "
        "Send a natural language message and an optional base64-encoded PDF. "
        "The agent will:\n"
        "1. Parse the PDF and extract payment fields\n"
        "2. Validate invoices against Acumatica\n"
        "3. Create the payment record\n"
        "4. Optionally release the payment if `auto_release=true`\n\n"
        "Supports multi-turn conversations via `conversation_id` and `history`.\n\n"
        "**Designed for Microsoft Copilot Studio** — returns structured `payment_created` and "
        "`extracted_data` fields alongside a plain-English `message`."
    ),
    tags=["AI Agent"]
)
async def agent(body: AgentRequest):
    conversation_id = body.conversation_id or f"CONV-{str(uuid.uuid4())[:8].upper()}"
    extracted_data = None
    payment = None
    payment_released = False
    action_taken = "needs_review"
    next_steps = []

    # Build the messages list for Claude
    messages = [{"role": m.role, "content": m.content} for m in body.history]

    # Build current user message content
    user_content = []

    # If a PDF was attached, extract first
    if body.pdf_base64:
        try:
            extraction_response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract payment data from this remittance PDF:"},
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": body.pdf_base64
                            }
                        }
                    ]
                }]
            )
            raw = extraction_response.content[0].text
            data = _parse_extraction(raw)
            extracted_data = ExtractedPaymentData(**data)

            # Enrich with customer match
            if extracted_data.customer_name:
                matches = db.search_customers(extracted_data.customer_name.split()[0])
                if matches:
                    extracted_data.customer_id = matches[0].customer_id

            # Summarise extraction for the conversation
            extraction_summary = (
                f"Extracted from PDF:\n"
                f"- Customer: {extracted_data.customer_name or 'unknown'}\n"
                f"- Invoices: {', '.join(extracted_data.invoice_numbers) or 'none found'}\n"
                f"- Total: ${extracted_data.total_amount or 0:,.2f}\n"
                f"- Date: {extracted_data.payment_date or 'unknown'}\n"
                f"- Method: {extracted_data.payment_method or 'unknown'}\n"
                f"- Reference: {extracted_data.payment_reference or 'unknown'}\n"
                f"- Confidence: {extracted_data.confidence:.0%}\n"
                f"- Needs review: {extracted_data.needs_review}"
            )
            user_content.append({"type": "text", "text": extraction_summary + "\n\nUser instruction: " + body.message})
        except Exception as e:
            user_content.append({"type": "text", "text": f"PDF extraction failed: {str(e)}\n\nUser instruction: {body.message}"})
    else:
        user_content.append({"type": "text", "text": body.message})

    # Attempt payment creation if we have enough data and extraction succeeded
    payment_error = None
    if extracted_data and not extracted_data.needs_review and extracted_data.customer_id:
        try:
            inv_apps = [
                InvoiceApplication(
                    reference_nbr=inv_num,
                    amount_to_apply=amt
                )
                for inv_num, amt in zip(extracted_data.invoice_numbers, extracted_data.payment_amounts)
            ]
            method = _map_payment_method(extracted_data.payment_method)
            pay_date = date.fromisoformat(extracted_data.payment_date) if extracted_data.payment_date else date.today()
            pay_ref = extracted_data.payment_reference or (extracted_data.invoice_numbers[0] if extracted_data.invoice_numbers else "NOREF")

            payment_req = CreatePaymentRequest(
                customer_id=extracted_data.customer_id,
                payment_amount=extracted_data.total_amount,
                payment_method=method,
                cash_account=_map_cash_account(method),
                application_date=pay_date,
                payment_ref=pay_ref,
                invoices_to_apply=inv_apps,
            )
            payment = db.create_payment(
                customer_id=payment_req.customer_id,
                payment_amount=payment_req.payment_amount,
                payment_method=payment_req.payment_method,
                cash_account=payment_req.cash_account,
                application_date=payment_req.application_date,
                payment_ref=payment_req.payment_ref,
                invoices_to_apply=payment_req.invoices_to_apply,
            )
            action_taken = "created_payment"

            if body.auto_release:
                released = db.release_payment(payment.payment_id)
                if released:
                    payment = released
                    payment_released = True
                    action_taken = "created_and_released"
                    next_steps.append("Payment is fully released and posted to the ledger.")
                    next_steps.append(f"Reference number: {payment.reference_nbr}")
                else:
                    next_steps.append("Payment created but release failed — release manually in Acumatica.")
            else:
                next_steps.append(f"Call POST /payments/{payment.payment_id}/release to release the payment.")
                next_steps.append(f"Or ask: 'Release payment {payment.payment_id}'")

        except HTTPException as e:
            payment_error = e.detail
            action_taken = "error"
            next_steps.append(f"Error: {payment_error}")
        except Exception as e:
            payment_error = str(e)
            action_taken = "error"

    elif extracted_data and extracted_data.needs_review:
        action_taken = "needs_review"
        if not extracted_data.customer_id:
            next_steps.append("Customer could not be matched — provide the Acumatica Customer ID.")
        if not extracted_data.invoice_numbers:
            next_steps.append("No invoice numbers detected — verify the PDF or enter manually.")
        if not extracted_data.payment_date:
            next_steps.append("Payment date not found — use the email date.")
        next_steps.append("Review the extracted data and POST to /payments manually.")

    elif body.pdf_base64 is None and extracted_data is None:
        action_taken = "extracted_only"
        next_steps.append("Attach a PDF remittance to process a payment.")

    # Build agent message context string
    context = f"""
User message: {body.message}
Action taken: {action_taken}
Payment created: {payment.reference_nbr if payment else 'None'}
Payment released: {payment_released}
Error: {payment_error or 'None'}
Extraction confidence: {extracted_data.confidence if extracted_data else 'N/A'}
Next steps: {', '.join(next_steps) if next_steps else 'None'}
""".strip()

    messages.append({"role": "user", "content": context})

    # Get the natural language response from Claude
    agent_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=AGENT_SYSTEM_PROMPT,
        messages=messages
    )
    agent_message = agent_response.content[0].text

    return AgentResponse(
        conversation_id=conversation_id,
        message=agent_message,
        extracted_data=extracted_data,
        payment_created=payment,
        payment_released=payment_released,
        action_taken=action_taken,
        next_steps=next_steps
    )
