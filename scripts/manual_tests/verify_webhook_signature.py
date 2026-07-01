from __future__ import annotations

import argparse
import hashlib
import hmac
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Signal webhook X-Signal-Signature.")
    parser.add_argument("--secret", required=True)
    parser.add_argument("--header", required=True, help='Full X-Signal-Signature header, e.g. "t=...,v1=..."')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--body", help="Raw request body string")
    group.add_argument("--body-file", help="Path to a file containing the raw request body")
    args = parser.parse_args()

    parts = dict(piece.split("=", 1) for piece in args.header.split(",") if "=" in piece)
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        raise SystemExit("Header must include t=... and v1=...")

    if args.body_file:
        body = Path(args.body_file).read_bytes()
    else:
        body = args.body.encode("utf-8")

    signed_payload = f"{timestamp}.".encode("utf-8") + body
    expected = hmac.new(args.secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    valid = hmac.compare_digest(expected, signature)
    print(f"signature_valid={valid}")
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
