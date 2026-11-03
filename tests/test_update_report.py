#!/usr/bin/env python3
"""Behaviour checks for roles/auto_updates/files/hsp-update-report.

The script must stay read-only and package-only: it reports the apt upgrade
list and sends everything through hsp-notify. Fake apt-get and hsp-notify
keep the test offline. Docker must not be consulted at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "auto_updates" / "files" / "hsp-update-report"

FAKE_APT = """#!/bin/sh
case "$*" in
  *"--just-print"*)
    [ "${NO_PACKAGES:-0}" = "1" ] && exit 0
    printf 'Inst docker-ce [5:29] (5:30 Debian:13/stable [amd64])\\n'
    printf 'Inst caddy [2.11.7] (2.11.8 Cloudsmith [amd64])\\n'
    ;;
esac
exit 0
"""

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "${NOTIFY_LOG}"
"""


def run(root: Path, no_packages: bool = False) -> str:
    log = root / "notify.log"
    if log.exists():
        log.unlink()
    env = dict(os.environ)
    env["HSP_UPDATE_REPORT_CONFIG"] = str(root / "update-report.conf")
    env["NOTIFY_LOG"] = str(log)
    env["NO_PACKAGES"] = "1" if no_packages else "0"
    env["PATH"] = f"{root / 'bin'}:{env.get('PATH', '')}"
    subprocess.run(["/bin/sh", str(SCRIPT)], env=env, check=True, capture_output=True, text=True)
    return log.read_text() if log.exists() else ""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, body in (("apt-get", FAKE_APT), ("hsp-notify", FAKE_NOTIFY)):
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        (root / "update-report.conf").write_text(
            f'MAX_ITEMS=15\nNOTIFY_BIN="{bin_dir / "hsp-notify"}"\n'
        )

        out = run(root)
        if "--priority low" not in out or "update_report,package" not in out:
            raise SystemExit(f"notification metadata missing: {out!r}")
        if "2 apt" not in out or "docker-ce" not in out or "caddy" not in out:
            raise SystemExit(f"package list missing: {out!r}")
        if "images" in out or "older than" in out:
            raise SystemExit(f"image section leaked into the report: {out!r}")

        out = run(root, no_packages=True)
        if "0 apt" not in out or "nothing to upgrade" not in out:
            raise SystemExit(f"empty package report is wrong: {out!r}")
        if "images" in out or "older than" in out:
            raise SystemExit(f"image section leaked into the empty report: {out!r}")

    print("update report tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
