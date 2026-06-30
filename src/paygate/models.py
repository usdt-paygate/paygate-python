from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Literal, Optional

PaymentStatus = Literal["UNPAID", "PARTIAL", "PAID", "OVERPAID", "EXPIRED", "CANCELLED"]
TxStatus = Literal["PENDING", "CONFIRMED"]


def _parse_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    # Python 3.9 does not support the trailing Z in fromisoformat — normalise it
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_decimal(value: str | int | float | None) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


@dataclass
class Transaction:
    txid: str
    amount_usdt: Decimal
    confirmations: int
    required_confirmations: int
    status: TxStatus

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            txid=d["txid"],
            amount_usdt=Decimal(str(d["amount_usdt"])),
            confirmations=int(d["confirmations"]),
            required_confirmations=int(d["required_confirmations"]),
            status=d["status"],
        )


@dataclass
class Invoice:
    invoice_id: int
    deposit_address: str
    amount_usdt: Decimal
    payment_status: PaymentStatus
    network: str
    token: str
    expires_at: Optional[datetime]
    transactions: List[Transaction] = field(default_factory=list)
    external_id: Optional[str] = None
    created_at: Optional[datetime] = None
    payment_url: Optional[str] = None
    merchant_amount_usdt: Optional[Decimal] = None
    platform_fee_usdt: Optional[Decimal] = None
    # Amount fields returned by the status endpoint and webhook payloads.
    # amount_received: total USDT confirmed on-chain for this invoice.
    # shortfall:       how much more is needed (0 when PAID/OVERPAID).
    # overpaid_by:     how much extra was sent (0 when PAID/PARTIAL).
    amount_received: Optional[Decimal] = None
    shortfall: Optional[Decimal] = None
    overpaid_by: Optional[Decimal] = None

    # ── Convenience ───────────────────────────────────────────────────────────

    def is_paid(self) -> bool:
        """True when payment_status is PAID or OVERPAID."""
        return self.payment_status in ("PAID", "OVERPAID")

    def is_partial(self) -> bool:
        """True when a confirmed payment exists but is below the required amount.

        The invoice stays open and the checkout page prompts the customer to
        top up to the same deposit address. The expiry window is automatically
        extended by 30 minutes on first partial detection.
        """
        return self.payment_status == "PARTIAL"

    def is_expired(self) -> bool:
        """True when the invoice timed out. Check amount_received > 0 to
        detect the partial-then-expired case where a refund may be needed."""
        return self.payment_status == "EXPIRED"

    def is_cancelled(self) -> bool:
        """True when the customer manually cancelled the order."""
        return self.payment_status == "CANCELLED"

    def is_pending(self) -> bool:
        """True while the invoice is still waiting for sufficient payment."""
        return self.payment_status in ("UNPAID", "PARTIAL")

    def needs_refund(self) -> bool:
        """True when funds were received but the invoice cannot be completed.

        This covers two cases:
        - PARTIAL + expired: customer underpaid and the window closed.
        - CANCELLED with a confirmed transaction (rare but possible).

        When True, inspect ``amount_received`` to know how much to refund.
        """
        received = self.amount_received or self.total_confirmed
        if received == Decimal("0"):
            return False
        return self.payment_status in ("EXPIRED", "CANCELLED")

    @property
    def total_confirmed(self) -> Decimal:
        """Sum of all CONFIRMED transaction amounts.

        Falls back to computing from the transactions list if ``amount_received``
        is not populated (e.g. when using the authenticated GET endpoint).
        """
        if self.amount_received is not None:
            return self.amount_received
        return sum(
            (t.amount_usdt for t in self.transactions if t.status == "CONFIRMED"),
            Decimal("0"),
        )

    # ── Deserialisation ───────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "Invoice":
        return cls(
            invoice_id=int(d["invoice_id"]),
            deposit_address=d["deposit_address"],
            amount_usdt=Decimal(str(d["amount_usdt"])),
            # POST /api/v1/payment response omits payment_status — default UNPAID
            payment_status=d.get("payment_status", "UNPAID"),
            network=d.get("network", "BEP20"),
            token=d.get("token", "USDT"),
            expires_at=_parse_dt(d.get("expires_at")),
            transactions=[
                Transaction.from_dict(t) for t in d.get("transactions", [])
            ],
            external_id=d.get("external_id"),
            created_at=_parse_dt(d.get("created_at")),
            payment_url=d.get("payment_url"),
            merchant_amount_usdt=_parse_decimal(d.get("merchant_amount_usdt")),
            platform_fee_usdt=_parse_decimal(d.get("platform_fee_usdt")),
            amount_received=_parse_decimal(d.get("amount_received")),
            shortfall=_parse_decimal(d.get("shortfall")),
            overpaid_by=_parse_decimal(d.get("overpaid_by")),
        )
