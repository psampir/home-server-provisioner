#!/usr/bin/env python3
"""Behaviour checks for roles/login_notify/files/hsp-login-notify.

Covers the PAM event filter, the ignored account, trusted versus untrusted
source networks and the local console case.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "login_notify" / "files" / "hsp-login-notify"

FAKE_NOTIFY = """#!/bin/sh
printf '%s\\n' "$*" >> "${NOTIFY_LOG}"
"""

CONFIG = """IGNORE_USERS="ansible"
TRUSTED_NETS="10.10.0.0/24 192.168.0.0/24"
TRUSTED_PRIORITY="low"
UNTRUSTED_PRIORITY="high"
NOTIFY_BIN="__NOTIFY__"
"""


def run(case: Path, log: Path, **pam: str) -> tuple[int, str]:
    if log.exists():
        log.unlink()
    env = dict(os.environ)
    env["HSP_LOGIN_NOTIFY_CONFIG"] = str(case / "login-notify.conf")
    env["NOTIFY_LOG"] = str(log)
    for key, value in pam.items():
        env[key] = value
    result = subprocess.run(["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    # The script backgrounds the notification, so give the child a moment.
    deadline = time.time() + 2
    while time.time() < deadline and not log.exists():
        time.sleep(0.05)
    time.sleep(0.2)
    line = log.read_text().strip() if log.exists() else ""
    return result.returncode, line


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        notify = root / "hsp-notify"
        notify.write_text(FAKE_NOTIFY)
        notify.chmod(0o755)
        log = root / "notify.log"
        (root / "login-notify.conf").write_text(CONFIG.replace("__NOTIFY__", str(notify)))

        rc, line = run(root, log, PAM_TYPE="open_session", PAM_USER="pawel",
                       PAM_RHOST="10.10.0.21", PAM_SERVICE="sshd", PAM_TTY="pts/0")
        if rc != 0 or "--priority low" not in line or "rotating_light" in line:
            raise SystemExit(f"trusted login: rc={rc} line={line!r}")

        rc, line = run(root, log, PAM_TYPE="open_session", PAM_USER="pawel",
                       PAM_RHOST="203.0.113.9", PAM_SERVICE="sshd", PAM_TTY="pts/0")
        if "--priority high" not in line or "rotating_light" not in line:
            raise SystemExit(f"untrusted login: {line!r}")

        rc, line = run(root, log, PAM_TYPE="open_session", PAM_USER="ansible",
                       PAM_RHOST="10.10.0.21", PAM_SERVICE="sshd", PAM_TTY="pts/0")
        if line:
            raise SystemExit(f"ignored user produced a notification: {line!r}")

        rc, line = run(root, log, PAM_TYPE="close_session", PAM_USER="pawel",
                       PAM_RHOST="203.0.113.9", PAM_SERVICE="sshd", PAM_TTY="pts/0")
        if line:
            raise SystemExit(f"close_session produced a notification: {line!r}")

        rc, line = run(root, log, PAM_TYPE="open_session", PAM_USER="pawel",
                       PAM_RHOST="", PAM_SERVICE="login", PAM_TTY="tty1")
        if "--priority low" not in line or "from local" not in line:
            raise SystemExit(f"local login: {line!r}")

        rc, line = run(root, log, PAM_TYPE="open_session", PAM_USER="pawel",
                       PAM_RHOST="::1", PAM_SERVICE="sshd", PAM_TTY="pts/0")
        if "--priority low" not in line:
            raise SystemExit(f"loopback login: {line!r}")

        rc, line = run(root, log, PAM_TYPE="open_session", PAM_USER="pawel",
                       PAM_RHOST="192.168.0.10", PAM_SERVICE="sshd", PAM_TTY="pts/0")
        if "--priority low" not in line:
            raise SystemExit(f"LAN login: {line!r}")

    print("login notify tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
