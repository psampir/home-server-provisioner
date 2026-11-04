#!/usr/bin/env python3
"""Behaviour checks for roles/docker_prune/files/hsp-docker-prune.

Runs the script against a fake `docker` that records its arguments, so the
test covers the cleanup set and the safety rails without touching a daemon.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "docker_prune" / "files" / "hsp-docker-prune"

FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "${DOCKER_LOG}"
exit "${FAKE_DOCKER_EXIT:-0}"
"""


def run(log: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DOCKER_LOG"] = str(log)
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


def calls(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def assert_safe(call_list: list[str]) -> None:
    for call in call_list:
        assert "volume" not in call, call
        assert "system prune" not in call, call
        assert "container prune" not in call, call
        assert "network prune" not in call, call


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)

        log = root / "docker.log"
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"

        result = run(log)
        assert result.returncode == 0, result.stderr
        assert calls(log) == [
            "image prune -a -f",
            "builder prune -f --all",
        ], calls(log)
        assert_safe(calls(log))

        log.unlink()
        result = run(log, {"HSP_DOCKER_PRUNE_BUILD_CACHE": "0"})
        assert result.returncode == 0, result.stderr
        assert calls(log) == ["image prune -a -f"], calls(log)

        log.unlink()
        result = run(log, {"FAKE_DOCKER_EXIT": "1"})
        assert result.returncode != 0
        assert calls(log) == ["image prune -a -f"], calls(log)

    print("test-docker-prune: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
