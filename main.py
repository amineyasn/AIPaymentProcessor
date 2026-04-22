"""
Acumatica Payment Simulation API
─────────────────────────────────
A FastAPI-based REST API that simulates Acumatica's Accounts Receivable payment workflow.
Includes an AI agent (Claude claude-sonnet-4-20250514) for extracting payment data from remittance PDFs.

OpenAPI-compliant — ready for Microsoft Copilot Studio custom connector import.

Endpoints:
  GET  /customers              — Search / list customers
  GET  /customers/{id}         — Get customer by ID
    PATCH /customers/{id}         — Update customer billing information
  GET  /invoices               — Search / list invoices
  GET  /invoices/{ref}         — Get invoice by reference number
  POST /payments               — Create a payment
  GET  /payments               — List payments
  GET  /payments/{id}          — Get payment by ID
  POST /payments/{id}/release  — Release a payment
  POST /extract                — AI: extract payment data from PDF
  POST /agent                  — AI: conversational payment agent
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from config import settings

from invoices  import router as invoices_router
from payments  import router as payments_router
from customers import router as customers_router
from agent     import router as agent_router


logger = logging.getLogger(__name__)

# Show application logs from route modules (e.g., agent.py) in the same terminal as Uvicorn.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


# ─────────────────────────────────────────────
# App instance
# ─────────────────────────────────────────────

app = FastAPI(
    title="Acumatica Payment Simulation API",
    description=(
        "Simulates Acumatica's Accounts Receivable payment entry workflow. "
        "Includes an AI agent (Claude) for extracting payment data from PDF remittance documents. "
        "Designed to be consumed by Microsoft Copilot Studio as a custom OpenAPI connector.\n\n"
        "## Workflow\n"
        "1. **Extract** — POST a remittance PDF to `/extract` → get structured payment fields\n"
        "2. **Validate** — GET `/invoices/{ref}` to confirm invoices are Open\n"
        "3. **Create** — POST to `/payments` with customer, amount, method, and invoice references\n"
        "4. **Release** — POST to `/payments/{id}/release` to finalize\n"
        "5. **Update Customer** — PATCH `/customers/{customer_id}` to update billing email/contact/phone/address\n\n"
        "## Conversational shortcut\n"
        "POST to `/agent` with a message and a base64 PDF to let the AI handle the payment-processing steps.\n\n"
        "## Authentication\n"
        "Set `ANTHROPIC_API_KEY` in your environment. Production deployments should add "
        "Azure API Management or OAuth2 in front of this service."
    ),
    version="1.0.0",
    contact={
        "name": "CiberSQL LLC",
        "url": "https://cibersql.com",
        "email": "info@cibersql.com"
    },
    license_info={
        "name": "Proprietary — CiberSQL LLC"
    },
    openapi_tags=[
        {
            "name": "Customers",
            "description": "Look up and update Acumatica customer billing records."
        },
        {
            "name": "Invoices",
            "description": (
                "Read-only access to Acumatica invoice records. "
                "Mirrors the **Receivables → Invoices and Memos** screen."
            )
        },
        {
            "name": "Payments",
            "description": (
                "Create, list, retrieve, and release payment records. "
                "Mirrors both **Method 1** (Pay from Invoice) and "
                "**Method 2** (New Payment from Receivables menu) workflows."
            )
        },
        {
            "name": "AI Agent",
            "description": (
                "AI-powered endpoints using Claude claude-sonnet-4-20250514. "
                "`/extract` parses a PDF remittance into structured fields. "
                "`/agent` is a conversational interface that handles the full "
                "extract → validate → create → release pipeline."
            )
        }
    ]
)

# ─────────────────────────────────────────────
# Observability — Azure Application Insights (OpenTelemetry)
# ─────────────────────────────────────────────

if settings.applicationinsights_connection_string.strip():
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string.strip()
        )
        FastAPIInstrumentor.instrument_app(app)
    except Exception as ex:
        logger.warning("Application Insights instrumentation was not enabled: %s", ex)

# ─────────────────────────────────────────────
# CORS — allow Copilot Studio + local dev
# ─────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# Register routers
# ─────────────────────────────────────────────

app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(payments_router)
app.include_router(agent_router)


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────

@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Returns service status. Use this as the Copilot Studio connector health probe."
)
def health():
    return {
        "status": "ok",
        "service": "Acumatica Payment Simulation API",
        "version": "1.0.0",
        "environment": settings.app_env,
        "anthropic_key_set": bool(settings.anthropic_api_key)
    }


# ─────────────────────────────────────────────
# OpenAPI schema — custom override for Copilot Studio
# (Copilot Studio requires operationId on every endpoint)
# ─────────────────────────────────────────────

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )

    # Ensure OpenAPI always includes at least one server entry.
    schema["servers"] = settings.openapi_servers

    # Copilot Studio requires unique operationId for every path+method
    op_id_map = {
        ("get",  "/customers"):                   "listCustomers",
        ("get",  "/customers/{customer_id}"):     "getCustomer",
        ("patch", "/customers/{customer_id}"):    "updateCustomerBillingInfo",
        ("get",  "/invoices"):                    "listInvoices",
        ("get",  "/invoices/{reference_nbr}"):    "getInvoice",
        ("post", "/payments"):                    "createPayment",
        ("get",  "/payments"):                    "listPayments",
        ("get",  "/payments/{payment_id}"):       "getPayment",
        ("post", "/payments/{payment_id}/release"): "releasePayment",
        ("post", "/extract"):                     "extractPdf",
        ("post", "/agent"):                       "agentChat",
        ("get",  "/health"):                      "healthCheck",
    }

    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            key = (method, path)
            if key in op_id_map:
                operation["operationId"] = op_id_map[key]

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
