from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any

from .exceptions import WebhookVerificationError

SIGNATURE_HEADER = "X-openbcp-Signature"
TIMESTAMP_HEADER = "X-openbcp-Timestamp"


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def compact_json_bytes(payload: dict[str, Any]) -> bytes:
    """
    Produce the canonical JSON bytes used for HMAC signing.

    Matches the server's serialization exactly:
    - Keys sorted alphabetically
    - No spaces around separators
    - Decimal values stringified
    """
    return json.dumps(
        payload,
        cls=_DecimalEncoder,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")


def _hmac_v1(secret: str, body: bytes, ts: int) -> str:
    key = secret.encode("utf-8")
    msg = f"{ts}.".encode("ascii") + body
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_webhook(
    payload: bytes,
    signature: str,
    timestamp: str | int,
    api_key: str,
    *,
    max_age_sec: int = 300,
) -> bool:
    """
    Verify the HMAC-SHA256 signature of an incoming PayGate webhook.

    Args:
        payload:     Raw request body bytes. Do NOT decode and re-encode — key
                     order in the original payload may differ from the sorted
                     canonical form and will break the signature.
        signature:   Value of the X-openbcp-Signature header (64-char hex).
        timestamp:   Value of the X-openbcp-Timestamp header (Unix seconds).
        api_key:     Your PayGate API key (used as the HMAC secret).
        max_age_sec: Replay-window size in seconds (default 300 = 5 minutes).

    Returns:
        True if the signature is valid and the timestamp is within the replay window.

    Raises:
        WebhookVerificationError: if the signature is invalid, malformed, or
                                  the timestamp is outside the replay window.

    Example (Flask)::

        from paygate import verify_webhook, WebhookVerificationError

        @app.post("/webhook")
        def webhook():
            try:
                verify_webhook(
                    request.get_data(),                          # raw bytes
                    request.headers["X-openbcp-Signature"],
                    request.headers["X-openbcp-Timestamp"],
                    api_key=os.environ["PAYGATE_API_KEY"],
                )
            except WebhookVerificationError as exc:
                abort(400, str(exc))
            data = request.get_json()
            if data["status"] in ("PAID", "OVERPAID"):
                fulfil_order(data["external_id"])
            elif data["status"] in ("EXPIRED", "CANCELLED"):
                cancel_order(data["external_id"])
            return "", 202
    """
    sig = signature.strip().lower()
    if len(sig) != 64:
        raise WebhookVerificationError(
            "Invalid signature format — expected 64 hex characters"
        )
    ts = int(timestamp)
    clock = int(time.time())
    if abs(clock - ts) > max_age_sec:
        raise WebhookVerificationError(
            f"Webhook timestamp outside replay window "
            f"({abs(clock - ts)}s ago, max {max_age_sec}s)"
        )
    expected = _hmac_v1(api_key, payload, ts)
    if not hmac.compare_digest(expected, sig):
        raise WebhookVerificationError("Webhook signature mismatch")
    return True
