#!/usr/bin/env python3
"""Behaviour checks for hsp-boot-check.

All host commands are replaced by fakes, so the test never touches mounts,
systemd or Docker.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "boot_check" / "files" / "hsp-boot-check"

FAKE_FINDMNT = """#!/bin/sh
mount=""; col=""
while [ $# -gt 0 ]; do
  case "$1" in
    -M) mount="$2"; shift 2 ;;
    -o) col="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [ "$mount" = "/srv/data" ]; then
  [ "${FAKE_MOUNTED:-1}" = "0" ] && exit 1
  [ "$col" = "SOURCE" ] && { echo "${FAKE_SOURCE:-/dev/sdb1}"; exit 0; }
  [ "$col" = "MAJ:MIN" ] && { echo "${FAKE_MAJMIN:-8:17}"; exit 0; }
  exit 0
fi
if [ "$mount" = "/" ]; then
  [ "$col" = "MAJ:MIN" ] && { echo 8:2; exit 0; }
  exit 0
fi
exit 1
"""

FAKE_SYSTEMCTL = """#!/bin/sh
if [ "$1" = "is-active" ]; then exit 0; fi
if [ "$1" = "show" ]; then
  unit="$2"; prop=""
  shift 2
  while [ $# -gt 0 ]; do
    case "$1" in
      -p) prop="$2"; shift 2 ;;
      --value) shift ;;
      *) shift ;;
    esac
  done
  case "$unit:$prop" in
    docker.service:RequiresMountsFor) echo "${FAKE_REQUIRES:-/srv/data}" ;;
    docker.service:After) echo "${FAKE_AFTER:-srv-data.mount}" ;;
    docker.service:ActiveEnterTimestamp) echo "Wed 2026-11-05 10:00:00 CET" ;;
    srv-data.mount:ActiveEnterTimestamp) echo "Wed 2026-11-05 09:59:00 CET" ;;
    *) echo "" ;;
  esac
  exit 0
fi
exit 0
"""

FAKE_SYSTEMD_ESCAPE = """#!/bin/sh
echo srv-data.mount
"""

FAKE_DOCKER = """#!/bin/sh
case "$1" in
  ps)
    [ -n "${FAKE_CONTAINER:-}" ] && echo "$FAKE_CONTAINER"
    exit 0
    ;;
  inspect)
    fmt="$3"
    case "$fmt" in
      *'.Name'*) echo "/test" ;;
      *'.State.Pid'*) echo "${FAKE_PID:-123}" ;;
      *'.Mounts'*) echo "${FAKE_MOUNTS:-}" ;;
    esac
    exit 0
    ;;
esac
exit 0
"""

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "$NOTIFY_LOG"
"""


def write_fake(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def run(config: Path, proc_root: Path, bin_dir: Path, log: Path, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["BOOT_CHECK_CONFIG"] = str(config)
    env["BOOT_CHECK_PROC_ROOT"] = str(proc_root)
    env["NOTIFY_LOG"] = str(log)
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        proc_root = root / "proc"
        proc_root.mkdir()

        write_fake(bin_dir / "findmnt", FAKE_FINDMNT)
        write_fake(bin_dir / "systemctl", FAKE_SYSTEMCTL)
        write_fake(bin_dir / "systemd-escape", FAKE_SYSTEMD_ESCAPE)
        write_fake(bin_dir / "docker", FAKE_DOCKER)
        notify = bin_dir / "hsp-notify"
        write_fake(notify, FAKE_NOTIFY)

        config = root / "boot-check.conf"
        config.write_text(
            f"retry 0\n"
            f"docker 1\n"
            f"notify {notify}\n"
            f"priority urgent\n"
            f"tags boot,floppy_disk\n"
            f"mount /srv/data /dev/sdb1\n"
        )
        log = root / "notify.log"

        result = run(config, proc_root, bin_dir, log)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "boot check OK" in result.stdout, result.stdout
        assert not log.exists(), log.read_text() if log.exists() else ""

        log.unlink(missing_ok=True)
        pid_dir = proc_root / "123"
        pid_dir.mkdir()
        (pid_dir / "mountinfo").write_text(
            "36 35 8:2 /srv/data/app /config rw - ext4 /dev/sda2 rw\n"
        )
        result = run(
            config,
            proc_root,
            bin_dir,
            log,
            FAKE_CONTAINER="abc",
            FAKE_PID="123",
            FAKE_MOUNTS="/srv/data/app|/config",
        )
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert "stale bind" in result.stderr, result.stderr
        assert "8:2" in result.stderr and "8:17" in result.stderr, result.stderr
        assert log.exists() and "boot check failed" in log.read_text(), log.read_text() if log.exists() else ""

        log.unlink(missing_ok=True)
        result = run(config, proc_root, bin_dir, log, FAKE_MOUNTED="0")
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert "not mounted" in result.stderr or "timed out" in result.stderr, result.stderr

    print("test-boot-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
