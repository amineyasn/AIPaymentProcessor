"""
AI Agent routes — PDF extraction and conversational payment processing.

POST /extract    — Upload a PDF remittance, get back structured payment data
POST /agent      — Conversational agent: understands natural language, extracts PDF,
                   validates invoices, creates and optionally releases the payment.
"""

import base64
import json
import logging
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
    AgentRequest, AgentResponse, AgentMessage
)

router = APIRouter(tags=["AI Agent"])
logger = logging.getLogger(__name__)

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

Important consistency rule:
- If extracted payment data is present in context, do NOT claim the PDF is missing or ask the user to attach a PDF.
""".strip()


def _claims_missing_pdf(message: str) -> bool:
    m = message.lower()
    phrases = [
        "don't see any pdf",
        "do not see any pdf",
        "no pdf",
        "missing pdf",
        "attach the remittance",
        "attach the pdf",
        "provide the pdf",
    ]
    return any(p in m for p in phrases)


def _build_fallback_message(
    extracted_data: Optional[ExtractedPaymentData],
    action_taken: str,
    payment_error: Optional[str],
    next_steps: list[str],
) -> str:
    if not extracted_data:
        return "I did not receive a remittance PDF to process. Please attach a PDF and try again."

    invoices = ", ".join(extracted_data.invoice_numbers) if extracted_data.invoice_numbers else "none found"
    total = f"${(extracted_data.total_amount or 0):,.2f}"
    summary = (
        f"I parsed the attached PDF and extracted: customer {extracted_data.customer_name or 'unknown'}, "
        f"invoices {invoices}, total {total}, and confidence {extracted_data.confidence:.0%}."
    )

    if action_taken == "needs_review":
        steps = " ".join(next_steps) if next_steps else "Please review extracted fields before creating the payment."
        return f"{summary} The remittance requires review before posting. {steps}"

    if action_taken == "error":
        err = payment_error or "An unexpected error occurred while creating the payment."
        return f"{summary} I could not complete payment creation: {err}"

    return summary


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
    logger.info("/extract called filename=%s has_email_subject=%s has_email_body=%s", file.filename, bool(email_subject), bool(email_body))

    if not file.filename.lower().endswith(".pdf"):
        logger.warning("/extract rejected non-pdf filename=%s", file.filename)
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
        logger.exception("/extract failed to parse AI response")
        raise HTTPException(status_code=500, detail=f"AI returned unparseable response: {str(e)}")

    extracted = ExtractedPaymentData(**data)
    logger.info(
        "/extract parsed confidence=%.2f needs_review=%s invoices=%d customer=%s",
        extracted.confidence,
        extracted.needs_review,
        len(extracted.invoice_numbers),
        extracted.customer_name,
    )

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
            logger.exception("/extract failed to build suggested payload")
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

    logger.info(
        "/agent called conversation_id=%s has_pdf=%s auto_release=%s history_items=%d",
        conversation_id,
        bool(body.pdf_base64),
        body.auto_release,
        len(body.history),
    )
    if body.pdf_base64:
        logger.info(
            "/agent pdf payload length=%d prefix=%s",
            len(body.pdf_base64),
            body.pdf_base64[:24],
        )

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
            logger.info(
                "/agent extraction success confidence=%.2f needs_review=%s invoices=%d customer=%s",
                extracted_data.confidence,
                extracted_data.needs_review,
                len(extracted_data.invoice_numbers),
                extracted_data.customer_name,
            )

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
            logger.exception("/agent extraction failed")
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
            logger.info("/agent payment created payment_id=%s reference=%s", payment.payment_id, payment.reference_nbr)

            if body.auto_release:
                released = db.release_payment(payment.payment_id)
                if released:
                    payment = released
                    payment_released = True
                    action_taken = "created_and_released"
                    logger.info("/agent payment released payment_id=%s reference=%s", payment.payment_id, payment.reference_nbr)
                    next_steps.append("Payment is fully released and posted to the ledger.")
                    next_steps.append(f"Reference number: {payment.reference_nbr}")
                else:
                    logger.warning("/agent release requested but payment release failed payment_id=%s", payment.payment_id)
                    next_steps.append("Payment created but release failed — release manually in Acumatica.")
            else:
                next_steps.append(f"Call POST /payments/{payment.payment_id}/release to release the payment.")
                next_steps.append(f"Or ask: 'Release payment {payment.payment_id}'")

        except HTTPException as e:
            payment_error = e.detail
            action_taken = "error"
            logger.exception("/agent payment creation HTTP error")
            next_steps.append(f"Error: {payment_error}")
        except Exception as e:
            payment_error = str(e)
            action_taken = "error"
            logger.exception("/agent payment creation unexpected error")

    elif extracted_data and extracted_data.needs_review:
        action_taken = "needs_review"
        logger.info("/agent routed to manual review")
        if not extracted_data.customer_id:
            next_steps.append("Customer could not be matched — provide the Acumatica Customer ID.")
        if not extracted_data.invoice_numbers:
            next_steps.append("No invoice numbers detected — verify the PDF or enter manually.")
        if not extracted_data.payment_date:
            next_steps.append("Payment date not found — use the email date.")
        next_steps.append("Review the extracted data and POST to /payments manually.")

    elif body.pdf_base64 is None and extracted_data is None:
        action_taken = "extracted_only"
        logger.info("/agent no pdf provided")
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

    # Guardrail: if extraction succeeded, never return a contradictory "missing PDF" message.
    if extracted_data and _claims_missing_pdf(agent_message):
        logger.warning("/agent model response contradicted extraction; applying fallback message")
        agent_message = _build_fallback_message(
            extracted_data=extracted_data,
            action_taken=action_taken,
            payment_error=payment_error,
            next_steps=next_steps,
        )

    logger.info("/agent completed action_taken=%s payment_released=%s", action_taken, payment_released)

    return AgentResponse(
        conversation_id=conversation_id,
        message=agent_message,
        extracted_data=extracted_data,
        payment_created=payment,
        payment_created_text=payment.reference_nbr if payment else "",
        payment_released=payment_released,
        action_taken=action_taken,
        next_steps=next_steps
    )


@router.post(
    "/agent/upload",
    response_model=AgentResponse,
    summary="Conversational AI payment agent (multipart upload)",
    description=(
        "Alternative to POST /agent for clients that cannot provide pdf_base64 directly. "
        "Accepts a multipart PDF file and converts it to base64 server-side before processing."
    ),
    tags=["AI Agent"],
    include_in_schema=False,
)
async def agent_upload(
    message: Optional[str] = Form(None, description="Natural language instruction from the user"),
    file: Optional[UploadFile] = File(None, description="PDF remittance document"),
    pdf_base64: Optional[str] = Form(None, description="Optional base64 PDF payload for clients that cannot send multipart file parts"),
    conversation_id: Optional[str] = Form(None, description="Session ID to maintain multi-turn context"),
    auto_release: Optional[str] = Form(None, description="If True, release payment immediately after creation"),
    history: Optional[str] = Form(None, description="Optional JSON array of prior messages: [{\"role\":\"user\",\"content\":\"...\"}]"),
):
    logger.info(
        "/agent/upload called filename=%s has_conversation_id=%s auto_release=%s",
        file.filename if file else None,
        bool(conversation_id),
        auto_release,
    )

    if not (message or "").strip():
        logger.warning("/agent/upload missing message")
        raise HTTPException(status_code=400, detail="Form field 'message' is required.")

    auto_release_value = str(auto_release or "").strip().lower() in {"1", "true", "yes", "y"}

    if file is None and not pdf_base64:
        logger.warning("/agent/upload missing both file and pdf_base64")
        raise HTTPException(
            status_code=400,
            detail="Provide either multipart field 'file' or form field 'pdf_base64'.",
        )

    normalized_pdf_base64: Optional[str] = None

    if file is not None:
        if file.filename and not file.filename.lower().endswith(".pdf"):
            logger.warning("/agent/upload rejected non-pdf filename=%s", file.filename)
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")

        pdf_bytes = await file.read()
        if not pdf_bytes:
            logger.warning("/agent/upload received empty file")
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        normalized_pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    else:
        s = (pdf_base64 or "").strip()
        if "," in s and s.lower().startswith("data:"):
            s = s.split(",", 1)[1].strip()
        if not s:
            logger.warning("/agent/upload received blank pdf_base64")
            raise HTTPException(status_code=400, detail="Form field 'pdf_base64' was provided but empty.")
        normalized_pdf_base64 = s

    parsed_history = []
    if history:
        try:
            raw_history = json.loads(history)
            if isinstance(raw_history, dict):
                raw_history = [raw_history]
            if isinstance(raw_history, list):
                parsed_history = [AgentMessage(**m) for m in raw_history if isinstance(m, dict)]
            else:
                logger.warning("/agent/upload history JSON was not a list or object; ignoring history")
        except Exception:
            logger.warning("/agent/upload received invalid history JSON; ignoring history")

    body = AgentRequest(
        message=message.strip(),
        pdf_base64=normalized_pdf_base64,
        conversation_id=conversation_id,
        auto_release=auto_release_value,
        history=parsed_history,
    )
    return await agent(body)
