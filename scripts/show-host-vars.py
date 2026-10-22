#!/usr/bin/env python3
"""Redact secret values from `ansible-inventory --host` JSON on stdin.

Used by `make host HOST=<name>`. The inventory output is valid JSON, so a
line-based grep would break the structure when it removes a value. This walks
the document instead and replaces the values of secret-looking keys while
keeping the JSON intact.
"""

import json
import sys

SECRET_SUBSTRINGS = ("privkey", "psk", "passphrase", "password", "token", "secret")
REDACTED = "<redacted>"


def is_secret(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("vault_") or any(
        part in lowered for part in SECRET_SUBSTRINGS
    )


def redact(value):
    if isinstance(value, dict):
        return {
            key: REDACTED if is_secret(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"show-host-vars: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 2
    json.dump(redact(data), sys.stdout, indent=4, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
