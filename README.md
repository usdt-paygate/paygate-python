# paygate-python

Official Python SDK for the [openbcp](https://openbcp.com) USDT BEP20 payment gateway.

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
    success_url="https://yoursite.com/orders/123/success",
)

print(invoice.invoice_id)       # 42
print(invoice.payment_url)      # https://openbcp.com/pay/<token>  ← redirect here
print(invoice.deposit_address)  # 0x4a7b...
print(invoice.amount_usdt)      # Decimal('29.99')
print(invoice.expires_at)       # datetime(2026, 6, 8, 12, 0, tzinfo=UTC)

# 2. Check status (server-side)
invoice = client.get_payment(invoice.invoice_id)
print(invoice.payment_status)   # "UNPAID" | "PARTIAL" | "PAID" | "OVERPAID" | "EXPIRED" | "CANCELLED"
print(invoice.is_paid())        # True / False

# 3. Block until paid (CLI tools, scripts)
paid = client.poll_until_paid(invoice.invoice_id, timeout=900)
print("Received", paid.total_confirmed, "USDT")
```

## Partial & Overpaid Payment Fields

Every status response and webhook now includes amount fields so you can detect underpayment, overpayment, and partial-then-expired scenarios:

```python
invoice = client.get_payment_status(42)

print(invoice.amount_usdt)       # Decimal('5.000000')  ← expected
print(invoice.amount_received)   # Decimal('4.000000')  ← actually received
print(invoice.shortfall)         # Decimal('1.000000')  ← still needed
print(invoice.overpaid_by)       # Decimal('0.000000')  ← excess (0 when PARTIAL)

# Helper methods
invoice.is_paid()         # True for PAID or OVERPAID — safe to fulfil
invoice.is_partial()      # True for PARTIAL — payment incomplete, do NOT fulfil
invoice.is_expired()      # True for EXPIRED
invoice.is_cancelled()    # True for CANCELLED
invoice.is_pending()      # True while UNPAID or PARTIAL
invoice.needs_refund()    # True when EXPIRED/CANCELLED with funds received
```

## Resume Payment

When an invoice expires with a partial payment, the merchant can resume it instead of refunding — creating a continuation invoice for the shortfall that reuses the **same deposit address**:

```python
# Customer's invoice expired with 4/5 USDT paid
try:
    paid = client.poll_until_paid(invoice_id=42, timeout=900)
except PayGateError:
    # Expired — offer customer a chance to complete payment
    resumed = client.resume_payment(invoice_id=42)
    print(resumed['amount_usdt'])              # '1.000000' (just the shortfall)
    print(resumed['amount_already_received'])  # '4.000000'
    print(resumed['payment_url'])              # new URL for the customer
    print(resumed['deposit_address'])          # SAME as original
```

**Cascade behaviour:** when the customer pays the continuation invoice, the original invoice is automatically marked PAID and the webhook fires on the **original invoice_id** — your webhook handler does not need any changes.

The method is idempotent: calling it twice returns the same continuation with `resumed_existing: True`.

## Context Manager

```python
with PayGateClient(base_url=..., api_key=...) as client:
    invoice = client.create_payment("10.00")
    # session is automatically closed on exit
```

## Webhook Verification & Complete Handler

Webhooks are signed with `HMAC-SHA256` over `"{timestamp}.{raw_body}"` using your API key.
Both the `X-openbcp-Signature` and `X-openbcp-Timestamp` headers must be present and verified.

```python
from paygate import verify_webhook, WebhookVerificationError

# Flask — full handler covering every status
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

    data   = request.get_json()
    status = data["status"]

    if status in ("PAID", "OVERPAID"):
        # ✅ Safe to fulfil. data["paid"] is True.
        fulfil_order(data["external_id"])
        if status == "OVERPAID":
            log_overpayment(data["external_id"], data["overpaid_by"])

    elif status == "PARTIAL":
        # ⏳ Customer underpaid — do NOT fulfil.
        # data["shortfall"] tells you how much more is needed.
        notify_underpaid(data["external_id"], data["shortfall"])

    elif status == "EXPIRED":
        # ❌ Invoice timed out.
        if float(data["amount_received"]) > 0:
            # Funds received — a refund record was auto-created.
            # Consider calling client.resume_payment(data["invoice_id"]) instead.
            record_unsettled(data["external_id"], data["amount_received"])
        cancel_order(data["external_id"])

    elif status == "CANCELLED":
        cancel_order(data["external_id"])

    return "", 202   # MUST return 202 — anything else triggers retry
