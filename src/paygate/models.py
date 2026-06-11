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

    # ── Convenience ───────────────────────────────────────────────────────────

    def is_paid(self) -> bool:
        """True when payment_status is PAID or OVERPAID."""
        return self.payment_status in ("PAID", "OVERPAID")

    def is_expired(self) -> bool:
        return self.payment_status == "EXPIRED"

    def is_cancelled(self) -> bool:
        return self.payment_status == "CANCELLED"

    def is_pending(self) -> bool:
        return self.payment_status in ("UNPAID", "PARTIAL")

    @property
    def total_confirmed(self) -> Decimal:
        """Sum of all CONFIRMED transaction amounts."""
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
        )
