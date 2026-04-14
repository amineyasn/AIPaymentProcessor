from aipaymentprocessor.core import process_payment


def test_process_payment():
    res = process_payment(10, "USD")
    assert res["status"] == "success"
    assert res["amount"] == 10
    assert res["currency"] == "USD"
