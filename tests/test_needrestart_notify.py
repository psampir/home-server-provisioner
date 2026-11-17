#!/usr/bin/env python3
"""Behaviour checks for roles/auto_updates/templates/hsp-needrestart-notify.j2.

Renders the template with a fake needrestart and hsp-notify, so the dedup
state machine is exercised without root or a real package upgrade.
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
TEMPLATE = REPO / "roles" / "auto_updates" / "templates" / "hsp-needrestart-notify.j2"

FAKE_NEEDRESTART = """#!/bin/sh
cat "${NR_OUT}"
"""

FAKE_NOTIFY = """#!/bin/sh
# One line per call: "$*" may contain the multi-line body.
printf '%s\\n' "$*" | tr '\\n' ' ' >> "${NOTIFY_LOG}"
printf '\\n' >> "${NOTIFY_LOG}"
"""

NOTHING = "NEEDRESTART-VER: 3.11\nNEEDRESTART-KSTA: 1\n"

KERNEL_116 = """NEEDRESTART-VER: 3.11
NEEDRESTART-KCUR: 6.12.116+deb13-amd64
NEEDRESTART-KEXP: 6.12.117+deb13-amd64
NEEDRESTART-KSTA: 3
"""

KERNEL_118 = KERNEL_116.replace("6.12.117", "6.12.118")

SERVICES = """NEEDRESTART-VER: 3.11
NEEDRESTART-KSTA: 1
NEEDRESTART-SVC: ssh.service
NEEDRESTART-SVC: cron.service
"""

SERVICES_REORDERED = SERVICES.replace(
    "NEEDRESTART-SVC: ssh.service\nNEEDRESTART-SVC: cron.service",
    "NEEDRESTART-SVC: cron.service\nNEEDRESTART-SVC: ssh.service",
)


def render(root: Path, repeat_days: int = 7) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    needrestart = bin_dir / "needrestart"
    needrestart.write_text(FAKE_NEEDRESTART)
    needrestart.chmod(0o755)

    notify = root / "hsp-notify"
    notify.write_text(FAKE_NOTIFY)
    notify.chmod(0o755)

    script = root / "hsp-needrestart-notify"
    script.write_text(
        jinja2.Template(TEMPLATE.read_text()).render(
            auto_updates_notify_bin=str(notify),
            auto_updates_needrestart_notify_state=str(root / "state"),
            auto_updates_needrestart_notify_repeat_days=str(repeat_days),
        )
    )
    script.chmod(0o755)
    return script


def run(script: Path, root: Path, output: str, expect_ok: bool = True) -> list[str]:
    nr_out = root / "needrestart.out"
    nr_out.write_text(output)
    log = root / "notify.log"
    log.unlink(missing_ok=True)

    env = dict(os.environ)
    env["NR_OUT"] = str(nr_out)
    env["NOTIFY_LOG"] = str(log)
    env["PATH"] = f"{root / 'bin'}:{env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
    )
    if expect_ok:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0, result.stdout

    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def age_state(state: Path, seconds: int) -> None:
    lines = []
    for line in state.read_text().splitlines():
        if line.startswith("sent="):
            lines.append(f"sent={int(time.time()) - seconds}")
        else:
            lines.append(line)
    state.write_text("\n".join(lines) + "\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = render(root)
        state = root / "state"

        assert run(script, root, NOTHING) == []
        assert not state.exists(), "state must not exist with nothing pending"

        sent = run(script, root, KERNEL_116)
        assert len(sent) == 1, sent
        assert "kernel reboot pending" in sent[0]
        assert "--priority high" in sent[0]
        assert state.exists(), "state must record a delivered alert"

        assert run(script, root, KERNEL_116) == [], "same state must stay quiet"

        sent = run(script, root, KERNEL_118)
        assert len(sent) == 1, sent
        assert "kernel reboot pending" in sent[0]

        sent = run(script, root, SERVICES)
        assert len(sent) == 1, sent
        assert "2 service(s) need restart" in sent[0]
        assert "--priority default" in sent[0]

        assert run(script, root, SERVICES_REORDERED) == [], "service order must not matter"

        assert run(script, root, NOTHING) == []
        assert not state.exists(), "state must be cleared when nothing is pending"

        assert len(run(script, root, KERNEL_116)) == 1
        age_state(state, 8 * 86400)
        assert len(run(script, root, KERNEL_116)) == 1, "an aged state must repeat"
        assert run(script, root, KERNEL_116) == [], "the repeat must refresh the state"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = render(root, repeat_days=0)
        state = root / "state"

        assert len(run(script, root, KERNEL_116)) == 1
        age_state(state, 365 * 86400)
        assert run(script, root, KERNEL_116) == [], "repeat_days=0 must never repeat"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = render(root)
        state = root / "state"

        broken = root / "hsp-notify"
        broken.write_text(
            '#!/bin/sh\nprintf "attempt\\n" >> "${NOTIFY_LOG}"\nexit 1\n'
        )
        broken.chmod(0o755)
        assert run(script, root, KERNEL_116, expect_ok=False) == ["attempt"]
        assert not state.exists(), "failed delivery must not suppress the next run"

    print("test-needrestart-notify: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
