from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from .exceptions import PayGateError, PaymentNotFound
from .models import Invoice


class PayGateClient:
    """
    Synchronous HTTP client for the PayGate USDT payment gateway API.

    Usage::

        from paygate import PayGateClient

        client = PayGateClient(
            base_url="https://openbcp.com",
            api_key="your-api-key",
        )

        # Create invoice — redirect customer to payment_url
        invoice = client.create_payment("29.99", external_id="order-123",
                                        callback_url="https://yoursite.com/webhook")
        redirect_customer_to(invoice.payment_url)
        # openbcp hosts the checkout page — QR code, countdown, confirmation

        # In your webhook handler — verify signature, then fulfil order
        invoice = client.get_payment(invoice.invoice_id)
        if invoice.is_paid():
            fulfil_order(invoice.external_id)

    Context manager::

        with PayGateClient(base_url=..., api_key=...) as client:
            invoice = client.create_payment("10.00")
    """

    DEFAULT_TIMEOUT = 20

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "X-openbcp-Api-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise PayGateError(f"Network error: {exc}") from exc

        try:
            body: dict = resp.json()
        except ValueError:
            body = {}

        if resp.status_code == 404:
            raise PaymentNotFound(body.get("message", "unknown"))
        if not resp.ok:
            msg = body.get("message", f"HTTP {resp.status_code}")
            raise PayGateError(msg, status_code=resp.status_code, response_body=body)

        return body

    # ── Public API ────────────────────────────────────────────────────────────

    def create_payment(
        self,
        amount_usdt: str | float,
        *,
        external_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        success_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Invoice:
        """
        Create a new USDT payment invoice.

        Args:
            amount_usdt:   Amount to charge in USDT. Pass as a string to avoid
                           float precision issues (e.g. ``"29.99"`` not ``29.99``).
            external_id:   Your internal order/reference ID stored with the invoice
                           and echoed back in every webhook.
            callback_url:  URL that receives a signed webhook POST on every status
                           change: PAID, OVERPAID, PARTIAL, EXPIRED, CANCELLED.
            success_url:   URL the customer is redirected to after payment is
                           confirmed on the hosted checkout page. Must be http
                           or https. If omitted, the checkout page attempts to
                           close the tab instead.
            metadata:      Arbitrary JSON dict stored with the invoice. Use this
                           for any custom merchant data including original fiat
                           reference price (e.g. ``{"price_eur": 30}``).

        Returns:
            :class:`Invoice` with ``payment_url`` (redirect the customer here),
            ``invoice_id``, ``amount_usdt``, ``merchant_amount_usdt``,
            ``platform_fee_usdt``, and ``expires_at`` populated.

        Webhook statuses you will receive on ``callback_url``:
            - ``PAID`` / ``OVERPAID`` → fulfil the order (``paid=True``)
            - ``PARTIAL`` → customer underpaid, do NOT fulfil, check ``shortfall``
            - ``EXPIRED`` → timed out; if ``amount_received > 0`` a refund was queued
            - ``CANCELLED`` → customer cancelled

        Raises:
            PayGateError: on API or network error.
        """
        payload: Dict[str, Any] = {"amount_usdt": str(amount_usdt)}
        if external_id is not None:
            payload["external_id"] = external_id
        if callback_url is not None:
            payload["callback_url"] = callback_url
        if success_url is not None:
            payload["success_url"] = success_url
        if metadata is not None:
            payload["metadata"] = metadata

        body = self._request("POST", "/api/v1/payment", json=payload)
        return Invoice.from_dict(body)

    def get_payment(self, invoice_id: int) -> Invoice:
        """
        Retrieve full invoice details including all transactions.

        Requires API key auth — use this for server-side status checks.

        Args:
            invoice_id: Integer invoice ID returned by :meth:`create_payment`.

        Returns:
            :class:`Invoice` with ``payment_status`` and ``transactions`` populated.

        Raises:
            PaymentNotFound: if the invoice does not exist.
            PayGateError: on other API errors.
        """
        body = self._request("GET", f"/api/v1/payment/{invoice_id}")
        return Invoice.from_dict(body)

    def get_payment_status(self, invoice_id: int) -> Invoice:
        """
        Check payment status using the public (no-auth) endpoint.

        Suitable for server-side polling. Returns ``payment_status``,
        ``amount_received``, ``shortfall``, ``overpaid_by``, and
        ``transactions``. No ``external_id`` or ``created_at``.

        Use :meth:`invoice.is_paid` to check if the order can be fulfilled.
        Use :meth:`invoice.is_partial` to detect underpayment.
        Use :meth:`invoice.needs_refund` to detect expired-with-funds cases.

        Args:
            invoice_id: Integer invoice ID.

        Returns:
            :class:`Invoice` with ``payment_status``, ``amount_received``,
            ``shortfall``, ``overpaid_by``, and ``transactions``.

        Raises:
            PaymentNotFound: if the invoice does not exist.
            PayGateError: on network or server errors.
        """
        url = f"{self.base_url}/api/v1/payment/{invoice_id}/status"
        try:
            resp = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise PayGateError(f"Network error: {exc}") from exc
        if resp.status_code == 404:
            raise PaymentNotFound(invoice_id)
        if not resp.ok:
            raise PayGateError(f"HTTP {resp.status_code}", status_code=resp.status_code)
        return Invoice.from_dict(resp.json())

    def poll_until_paid(
        self,
        invoice_id: int,
        *,
        poll_interval: float = 5.0,
        timeout: float = 3600.0,
        include_partial: bool = False,
    ) -> Invoice:
        """
        Block until the invoice is paid, then return it.

        Polls :meth:`get_payment` every ``poll_interval`` seconds up to
        ``timeout`` seconds total.

        Args:
            invoice_id:      Invoice to watch.
            poll_interval:   Seconds between checks (default 5).
            timeout:         Maximum seconds to wait (default 3600 = 1 hour).
            include_partial: If ``True``, also return on PARTIAL status.

        Returns:
            The paid :class:`Invoice`.

        Raises:
            PayGateError: if the invoice expires before payment, or if
                          ``timeout`` is exceeded.
            PaymentNotFound: if the invoice does not exist.

        Example::

            invoice = client.create_payment("10.00")
            print(f"Send {invoice.amount_usdt} USDT to {invoice.deposit_address}")
            paid = client.poll_until_paid(invoice.invoice_id, timeout=900)
            print("Paid!", paid.total_confirmed)
        """
        paid_statuses = {"PAID", "OVERPAID"}
        if include_partial:
            paid_statuses.add("PARTIAL")

        deadline = time.monotonic() + timeout
        while True:
            invoice = self.get_payment(invoice_id)
            if invoice.payment_status in paid_statuses:
                return invoice
            if invoice.is_expired():
                raise PayGateError(
                    f"Invoice {invoice_id} expired before payment was received"
                )
            if time.monotonic() >= deadline:
                raise PayGateError(
                    f"poll_until_paid timed out after {timeout:.0f}s "
                    f"(invoice {invoice_id} still {invoice.payment_status})"
                )
            time.sleep(poll_interval)

    def resume_payment(self, invoice_id: int) -> dict:
        """
        Resume an EXPIRED-with-partial invoice by creating a continuation invoice
        for the shortfall amount. Reuses the SAME deposit address — the customer
        can pay via the old QR/URL or the new payment_url. Both work.

        When the continuation is paid, the original invoice is automatically
        marked PAID via cascade and the webhook fires on the ORIGINAL invoice_id.
        Your webhook handler does NOT need any changes to work with resume.

        Args:
            invoice_id: ID of the original EXPIRED invoice with partial payment.

        Returns:
            Dict with: ``continuation_invoice_id``, ``original_invoice_id``,
            ``amount_usdt`` (the shortfall), ``amount_already_received``,
            ``deposit_address`` (same as original), ``payment_url`` (to share
            with customer), ``expires_at``, ``cancelled_refund_count``.

            If the invoice was already resumed previously, returns the existing
            continuation with ``resumed_existing: True`` — idempotent.

        Raises:
            PayGateError: If invoice is not EXPIRED, has no partial payment,
                          or doesn't belong to your account.
            PaymentNotFound: If invoice doesn't exist.

        Example::

            # Customer's invoice expired with 4/5 USDT paid
            try:
                paid = client.poll_until_paid(invoice_id=42, timeout=900)
            except PayGateError:
                # Expired — offer customer a chance to complete payment
                resumed = client.resume_payment(invoice_id=42)
                send_email(
                    customer.email,
                    subject="Finish your order",
                    body=f"Pay the remaining {resumed['amount_usdt']} USDT here: "
                         f"{resumed['payment_url']}"
                )
        """
        body = self._request("POST", f"/api/v1/payment/{invoice_id}/resume")
        return body

    # ── Context manager ───────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying requests Session."""
        self._session.close()

    def __enter__(self) -> "PayGateClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
