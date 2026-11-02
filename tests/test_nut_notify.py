#!/usr/bin/env python3
"""Behaviour checks for roles/nut/files/hsp-notify-ups.

Maps the upssched event text to an ntfy priority, so a battery-low event is
urgent while power returning is just informational.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "roles" / "nut" / "files" / "hsp-notify-ups"

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "${NOTIFY_LOG}"
"""

CASES = [
    ("UPS on battery", "high"),
    ("UPS battery low; upsmon will shut down", "urgent"),
    ("Lost communication with UPS; waiting 300s", "high"),
    ("UPS communication not restored after 300s; shutting down", "urgent"),
    ("UPS on line power", "default"),
    ("Communication restored with greencell", "default"),
]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        notify = root / "hsp-notify"
        notify.write_text(FAKE_NOTIFY)
        notify.chmod(0o755)
        log = root / "notify.log"

        for message, expected in CASES:
            if log.exists():
                log.unlink()
            env = dict(os.environ)
            env["HSP_NOTIFY_BIN"] = str(notify)
            env["NOTIFY_LOG"] = str(log)
            result = subprocess.run(["/bin/sh", str(WRAPPER), message], env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise SystemExit(f"wrapper failed for {message!r}: {result.stderr}")
            line = log.read_text().strip() if log.exists() else ""
            if f"--priority {expected}" not in line:
                raise SystemExit(f"{message!r}: expected priority {expected}, got {line!r}")
            if "--tags ups,battery" not in line:
                raise SystemExit(f"{message!r}: tags missing: {line!r}")
            if "UPS " not in line:
                raise SystemExit(f"{message!r}: subject missing host: {line!r}")

    print("nut notify tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
