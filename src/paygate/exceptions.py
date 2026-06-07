from __future__ import annotations


class PayGateError(Exception):
    """Base exception for all PayGate SDK errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: dict | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


class PaymentNotFound(PayGateError):
    """Raised when the requested invoice does not exist."""

    def __init__(self, invoice_id: int | str):
        super().__init__(
            f"Invoice {invoice_id} not found",
            status_code=404,
        )
        self.invoice_id = invoice_id


class WebhookVerificationError(PayGateError):
    """Raised by verify_webhook() when the signature or timestamp check fails."""
