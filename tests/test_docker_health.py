#!/usr/bin/env python3
"""Behaviour checks for roles/docker_health/files/hsp-docker-health.

Runs the script against a fake `docker` and a fake `curl`, so it covers
the healthy, degraded, missing and push-failure paths without a daemon.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "docker_health" / "files" / "hsp-docker-health"

FAKE_DOCKER = """#!/bin/sh
fmt=""
name=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--format" ]; then fmt="$arg"; fi
  prev="$arg"
  name="$arg"
done
[ -f "$FAKE_DOCKER_STATE/$name" ] || exit 1
case "$fmt" in
  *Health*) cat "$FAKE_DOCKER_STATE/$name" ;;
  *) awk '{print $1}' "$FAKE_DOCKER_STATE/$name" ;;
esac
"""

FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "${CURL_LOG}"
[ "${FAIL_PUSH:-0}" = "1" ] && exit 22
exit 0
"""


class Case:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        (self.bin / "docker").write_text(FAKE_DOCKER)
        (self.bin / "docker").chmod(0o755)
        (self.bin / "curl").write_text(FAKE_CURL)
        (self.bin / "curl").chmod(0o755)
        self.state = root / "state"
        self.state.mkdir()
        self.log = root / "curl.log"
        self.conf = root / "docker-health.env"

    def container(self, name: str, state: str) -> None:
        (self.state / name).write_text(state + "\n")

    def run(
        self,
        healthy: str = "",
        running: str = "",
        fail_push: bool = False,
        ca: str = "",
        per: str = "",
    ) -> tuple[int, str, str]:
        self.conf.write_text(
            'GATUS_URL="http://gatus.test"\n'
            'ENDPOINT_KEY="apps_docker-health"\n'
            'GATUS_TOKEN="test-token"\n'
            f'REQUIRE_HEALTHY="{healthy}"\n'
            f'REQUIRE_RUNNING="{running}"\n'
            f'GATUS_CA="{ca}"\n'
            f'PER_CONTAINER="{per}"\n'
            'ENDPOINT_PREFIX="docker"\n'
            'TIMEOUT=10\n'
        )
        if self.log.exists():
            self.log.unlink()
        env = dict(os.environ)
        env["HSP_DOCKER_HEALTH_CONFIG"] = str(self.conf)
        env["FAKE_DOCKER_STATE"] = str(self.state)
        env["CURL_LOG"] = str(self.log)
        env["FAIL_PUSH"] = "1" if fail_push else "0"
        env["PATH"] = f"{self.bin}:{env.get('PATH', '')}"
        result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
        log = self.log.read_text() if self.log.exists() else ""
        return result.returncode, log, result.stderr


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        case = Case(Path(tmp))
        case.container("ok1", "running healthy")
        case.container("run1", "running none")
        case.container("bad1", "running unhealthy")
        case.container("down1", "exited none")
        case.container("nohealth", "running none")

        rc, log, err = case.run(healthy="ok1", running="run1")
        if rc != 0 or "success=true" not in log or "error=" in log:
            raise SystemExit(f"healthy containers: rc={rc} log={log!r}")
        if "--cacert" in log:
            raise SystemExit("no CA configured but curl got --cacert")

        rc, log, err = case.run(healthy="ok1", ca="/etc/hsp/ca.crt")
        if "--cacert /etc/hsp/ca.crt" not in log:
            raise SystemExit(f"CA bundle was not passed to curl: {log!r}")

        rc, log, err = case.run(healthy="ok1", per="ok1")
        if rc != 0 or log.count("success=true") != 2:
            raise SystemExit(f"per-container endpoint was not pushed: rc={rc} log={log!r}")
        if "docker_ok1" not in log:
            raise SystemExit(f"per-container key missing: {log!r}")

        case.container("immich_server", "running healthy")
        rc, log, err = case.run(healthy="immich_server", per="immich_server")
        if "docker_immich-server" not in log:
            raise SystemExit(f"underscore was not slugified: {log!r}")

        rc, log, err = case.run(healthy="bad1", per="bad1")
        if "docker_bad1" not in log or "success=false" not in log:
            raise SystemExit(f"failing per-container status was not pushed: {log!r}")

        rc, log, err = case.run(healthy="ok1", per="unknown")
        if rc == 0 or "not monitored" not in err:
            raise SystemExit(f"unknown per-container name was accepted: rc={rc} err={err!r}")

        rc, log, err = case.run(healthy="ok1 bad1")
        if rc != 0 or "success=false" not in log or "bad1: unhealthy" not in log:
            raise SystemExit(f"unhealthy container: rc={rc} log={log!r}")

        rc, log, err = case.run(healthy="ok1 down1")
        if "down1: exited" not in log:
            raise SystemExit(f"stopped container: {log!r}")

        rc, log, err = case.run(healthy="missing1")
        if "missing1: missing" not in log:
            raise SystemExit(f"missing container: {log!r}")

        rc, log, err = case.run(healthy="nohealth")
        if "nohealth: no healthcheck" not in log:
            raise SystemExit(f"healthy list without healthcheck: {log!r}")

        rc, log, err = case.run(healthy="", running="")
        if rc == 0 or "no containers configured" not in err:
            raise SystemExit(f"empty configuration accepted: rc={rc} log={log!r}")

        rc, log, err = case.run(healthy="ok1", fail_push=True)
        if rc == 0:
            raise SystemExit("a failed push did not fail the script")

    print("docker health tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
