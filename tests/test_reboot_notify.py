#!/usr/bin/env python3
"""Behaviour checks for roles/auto_updates/templates/hsp-reboot-notify.j2.

The script is rendered with a fake notification helper and run against
temporary scheduled-shutdown files, so no real shutdown is involved.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import jinja2

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "roles" / "auto_updates" / "templates" / "hsp-reboot-notify.j2"

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "${NOTIFY_LOG}"
"""


def schedule_file(path: Path, mode: str, minutes_from_now: int) -> None:
    usec = int((time.time() + minutes_from_now * 60) * 1_000_000)
    path.write_text(f"USEC={usec}\nMODE={mode}\n")


def run(script: Path, schedule: Path, log: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HSP_REBOOT_SCHEDULE_FILE"] = str(schedule)
    env["NOTIFY_LOG"] = str(log)
    return subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
    )


def sent(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        notify = root / "hsp-notify"
        notify.write_text(FAKE_NOTIFY)
        notify.chmod(0o755)

        script = root / "hsp-reboot-notify"
        script.write_text(
            jinja2.Template(TEMPLATE.read_text()).render(
                auto_updates_notify_bin=str(notify)
            )
        )
        script.chmod(0o755)

        schedule = root / "scheduled"
        log = root / "notify.log"

        result = run(script, schedule, log)
        assert result.returncode == 0, result.stderr
        assert sent(log) == []

        schedule_file(schedule, "poweroff", 30)
        result = run(script, schedule, log)
        assert result.returncode == 0, result.stderr
        assert sent(log) == []

        schedule_file(schedule, "reboot", 30)
        result = run(script, schedule, log)
        assert result.returncode == 0, result.stderr
        assert len(sent(log)) == 1, sent(log)
        assert "reboot on" in sent(log)[0]
        assert "30 min" in sent(log)[0]

        log.unlink()
        schedule_file(schedule, "reboot", 180)
        result = run(script, schedule, log)
        assert result.returncode == 0, result.stderr
        assert sent(log) == []

        schedule_file(schedule, "reboot", -5)
        result = run(script, schedule, log)
        assert result.returncode == 0, result.stderr
        assert len(sent(log)) == 1, sent(log)
        assert "0 min" in sent(log)[0]

    print("test-reboot-notify: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
