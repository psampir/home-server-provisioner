#!/usr/bin/env python3
"""Behaviour checks for roles/auto_updates/files/hsp-update-report.

The script must stay read-only: it reports the apt upgrade list and the
Docker images older than a threshold, and sends everything through
hsp-notify. Fake apt-get, docker and hsp-notify keep the test offline.
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

FAKE_DOCKER = """#!/bin/sh
case "$1" in
  info) [ "${NO_DOCKER:-0}" = "1" ] && exit 1; exit 0 ;;
  ps) printf 'caddy\\nimmich\\nvaultwarden\\n' ;;
  inspect)
    case "$4" in
      caddy) echo 'caddy:2.9.1' ;;
      immich) echo 'ghcr.io/immich-app/immich-server:v3.2.2' ;;
      vaultwarden) echo 'vaultwarden/server@sha256:094b5689ed81549bd293418395c7cf495ae9d960fc2d4928cef2083ef913d912' ;;
    esac
    ;;
  image)
    case "$5" in
      caddy:*|vaultwarden/*) echo '2025-01-01T00:00:00.000000000Z' ;;
      *) date -u +%Y-%m-%dT00:00:00.000000000Z ;;
    esac
    ;;
esac
"""

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "${NOTIFY_LOG}"
"""


def run(root: Path, no_packages: bool = False, no_docker: bool = False) -> str:
    log = root / "notify.log"
    if log.exists():
        log.unlink()
    env = dict(os.environ)
    env["HSP_UPDATE_REPORT_CONFIG"] = str(root / "update-report.conf")
    env["NOTIFY_LOG"] = str(log)
    env["NO_PACKAGES"] = "1" if no_packages else "0"
    env["NO_DOCKER"] = "1" if no_docker else "0"
    env["PATH"] = f"{root / 'bin'}:{env.get('PATH', '')}"
    subprocess.run(["/bin/sh", str(SCRIPT)], env=env, check=True, capture_output=True, text=True)
    return log.read_text() if log.exists() else ""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, body in (("apt-get", FAKE_APT), ("docker", FAKE_DOCKER), ("hsp-notify", FAKE_NOTIFY)):
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        (root / "update-report.conf").write_text(
            f'AGE_DAYS=1\nMAX_ITEMS=15\nNOTIFY_BIN="{bin_dir / "hsp-notify"}"\n'
        )

        out = run(root)
        if "--priority low" not in out or "update_report,package" not in out:
            raise SystemExit(f"notification metadata missing: {out!r}")
        if "2 apt" not in out or "docker-ce" not in out or "caddy" not in out:
            raise SystemExit(f"package list missing: {out!r}")
        if "caddy:2.9.1 (4" not in out and "caddy:2.9.1" not in out:
            raise SystemExit(f"stale image not reported: {out!r}")
        if "immich-server:v3.2.2" in out:
            raise SystemExit(f"fresh image was reported as stale: {out!r}")
        if "vaultwarden/server@sha256:094b5689ed81" not in out:
            raise SystemExit(f"digest was not shortened: {out!r}")
        if "094b5689ed81549bd293418395c7cf495ae9d960fc2d4928cef2083ef913d912" in out:
            raise SystemExit(f"full digest leaked into the report: {out!r}")

        out = run(root, no_packages=True, no_docker=True)
        if "0 apt" not in out or "nothing to upgrade" not in out:
            raise SystemExit(f"empty package report is wrong: {out!r}")
        if "images: none" not in out:
            raise SystemExit(f"empty image report is wrong: {out!r}")

    print("update report tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
