# paygate-python

Official Python SDK for the [openbcp](https://github.com/usdt-paygate/paygate-python) USDT BEP20 payment gateway.

## Installation

```bash
pip install git+https://github.com/usdt-paygate/paygate-python.git
```

## Quick Start

```python
from paygate import PayGateClient

client = PayGateClient(
    base_url="https://openbcp.com",   # hosted gateway
    api_key="your-api-key",           # from the dashboard → Integration
)

# 1. Create a payment invoice — redirect customer to payment_url
invoice = client.create_payment(
    "29.99",
    external_id="order-123",
    callback_url="https://yoursite.com/webhooks/openbcp",
)

print(invoice.invoice_id)       # 42
print(invoice.payment_url)      # https://openbcp.com/pay/<token>  ← redirect here
print(invoice.deposit_address)  # 0x4a7b...
print(invoice.amount_usdt)      # Decimal('29.99')
print(invoice.expires_at)       # datetime(2026, 6, 8, 12, 0, tzinfo=UTC)

# 2. Check status (server-side)
invoice = client.get_payment(invoice.invoice_id)
print(invoice.payment_status)   # "UNPAID" | "PARTIAL" | "PAID" | "OVERPAID" | "EXPIRED"
print(invoice.is_paid())        # True / False

# 3. Block until paid (CLI tools, scripts)
paid = client.poll_until_paid(invoice.invoice_id, timeout=900)
print("Received", paid.total_confirmed, "USDT")
```

## Context Manager

```python
with PayGateClient(base_url=..., api_key=...) as client:
    invoice = client.create_payment("10.00")
    # session is automatically closed on exit
```

## Webhook Verification

Webhooks are signed with `HMAC-SHA256` over `"{timestamp}.{raw_body}"` using your API key.
Both the `X-openbcp-Signature` and `X-openbcp-Timestamp` headers must be present and verified.

```python
from paygate import verify_webhook, WebhookVerificationError

# Flask
@app.post("/webhooks/openbcp")
def webhook():
    try:
        verify_webhook(
            request.get_data(),                            # raw bytes — do NOT decode first
            request.headers["X-openbcp-Signature"],
            request.headers["X-openbcp-Timestamp"],
            api_key=os.environ["PAYGATE_API_KEY"],
        )
    except WebhookVerificationError as exc:
        app.logger.warning("Bad webhook: %s", exc)
        abort(400)

    data = request.get_json()
    if data["status"] in ("PAID", "OVERPAID"):
        fulfil_order(data["external_id"])
    return "", 202
```

> **Important:** always pass the raw request body (`request.get_data()` in Flask,
> `await request.body()` in FastAPI) — not a re-serialised dict. The HMAC is
> computed over the exact bytes sent by openbcp.

## API Reference

### `PayGateClient(base_url, api_key, *, timeout=20, session=None)`

| Method | Description |
|--------|-------------|
| `create_payment(amount_usdt, *, external_id, callback_url, metadata, amount_fiat, fiat_currency)` | Create an invoice → `Invoice` |
| `get_payment(invoice_id)` | Full invoice with transactions (auth required) → `Invoice` |
| `get_payment_status(invoice_id)` | Quick public status check (no auth) → `Invoice` |
| `poll_until_paid(invoice_id, *, poll_interval=5, timeout=3600, include_partial=False)` | Block until paid → `Invoice` |
| `close()` | Close the HTTP session |

### `Invoice`

| Field | Type | Notes |
|-------|------|-------|
| `invoice_id` | `int` | |
| `payment_url` | `str` | Hosted checkout URL — redirect the customer here |
| `deposit_address` | `str` | BEP20 address to send USDT to |
| `amount_usdt` | `Decimal` | Exact amount expected (merchant amount + platform fee) |
| `payment_status` | `str` | `UNPAID` / `PARTIAL` / `PAID` / `OVERPAID` / `EXPIRED` |
| `expires_at` | `datetime` | UTC-aware |
| `transactions` | `list[Transaction]` | |
| `external_id` | `str \| None` | Your order reference |
| `created_at` | `datetime \| None` | |
| `is_paid()` | `bool` | `True` if PAID or OVERPAID |
| `is_expired()` | `bool` | |
| `total_confirmed` | `Decimal` | Sum of confirmed tx amounts |

### `verify_webhook(payload, signature, timestamp, api_key, *, max_age_sec=300)`

Returns `True` or raises `WebhookVerificationError`.

## Exceptions

| Exception | When |
|-----------|------|
| `PayGateError` | Base class — API errors, network errors |
| `PaymentNotFound` | 404 from `get_payment` |
| `WebhookVerificationError` | Invalid signature or expired timestamp |

All exceptions expose `.status_code` and `.response_body` attributes.
