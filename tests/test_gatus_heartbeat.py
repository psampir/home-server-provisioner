#!/usr/bin/env python3
"""Behaviour checks for roles/gatus/files/hsp-gatus-heartbeat.

The script pings the external heartbeat only while the local health
endpoint answers, so silence means either the hub or the monitor is down.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "gatus" / "files" / "hsp-gatus-heartbeat"

FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "${CURL_LOG}"
case "$*" in
  *health*) [ "${FAKE_HEALTH_OK:-0}" = "1" ] || exit 22 ;;
esac
exit 0
"""


def run(root: Path, health_ok: bool) -> tuple[int, list[str]]:
    log = root / "curl.log"
    if log.exists():
        log.unlink()
    env = dict(os.environ)
    env["HSP_GATUS_HEARTBEAT_ENV"] = str(root / "gatus-heartbeat.env")
    env["CURL_BIN"] = str(root / "curl")
    env["CURL_LOG"] = str(log)
    env["FAKE_HEALTH_OK"] = "1" if health_ok else "0"
    result = subprocess.run(["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    lines = [line for line in log.read_text().splitlines() if line.strip()] if log.exists() else []
    return result.returncode, lines


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        curl = root / "curl"
        curl.write_text(FAKE_CURL)
        curl.chmod(0o755)
        (root / "gatus-heartbeat.env").write_text(
            'HEALTH_URL="http://127.0.0.1:8080/health"\n'
            'HEARTBEAT_URL="https://hc-ping.com/test-uuid"\n'
        )

        rc, lines = run(root, health_ok=True)
        if rc != 0 or len(lines) != 2:
            raise SystemExit(f"healthy monitor: rc={rc} lines={lines!r}")
        if "hc-ping.com/test-uuid" not in lines[-1] or "-X POST" not in lines[-1]:
            raise SystemExit(f"heartbeat was not pinged: {lines!r}")

        rc, lines = run(root, health_ok=False)
        if rc == 0:
            raise SystemExit("an unhealthy monitor still exited zero")
        if len(lines) != 1 or any("hc-ping.com" in line for line in lines):
            raise SystemExit(f"heartbeat was pinged while unhealthy: {lines!r}")

    print("gatus heartbeat tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
