"""
PayGate Python SDK — USDT BEP20 payment gateway client.

Quick start::

    from paygate import PayGateClient, verify_webhook, WebhookVerificationError

    client = PayGateClient(
        base_url="http://localhost:9000",
        api_key="your-api-key",
    )

    # Create an invoice
    invoice = client.create_payment("29.99", external_id="order-123")
    print(invoice.deposit_address)
    print(invoice.expires_at)

    # Check status
    invoice = client.get_payment(invoice.invoice_id)
    if invoice.is_paid():
        fulfil_order()

    # Verify incoming webhook (Flask example)
    @app.post("/webhook")
    def webhook():
        try:
            verify_webhook(
                request.get_data(),
                request.headers["X-PayGate-Signature"],
                request.headers["X-PayGate-Timestamp"],
                api_key=os.environ["PAYGATE_API_KEY"],
            )
        except WebhookVerificationError:
            abort(400)
        # handle request.get_json()["status"] == "PAID"
        return "", 202
"""

from .client import PayGateClient
from .exceptions import PayGateError, PaymentNotFound, WebhookVerificationError
from .models import Invoice, Transaction
from .webhook import compact_json_bytes, verify_webhook

__all__ = [
    "PayGateClient",
    "Invoice",
    "Transaction",
    "PayGateError",
    "PaymentNotFound",
    "WebhookVerificationError",
    "verify_webhook",
    "compact_json_bytes",
]

__version__ = "0.1.0"
