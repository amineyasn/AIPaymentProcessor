import os

from fastapi.testclient import TestClient

import database as db

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from main import app


client = TestClient(app)


def test_update_customer_billing_email():
    customer_id = "OXBLUE001"
    original_customer = db.CUSTOMERS[customer_id]
    payload = {
        "email": "billing@oxblue.com",
        "billing_contact_name": "Jamie Lee",
        "billing_phone": "555-0110",
        "billing_address_line1": "500 Billing Ave",
        "billing_city": "Atlanta",
        "billing_state": "GA",
        "billing_postal_code": "30309",
    }

    try:
        response = client.patch(
            f"/customers/{customer_id}",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["customer_id"] == customer_id
        for field, expected in payload.items():
            assert body[field] == expected
            assert getattr(db.CUSTOMERS[customer_id], field) == expected
        assert body["billing_address_line2"] == original_customer.billing_address_line2
    finally:
        db.CUSTOMERS[customer_id] = original_customer