"""Generate VAPID keys for vendor-app web push notifications.

Run from the backend directory:

    python scripts/gen_vapid.py

It prints the three values to paste into your production env (Render →
Environment → add the variables). The keys are also saved to
``backend/vapid_keys.json`` (git-ignored) so local development works with
zero configuration — production should use the env vars instead.
"""
import base64
import json
import os
import sys

from pathlib import Path


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate() -> dict:
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_numbers = private_key.public_key().public_numbers()
    point = b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
    return {
        "public_key": _b64url(point),
        "private_key": _b64url(private_value),
    }


def main() -> None:
    keys = generate()
    out = Path(__file__).resolve().parents[1] / "vapid_keys.json"
    out.write_text(json.dumps({**keys, "subject": "mailto:admin@detomsite.local"}, indent=2), encoding="utf-8")

    print("✔ VAPID keys generated and saved to:", out)
    print()
    print("Add these to your PRODUCTION environment (Render → Environment):")
    print()
    print("VAPID_PUBLIC_KEY=" + keys["public_key"])
    print("VAPID_PRIVATE_KEY=" + keys["private_key"])
    print("VAPID_SUBJECT=mailto:admin@detomsite.local")
    print()
    print("After adding them, redeploy the backend once. The vendor app's")
    print('"Enable order notifications" button will then work for real.')


if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("The 'cryptography' package is required. Install dependencies first:")
        print("  pip install -r requirements.txt")
        sys.exit(1)
