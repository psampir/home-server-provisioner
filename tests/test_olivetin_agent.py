#!/usr/bin/env python3
"""Checks for the generated OliveTin sudoers file.

The role only renders the environment's exact allowlist. Operation scripts
are owned by the environment and installed with custom_scripts; this test
also checks that the public reference copies are present.
"""

from __future__ import annotations

import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULTS = REPO / "roles" / "olivetin_agent" / "defaults" / "main.yml"
TEMPLATE = REPO / "roles" / "olivetin_agent" / "templates" / "90-olivetin.j2"
SCRIPTS = REPO / "configs" / "example" / "scripts" / "_common"

REFERENCE_SCRIPTS = (
    "hsp-apt",
    "hsp-needrestart",
    "hsp-reboot",
    "hsp-backup-check",
    "hsp-journal-vacuum",
    "hsp-etckeeper",
)


def render(defaults: dict, **overrides) -> str:
    context = {
        "olivetin_agent_user": defaults["olivetin_agent_user"],
        "olivetin_agent_allowed_commands": defaults["olivetin_agent_allowed_commands"],
    }
    context.update(overrides)
    return jinja2.Template(TEMPLATE.read_text()).render(**context)


def command_line(rendered: str) -> str:
    lines = [line for line in rendered.splitlines() if "NOPASSWD" in line]
    assert len(lines) == 1, rendered
    return lines[0]


def main() -> int:
    defaults = yaml.safe_load(DEFAULTS.read_text())
    assert defaults["olivetin_agent_allowed_commands"] == [], (
        "olivetin_agent_allowed_commands must default to an empty list"
    )

    for name in REFERENCE_SCRIPTS:
        assert (SCRIPTS / name).is_file(), f"missing reference script: {name}"

    rendered = render(defaults)
    assert rendered == "# Managed by Ansible - do not edit manually.\n", repr(rendered)

    expected = [
        "/usr/local/bin/hsp-apt check",
        "/usr/local/bin/hsp-apt upgrade",
        "/usr/local/bin/hsp-apt autoremove-check",
        "/usr/local/bin/hsp-apt autoremove",
        "/usr/local/bin/hsp-needrestart",
        "/usr/local/bin/hsp-reboot schedule",
        "/usr/local/bin/hsp-reboot cancel",
        "/usr/local/bin/hsp-backup-check",
        "/usr/local/bin/hsp-journal-vacuum",
        "/usr/local/bin/hsp-etckeeper",
    ]
    rendered = render(defaults, olivetin_agent_allowed_commands=expected)
    assert command_line(rendered) == (
        "olivetin ALL=(root) NOPASSWD: " + ", ".join(expected)
    ), command_line(rendered)
    assert "hsp-smart" not in rendered, rendered
    assert "*" not in rendered
    assert "?" not in rendered

    print("test_olivetin_agent: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
