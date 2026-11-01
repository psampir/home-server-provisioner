#!/usr/bin/env python3
"""Behaviour checks for roles/notifications/files/hsp-disk-check.

The script is run against a fake `df` and a fake `hsp-notify`, so the test
covers thresholds, deduplication, reminders and recovery without touching
a real filesystem.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "notifications" / "files" / "hsp-disk-check"

FAKE_DF = """#!/bin/sh
last=""
for arg in "$@"; do
  last="$arg"
  [ "$arg" = "-P" ] && exit 1
done
[ "$last" = "/missing" ] && exit 1
case " $* " in
  *" -i "*) printf ' %s%%\\n' "${FAKE_INODE:-3}" ;;
  *) printf ' %s%%\\n' "${FAKE_USAGE:-50}" ;;
esac
"""

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "${NOTIFY_LOG}"
"""


def run(conf: Path, notify_log: Path, usage: int, inode: int = 3) -> None:
    env = dict(os.environ)
    env["HSP_DISK_CHECK_CONFIG"] = str(conf)
    env["FAKE_USAGE"] = str(usage)
    env["FAKE_INODE"] = str(inode)
    env["NOTIFY_LOG"] = str(notify_log)
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)


def lines(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "df").write_text(FAKE_DF)
        (bin_dir / "df").chmod(0o755)
        notify = root / "hsp-notify"
        notify.write_text(FAKE_NOTIFY)
        notify.chmod(0o755)
        log = root / "notify.log"

        conf = root / "disk-check.conf"
        conf.write_text(
            f'PATHS="/"\n'
            f'WARN=80\n'
            f'CRIT=90\n'
            f'INODE_WARN=90\n'
            f'REMIND=86400\n'
            f'STATE_FILE="{root}/state"\n'
            f'NOTIFY_BIN="{notify}"\n'
        )

        env_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}:{env_path}"

        run(conf, log, 50)
        if lines(log):
            raise SystemExit(f"quiet disk produced a notification: {lines(log)}")

        run(conf, log, 85)
        if len(lines(log)) != 1:
            raise SystemExit(f"warn threshold did not notify once: {lines(log)}")
        if "warn" not in lines(log)[0] or "85%" not in lines(log)[0]:
            raise SystemExit(f"warn notification has the wrong text: {lines(log)[0]}")

        run(conf, log, 85)
        if len(lines(log)) != 1:
            raise SystemExit(f"warn level was not deduplicated: {lines(log)}")

        run(conf, log, 95)
        if len(lines(log)) != 2 or "crit" not in lines(log)[1]:
            raise SystemExit(f"crit threshold did not notify: {lines(log)}")

        run(conf, log, 50)
        if len(lines(log)) != 3 or "recovered" not in lines(log)[2]:
            raise SystemExit(f"recovery did not notify: {lines(log)}")

        run(conf, log, 50)
        if len(lines(log)) != 3:
            raise SystemExit(f"recovery was not deduplicated: {lines(log)}")

        # An unavailable path must be reported as critical.
        conf.write_text(
            f'PATHS="/missing"\n'
            f'WARN=80\n'
            f'CRIT=90\n'
            f'INODE_WARN=90\n'
            f'REMIND=86400\n'
            f'STATE_FILE="{root}/state"\n'
            f'NOTIFY_BIN="{notify}"\n'
        )
        run(conf, log, 50)
        if len(lines(log)) != 4 or "unavailable" not in lines(log)[3]:
            raise SystemExit(f"missing path was not reported: {lines(log)}")

    print("disk check tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
