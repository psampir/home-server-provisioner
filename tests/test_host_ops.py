#!/usr/bin/env python3
"""Behaviour checks for the OliveTin host operation wrappers.

Every system command is replaced by a fake that records its arguments, so
the tests never touch apt, systemd or a disk.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "roles" / "olivetin_agent" / "files"

FAKE = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "${CALL_LOG}"
exit "${FAKE_EXIT:-0}"
"""

FAKE_SMARTCTL = """#!/bin/sh
if [ "$1" = "--scan" ]; then
  printf '/dev/sda -d scsi # /dev/sda, SCSI device\\n'
  exit 0
fi
printf '%s %s\\n' "$(basename "$0")" "$*" >> "${CALL_LOG}"
if [ "$1" = "--json" ]; then
  cat <<'JSON'
{"smart_status":{"passed":true},"model_name":"Test Disk","ata_smart_attributes":{"table":[{"id":5,"raw":{"value":0,"string":"0"}},{"id":9,"raw":{"value":198586402896410,"string":"16932 (92 176 0)"}},{"id":194,"raw":{"value":85899345963,"string":"43 (Min/Max 25/50)"}}]}}
JSON
fi
exit 0
"""


def run(script: str, args: list[str], bin_dir: Path, log: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CALL_LOG"] = str(log)
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        env=env,
        capture_output=True,
        text=True,
    )


def calls(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name in ("apt-get", "needrestart", "shutdown", "journalctl", "borgmatic", "docker", "dpkg", "systemctl", "etckeeper"):
            path = bin_dir / name
            path.write_text(FAKE)
            path.chmod(0o755)
        smartctl = bin_dir / "smartctl"
        smartctl.write_text(FAKE_SMARTCTL)
        smartctl.chmod(0o755)

        log = root / "calls.log"

        result = run("hsp-apt", ["check"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        got = calls(log)
        assert "apt-get update" in got, got
        assert any(call.startswith("apt-get -s ") and "upgrade --with-new-pkgs" in call for call in got), got
        assert "needrestart -b" in got, got
        assert "dpkg --audit" in got, got
        assert "apt-get check" in got, got
        assert "systemctl --failed --no-pager" in got, got
        assert any(call.startswith("etckeeper vcs log -1") for call in got), got
        assert not any("full-upgrade" in call or "autoremove" in call for call in got), got

        log.unlink(missing_ok=True)
        result = run("hsp-apt", ["upgrade"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        got = calls(log)
        assert any(call.startswith("apt-get -y ") and "upgrade --with-new-pkgs" in call for call in got), got
        assert "apt-get -y autoclean" in got, got
        assert "dpkg --audit" in got, got
        assert "apt-get check" in got, got
        assert "systemctl --failed --no-pager" in got, got
        assert any(call.startswith("etckeeper vcs log -1") for call in got), got
        assert not any("full-upgrade" in call or "autoremove" in call for call in got), got

        log.unlink(missing_ok=True)
        result = run("hsp-apt", ["wrong"], bin_dir, log)
        assert result.returncode == 2
        assert calls(log) == []

        log.unlink(missing_ok=True)
        result = run("hsp-reboot", ["schedule"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert calls(log) == ["shutdown -r +5 Scheduled from OliveTin"], calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-reboot", ["cancel"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert calls(log) == ["shutdown -c"], calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-journal-vacuum", [], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert calls(log) == ["journalctl --vacuum-time=30d"], calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-smart", ["short"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert calls(log) == ["smartctl -t short /dev/sda -d scsi"], calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-smart", ["status", "summary"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert "health: PASSED" in result.stdout, result.stdout
        assert "temperature: 43 C" in result.stdout, result.stdout
        assert "power_on_hours: 16932" in result.stdout, result.stdout
        assert any(call.startswith("smartctl --json") for call in calls(log)), calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-smart", ["status", "full"], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert any(call.startswith("smartctl -H -A") for call in calls(log)), calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-backup-check", [], bin_dir, log)
        assert result.returncode == 0, result.stderr
        assert calls(log) == ["borgmatic check"], calls(log)

        log.unlink(missing_ok=True)
        result = run("hsp-etckeeper", [], bin_dir, log)
        assert result.returncode == 0, result.stderr
        got = calls(log)
        assert "etckeeper vcs log -5 --oneline" in got, got
        assert any(call.startswith("etckeeper vcs show --stat --oneline HEAD") for call in got), got

    print("test-host-ops: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