```

> **Important:** always pass the raw request body (`request.get_data()` in Flask,
> `await request.body()` in FastAPI) — not a re-serialised dict. The HMAC is
> computed over the exact bytes sent by openbcp.

## API Reference

### `PayGateClient(base_url, api_key, *, timeout=20, session=None)`

| Method | Description |
|--------|-------------|
| `create_payment(amount_usdt, *, external_id, callback_url, success_url, metadata)` | Create an invoice → `Invoice` |
| `get_payment(invoice_id)` | Full invoice with transactions (auth required) → `Invoice` |
| `get_payment_status(invoice_id)` | Quick public status check (no auth) → `Invoice` |
| `poll_until_paid(invoice_id, *, poll_interval=5, timeout=3600, include_partial=False)` | Block until paid → `Invoice` |
| `resume_payment(invoice_id)` | Resume EXPIRED-with-partial invoice → `dict` |
| `list_refunds(*, status, type, invoice_id, from_date, to_date, page, limit)` | List refunds with filters → `dict` |
| `get_refund(refund_id)` | Single refund detail → `dict` |
| `approve_refund(refund_id)` | Approve a refund (auto-queues for batch) → `dict` |
| `decline_refund(refund_id, *, reason)` | Decline a refund (moves to blacklist) → `dict` |
| `restore_refund(refund_id)` | Restore a blacklisted refund → `dict` |
| `get_refund_settings()` | Read per-type refund mode → `dict` |
| `update_refund_settings(*, underpaid_mode, overpaid_mode)` | Update per-type refund mode → `dict` |
| `close()` | Close the HTTP session |

## Refund API (Multi-Tenant Platforms)

For SaaS/platform merchants managing payments on behalf of many tenants, the Refund API lets you automate refund approval/decline/notification end-to-end without touching the dashboard:

```python
# List pending underpaid refunds
result = client.list_refunds(status="pending", type="underpaid")
print(result["count"], "pending")

# Auto-approve every pending refund programmatically
for r in result["results"]:
    client.approve_refund(r["refund_id"])

# Configure per-type mode (recommended for platforms):
#   underpaid → auto (no debate, just refund)
#   overpaid  → manual (may want to offer credit instead)
client.update_refund_settings(underpaid_mode="auto", overpaid_mode="manual")

# Decline with reason
client.decline_refund(123, reason="Customer requested credit instead")
```

### Refund Webhook Events

In addition to invoice webhooks, openbcp fires `refund.approved`, `refund.sent`, `refund.declined`, and `refund.failed` events using the same HMAC signature scheme. Discriminate by the `event` field in the payload:

```python
data = request.get_json()
event = data.get("event")

if event and event.startswith("refund."):
    if event == "refund.sent":
        mark_refunded(data["invoice_id"], data["txid"])
        notify_tenant(data["external_id"], data["amount_usdt"])
    elif event == "refund.failed":
        alert_ops(data["refund_id"], data["reason"])
else:
    # Invoice webhook — existing handler
    handle_invoice_status(data)

return "", 202
```

### `Invoice`

| Field | Type | Notes |
|-------|------|-------|
| `invoice_id` | `int` | |
| `payment_url` | `str` | Hosted checkout URL — redirect the customer here |
| `deposit_address` | `str` | BEP20 address to send USDT to |
| `amount_usdt` | `Decimal` | Gross amount expected (merchant amount + platform fee) |
| `amount_received` | `Decimal \| None` | Total confirmed on-chain |
| `shortfall` | `Decimal \| None` | How much more is needed (0 when PAID/OVERPAID) |
| `overpaid_by` | `Decimal \| None` | How much extra was sent (0 when PARTIAL/PAID) |
| `payment_status` | `str` | `UNPAID` / `PARTIAL` / `PAID` / `OVERPAID` / `EXPIRED` / `CANCELLED` |
| `expires_at` | `datetime` | UTC-aware |
| `transactions` | `list[Transaction]` | Each tx has `from_address`, `amount_usdt`, `confirmations` |
| `external_id` | `str \| None` | Your order reference |
| `created_at` | `datetime \| None` | |
| `is_paid()` | `bool` | True if PAID or OVERPAID — safe to fulfil |
| `is_partial()` | `bool` | True if PARTIAL — payment incomplete |
| `is_expired()` | `bool` | True if EXPIRED |
| `is_cancelled()` | `bool` | True if CANCELLED |
| `is_pending()` | `bool` | True while UNPAID or PARTIAL |
| `needs_refund()` | `bool` | True when EXPIRED/CANCELLED with funds received |
| `total_confirmed` | `Decimal` | Sum of confirmed tx amounts (or `amount_received` if available) |

### `verify_webhook(payload, signature, timestamp, api_key, *, max_age_sec=300)`

Returns `True` or raises `WebhookVerificationError`.

## Multi-Wallet Payments

A single invoice can receive payments from unlimited wallets. Each transaction's `from_address` is tracked separately. For refund routing:

- **Underpaid + expired:** each unique sender gets their own refund record back to their wallet.
- **Overpaid:** FIFO routing — the wallet that tipped the total past 100% gets the excess portion refunded; any later senders get refunded in full.

## Exceptions

| Exception | When |
|-----------|------|
| `PayGateError` | Base class — API errors, network errors |
| `PaymentNotFound` | 404 from `get_payment` |
| `WebhookVerificationError` | Invalid signature or expired timestamp |

All exceptions expose `.status_code` and `.response_body` attributes.
